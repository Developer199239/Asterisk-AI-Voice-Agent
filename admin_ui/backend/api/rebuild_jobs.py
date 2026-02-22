"""
Backend Rebuild Job Management

Handles Docker container rebuilds with progress tracking, error capture, and rollback.
Similar pattern to download jobs in wizard.py.
"""

import logging
import os
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import yaml

from settings import PROJECT_ROOT

logger = logging.getLogger(__name__)

# Build time estimates (seconds) based on backend type
BUILD_TIME_ESTIMATES = {
    "faster_whisper": 180,  # ~3 min
    "whisper_cpp": 240,     # ~4 min
    "melotts": 300,         # ~5 min
    "kroko": 120,           # ~2 min
    "vosk": 60,             # ~1 min
    "default": 180,         # ~3 min fallback
}

# Backend to build arg mapping
BACKEND_BUILD_ARGS = {
    "faster_whisper": "INCLUDE_FASTER_WHISPER",
    "whisper_cpp": "INCLUDE_WHISPER_CPP",
    "melotts": "INCLUDE_MELOTTS",
    "kroko": "INCLUDE_KROKO",
    "vosk": "INCLUDE_VOSK",
    "llama": "INCLUDE_LLAMA",
    "piper": "INCLUDE_PIPER",
    "kokoro": "INCLUDE_KOKORO",
    "sherpa": "INCLUDE_SHERPA",
}


@dataclass
class RebuildJob:
    """Tracks a container rebuild operation."""
    id: str
    backend: str
    service: str = "local_ai_server"
    created_at: float = field(default_factory=time.time)
    running: bool = True
    completed: bool = False
    error: Optional[str] = None
    rolled_back: bool = False
    output: List[str] = field(default_factory=list)
    progress: Dict[str, Any] = field(
        default_factory=lambda: {
            "phase": "pending",  # pending, backup, updating, building, restarting, verifying, done, error
            "percent": 0,
            "estimated_seconds": 0,
            "elapsed_seconds": 0,
            "start_time": None,
            "message": "",
        }
    )


_rebuild_jobs: Dict[str, RebuildJob] = {}
_rebuild_jobs_lock = threading.Lock()
_latest_rebuild_job_id: Optional[str] = None
_active_rebuild: bool = False  # Only one rebuild at a time


def get_enabled_backends() -> Dict[str, bool]:
    """Check which backends are currently enabled in docker-compose.override.yml."""
    override_path = os.path.join(PROJECT_ROOT, "docker-compose.override.yml")
    enabled = {k: False for k in BACKEND_BUILD_ARGS.keys()}
    
    if not os.path.exists(override_path):
        return enabled
    
    try:
        with open(override_path, "r") as f:
            override = yaml.safe_load(f) or {}
        
        services = override.get("services", {})
        local_ai = services.get("local_ai_server", {})
        build_config = local_ai.get("build", {})
        build_args = build_config.get("args", {})
        
        for backend, arg_name in BACKEND_BUILD_ARGS.items():
            val = build_args.get(arg_name, "false")
            enabled[backend] = str(val).lower() == "true"
        
        return enabled
    except Exception as e:
        logger.error(f"Failed to read enabled backends: {e}")
        return enabled


def _create_rebuild_job(backend: str) -> RebuildJob:
    """Create and register a new rebuild job."""
    global _latest_rebuild_job_id
    job_id = str(uuid.uuid4())
    job = RebuildJob(id=job_id, backend=backend)
    job.progress["start_time"] = time.time()
    job.progress["estimated_seconds"] = BUILD_TIME_ESTIMATES.get(backend, BUILD_TIME_ESTIMATES["default"])
    job.progress["message"] = f"Starting {backend} backend installation..."
    
    with _rebuild_jobs_lock:
        _rebuild_jobs[job_id] = job
        _latest_rebuild_job_id = job_id
        # Keep only last 10 jobs
        if len(_rebuild_jobs) > 10:
            oldest = sorted(_rebuild_jobs.values(), key=lambda j: j.created_at)[:-10]
            for j in oldest:
                _rebuild_jobs.pop(j.id, None)
    return job


def get_rebuild_job(job_id: Optional[str] = None) -> Optional[RebuildJob]:
    """Return the requested job, or the most recent job if job_id is None."""
    with _rebuild_jobs_lock:
        if job_id:
            return _rebuild_jobs.get(job_id)
        if _latest_rebuild_job_id:
            return _rebuild_jobs.get(_latest_rebuild_job_id)
        return None


def _job_output(job_id: str, line: str) -> None:
    """Append a log line to a rebuild job."""
    with _rebuild_jobs_lock:
        job = _rebuild_jobs.get(job_id)
        if not job:
            return
        job.output.append(str(line))
        if len(job.output) > 500:
            job.output = job.output[-500:]


def _job_set_progress(job_id: str, **updates: Any) -> None:
    """Update progress fields for an in-flight rebuild job."""
    with _rebuild_jobs_lock:
        job = _rebuild_jobs.get(job_id)
        if not job:
            return
        job.progress.update(updates)
        if job.progress.get("start_time"):
            job.progress["elapsed_seconds"] = time.time() - job.progress["start_time"]


def _job_finish(job_id: str, *, completed: bool, error: Optional[str] = None, rolled_back: bool = False) -> None:
    """Mark a rebuild job as finished."""
    global _active_rebuild
    with _rebuild_jobs_lock:
        job = _rebuild_jobs.get(job_id)
        if not job:
            return
        job.running = False
        job.completed = bool(completed)
        job.error = error
        job.rolled_back = rolled_back
        job.progress["phase"] = "done" if completed else "error"
        job.progress["percent"] = 100 if completed else job.progress.get("percent", 0)
        _active_rebuild = False


def is_rebuild_in_progress() -> bool:
    """Check if a rebuild is currently in progress."""
    return _active_rebuild


def _backup_override_file() -> Optional[str]:
    """Backup docker-compose.override.yml. Returns backup path or None."""
    override_path = os.path.join(PROJECT_ROOT, "docker-compose.override.yml")
    if not os.path.exists(override_path):
        return None
    
    backup_path = os.path.join(PROJECT_ROOT, f".docker-compose.override.backup.{int(time.time())}.yml")
    try:
        shutil.copy2(override_path, backup_path)
        return backup_path
    except Exception as e:
        logger.error(f"Failed to backup override file: {e}")
        return None


def _restore_backup(backup_path: str) -> bool:
    """Restore docker-compose.override.yml from backup."""
    override_path = os.path.join(PROJECT_ROOT, "docker-compose.override.yml")
    try:
        if backup_path and os.path.exists(backup_path):
            shutil.copy2(backup_path, override_path)
            os.remove(backup_path)
            return True
        return False
    except Exception as e:
        logger.error(f"Failed to restore backup: {e}")
        return False


def _update_build_arg(backend: str, enabled: bool = True) -> bool:
    """Update docker-compose.override.yml with build arg for backend."""
    override_path = os.path.join(PROJECT_ROOT, "docker-compose.override.yml")
    
    # Load existing or create new
    if os.path.exists(override_path):
        with open(override_path, "r") as f:
            override = yaml.safe_load(f) or {}
    else:
        override = {}
    
    # Ensure structure exists
    if "services" not in override:
        override["services"] = {}
    if "local_ai_server" not in override["services"]:
        override["services"]["local_ai_server"] = {}
    if "build" not in override["services"]["local_ai_server"]:
        override["services"]["local_ai_server"]["build"] = {
            "context": "./local_ai_server",
            "dockerfile": "Dockerfile.gpu",
        }
    if "args" not in override["services"]["local_ai_server"]["build"]:
        override["services"]["local_ai_server"]["build"]["args"] = {}
    
    # Set the build arg
    arg_name = BACKEND_BUILD_ARGS.get(backend)
    if not arg_name:
        return False
    
    override["services"]["local_ai_server"]["build"]["args"][arg_name] = "true" if enabled else "false"
    
    # Write back
    try:
        with open(override_path, "w") as f:
            yaml.dump(override, f, default_flow_style=False)
        return True
    except Exception as e:
        logger.error(f"Failed to update build arg: {e}")
        return False


def _run_docker_build(job_id: str, service: str = "local_ai_server") -> bool:
    """Run docker compose build with streaming output."""
    try:
        cmd = ["docker", "compose", "build", "--no-cache", service]
        _job_output(job_id, f"$ {' '.join(cmd)}")
        
        process = subprocess.Popen(
            cmd,
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        
        # Stream output
        for line in iter(process.stdout.readline, ""):
            line = line.rstrip()
            if line:
                _job_output(job_id, line)
                # Update progress based on build stages
                if "FROM" in line or "COPY" in line or "RUN" in line:
                    _job_set_progress(job_id, message=line[:80])
        
        process.wait()
        return process.returncode == 0
    except Exception as e:
        _job_output(job_id, f"Build error: {e}")
        return False


def _run_docker_up(job_id: str, service: str = "local_ai_server") -> bool:
    """Restart the container with docker compose up."""
    try:
        cmd = ["docker", "compose", "up", "-d", service]
        _job_output(job_id, f"$ {' '.join(cmd)}")
        
        result = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        
        _job_output(job_id, result.stdout)
        if result.stderr:
            _job_output(job_id, result.stderr)
        
        return result.returncode == 0
    except Exception as e:
        _job_output(job_id, f"Restart error: {e}")
        return False


def _verify_backend_loaded(job_id: str, backend: str, timeout: int = 60) -> bool:
    """Wait for container to be healthy and verify backend is available."""
    import httpx
    
    _job_output(job_id, f"Waiting for local_ai_server to be healthy...")
    
    start = time.time()
    while time.time() - start < timeout:
        try:
            # Check container health
            result = subprocess.run(
                ["docker", "inspect", "--format", "{{.State.Health.Status}}", "local_ai_server"],
                capture_output=True,
                text=True,
            )
            status = result.stdout.strip()
            
            if status == "healthy":
                _job_output(job_id, "Container is healthy, checking backend availability...")
                
                # Check capabilities endpoint
                try:
                    resp = httpx.get("http://localhost:8088/capabilities", timeout=5.0)
                    if resp.status_code == 200:
                        caps = resp.json()
                        available = caps.get("stt_backends", []) + caps.get("tts_backends", [])
                        if backend in available or backend.replace("_", "-") in available:
                            _job_output(job_id, f"✅ Backend '{backend}' is now available!")
                            return True
                        else:
                            _job_output(job_id, f"Backend '{backend}' not in available list: {available}")
                except Exception as e:
                    _job_output(job_id, f"Capabilities check failed: {e}")
            
            time.sleep(3)
        except Exception as e:
            _job_output(job_id, f"Health check error: {e}")
            time.sleep(3)
    
    _job_output(job_id, f"⚠️ Timeout waiting for backend verification")
    return False


def start_rebuild_job(backend: str) -> Dict[str, Any]:
    """Start a rebuild job for a backend. Returns job info."""
    global _active_rebuild
    
    # Check if rebuild already in progress
    if _active_rebuild:
        return {"error": "A rebuild is already in progress", "job_id": _latest_rebuild_job_id}
    
    # Validate backend
    if backend not in BACKEND_BUILD_ARGS:
        return {"error": f"Unknown backend: {backend}"}
    
    # Check if already enabled
    enabled = get_enabled_backends()
    if enabled.get(backend):
        return {"error": f"Backend '{backend}' is already enabled", "already_enabled": True}
    
    # Create job
    job = _create_rebuild_job(backend)
    _active_rebuild = True
    
    # Start rebuild in background thread
    thread = threading.Thread(target=_rebuild_worker, args=(job.id, backend), daemon=True)
    thread.start()
    
    return {
        "job_id": job.id,
        "backend": backend,
        "estimated_seconds": job.progress["estimated_seconds"],
        "message": f"Starting {backend} backend installation...",
    }


def _rebuild_worker(job_id: str, backend: str) -> None:
    """Background worker that performs the rebuild."""
    backup_path = None
    
    try:
        # Phase 1: Backup
        _job_set_progress(job_id, phase="backup", percent=5, message="Creating backup...")
        _job_output(job_id, "Creating backup of docker-compose.override.yml...")
        backup_path = _backup_override_file()
        if backup_path:
            _job_output(job_id, f"Backup created: {backup_path}")
        
        # Phase 2: Update config
        _job_set_progress(job_id, phase="updating", percent=10, message="Updating build configuration...")
        _job_output(job_id, f"Setting {BACKEND_BUILD_ARGS[backend]}=true...")
        if not _update_build_arg(backend, enabled=True):
            raise Exception("Failed to update docker-compose.override.yml")
        _job_output(job_id, "Build configuration updated successfully")
        
        # Phase 3: Build
        _job_set_progress(job_id, phase="building", percent=15, message="Building container (this may take several minutes)...")
        _job_output(job_id, "Starting Docker build...")
        
        if not _run_docker_build(job_id):
            raise Exception("Docker build failed")
        
        _job_set_progress(job_id, percent=80, message="Build completed, restarting service...")
        
        # Phase 4: Restart
        _job_set_progress(job_id, phase="restarting", percent=85, message="Restarting local_ai_server...")
        _job_output(job_id, "Restarting container...")
        
        if not _run_docker_up(job_id):
            raise Exception("Failed to restart container")
        
        # Phase 5: Verify
        _job_set_progress(job_id, phase="verifying", percent=90, message="Verifying backend availability...")
        
        if not _verify_backend_loaded(job_id, backend):
            _job_output(job_id, "⚠️ Backend verification timed out, but build completed successfully")
        
        # Success
        _job_set_progress(job_id, phase="done", percent=100, message=f"✅ {backend} backend installed successfully!")
        _job_output(job_id, f"✅ {backend} backend installation complete!")
        
        # Cleanup backup
        if backup_path and os.path.exists(backup_path):
            os.remove(backup_path)
        
        _job_finish(job_id, completed=True)
        
    except Exception as e:
        error_msg = str(e)
        _job_output(job_id, f"❌ ERROR: {error_msg}")
        _job_set_progress(job_id, phase="error", message=f"Failed: {error_msg}")
        
        # Rollback
        rolled_back = False
        if backup_path:
            _job_output(job_id, "Rolling back configuration...")
            if _restore_backup(backup_path):
                _job_output(job_id, "Configuration restored from backup")
                rolled_back = True
            else:
                _job_output(job_id, "⚠️ Failed to restore backup - manual intervention may be needed")
        
        _job_finish(job_id, completed=False, error=error_msg, rolled_back=rolled_back)

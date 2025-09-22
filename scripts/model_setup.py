#!/usr/bin/env python3
"""Model setup utility for the Asterisk AI Voice Agent.

This script detects the host system capabilities, selects an appropriate
model tier from ``models/registry.json``, downloads the required
artifacts, and prints expected conversational performance so users know
what to expect before placing a call with the local provider.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple
from urllib.request import urlopen

REGISTRY_PATH = Path("models/registry.json")
DEFAULT_MODELS_DIR = Path("models")


class DownloadError(RuntimeError):
    """Raised when a download fails."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Setup local AI provider models")
    parser.add_argument(
        "--registry",
        type=Path,
        default=REGISTRY_PATH,
        help="Path to model registry (default: %(default)s)",
    )
    parser.add_argument(
        "--tier",
        choices=["LIGHT", "MEDIUM", "HEAVY"],
        help="Override detected system tier",
    )
    parser.add_argument(
        "--assume-yes",
        action="store_true",
        help="Proceed without prompting",
    )
    parser.add_argument(
        "--models-dir",
        type=Path,
        default=DEFAULT_MODELS_DIR,
        help="Base directory for downloaded models (default: %(default)s)",
    )
    return parser.parse_args()


def detect_cpu_cores() -> int:
    return max(1, os.cpu_count() or 1)


def detect_total_ram_gb() -> int:
    # Try psutil if present
    try:
        import psutil  # type: ignore

        return int(psutil.virtual_memory().total / (1024 ** 3))
    except Exception:
        pass

    # Linux: /proc/meminfo
    if Path("/proc/meminfo").exists():
        try:
            with open("/proc/meminfo", "r") as meminfo:
                for line in meminfo:
                    if line.startswith("MemTotal:"):
                        parts = line.split()
                        if len(parts) >= 2:
                            kb = int(parts[1])
                            return max(1, kb // (1024 ** 2))
        except Exception:
            pass

    # macOS: sysctl
    if sys.platform == "darwin":
        try:
            output = subprocess.check_output(["sysctl", "-n", "hw.memsize"])
            return int(output.strip()) // (1024 ** 3)
        except Exception:
            pass

    # Fallback
    return 0


def detect_available_disk_gb(path: Path) -> int:
    usage = shutil.disk_usage(path)
    return int(usage.free / (1024 ** 3))


def detect_environment() -> str:
    if Path("/.dockerenv").exists():
        return "docker"
    if "KUBERNETES_SERVICE_HOST" in os.environ:
        return "kubernetes"
    return "host"


def determine_tier(
    registry: Dict[str, Any], cpu_cores: int, ram_gb: int, override: Optional[str] = None
) -> str:
    tiers = registry.get("tiers", {})
    if override:
        if override not in tiers:
            raise SystemExit(f"Requested tier '{override}' not found in registry")
        return override

    # Select the highest tier whose requirements are satisfied
    selected: Optional[str] = None
    for name, info in tiers.items():
        requirements = info.get("requirements", {})
        min_ram = requirements.get("min_ram_gb", 0)
        min_cpu = requirements.get("min_cpu_cores", 0)
        if ram_gb >= min_ram and cpu_cores >= min_cpu:
            selected = name
    if not selected:
        # Default to LIGHT if nothing matches
        selected = "LIGHT"
    return selected


def human_readable_size_mb(size_mb: float) -> str:
    if size_mb >= 1024:
        return f"{size_mb / 1024:.1f} GB"
    return f"{size_mb:.0f} MB"


def prompt_yes_no(message: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    response = input(f"{message} [y/N]: ").strip().lower()
    return response in {"y", "yes"}


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def download_file(url: str, dest: Path, label: str) -> None:
    ensure_parent(dest)
    tmp_fd, tmp_path = tempfile.mkstemp(prefix="download_", suffix=dest.suffix)
    os.close(tmp_fd)
    tmp_file = Path(tmp_path)
    try:
        print(f"Downloading {label} → {dest}...")
        with urlopen(url) as response, tmp_file.open("wb") as out:
            shutil.copyfileobj(response, out)
        tmp_file.replace(dest)
    except Exception as exc:
        tmp_file.unlink(missing_ok=True)
        raise DownloadError(f"Failed to download {label} from {url}: {exc}")


def extract_zip(archive: Path, target_dir: Path) -> None:
    print(f"Extracting {archive.name} → {target_dir}")
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "r") as zip_ref:
        zip_ref.extractall(target_dir)


def download_models_for_tier(tier_info: Dict[str, Any], models_dir: Path) -> None:
    models = tier_info.get("models", {})

    stt = models.get("stt")
    if stt:
        url = stt["url"]
        dest_dir = models_dir / stt.get("dest_dir", "")
        target_path = models_dir / stt.get("target_path", "")
        archive_name = Path(url).name
        archive_path = dest_dir / archive_name
        if target_path.exists():
            print(f"STT model already present: {target_path}")
        else:
            download_file(url, archive_path, stt["name"])
            extract_zip(archive_path, target_path)
            archive_path.unlink(missing_ok=True)

    llm = models.get("llm")
    if llm:
        dest_path = models_dir / llm.get("dest_path", "")
        if dest_path.exists():
            print(f"LLM model already present: {dest_path}")
        else:
            download_file(llm["url"], dest_path, llm["name"])

    tts = models.get("tts")
    if tts:
        files: Iterable[Dict[str, str]] = tts.get("files", [])
        for item in files:
            dest_path = models_dir / item.get("dest_path", "")
            if dest_path.exists():
                print(f"TTS artifact already present: {dest_path}")
            else:
                download_file(item["url"], dest_path, item["name"])


def print_expectations(tier_name: str, tier_info: Dict[str, Any]) -> None:
    expectations = tier_info.get("expectations", {})
    summary = expectations.get("two_way_summary", "")
    print("\n=== Conversational Expectations ===")
    print(f"Tier: {tier_name}")
    if summary:
        print(f"Summary: {summary}")
    stt = expectations.get("stt_latency_sec")
    llm = expectations.get("llm_latency_sec")
    tts = expectations.get("tts_latency_sec")
    if stt or llm or tts:
        print("Approximate latencies per turn:")
        if stt:
            print(f"  STT: ~{stt} sec")
        if llm:
            print(f"  LLM: ~{llm} sec")
        if tts:
            print(f"  TTS: ~{tts} sec")
    rec_calls = expectations.get("recommended_concurrent_calls")
    if rec_calls is not None:
        print(f"Recommended concurrent calls: {rec_calls}")


def main() -> None:
    args = parse_args()
    if not args.registry.exists():
        raise SystemExit(f"Registry file not found: {args.registry}")

    registry: Dict[str, Any] = json.loads(args.registry.read_text())
    cpu = detect_cpu_cores()
    ram = detect_total_ram_gb()
    disk = detect_available_disk_gb(Path.cwd())
    env = detect_environment()

    print("=== System detection ===")
    print(f"CPU cores: {cpu}")
    print(f"Total RAM: {ram} GB")
    print(f"Available disk: {disk} GB")
    print(f"Environment: {env}")
    print(f"Architecture: {platform.machine()} ({platform.system()})")

    tier_name = determine_tier(registry, cpu, ram, args.tier)
    tier_info = registry["tiers"][tier_name]
    print(f"\nSelected tier: {tier_name} — {tier_info.get('description','')}")

    if not prompt_yes_no("Proceed with model download/setup?", args.assume_yes):
        print("Aborted by user.")
        return

    download_models_for_tier(tier_info, args.models_dir)
    print_expectations(tier_name, tier_info)

    print("\nModels ready. Update your config to point at the downloaded paths and run a quick regression call.")


if __name__ == "__main__":
    try:
        main()
    except DownloadError as exc:
        raise SystemExit(f"Error: {exc}")

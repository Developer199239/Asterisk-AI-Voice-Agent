import sys
import types
from importlib import util
from pathlib import Path

import pytest


BACKEND_ROOT = Path(__file__).resolve().parents[1] / "admin_ui" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from services.google_live_validation import (  # noqa: E402
    GOOGLE_LIVE_DEFAULT_MODEL,
    build_google_key_validation_result,
    extract_google_live_models,
    select_google_live_model,
)


class _FakeGoogleResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class _FakeAsyncClient:
    response = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, *args, **kwargs):
        return self.response


def _install_wizard_import_stubs(monkeypatch):
    api_pkg = types.ModuleType("api")
    api_pkg.__path__ = [str(BACKEND_ROOT / "api")]
    monkeypatch.setitem(sys.modules, "api", api_pkg)

    fastapi = types.ModuleType("fastapi")

    class HTTPException(Exception):
        def __init__(self, status_code=None, detail=None):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    class APIRouter:
        def post(self, *args, **kwargs):
            return lambda func: func

        def get(self, *args, **kwargs):
            return lambda func: func

        def delete(self, *args, **kwargs):
            return lambda func: func

    fastapi.APIRouter = APIRouter
    fastapi.HTTPException = HTTPException
    monkeypatch.setitem(sys.modules, "fastapi", fastapi)

    pydantic = types.ModuleType("pydantic")

    class BaseModel:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

    pydantic.BaseModel = BaseModel
    pydantic.Field = lambda default=None, **kwargs: default
    monkeypatch.setitem(sys.modules, "pydantic", pydantic)

    docker = types.ModuleType("docker")
    docker.from_env = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "docker", docker)

    models_catalog = types.ModuleType("api.models_catalog")
    for name in (
        "get_full_catalog",
        "get_models_by_language",
        "get_available_languages",
    ):
        setattr(models_catalog, name, lambda *args, **kwargs: {})
    for name in (
        "LANGUAGE_NAMES",
        "REGION_NAMES",
        "VOSK_STT_MODELS",
        "SHERPA_STT_MODELS",
        "KROKO_STT_MODELS",
        "PIPER_TTS_MODELS",
        "KOKORO_TTS_MODELS",
        "SILERO_TTS_MODELS",
        "LLM_MODELS",
    ):
        setattr(models_catalog, name, {})
    monkeypatch.setitem(sys.modules, "api.models_catalog", models_catalog)

    custom_models = types.ModuleType("api.custom_models")
    custom_models.merge_into_catalog = lambda catalog: catalog
    monkeypatch.setitem(sys.modules, "api.custom_models", custom_models)

    rebuild_jobs = types.ModuleType("api.rebuild_jobs")
    for name in (
        "start_rebuild_job",
        "get_rebuild_job",
        "get_enabled_backends",
        "is_rebuild_in_progress",
    ):
        setattr(rebuild_jobs, name, lambda *args, **kwargs: None)
    rebuild_jobs.BACKEND_BUILD_ARGS = {}
    rebuild_jobs.BUILD_TIME_ESTIMATES = {}
    monkeypatch.setitem(sys.modules, "api.rebuild_jobs", rebuild_jobs)


def _load_wizard_module(monkeypatch):
    _install_wizard_import_stubs(monkeypatch)
    module_name = "wizard_for_google_validation_tests"
    module_path = BACKEND_ROOT / "api" / "wizard.py"
    spec = util.spec_from_file_location(module_name, module_path)
    module = util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_google_live_validation_accepts_key_when_live_models_are_not_advertised():
    result = build_google_key_validation_result(
        [
            {
                "name": "models/gemini-2.5-flash",
                "supportedGenerationMethods": ["generateContent", "countTokens"],
            }
        ]
    )

    assert result["valid"] is True
    assert result["selected_model"] == GOOGLE_LIVE_DEFAULT_MODEL
    assert result["available_models"] == []
    assert "warning" in result
    assert "did not advertise Live-capable models" in result["warning"]


def test_google_live_validation_selects_preferred_live_model():
    result = build_google_key_validation_result(
        [
            {
                "name": "models/gemini-3.1-flash-live-preview",
                "supportedGenerationMethods": ["bidiGenerateContent"],
            },
            {
                "name": "models/gemini-2.5-flash-native-audio-preview-12-2025",
                "supportedGenerationMethods": ["generateContent", "bidiGenerateContent"],
            },
        ]
    )

    assert result["valid"] is True
    assert result["selected_model"] == "gemini-2.5-flash-native-audio-preview-12-2025"
    assert "warning" not in result


def test_google_live_model_extraction_strips_models_prefix():
    live_models = extract_google_live_models(
        [
            {
                "name": "models/gemini-3.1-flash-live-preview",
                "supportedGenerationMethods": ["bidiGenerateContent"],
            },
            {
                "name": "models/gemini-2.5-flash",
                "supportedGenerationMethods": ["generateContent"],
            },
        ]
    )

    assert live_models == ["gemini-3.1-flash-live-preview"]
    assert select_google_live_model(live_models) == "gemini-3.1-flash-live-preview"


@pytest.mark.asyncio
async def test_google_validate_key_route_accepts_200_without_live_models(monkeypatch):
    wizard = _load_wizard_module(monkeypatch)
    _FakeAsyncClient.response = _FakeGoogleResponse(
        200,
        {
            "models": [
                {
                    "name": "models/gemini-2.5-flash",
                    "supportedGenerationMethods": ["generateContent"],
                }
            ]
        },
    )
    monkeypatch.setattr(wizard.httpx, "AsyncClient", _FakeAsyncClient)

    result = await wizard.validate_api_key(
        wizard.ApiKeyValidation(provider="google", api_key="AIza-test-key")
    )

    assert result["valid"] is True
    assert result["selected_model"] == GOOGLE_LIVE_DEFAULT_MODEL
    assert result["available_models"] == []
    assert "warning" in result


@pytest.mark.asyncio
async def test_google_validate_key_route_treats_429_as_advisory(monkeypatch):
    wizard = _load_wizard_module(monkeypatch)
    _FakeAsyncClient.response = _FakeGoogleResponse(429, {"error": {"message": "quota"}})
    monkeypatch.setattr(wizard.httpx, "AsyncClient", _FakeAsyncClient)

    result = await wizard.validate_api_key(
        wizard.ApiKeyValidation(provider="google", api_key="AIza-test-key")
    )

    assert result["valid"] is True
    assert result["selected_model"] == GOOGLE_LIVE_DEFAULT_MODEL
    assert result["available_models"] == []
    assert "warning" in result
    assert "rate-limited" in result["warning"]


@pytest.mark.asyncio
async def test_google_validate_key_route_separates_403_access_denied(monkeypatch):
    wizard = _load_wizard_module(monkeypatch)
    _FakeAsyncClient.response = _FakeGoogleResponse(
        403,
        {"error": {"message": "API key not authorized for this project"}},
    )
    monkeypatch.setattr(wizard.httpx, "AsyncClient", _FakeAsyncClient)

    result = await wizard.validate_api_key(
        wizard.ApiKeyValidation(provider="google", api_key="AIza-test-key")
    )

    assert result["valid"] is False
    assert result["error"] == "API key not authorized for this project"

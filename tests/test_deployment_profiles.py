"""Local profile separation and Azure object-key safety."""
import json
import sys
from pathlib import Path

import pytest

from backend.services.blob_storage import AzureBlobStorage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "farmcraft-evaluator" / "app"))
from configuration import credentials, profile_path, settings  # noqa: E402


def test_azure_and_render_identities_are_not_interchangeable(monkeypatch, tmp_path):
    repo = Path(__file__).resolve().parents[1]
    profiles = repo / "config" / "local-profiles"
    profiles.mkdir(parents=True, exist_ok=True)
    env_path = profiles / "test-azure.env"
    identity_path = profiles / "test-azure-credentials.json"
    try:
        env_path.write_text("FARMCRAFT_API_URL=https://farmcraft.example.azurecontainerapps.io\n"
                            "WORKER_NAME=Azure test laptop\n", encoding="utf-8")
        identity_path.write_text(json.dumps({"workerId": "azure-id", "credential": "azure-secret"}),
                                 encoding="utf-8")
        monkeypatch.setenv("FARMCRAFT_WORKER_ENV_FILE", str(env_path))
        monkeypatch.setenv("FARMCRAFT_WORKER_CREDENTIAL_FILE", str(identity_path))
        assert settings()["FARMCRAFT_API_URL"].endswith("azurecontainerapps.io")
        assert credentials()["workerId"] == "azure-id"
        assert credentials()["credential"] == "azure-secret"
    finally:
        env_path.unlink(missing_ok=True)
        identity_path.unlink(missing_ok=True)


def test_profile_paths_cannot_escape_checkout(monkeypatch, tmp_path):
    monkeypatch.setenv("FARMCRAFT_WORKER_CREDENTIAL_FILE", str(tmp_path / "other.json"))
    with pytest.raises(ValueError, match="inside the FarmCraft checkout"):
        profile_path("FARMCRAFT_WORKER_CREDENTIAL_FILE", "credentials.json")


@pytest.mark.parametrize("key", ["", "/private/x", "private/../x", "private//x", "./x"])
def test_azure_blob_rejects_invalid_object_keys(key):
    with pytest.raises(ValueError):
        AzureBlobStorage._key(key)

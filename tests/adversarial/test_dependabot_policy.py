from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEPENDABOT_CONFIG = PROJECT_ROOT / ".github" / "dependabot.yml"


def test_dependabot_updates_are_bounded_and_exclude_runtime_images() -> None:
    config = yaml.safe_load(DEPENDABOT_CONFIG.read_text(encoding="utf-8"))

    assert config["version"] == 2
    assert "registries" not in config
    updates = config["updates"]
    assert {(entry["package-ecosystem"], entry["directory"]) for entry in updates} == {
        ("github-actions", "/"),
        ("npm", "/adapters"),
        ("pip", "/"),
    }

    expected_days = {"pip": "monday", "npm": "tuesday", "github-actions": "wednesday"}
    for entry in updates:
        ecosystem = entry["package-ecosystem"]
        assert entry["schedule"] == {
            "interval": "weekly",
            "day": expected_days[ecosystem],
            "time": "06:00",
            "timezone": "Europe/Ljubljana",
        }
        assert entry["cooldown"]["default-days"] >= 7
        if ecosystem == "pip":
            assert 0 < entry["open-pull-requests-limit"] <= 2
            assert "versioning-strategy" not in entry
        else:
            assert 0 < entry["open-pull-requests-limit"] <= 2
        assert "groups" not in entry
        assert "target-branch" not in entry


def test_python_installations_enforce_hashes_and_lock_regeneration() -> None:
    workflow = (PROJECT_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    runtime_dockerfile = (PROJECT_ROOT / "deploy/Dockerfile").read_text(encoding="utf-8")
    adapter_dockerfile = (PROJECT_ROOT / "deploy/Dockerfile.adapters-python").read_text(
        encoding="utf-8"
    )
    evaluator_dockerfile = (PROJECT_ROOT / "deploy/Dockerfile.evolution-evaluator").read_text(
        encoding="utf-8"
    )
    assert workflow.count("--require-hashes --requirement requirements-dev.lock") == 2
    assert workflow.count("make lock-check UV=uv") == 2
    assert "--require-hashes --requirement requirements.lock" in runtime_dockerfile
    assert "--require-hashes --requirement requirements.lock" in adapter_dockerfile
    assert "--require-hashes --requirement requirements-dev.lock" in evaluator_dockerfile
    assert (PROJECT_ROOT / "requirements.in").is_file()
    assert (PROJECT_ROOT / "requirements-dev.in").is_file()

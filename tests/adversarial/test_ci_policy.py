import re
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = PROJECT_ROOT / ".github" / "workflows"
FULL_COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")


def _load_workflow(path: Path) -> dict[str, object]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def test_workflows_have_read_only_authority_and_safe_triggers() -> None:
    workflows = sorted((*WORKFLOW_DIR.glob("*.yml"), *WORKFLOW_DIR.glob("*.yaml")))
    assert workflows

    for path in workflows:
        workflow = _load_workflow(path)
        assert workflow.get("permissions") == {"contents": "read"}

        # PyYAML's YAML 1.1 resolver interprets the plain key `on` as true.
        triggers = workflow.get("on", workflow.get(True))
        assert isinstance(triggers, dict)
        assert "pull_request_target" not in triggers

        text = path.read_text(encoding="utf-8")
        assert "permissions: write-all" not in text
        assert not re.search(r"^\s+[a-z-]+:\s+write\s*$", text, re.MULTILINE)
        assert "secrets: inherit" not in text


def test_external_actions_are_commit_pinned_without_persisted_credentials() -> None:
    workflows = sorted((*WORKFLOW_DIR.glob("*.yml"), *WORKFLOW_DIR.glob("*.yaml")))

    for path in workflows:
        workflow = _load_workflow(path)
        jobs = workflow.get("jobs")
        assert isinstance(jobs, dict)

        for job in jobs.values():
            assert isinstance(job, dict)
            steps = job.get("steps", [])
            assert isinstance(steps, list)
            for step in steps:
                assert isinstance(step, dict)
                action = step.get("uses")
                if action is None:
                    continue
                assert isinstance(action, str)
                reference = action.rsplit("@", maxsplit=1)[-1]
                assert FULL_COMMIT_SHA.fullmatch(reference)
                if action.startswith("actions/checkout@"):
                    assert step.get("with", {}).get("persist-credentials") is False

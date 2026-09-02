from pathlib import Path

import yaml

from rosetta.config import load_config
from rosetta.observer import WATCHED_PATHS

ROOT = Path(__file__).resolve().parents[2]


def test_staging_compose_has_no_ingress_secrets_or_worker_internet() -> None:
    compose = yaml.safe_load((ROOT / "deploy/compose.staging.yaml").read_text())
    services = compose["services"]
    assert set(services) == {"observer", "egress-proxy"}
    assert compose["networks"]["observer-internal"]["internal"] is True

    for service in services.values():
        assert "ports" not in service
        assert "build" not in service
        assert service["read_only"] is True
        assert service["user"] == "65532:65532"
        assert service["cap_drop"] == ["ALL"]
        assert service["security_opt"] == ["no-new-privileges:true"]
        assert "/var/run/docker.sock" not in str(service)
        assert "secret" not in str(service).lower()

    assert services["observer"]["networks"] == ["observer-internal"]
    assert set(services["egress-proxy"]["networks"]) == {"observer-internal", "egress"}
    assert "https://technocore.chat" in services["egress-proxy"]["command"]
    assert services["egress-proxy"]["healthcheck"]["retries"] == 12
    assert services["observer"]["depends_on"]["egress-proxy"]["condition"] == "service_healthy"
    assert services["observer"]["command"][0] == "rosetta.observer"
    assert "public_writes" in services["observer"]["healthcheck"]["test"][-1]
    assert "safety_status" in services["observer"]["healthcheck"]["test"][-1]


def test_staging_profile_is_strictly_read_only_and_closed() -> None:
    config = load_config(ROOT / "config/config.staging.example.yaml", {})
    assert config.mode == "dry_run"
    assert config.observer.enabled
    assert config.technocore.base_url == "https://technocore.chat"
    assert config.observer.fetch_base_url == "http://egress-proxy:8081"
    assert not config.discovery.enabled
    assert not config.service.enabled
    assert not config.publisher.enabled
    assert config.model.provider == "disabled"
    assert config.rosetta.max_parallel_runners == 1
    assert WATCHED_PATHS == (
        "/healthz",
        "/.well-known/agent.json",
        "/openapi.json",
    )


def test_systemd_supervises_the_whole_compose_boundary() -> None:
    unit = (ROOT / "deploy/rosetta-observer.service").read_text()
    assert "--abort-on-container-exit" in unit
    assert "Restart=on-failure" in unit
    assert "EnvironmentFile=/etc/rosetta/staging.env" in unit
    assert "deploy/compose.staging.yaml" in unit


def test_staging_health_and_backup_timers_are_local_and_fail_closed() -> None:
    health = (ROOT / "deploy/rosetta-healthcheck.service").read_text()
    backup = (ROOT / "deploy/rosetta-backup.service").read_text()
    assert "tools/staging_status.py" in health
    assert "--expected-release v0.10.0" in health
    assert "ReadOnlyPaths=/var/lib/rosetta/state /var/lib/rosetta/evidence" in health
    assert "User=65532" in health
    assert "CapabilityBoundingSet=" in health
    assert "tools/export_encrypted_backup.sh" in backup
    assert "/etc/rosetta/backup-recipient.txt" in backup
    assert "ReadWritePaths=/var/backups/rosetta/encrypted" in backup
    assert "User=65532" in backup
    assert "CapabilityBoundingSet=" in backup
    assert "http" not in backup.lower()


def test_production_signer_uses_encrypted_credential_and_no_network() -> None:
    unit = (ROOT / "deploy/rosetta-signer.production.service").read_text()
    assert "LoadCredentialEncrypted=rosetta.seed:" in unit
    assert "--seed-file %d/rosetta.seed" in unit
    assert "PrivateNetwork=yes" in unit
    assert "RestrictAddressFamilies=AF_UNIX" in unit
    assert "CapabilityBoundingSet=" in unit
    assert "ProtectKernelTunables=yes" in unit
    assert "Environment=" not in unit
    assert "synthetic" not in unit.lower()


def test_remote_upgrade_requires_a_signed_package_and_narrow_sudo() -> None:
    unit = (ROOT / "deploy/rosetta-upgrade.service").read_text()
    sudoers = (ROOT / "deploy/rosetta-upgrade.sudoers").read_text()
    installer = (ROOT / "deploy/install-rosetta-upgrader.sh").read_text()
    apply_script = (ROOT / "deploy/rosetta-upgrade-apply.sh").read_text()

    assert "release-manifest.json.sig" in unit
    assert "release-allowed-signers" in unit
    assert "User=root" in unit
    assert "RestrictAddressFamilies=AF_UNIX AF_NETLINK" in unit
    assert "ProtectSystem=strict" in unit
    assert "TimeoutStartSec=15min" in unit
    assert "CapabilityBoundingSet=CAP_CHOWN" in unit
    assert "systemctl start rosetta-upgrade.service" in sudoers
    assert "NOPASSWD: ALL" not in sudoers
    assert "rosetta-release-package" in installer
    assert "visudo -cf" in installer
    assert "count == 1 && bad == 0" in installer
    assert (ROOT / "tools/release_package.py").read_text().startswith("#!/usr/bin/env python3")
    assert "ROSETTA_IMAGE" in apply_script
    assert "verify_staging_live.py" in apply_script
    assert "rollback" in apply_script
    assert "trap 'rollback 143' TERM" in apply_script
    assert 'docker build --no-cache --file "$release_dir/deploy/Dockerfile"' in apply_script
    assert "for module in rosetta.egress rosetta.observer" in apply_script
    assert "docker run --rm --network none --read-only --user 65532:65532" in apply_script
    assert "--cap-drop ALL --security-opt no-new-privileges" in apply_script
    assert '"$new_image" "$module" --help >/dev/null' in apply_script
    assert 'cat "$backup_directory/live-verification.pending" >&2' in apply_script
    live_verifier = (ROOT / "tools/verify_staging_live.py").read_text()
    assert "user=RUNTIME_UID" in live_verifier
    assert "group=RUNTIME_GID" in live_verifier
    assert "extra_groups=()" in live_verifier
    assert '"setpriv"' not in live_verifier
    assert "offline_status_failed:" in live_verifier
    assert 'sqlite_source="$backup_directory/sqlite-source"' in apply_script
    assert "for suffix in -wal -shm" in apply_script
    assert 'test ! -L "$sidecar_source"' in apply_script
    assert "PRAGMA integrity_check" in apply_script
    assert 'environment_new="$backup_directory/staging.env.new"' in apply_script
    assert 'environment_new="${environment_file}.new"' not in apply_script
    replace_tool = (ROOT / "tools/replace_existing_file.py").read_text()
    assert "os.O_RDWR" in replace_tool
    assert 'getattr(os, "O_NOFOLLOW", None)' in replace_tool
    assert "os.ftruncate(destination_fd, 0)" in replace_tool
    assert "os.fsync(destination_fd)" in replace_tool
    assert "destination_verification_failed" in replace_tool
    assert 'replace_existing_file "$backup_directory/staging.env"' in apply_script
    assert 'replace_existing_file "$environment_new" "$environment_file"' in apply_script
    assert "ReadWritePaths=/opt/rosetta /etc/rosetta/staging.env " in unit
    assert "ReadWritePaths=/opt/rosetta /etc/rosetta " not in unit


def test_staging_image_and_healthcheck_fail_closed_without_log_noise() -> None:
    dockerfile = (ROOT / "deploy/Dockerfile").read_text()
    compose = yaml.safe_load((ROOT / "deploy/compose.staging.yaml").read_text())
    healthcheck = compose["services"]["egress-proxy"]["healthcheck"]["test"][-1]
    ci = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())

    normalization = "RUN chmod -R u=rwX,go=rX src config adapters vendor"
    runtime_user = "USER 65532:65532"
    runtime_import = (
        'RUN test "$(id -u)" = "65532" && ' 'python -c "import rosetta.egress, rosetta.observer"'
    )
    assert normalization in dockerfile
    assert runtime_import in dockerfile
    assert dockerfile.index(normalization) < dockerfile.index(runtime_user)
    assert dockerfile.index(runtime_user) < dockerfile.index(runtime_import)
    assert dockerfile.count("COPY --chown=0:0") == 5
    assert "r=c.getresponse()" in healthcheck
    assert "r.read()" in healthcheck
    assert "c.close()" in healthcheck
    assert "r.status == 404" in healthcheck
    image_job = ci["jobs"]["observer-image"]
    image_steps = "\n".join(str(step) for step in image_job["steps"])
    assert "git archive --format=tar.gz" in image_steps
    assert "from tools.release_package import extract_archive" in image_steps
    assert '"$RUNNER_TEMP/release-tree/deploy/Dockerfile"' in image_steps
    assert '--tag rosetta/observer:ci "$RUNNER_TEMP/release-tree"' in image_steps
    assert "for module in rosetta.egress rosetta.observer" in image_steps
    assert "--network none --read-only --user 65532:65532" in image_steps
    assert "--cap-drop ALL --cap-add SETUID --cap-add SETGID" in image_steps
    assert "result.stdout.strip()" in image_steps

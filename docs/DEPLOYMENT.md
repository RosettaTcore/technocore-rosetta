# Deployment target

## Recommended pilot host

One dedicated small EU cloud server/project with no other workloads or credentials. Prefer at least 4 GB RAM so two bounded runner containers and the local test target can coexist.

- Debian stable or equivalent minimal host;
- provider backup and explicit monthly alert;
- SSH keys only and restricted administrative ingress;
- no general public application endpoint;
- controlled security updates and reboot policy;
- no automatic resource scaling.

Do not provision until local acceptance passes and the operator approves paid infrastructure.

The repository includes `deploy/Dockerfile`, the offline `deploy/compose.yaml`, the read-only
`deploy/compose.staging.yaml`, hardened systemd units and a runner seccomp template. The Dockerfile
uses reviewed immutable defaults and permits overrides only with another reviewed
`image@sha256:...` reference.

Local Phase 3 validation used pinned Python 3.12.5 and Node 20.9.0 base digests, separate worker and
adapter images, the official Technocore v0.10.0 OCI image, and an internal Docker network with no
host port. The v0.7.0 fixture remains only for deterministic historical replay.
All containers were removed after evidence capture; the images remain local for reproducibility.

## Service layout

- `rosetta-scheduler`: resolves immutable versions and queues runs.
- `rosetta-discovery`: polls the Technocore request mailbox, validates closed requests and delivers signed responses.
- `rosetta-runner-supervisor`: creates/destroys isolated ephemeral runners.
- `rosetta-signer`: networkless seed boundary and nonce state.
- `rosetta-egress`: exact origin allowlist with no body logging.
- `rosetta-publisher`: optional, separately approved, one destination only.
- local pinned Technocore target used for the full matrix.

The Phase 4 staging profile intentionally starts only `observer` and `egress-proxy`. It does not
start the scheduler, runners, discovery, signer or publisher because there is no authorized public
write or production identity yet. The observer can reach only the internal egress container. The
egress container alone has an outbound network and its code permits three fixed metadata paths.

Production runners must not share a writable filesystem or network namespace with scheduler, signer, publisher or other runners.

## Persistent paths

```text
/var/lib/rosetta/state/          scheduler SQLite
/var/lib/rosetta/evidence/       immutable bundles
/var/lib/rosetta/spool/          signed publication queue
/var/lib/rosetta-signer/         signer nonce state
/run/rosetta-signer/             Unix socket
/etc/rosetta/                    non-secret config and adapter lock
/run/secrets/                    service-specific secret mounts
/var/lib/rosetta/upgrades/       fixed incoming spool and root-only verification work
```

Mount each path only into the service that requires it. Runner containers receive none of them.

## Publisher boundary

Publisher is absent or disabled until separately approved. When enabled:

- accepts only bundles whose attestation verifies against configured DID;
- writes only content-addressed artifacts plus an atomic index;
- has a credential restricted to one repository/bucket;
- cannot create issues, PRs, releases in unrelated repositories or social posts;
- cannot read signer state or general scheduler secrets.
- serves the attested service card, request/result schemas, skill document and content-addressed reports as static files.

Discovery does not require an inbound application service. Peers read static documents from the publisher and submit requests through Technocore. The discovery process receives no publisher credential and the publisher receives no Technocore signing seed.

## Backups

- Provider server backup.
- Encrypted external backup of production DID seed.
- Daily encrypted state/evidence export.
- Restore rehearsal with synthetic data before first public write.
- Retain immutable published bundle roots locally.
- Never rely on Technocore as recovery storage.

`rosetta-backup.service` uses SQLite's live backup API and streams a temporary snapshot directly
through Age encryption. The server receives only an Age public recipient and must never hold the
matching secret key. `rosetta-healthcheck.service` validates health/evidence/SQLite state locally;
its timer failure must be connected to an independently controlled external alert destination
before public service intake. Exact setup and restore gates are in `LAUNCH_RUNBOOK.md`.

The reviewed Healthchecks.io notifier is a separate least-privilege network process. It receives a
single ping capability through a systemd credential and sends no health record, host data or log
body. The fixed client accepts only one exact `hc-ping.com` check identifier and does not follow
redirects. Alert delivery never changes the deterministic local health verdict.

## Operational access

- Cloud firewall denies all unnecessary ingress.
- Prefer private admin path or fixed management IPs.
- Separate cloud project and billing alert.
- No cloud API token inside Rosetta.
- Kill switch must work without entering scheduler or runner containers.
- Routine deployment uses the signed fixed-path gate; provider-console root login remains locked.

## Read-only staging on the single pilot server

The same server advances through read-only staging, controlled pilot and live operation. Do not
buy a second server solely for these phases. Before each transition, retain the provider backup,
take an application backup and preserve the prior immutable image/release for rollback.

Install the checked-in configuration and persistent directories as root. The configuration is not
a secret; it is read-only inside the observer. No credential or DID is used in this phase.

```sh
install -d -o root -g root -m 0755 /etc/rosetta
install -d -o 65532 -g 65532 -m 0700 /var/lib/rosetta/state
install -d -o 65532 -g 65532 -m 0700 /var/lib/rosetta/evidence
install -o root -g root -m 0644 \
  config/config.staging.example.yaml /etc/rosetta/config.yaml
```

Create `/etc/rosetta/staging.env` as root. `ROSETTA_IMAGE` must be the reviewed immutable local image
ID or an immutable registry digest, never a floating tag.

```text
ROSETTA_IMAGE=sha256:REVIEWED_IMAGE_ID
ROSETTA_CONFIG=/etc/rosetta/config.yaml
ROSETTA_STATE_DIR=/var/lib/rosetta/state
ROSETTA_EVIDENCE_DIR=/var/lib/rosetta/evidence
```

Validate the rendered deployment before starting it. The output must contain no `ports`, no
secret, no Docker socket and no direct egress network on `observer`.

```sh
set -a
. /etc/rosetta/staging.env
set +a
docker compose -f deploy/compose.staging.yaml config
```

Run one foreground observation first, inspect its exit status and confirm that the only public
listener on the host remains SSH. Then install and enable the service:

```sh
install -o root -g root -m 0644 \
  deploy/rosetta-observer.service /etc/systemd/system/rosetta-observer.service
systemctl daemon-reload
systemctl enable --now rosetta-observer.service
systemctl is-active rosetta-observer.service
```

The current state is a bounded JSON file and the first view of each distinct protocol digest is a
content-addressed evidence file:

```text
/var/lib/rosetta/state/health.json
/var/lib/rosetta/state/observer.sqlite3
/var/lib/rosetta/evidence/<protocol-sha256>.json
```

Activate the kill switch from the host with `touch /var/lib/rosetta/state/KILL_SWITCH`. The observer
then exits without attempting another request; systemd may restart it, but it remains stopped while
the switch exists. Removal is a manual incident-review decision. Rollback stops the unit, restores
the previous `/opt/rosetta/current` release and immutable image setting, then starts the unit again.

Read-only staging acceptance requires continuous safety-safe operation with: service active, no
non-SSH host listener, no public writes, no unexplained restarts, a fresh local heartbeat and
bounded disk growth. Upstream availability and release drift are separate compatibility warnings;
they do not reset the read-only safety window. A changed digest must be reviewed before it becomes
an execution baseline. Public signing, discovery/service intake and publication each remain
separate approval gates.

## Signed remote upgrades

Routine upgrades use `tools/release_package.py`; they do not use an interactive root shell. Install
the root-owned gate once from a reviewed checkout while provider-console access is available:

```sh
printf '%s\n' 'rosetta-release ssh-ed25519 APPROVED_RELEASE_PUBLIC_KEY' \
  > /root/rosetta-release-allowed-signers
deploy/install-rosetta-upgrader.sh "$PWD" /root/rosetta-release-allowed-signers
```

The placeholder is an SSH **public** key only. Keep the private release-signing key on the operator
workstation or hardware-backed agent. After checking the installed files, lock root password login
again. The `rosetta` account receives permission only to start and inspect the fixed
`rosetta-upgrade.service`; it never receives general `sudo` or a writable root-owned executable.

Prepare a package locally from a reviewed, committed ref. `--previous-commit` must be the exact
current target on the server:

```sh
python3 tools/release_package.py prepare \
  --repository "$PWD" \
  --ref REVIEWED_COMMIT \
  --previous-commit CURRENT_SERVER_COMMIT \
  --output local/releases/REVIEWED_COMMIT \
  --signing-key /path/to/release-signing-key
```

Upload exactly `release.tar.gz`, `release-manifest.json` and `release-manifest.json.sig` to
`/var/lib/rosetta/upgrades/incoming/`, then run:

```sh
sudo systemctl start rosetta-upgrade.service
sudo systemctl --no-pager status rosetta-upgrade.service
sudo journalctl -u rosetta-upgrade.service -n 200 --no-pager
```

The gate copies the upload without following links, verifies its canonical manifest and
domain-separated signature, checks digest and predecessor, and extracts only bounded regular files
and directories. It builds and validates the new image before stopping the observer. The stopped
interval covers the consistent SQLite/evidence backup and atomic activation only. A fresh healthy,
safe, zero-write observation and the complete host/container/offline verifier must pass within five
minutes. Otherwise the previous release and image are restored and restarted automatically.

The state directory remains read-only inside the upgrade unit. After the observer stops, the gate
copies the SQLite database and present WAL/SHM sidecars into the root-only backup area and runs the
backup API there. Activation cannot proceed unless that frozen-copy backup passes SQLite integrity
checking.

The systemd sandbox exposes only the existing `staging.env` file as writable, not the surrounding
configuration directory or release signer allowlist. The gate renders replacement content under
the root-only backup directory, validates both source and destination as bounded root-owned regular
files without following links, writes through the existing file descriptor and flushes it to disk.
Rollback uses the same constrained write path.

An upstream version change does not itself require a Rosetta deployment. The running observer
records a safe `release_drift` compatibility warning and stays live. Only a reviewed baseline or
Rosetta code/configuration change enters this signed release path. Release signatures authorize
deployment of the exact read-only package only; public Technocore writes and production identity
remain separate gates.

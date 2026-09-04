# Deployment artifacts

These files are staging templates, not an authorization to deploy. Supply a reviewed
`python@sha256:...` base image, replace the synthetic signer mode with an operator-provisioned
secret boundary, and complete the cloud and public-write approval gates first.

`Dockerfile` pins reviewed Python and Node base digests and produces the combined local worker and
target image. `Dockerfile.node-adapters` produces the minimal Node profile image. Neither image is
published; local image IDs are recorded in `docs/LOCAL_MVP_STATUS.md`.

`Dockerfile.evolution-evaluator` is a separate fixed quality-gate image. It contains locked Python
and TypeScript tooling but no Rosetta candidate at build time. A candidate is mounted read-only at
runtime with no network, all capabilities dropped, a non-root UID and bounded tmpfs. Its local image
ID must be copied into `config/evolution.policy.yaml`; mutable tags are never evaluation authority.

The Compose profile has no public ports. The signer has `network_mode: none`; the local demo is
also offline. Production adapter runners are created by the supervisor from the reviewed registry,
using the non-root/read-only/no-mount policy recorded in each evidence run.

`compose.staging.yaml` is the first continuous, read-only profile. It starts a network-isolated
observer and a separate fixed-origin/fixed-path egress proxy, publishes no ports, mounts no secret
and contains no signer. `rosetta-observer.service` supervises both on the single pilot host. Follow
`docs/DEPLOYMENT.md`; do not enable public writes by editing this profile.

`rosetta-healthcheck.service`/`.timer` validate the read-only state without network access.
`rosetta-backup.service`/`.timer` create Age-encrypted snapshots using only a public recipient on the
server. `rosetta-signer.production.service` is a disabled template that loads a machine-encrypted
systemd credential. The host supervisor copies the decrypted 32-byte credential only into `/run`,
then starts the signer from one exact local OCI image ID as UID/GID 65531 with a read-only root,
all capabilities dropped and `--network none`. The signer container never receives the Docker
socket. Install the disabled boundary with `install-rosetta-signer.sh`; provision the credential
separately through stdin with `provision-rosetta-signer-credential.sh`. Neither action enables the
unit or authorizes production key creation, public signing or publication; follow
`docs/LAUNCH_RUNBOOK.md` and the separate key ceremony.

`rosetta-healthcheck-notify@.service` is an optional separate notifier for one exact
Healthchecks.io check. It receives only a ping URL credential and emits only success/failure; the
local validator itself remains networkless. `install-rosetta-operations.sh` installs, exercises and
enables the health and encrypted-backup timers from the immutable current release. It also creates
or validates the locked `rosetta-runtime` host identity at UID/GID 65532 and prepares a
traverse-only backup parent with a private encrypted-output directory.

`install-rosetta-upgrader.sh` performs the one-time installation of a root-owned signed-release
gate. `rosetta-upgrade.service` accepts only three fixed spool files and can be started by the
unprivileged deployment account through the narrow `rosetta-upgrade.sudoers` rule.
`rosetta-upgrade-apply.sh` builds before downtime, backs up state, atomically activates the reviewed
release, verifies a fresh zero-write observation and automatically restores the previous release on
failure. Its environment update can write only the existing root-owned file, never the surrounding
configuration directory or signer allowlist. See `docs/DEPLOYMENT.md`; release signing grants no
public-write or identity authority.

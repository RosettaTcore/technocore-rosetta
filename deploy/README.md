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
systemd credential into the networkless signer. None of these units authorize production key
creation, public signing or publication; follow `docs/LAUNCH_RUNBOOK.md` and the separate key
ceremony.

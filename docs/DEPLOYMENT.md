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

The repository now includes `deploy/Dockerfile`, `deploy/compose.yaml`, a hardened signer systemd
unit and a runner seccomp template. The Dockerfile has no mutable default base; a reviewed
`image@sha256:...` reference is mandatory at build time. These artifacts were not deployed.

Local Phase 3 validation used pinned Python 3.12.5 and Node 20.9.0 base digests, separate worker and
adapter images, the official Technocore v0.7.0 OCI image, and an internal Docker network with no host port.
All containers were removed after evidence capture; the images remain local for reproducibility.

## Service layout

- `rosetta-scheduler`: resolves immutable versions and queues runs.
- `rosetta-discovery`: polls the Technocore request mailbox, validates closed requests and delivers signed responses.
- `rosetta-runner-supervisor`: creates/destroys isolated ephemeral runners.
- `rosetta-signer`: networkless seed boundary and nonce state.
- `rosetta-egress`: exact origin allowlist with no body logging.
- `rosetta-publisher`: optional, separately approved, one destination only.
- local pinned Technocore target used for the full matrix.

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

## Operational access

- Cloud firewall denies all unnecessary ingress.
- Prefer private admin path or fixed management IPs.
- Separate cloud project and billing alert.
- No cloud API token inside Rosetta.
- Kill switch must work without entering scheduler or runner containers.

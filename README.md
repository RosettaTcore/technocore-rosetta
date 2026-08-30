# Technocore Rosetta

Technocore Rosetta is a deterministic interoperability observatory for Technocore integrations.
It executes the same signed mailbox workflow through independent runtime and adapter paths, detects
behavioral differences, and produces evidence bundles that can be verified offline.

The project is a complete local MVP with a reviewed read-only staging observer. It uses synthetic
identities and pinned local or reviewed upstream components. It does not contain a production DID,
cloud credentials, financial capabilities, or a model in the verdict path.

## What it verifies

- raw Node.js HTTP, official MCP, Python `httpx`, and TypeScript `fetch` interoperability;
- canonical signing and the official Technocore Ed25519 compatibility vector;
- restart and cursor recovery;
- bounded retry after HTTP 429 responses;
- reconciliation of uncertain writes without duplicate submission;
- deterministic evidence, checksums, hash chains, and domain-separated attestations;
- signed service discovery and closed-schema request, acknowledgement, and result messages;
- idempotency, quotas, kill switches, and persistent infrastructure quarantine;
- continuous fixed-origin protocol observation with restart-safe, content-addressed change records.

Rosetta reports observed behavior only. It does not assign reputation, certify agents, execute
request-supplied code, or accept request-supplied repositories, images, commands, or URLs.

## Security model

Adapter roles run in disposable containers as a non-root user with a read-only root filesystem,
dropped capabilities, bounded resources, and no host, secret, or container-socket mounts. The
signer is a separate networkless process with a narrow Unix-socket protocol. External publication,
service intake, and production identity use are disabled by default.

Controlled self-evolution is proposal-only. A candidate is bound to the complete source tree,
registry, policy, evaluator, parent evidence, and exact mutation bytes. It must pass the fixed
quality gates in a pinned networkless evaluator. Promotion and rollback require a separately held
operator signature; the checked-in trust list is empty.

See [`docs/SECURITY.md`](docs/SECURITY.md), [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md),
[`docs/SELF_EVOLUTION.md`](docs/SELF_EVOLUTION.md), and
[`docs/STAGING_SECURITY_REVIEW.md`](docs/STAGING_SECURITY_REVIEW.md) for the complete boundaries.

## Requirements

- Python 3.10 or newer;
- Node.js 20 or newer;
- Docker or another compatible OCI runtime for container acceptance tests.

## Local verification

Enable the repository-owned safety hooks once after cloning:

```sh
make install-hooks
```

The pre-push hook blocks accidental direct updates to `main`. Normal work is pushed to a feature
branch and merged through a pull request after CI passes. Git hooks are a local accident-prevention
control, not a substitute for server-side branch protection.

Create the development environment and run the complete host-side acceptance gate:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-dev.lock
npm --prefix adapters ci
make acceptance PYTHON=.venv/bin/python
```

Run the official upstream Technocore matrix in isolated containers:

```sh
PYTHONPATH=src .venv/bin/python tools/upstream_acceptance.py \
  --output artifacts/upstream-acceptance --soak-iterations 20
```

Run and verify the deterministic local demonstration:

```sh
PYTHONPATH=src .venv/bin/python -m rosetta.cli demo --output artifacts/demo
PYTHONPATH=src .venv/bin/python -m rosetta.cli verify artifacts/demo/bundle
```

Generated artifacts and runtime state remain under ignored `artifacts/` and `local/` directories.
Commands refuse unsafe or non-empty output targets where replacement would be ambiguous.

## Quality baseline

The current local baseline includes:

- 185 passing Python tests;
- 95.01% branch-aware Python coverage with a 90% enforced floor;
- strict Ruff, Mypy, and TypeScript checks;
- transitive, hash-locked Python dependencies with no known OSV vulnerabilities at the recorded
  audit time;
- official four-runtime matrix and 20-iteration soak passes;
- 27 live OCI isolation checks;
- a verified signed evolution proposal that does not mutate the live project;
- a containerized read-only observer restart/kill-switch smoke test with zero public writes.

Exact local image identities and verification results are recorded in
[`docs/LOCAL_MVP_STATUS.md`](docs/LOCAL_MVP_STATUS.md). Image IDs are architecture-specific and must
be rebuilt and revalidated on another host.

## Repository map

- `src/rosetta/`: orchestration, contracts, adapters, evidence, operations, and service protocol;
- `src/rosetta_signer/`: canonical signing and the isolated signer service;
- `adapters/`: independent Python and Node.js adapter implementations;
- `config/`: closed local profiles, registries, policies, and immutable upstream identities;
- `tests/`: unit, integration, and adversarial suites;
- `tools/`: local acceptance, isolation, backup, and secret-scanning utilities;
- `deploy/`: non-production container and service templates;
- `vendor/`: the exact reviewed Technocore source used for offline provenance.

## Deployment status

The checked-in deployment files provide a no-ingress, read-only staging profile but do not
authorize public writes. Production key generation, public request intake, Technocore writes and
report publication remain separate operator-approved release gates.

The controlled sequence, 72-hour review, encrypted-backup preparation and remaining operator inputs
are in [`docs/LAUNCH_RUNBOOK.md`](docs/LAUNCH_RUNBOOK.md). Production identity handling is specified
separately in [`docs/PRODUCTION_KEY_CEREMONY.md`](docs/PRODUCTION_KEY_CEREMONY.md); no production key
is present or authorized.

## License

Technocore Rosetta is licensed under the Apache License 2.0. Vendored third-party components retain
their own copyright and attribution notices; see [`NOTICE`](NOTICE) and the files under `vendor/`.

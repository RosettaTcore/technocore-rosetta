# Technocore Rosetta

[![CI](https://github.com/RosettaTcore/technocore-rosetta/actions/workflows/ci.yml/badge.svg)](https://github.com/RosettaTcore/technocore-rosetta/actions/workflows/ci.yml)
[Apache-2.0](LICENSE) · Python 3.10–3.12 · deterministic verdicts · dry-run by default

![Four independent runtime paths converge through Rosetta into one evidence bundle.](site/assets/rosetta-social-card.jpg)

**One signed workflow. Four independent paths. Evidence you can replay.**

Technocore Rosetta is an autonomous interoperability observatory. Before an integrator upgrades
Technocore or an adapter, Rosetta runs the complete signed mailbox workflow across independent
runtime paths, detects behavioral drift and produces a signed evidence bundle that can be verified
offline.

Rosetta complements protocol vectors and conformance suites. Its focus is the stateful behavior
around a real mailbox roundtrip: restart and cursor recovery, HTTP 429 handling, uncertain-write
reconciliation, differential reads and exactly-once confirmation.

> **Current status:** complete local MVP and reviewed read-only staging observer. The checked-in
> launch evidence uses a deterministic synthetic identity and performs zero public writes. Public
> request intake, production identity use and publication remain separately approved release gates.

## See the proof first

Preview the static launch observatory with only Python's standard library:

```sh
make site-preview
```

Open <http://127.0.0.1:4173/> and select **Verify live evidence**. The page fetches only the bounded
reference files from its own origin, then recomputes every digest, the bundle root and the Ed25519
attestation in the browser. No account, install, upload or model is involved. Downloading a bundle
is an optional advanced path for an independent offline audit, not a prerequisite for using the
observatory.

The same launch surface can be checked non-interactively:

```sh
make site-check
```

That gate validates the site's security boundary, deterministic archive, exact bundle root and real
Ed25519 attestation. It also exercises both the instant same-origin verifier and the independent
file verifier against valid, mutated, extra-file, cross-origin and substituted-signature cases.

| Reviewed reference | Result |
|---|---|
| Protocol target | Technocore v0.10.0 |
| Runtime paths | raw Node.js HTTP, official MCP, Python `httpx`, TypeScript `fetch` |
| Matrix | 4 of 4 cells pass |
| Deterministic assertions | 29 pass |
| Isolated read soak | 20 of 20 pass |
| Public writes | 0 |
| Bundle root | [`sha256:0b3435df…43c1b9f`](site/evidence/latest/attestation.json) |

The reference is synthetic, dry-run evidence. Its signature establishes byte integrity and signer
control only—not safety, trust, endorsement, affiliation or eligibility for a reward.

## Why workflow-level evidence

A valid signature proves that specific bytes were signed. It does not prove that a multi-step
integration survives the edges of a stateful workflow. Rosetta evaluates this closed scenario:

```text
discover capabilities
  -> create signed mailbox request
  -> read and correlate through a second adapter
  -> post signed result
  -> force restart and resume cursor
  -> absorb one bounded 429
  -> reconcile an uncertain write before retrying
  -> confirm the result exactly once
  -> attest the complete evidence bundle
```

Every verdict is produced by deterministic assertions and stable reason codes. No language model
participates in pass, fail, skip, error, minimization or attestation.

Rosetta is built for:

- **integrators** making upgrade decisions from exact, versioned evidence;
- **maintainers** receiving bounded transcripts and minimal reproductions;
- **agent operators** verifying observed interoperability without trusting a prose summary.

The dated ecosystem review and deliberately bounded positioning are documented in
[`RESEARCH.md`](RESEARCH.md) and [`docs/UNIQUENESS_STRATEGY.md`](docs/UNIQUENESS_STRATEGY.md).

## What it verifies

- raw Node.js HTTP, official MCP, Python `httpx` and TypeScript `fetch` interoperability;
- canonical signing and the official Technocore Ed25519 compatibility vector;
- restart and cursor recovery;
- bounded retry after HTTP 429 responses;
- reconciliation of uncertain writes without duplicate submission;
- deterministic evidence, checksums, hash chains and domain-separated attestations;
- signed service discovery and closed-schema request, acknowledgement and result messages;
- idempotency, quotas, kill switches and persistent infrastructure quarantine;
- continuous fixed-origin protocol observation with restart-safe, content-addressed change records.

Rosetta reports observed behavior only. It does not assign reputation, certify agents, execute
request-supplied code, or accept request-supplied repositories, images, commands or URLs.

## Security model

Adapter roles run in disposable containers as a non-root user with a read-only root filesystem,
dropped capabilities, bounded resources and no host, secret or container-socket mounts. The signer
is a separate networkless process with a narrow Unix-socket protocol. External publication, service
intake and production identity use are disabled by default.

Controlled self-evolution is proposal-only. A candidate is bound to the complete source tree,
registry, policy, evaluator, parent evidence and exact mutation bytes. It must pass the fixed quality
gates in a pinned networkless evaluator. Promotion and rollback require a separately held operator
signature; the checked-in trust list is empty.

Read the complete boundaries in:

- [`docs/SECURITY.md`](docs/SECURITY.md)
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- [`docs/SELF_EVOLUTION.md`](docs/SELF_EVOLUTION.md)
- [`docs/STAGING_SECURITY_REVIEW.md`](docs/STAGING_SECURITY_REVIEW.md)

## Full local verification

Requirements:

- Python 3.10 or newer;
- Node.js 20 or newer;
- Docker or another compatible OCI runtime for container acceptance tests.

Enable the repository-owned safety hooks once after cloning:

```sh
make install-hooks
```

The pre-push hook blocks accidental direct updates to `main`. Normal work is pushed to a feature
branch and merged through a pull request after CI passes. Git hooks are an accident-prevention
control, not a substitute for server-side branch protection.

Create the hash-locked development environment and run the complete host-side acceptance gate:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-dev.lock
npm --prefix adapters ci
make acceptance PYTHON=.venv/bin/python
```

Run the pinned upstream Technocore matrix in isolated containers:

```sh
PYTHONPATH=src .venv/bin/python tools/upstream_acceptance.py \
  --output artifacts/upstream-acceptance --soak-iterations 20
```

Run and independently verify the deterministic local demonstration:

```sh
PYTHONPATH=src .venv/bin/python -m rosetta.cli demo --output artifacts/demo
PYTHONPATH=src .venv/bin/python -m rosetta.cli verify artifacts/demo/bundle
```

Generated artifacts and runtime state remain under ignored `artifacts/` and `local/` directories.
Commands refuse unsafe or non-empty output targets where replacement would be ambiguous.

## Quality baseline

The current measured baseline includes:

- 185 passing Python tests;
- 95.01% branch-aware Python coverage with a 90% enforced floor;
- strict Ruff, Mypy and TypeScript checks;
- transitive, hash-locked Python dependencies;
- official four-runtime matrix and 20-iteration soak passes;
- 27 live OCI isolation checks;
- a verified signed evolution proposal that does not mutate the live project;
- a containerized read-only observer restart/kill-switch smoke test with zero public writes.

Exact local image identities and verification results are recorded in
[`docs/LOCAL_MVP_STATUS.md`](docs/LOCAL_MVP_STATUS.md). Image IDs are architecture-specific and must
be rebuilt and revalidated on another host.

## Repository map

- `src/rosetta/`: orchestration, contracts, adapters, evidence, operations and service protocol;
- `src/rosetta_signer/`: canonical signing and the isolated signer service;
- `adapters/`: independent Python and Node.js adapter implementations;
- `config/`: closed local profiles, registries, policies and immutable upstream identities;
- `tests/`: unit, integration, adversarial and launch-site suites;
- `tools/`: acceptance, isolation, backup, packaging and secret-scanning utilities;
- `deploy/`: non-production container and service templates;
- `site/`: static read-only launch observatory and synthetic reference evidence;
- `vendor/`: exact reviewed Technocore source used for offline provenance.

## Deployment status

The checked-in deployment files provide a no-ingress, read-only staging profile. They do not
authorize public writes. Production key generation, public request intake, Technocore writes and
report publication remain separate operator-approved release gates.

The controlled launch sequence, 72-hour review, encrypted-backup preparation and remaining inputs
are in [`docs/LAUNCH_RUNBOOK.md`](docs/LAUNCH_RUNBOOK.md). Production identity handling is specified
separately in [`docs/PRODUCTION_KEY_CEREMONY.md`](docs/PRODUCTION_KEY_CEREMONY.md); no production key
is present or authorized.

## Audit and feedback

Start with the [reference evidence](site/evidence/latest), the
[acceptance specification](docs/ACCEPTANCE_TESTS.md) and the
[security model](docs/SECURITY.md). If an observed claim cannot be reproduced, open a
[GitHub issue](https://github.com/RosettaTcore/technocore-rosetta/issues/new/choose) with the exact command,
platform and bundle root. Never include credentials, private mailbox capabilities or key material.

## License

Technocore Rosetta is licensed under the Apache License 2.0. Vendored third-party components retain
their own copyright and attribution notices; see [`NOTICE`](NOTICE) and the files under `vendor/`.

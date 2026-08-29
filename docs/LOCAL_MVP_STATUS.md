# Local MVP status

Date: 29 August 2026

## Outcome

Phases 0–3 plus the controlled evolution proposal lane are implemented. The authoritative local
acceptance path runs the official
Technocore `v0.7.0` image rather than Rosetta's behavioral fixture. No public Technocore endpoint,
cloud runtime, production DID, publisher or live Technocore write was used. Source control uses a
dedicated private GitHub repository and identity, separate from the operator's other projects.

## Implemented

- exact upstream source archive vendored with source, lock and OCI provenance;
- four independent runtime paths: Node `http`, official MCP 0.7.0, Python `httpx`, and
  TypeScript/Node `fetch`;
- direct signed HTTP boundary for MCP, matching the upstream MCP's deliberate no-private-key rule;
- separate disposable non-root/read-only containers for every matrix operation on an internal-only
  network, with no host ports, mounts, secrets or Docker socket;
- official Ed25519 vector imported from upstream tests and verified byte-for-byte by both
  implementations, including mutation rejection;
- signed mailbox round-trip, cursor restart, exact correlation, deterministic 429 retry,
  post-commit disconnect reconciliation and differential reads;
- deterministic evidence model, hash chains, checksums, offline Ed25519 attestation and regression
  reproduction;
- signed local service card and discovery/request/ack/result protocol with transactional quotas and
  idempotency;
- shared kill switch, daily run/monthly cost limits, bounded parallelism and persistent
  three-failure quarantine across scheduler, runner, signer, service and publisher;
- closed self-evolution candidates bound to the complete source base, registry, parent evidence,
  policy, evaluator and exact mutation bytes;
- pinned networkless evolution evaluator with six fixed gates, signed proposal lineage, empty-by-
  default operator trust, cryptographic promotion/rollback approval and crash-recoverable backups;
- deployment/container templates, secret scan, backup rehearsal and operator documentation.

## Verified results

- Pytest: 119/119 pass;
- branch-aware Python coverage: 93.85%, enforced floor 90%;
- Ruff lint/security: pass;
- Mypy strict: pass for 28 source modules;
- TypeScript strict check: pass;
- secret scan: pass over 151 files;
- official upstream matrix: 4/4 cells pass;
- upstream soak: 20/20 isolated reads pass;
- simultaneous four-runtime isolated reads: pass;
- deterministic 429 retry observed: pass;
- uncertain write reconciled with no retry: pass;
- signed upstream bundle verification: pass;
- upstream bundle root:
  `sha256:c76200e6087a56537743e9b7b301baf3f6c41d074beeaae6033177e212a6be7b`;
- live OCI isolation: 27/27 checks pass;
- rebuilt worker image after the coverage ratchet:
  `sha256:0daac106f36240564ceb8d5d90a044236f8fe5d84ccbf1ebddc233b3858dd447`;
- local discovery/service/idempotency demo: pass with zero public writes;
- local service bundle root:
  `sha256:e8f82d0630074a00d8eb07a4d2d3ec656d8e88d11b69f56e5f2e8e622faa5e6b`.
- real evolution evaluator: all six gates pass with no network, read-only source, non-root UID,
  dropped capabilities and bounded resources;
- evolution proposal verification: pass; state `awaiting_human_approval`, live project unchanged,
  automatic promotion false;
- evolution evaluator image:
  `sha256:cfca6bca3c306f715b9db6b8fa81dcc8e8aa5b1d69f593b0dfbf021988f93abd`.

## Remaining production-only work

- independent operator security review and a longer multi-hour/day soak;
- production key-generation/recovery ceremony and secret-store provisioning;
- operator approval-key ceremony and addition of its public DID to protected evolution policy;
- dedicated hosting, alert delivery, encrypted backups and egress proxy;
- fresh landscape/uniqueness check immediately before launch;
- separately approved read-only staging, then separately approved public signed writes and static
  publication.

The repository is version-controlled in its dedicated private remote. CI and deployment files do
not authorize a deployment, production identity, public service intake or external publication.

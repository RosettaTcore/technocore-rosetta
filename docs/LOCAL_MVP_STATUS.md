# Local MVP status

Date: 30 August 2026

## Outcome

Phases 0–3 plus the controlled evolution proposal lane are implemented. The authoritative local
acceptance path runs the official Technocore `v0.10.0` image while preserving the original v0.7.0
fixture and evidence for historical replay. No public Technocore write,
production DID, publisher or public service intake was used. Source control uses a
dedicated private GitHub repository and identity, separate from the operator's other projects.
The no-ingress read-only observer is running on its dedicated staging host; its 72-hour gate is not
yet complete.

## Implemented

- exact upstream source archive retained with a minimal vendored runtime subset, lock and OCI
  provenance;
- four independent runtime paths: Node `http`, official MCP 0.10.0, Python `httpx`, and
  TypeScript/Node `fetch`;
- direct signed HTTP boundary for MCP, matching the upstream MCP's deliberate no-private-key rule;
- separate disposable non-root/read-only containers for every matrix operation on an internal-only
  network, with no host ports, mounts, secrets or Docker socket;
- official Ed25519 vectors imported from v0.7.0 and v0.10.0 and verified byte-for-byte across
  Rosetta, the former OpenSSL verifier and current libsodium/PyNaCl verifier, including mutation
  rejection;
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
- deployment/container templates, secret scan, backup rehearsal, fail-closed staging status check,
  encrypted-backup/health timer templates and operator documentation;
- strict production seed-file loading and a networkless systemd signer template without generating
  or storing a production seed;
- universal Python 3.10+ transitive hash locks and a reproducible lock-drift gate;
- long-running read-only observer with fixed-path egress, restart deduplication, atomic health/
  evidence state, host kill switch and one-server staging artifacts.

## Verified results

- Pytest: 185/185 pass;
- branch-aware Python coverage: 95.01%, enforced floor 90%;
- Ruff lint/security: pass;
- Mypy strict: pass for 31 source modules;
- TypeScript strict check: pass;
- secret scan: pass over 198 files;
- fresh install from the development hash lock: pass; `pip check`: pass;
- recorded runtime dependency OSV batch query: no known vulnerabilities;
- official upstream matrix: 4/4 cells pass;
- upstream soak: 20/20 isolated reads pass;
- simultaneous four-runtime isolated reads: pass;
- deterministic 429 retry observed: pass;
- uncertain write reconciled with no retry: pass;
- signed upstream bundle verification: pass;
- upstream v0.10.0 bundle root:
  `sha256:0b3435df9b0f6eb8b1ac2eaab22120a0b14730764fceaa9d1a701860f43c1b9f`;
- live OCI isolation: 27/27 checks pass;
- launch-readiness runtime image:
  `sha256:e45c4429997ea36a9bbeb2b0bd152ad50e8b9edc872bc29a30d79a3e8082fd6e`;
- launch-readiness Python adapter image:
  `sha256:a5e5592ae4213931d470d54e67642fff95d08e15d6430d491a3042670d1c7b15`;
- local discovery/service/idempotency demo: pass with zero public writes;
- local service bundle root:
  `sha256:df2b05c5ab3d1c12c266287b51f92fcd00f1936e6dadbaabab9d27a5dafd9c16`;
- real evolution evaluator: all six gates pass with no network, read-only source, non-root UID,
  dropped capabilities and bounded resources;
- evolution proposal verification: pass; state `awaiting_human_approval`, live project unchanged,
  automatic promotion false;
- evolution evaluator image:
  `sha256:cfca6bca3c306f715b9db6b8fa81dcc8e8aa5b1d69f593b0dfbf021988f93abd`;
- read-only observer/egress Compose validation: pass, with no public ports, secrets, Docker socket
  or direct worker egress;
- observer container smoke: initial change evidence pass, restart deduplication pass, kill switch
  pass and `public_writes: 0` throughout;
- deployed observer check on 30 August 2026: service active/enabled, zero restarts, healthy
  `dry_run` state and `public_writes: 0`; the deployed commit remains `4d2a374...` until this
  launch-readiness change is reviewed and merged.

## Remaining production-only work

- completion and human review of the running 72-hour staging soak;
- production key-generation/recovery ceremony and secret-store provisioning;
- operator approval-key ceremony and addition of its public DID to protected evolution policy;
- external alert delivery and an independently controlled encrypted off-device backup destination;
- branding artwork and public contact-surface approval;
- static publication destination, bounded public intake and exact first signed payload approvals;
- production deployment of the reviewed, signed release after all applicable gates pass.

The repository is version-controlled in its dedicated private remote. CI and deployment files do
not authorize a deployment, production identity, public service intake or external publication.

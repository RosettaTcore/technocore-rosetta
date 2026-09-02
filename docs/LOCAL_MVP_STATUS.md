# Local MVP status

Date: 3 September 2026

## Outcome

Phases 0–3 plus the controlled evolution proposal lane are implemented. The authoritative local
acceptance path runs the official Technocore `v0.10.0` image while preserving the original v0.7.0
fixture and evidence for historical replay. No public Technocore write,
production DID, publisher or public service intake was used. Source control uses a
dedicated public GitHub repository and identity, separate from the operator's other projects.
The no-ingress read-only observer is running on its dedicated staging host. The 1 September check
verified its zero-write safety boundary while upstream availability was degraded; safety and
compatibility are now independent verdicts, so external release churn does not reset the safety
window.

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
  evidence state, host kill switch and one-server staging artifacts;
- public read-only observatory with canonical metadata, no-download same-origin evidence
  verification, optional offline audit, sitemap and a CI-gated GitHub Pages workflow.
- signed, predecessor-bound remote release packages, a root-owned fixed-path deployment gate,
  pre-downtime image validation, consistent state backup, fresh post-activation verification and
  automatic rollback without routine provider-console access or general deployment-user `sudo`.

## Verified results

- Pytest: 228/228 pass;
- branch-aware Python coverage: 95.14%, enforced floor 90%; observer coverage: 99%;
- Ruff lint/security: pass;
- Mypy strict: pass for 31 source modules;
- TypeScript strict check: pass;
- secret scan: pass over 238 files;
- fresh install from the development hash lock: pass; `pip check`: pass;
- recorded runtime dependency OSV batch query: no known vulnerabilities;
- official upstream matrix: 4/4 cells pass;
- upstream soak: 20/20 isolated reads pass;
- simultaneous four-runtime isolated reads: pass;
- deterministic 429 retry observed: pass;
- uncertain write reconciled with no retry: pass;
- deterministic next-upstream canary: pass across baseline, additive `v0.11.0` drift, 429, 503,
  rejected authority metadata and recovery; 6/6 safety checkpoints safe, zero writes and no restart;
- unexpected internal probe fault: process survives and recovers on the next cycle without restart,
  while the failed cycle remains durably unsafe as required;
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
- deployed observer check on 1 September 2026: service active/enabled, zero restarts, `dry_run`,
  `public_writes: 0`, SSH-only public listener and 7% disk use; all watched upstream endpoints
  returned 503, recorded separately as an availability warning;
- deployed observer upgrade rehearsal on 2 September 2026: reviewed commit
  `bdd95d614eb7c9ac1ef9b45046e7f421f8437970`, immutable image
  `sha256:a1703bf5674d76749181cd44c2992d3809663e4378fe7ad64484b0cf460e996f`, two expected
  healthy containers, fresh `safe` observation, zero public writes and an explicit
  `release_drift` compatibility warning for upstream v0.11.3;
- transitional 72-hour Gate B review: pass after 73 hours and 34 minutes, combining the truthful
  v1 interval with v2 safety checkpoints; zero public writes, no unexplained restarts, SSH-only
  public listeners and 9% disk use;
- signed remote deployment on 3 September 2026: reviewed commit
  `db810b15954cef1bbecfa8f25e4000ec40d16092`, immutable image
  `sha256:d19fd4871c9c9ca0168e13b2e67b3dc8d60dd7a8f3c5e181494d6af5faa3dd00`, complete live verifier
  pass, two healthy expected containers, current safe observation and zero public writes;
- GitHub Pages project-subpath QA: desktop and 390×844 mobile pass; all relative assets load and
  the one-click verifier validates the 15-file reference bundle;
- public Pages deployment: success from reviewed `main` commit `8ddaee9` in workflow run
  `33446317758`; the live verifier reproduced
  `sha256:0b3435df9b0f6eb8b1ac2eaab22120a0b14730764fceaa9d1a701860f43c1b9f` and accepted the
  domain-separated Ed25519 attestation.

## Remaining production-only work

- installation and exercise of the periodic healthcheck and encrypted-backup timers;
- production key-generation/recovery ceremony and secret-store provisioning;
- operator approval-key ceremony and addition of its public DID to protected evolution policy;
- external alert delivery and an independently controlled encrypted off-device backup destination;
- public contact-surface approval, including whether the Proton address is published;
- bounded public intake and exact first signed payload approvals;
- production deployment of the reviewed, signed release after all applicable gates pass.

The repository and static observatory are public. This publication does not authorize a production
identity, public service intake, Technocore writes or any broader external action.

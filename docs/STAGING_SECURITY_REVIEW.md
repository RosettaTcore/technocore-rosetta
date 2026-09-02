# Read-only staging security and effectiveness review

Date: 3 September 2026

## Assessment

The staging observer passed its transitional 72-hour read-only gate on the dedicated pilot server.
The static observatory and no-ingress observer are suitable to remain publicly available. Rosetta
is intentionally not yet a public service agent: it has no production identity, signing process,
request intake, publisher or Technocore write path.

The implementation is effective for its present purpose. It continuously proves Rosetta's local
zero-write safety boundary and independently reports whether the fixed-origin Technocore metadata
is compatible, changed, unavailable or rejected. It records a new content-addressed observation
only when valid bytes change, survives restarts without duplicate evidence and exposes bounded
health plus compatibility records for host monitoring.

## Verified controls

- the observer container has no direct outbound network and no host port;
- a separate egress container permits only three fixed paths on one fixed HTTPS origin;
- redirects, queries, arbitrary paths, responses over 1 MiB and all non-GET methods are rejected;
- both containers run as UID/GID 65532 with read-only roots, all capabilities dropped,
  `no-new-privileges`, PID/memory/CPU limits and bounded tmpfs;
- neither container mounts a secret, Docker socket, source tree, signer state or production key;
- public content is parsed only as bounded data and never as instructions or executable input;
- service identity and authority must match; manifest and OpenAPI releases must agree before a new
  release is recorded as drift rather than silently promoted;
- SQLite persistence deduplicates protocol digests across restarts;
- health and evidence files are atomically replaced with mode `0600`;
- external exception details are not logged; only closed failure categories reach health state;
- the host-visible kill switch stops observation before another request;
- Docker health checks cover egress readiness and observer freshness/zero-write safety state;
- no model participates in probing, validation, change detection or any verdict.
- the observed v0.10.0 release is bound to a verified GitHub commit, exact archived source,
  dependency lock and immutable multi-platform OCI index before the observer is enabled.

## Residual risk and compensating controls

- DNS and public TLS certificate authorities remain external dependencies. HTTPS verification,
  fixed origin checks and rejection of redirects limit but do not eliminate that trust.
- The egress proxy is deliberately dual-homed. A proxy defect could broaden network access, so its
  allowlist is code-level, tested adversarially and must remain human-reviewed authority code.
- The host Docker daemon is privileged. Rosetta containers receive no socket, while administrative
  Docker access remains limited to the hardened host account and root service manager.
- Local evidence is not yet externally replicated. Provider backups protect the server; encrypted
  off-device application backup remains a gate before public identity or writes.
- An unsafe Docker container is visible but does not send an external alert by itself. During the
  initial stage the operator must review service status and `health.json`; an alert destination
  should be configured before the controlled public pilot.
- Three metadata endpoints prove protocol visibility, not full live write interoperability. The
  complete four-runtime matrix remains offline until a separately approved public-write pilot.

## 72-hour review result

The review covered 30 August 2026 21:14 UTC through 2 September 2026 22:48 UTC, a 73-hour,
34-minute observation period. The host had remained up since 29 August 2026 23:34 UTC. The initial
v1 interval truthfully recorded zero writes, zero restarts, an SSH-only public listener and bounded
disk while upstream returned HTTP 503. After the reviewed v2 safety/compatibility migration, each
deployment verification recorded a fresh `safe` observation and zero writes. Two failed upgrade
rehearsals stopped and restored the service through the documented transactional rollback; these
are explained maintenance events, not unexplained restarts or unsafe checks.

The final signed deployment activated commit `db810b15954cef1bbecfa8f25e4000ec40d16092` as immutable
image `sha256:d19fd4871c9c9ca0168e13b2e67b3dc8d60dd7a8f3c5e181494d6af5faa3dd00`. Its independent
post-activation verifier passed with two healthy expected containers, current observation,
`safety_status: safe`, `public_writes: 0`, intact SQLite state, bounded evidence, no kill switch and
the exact container isolation policy. The service was active and enabled with `NRestarts=0`; disk
use was 9%; public TCP listeners were SSH only, with one additional loopback-only listener.

Upstream v0.11.3 is recorded as `release_drift`. This is a compatibility warning and is not promoted
to the v0.10.0 execution baseline. Under the migration rule in `LAUNCH_RUNBOOK.md`, the reviewed
legacy interval plus truthful v2 checkpoints passes Gate B for the read-only surface. It does not
pass Gates C–F or authorize a public identity, intake, signing, publication to Technocore, or any
write.

## Launch gate

Proceed with read-only staging only when the reviewed image digest, rendered Compose configuration,
CI result and host listener inventory all match the deployment record. During the initial safety
window, require fresh safety-safe checks, zero public writes, zero unexplained restarts and bounded
disk growth. Availability or release warnings stay visible and require compatibility review before
execution promotion, but do not reset the read-only window. Any ambiguity about Rosetta's own
safety boundary activates the kill switch and returns the server to the previous immutable release.
Before a write-capable pilot, install and exercise the periodic healthcheck and encrypted-backup
timers, test an independently controlled off-device restore, add an external alert destination,
complete the production identity ceremony and obtain the remaining per-boundary approvals.

# Read-only staging security and effectiveness review

Date: 30 August 2026

## Assessment

The staging observer is suitable for a bounded 72-hour read-only launch on the dedicated pilot
server after ordinary pull-request review and green CI. It is intentionally not yet a public
service agent: it has no production identity, signing process, request intake, publisher or
Technocore write path.

The implementation is effective for its present purpose. It continuously proves that the pinned
Technocore release is healthy and that its two machine-readable protocol descriptions remain
available, internally consistent and byte-stable. It records a new content-addressed observation
only when those bytes change, survives restarts without duplicate evidence and exposes a bounded
health record for host monitoring.

## Verified controls

- the observer container has no direct outbound network and no host port;
- a separate egress container permits only three fixed paths on one fixed HTTPS origin;
- redirects, queries, arbitrary paths, responses over 1 MiB and all non-GET methods are rejected;
- both containers run as UID/GID 65532 with read-only roots, all capabilities dropped,
  `no-new-privileges`, PID/memory/CPU limits and bounded tmpfs;
- neither container mounts a secret, Docker socket, source tree, signer state or production key;
- public content is parsed only as bounded data and never as instructions or executable input;
- release and service identity must match the pinned authority before an observation is accepted;
- SQLite persistence deduplicates protocol digests across restarts;
- health and evidence files are atomically replaced with mode `0600`;
- external exception details are not logged; only closed failure categories reach health state;
- the host-visible kill switch stops observation before another request;
- Docker health checks cover egress readiness and observer freshness/zero-write state;
- no model participates in probing, validation, change detection or any verdict.

## Residual risk and compensating controls

- DNS and public TLS certificate authorities remain external dependencies. HTTPS verification,
  fixed origin checks and rejection of redirects limit but do not eliminate that trust.
- The egress proxy is deliberately dual-homed. A proxy defect could broaden network access, so its
  allowlist is code-level, tested adversarially and must remain human-reviewed authority code.
- The host Docker daemon is privileged. Rosetta containers receive no socket, while administrative
  Docker access remains limited to the hardened host account and root service manager.
- Local evidence is not yet externally replicated. Provider backups protect the server; encrypted
  off-device application backup remains a gate before public identity or writes.
- An unhealthy Docker container is visible but does not send an external alert by itself. During
  the 72-hour stage the operator must review service status and `health.json`; an alert destination
  should be configured before the controlled public pilot.
- Three metadata endpoints prove protocol visibility, not full live write interoperability. The
  complete four-runtime matrix remains offline until a separately approved public-write pilot.

## Launch gate

Proceed with read-only staging only when the reviewed image digest, rendered Compose configuration,
CI result and host listener inventory all match the deployment record. During the first 72 hours,
require current healthy observations, zero public writes, zero unexplained restarts, bounded disk
growth and human review of every new protocol digest. Any ambiguity activates the kill switch and
returns the server to the previous immutable release.

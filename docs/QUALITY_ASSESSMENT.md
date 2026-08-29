# Quality and effectiveness assessment

Date: 26 August 2026

## Bottom line

Rosetta is a strong local MVP and a credible foundation for a staged pilot. It is effective at its
narrow job: detecting whether a signed Technocore mailbox workflow interoperates across materially
different runtimes and producing evidence another operator can verify offline. It is not yet a
production service and has not demonstrated longitudinal value on real release changes.

| Dimension | Score | Evidence and caveat |
|---|---:|---|
| Protocol correctness | 9.0/10 | Official v0.7.0 target, source and signer vector; four real paths. The service does not retain signatures, so evidence correctly preserves the signed request. |
| Security boundaries | 9.1/10 | Non-root/read-only containers, internal-only network, no secrets/mounts/socket, networkless signer, closed registry and shared kill switch. Evolution cannot rewrite its authority and needs a trusted external signature. Production key ceremonies are intentionally absent. |
| Interoperability signal | 8.7/10 | Four cross-runtime cells plus differential reads and real MCP. One protocol release and one primary scenario limit breadth. |
| Reliability | 8.6/10 | Restart, cursor, 429, uncertain writes, idempotency, crash-persistent controls, atomic evolution preflight/recovery, simultaneous four-runtime reads and a 20-iteration soak pass. This is not a long-duration load test. |
| Reproducibility/auditability | 9.3/10 | Exact source/archive/lock/OCI identities, canonical artifacts, checksums, signed roots and evolution lineage binding the complete base/policy/evaluator. Local image IDs must be rebuilt and re-recorded on another host. |
| Test quality | 9.3/10 | 122 tests, adversarial/property coverage, signature/package mutation, CI, local-push and dependency-update authority constraints, approval and rollback boundaries, 93.85% branch-aware coverage with a 90% ratchet, and 27 OCI checks. No full mutation-testing engine or high-volume stress campaign yet. |
| Operations | 8.5/10 | Atomic quotas/budgets, persistent quarantine, bounded concurrency, backup rehearsal, safe defaults and cryptographically gated reversible promotion. No deployed alerting or operator rotation exists locally. |
| Production readiness | 6.0/10 | Deployment artifacts exist, but hosting, production identity, monitoring, public discovery and external publication remain intentionally unprovisioned. |

Overall local-MVP quality: **9.0/10**. Current public-production readiness: **6.0/10**.

## Expected effectiveness

Rosetta should reliably catch signature/canonicalization drift, cursor regressions, MCP/HTTP
rendering differences, retry mistakes and duplicate writes before an integration upgrade ships. Its
evidence is useful to maintainers because it identifies the exact target, adapter source, runtime,
image and failed assertion without using a model to decide the verdict.

The main unproven hypothesis is adoption: no real maintainer or external agent has yet consumed a
report or requested a test. The next value gate is therefore a read-only staging period followed,
only with approval, by a small public pilot measuring report use and regressions found—not more
features by default.

The evolution lane improves maintainability without placing a model in authority: it can convert a
known failure into a contained, signed, reproducible candidate and makes stale-base or self-approval
attempts fail closed. Its effectiveness is not yet longitudinally proven. No candidate has been
promoted on the authoritative tree, no real operator approval key exists, and a passing gate set is
evidence for one exact base—not proof that a change is strategically desirable or production-safe.

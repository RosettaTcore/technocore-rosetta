# Quality and effectiveness assessment

Date: 13 September 2026

## Bottom line

Rosetta is a strong local MVP, a live read-only product and an active bounded public-service pilot.
It is effective at its
narrow job: detecting whether a signed Technocore mailbox workflow interoperates across materially
different runtimes and producing evidence another operator can verify offline. One external
synthetic request now proves the public path end to end; longitudinal value and organic adoption
remain unproven.

| Dimension | Score | Evidence and caveat |
|---|---:|---|
| Protocol correctness | 9.6/10 | Official v0.13.0 target plus retained v0.7.0/v0.10.0 history, exact source/OCI provenance, generation-safe cursors, locally verified signed records and four real paths. |
| Security boundaries | 9.3/10 | Non-root/read-only containers, internal-only network, no secrets/mounts/socket, networkless signer, strict seed-file loader, closed registry and shared kill switch. Evolution cannot rewrite its authority and needs a trusted external signature. The production seed remains confined to the encrypted signer credential boundary. |
| Interoperability signal | 9.0/10 | Four cross-runtime cells, differential reads and real MCP now pass on a second protocol baseline. One primary scenario still limits breadth. |
| Reliability | 8.6/10 | Restart, cursor, 429, uncertain writes, idempotency, crash-persistent controls, atomic evolution preflight/recovery, simultaneous four-runtime reads and a 20-iteration soak pass. This is not a long-duration load test. |
| Reproducibility/auditability | 9.7/10 | Exact v0.13.0 tag/commit, archive and upstream lock, universal transitive hash locks, cross-platform OCI identities, separate real MCP SDK image, canonical artifacts, signed roots and evolution lineage. |
| Test quality | 9.7/10 | 389 tests, adversarial/property coverage, immutable-upstream checks, signature/backend parity, CI and authority constraints, 93% combined line/branch coverage with a 90% ratchet and 27 OCI checks. No full mutation-testing engine or high-volume stress campaign yet. |
| Operations | 9.5/10 | Atomic quotas/budgets, persistent quarantine, bounded concurrency, separate safety/compatibility verdicts, active encrypted backups and health timer, external dead-man alert, successful off-device restore, safe defaults and cryptographically gated reversible promotion. Fresh off-device replication is not yet automated. |
| Production readiness | 9.4/10 | The static product, read-only observer and bounded no-ingress pilot are live. Exact activation approval, public discovery, signed acknowledgement/result delivery and independent report verification passed. The 14-day pilot and organic use remain outstanding. |

Overall local-MVP quality: **9.5/10**. Current public-production readiness: **9.2/10**.

## Expected effectiveness

Rosetta should reliably catch signature/canonicalization drift, cursor regressions, MCP/HTTP
rendering differences, retry mistakes and duplicate writes before an integration upgrade ships. Its
evidence is useful to maintainers because it identifies the exact target, adapter source, runtime,
image and failed assertion without using a model to decide the verdict.

The main unproven hypothesis is adoption: no organic maintainer or external agent has yet consumed
a report or requested a test. The next value gate is completing the bounded 14-day pilot while
measuring report use and regressions found—not adding more features by default.

The evolution lane improves maintainability without placing a model in authority: it can convert a
known failure into a contained, signed, reproducible candidate and makes stale-base or self-approval
attempts fail closed. Its effectiveness is not yet longitudinally proven. No candidate has been
promoted on the authoritative tree, no real operator approval key exists, and a passing gate set is
evidence for one exact base—not proof that a change is strategically desirable or production-safe.

# Quality and effectiveness assessment

Date: 1 September 2026

## Bottom line

Rosetta is a strong local MVP and a credible foundation for a staged pilot. It is effective at its
narrow job: detecting whether a signed Technocore mailbox workflow interoperates across materially
different runtimes and producing evidence another operator can verify offline. It is not yet a
production service and has not demonstrated longitudinal value on real release changes.

| Dimension | Score | Evidence and caveat |
|---|---:|---|
| Protocol correctness | 9.3/10 | Official v0.10.0 target plus retained v0.7.0 history, exact source/OCI provenance and signer parity across the OpenSSL-to-libsodium change; four real paths. |
| Security boundaries | 9.3/10 | Non-root/read-only containers, internal-only network, no secrets/mounts/socket, networkless signer, strict seed-file loader, closed registry and shared kill switch. Evolution cannot rewrite its authority and needs a trusted external signature. Production key ceremonies are intentionally absent. |
| Interoperability signal | 9.0/10 | Four cross-runtime cells, differential reads and real MCP now pass on a second protocol baseline. One primary scenario still limits breadth. |
| Reliability | 8.6/10 | Restart, cursor, 429, uncertain writes, idempotency, crash-persistent controls, atomic evolution preflight/recovery, simultaneous four-runtime reads and a 20-iteration soak pass. This is not a long-duration load test. |
| Reproducibility/auditability | 9.6/10 | Exact v0.10.0 tag/commit, archive and upstream lock, universal transitive hash locks, cross-platform OCI identities, vendored runtime subset, canonical artifacts, signed roots and evolution lineage. Local image IDs must still be rebuilt and recorded per architecture. |
| Test quality | 9.6/10 | 194 tests, adversarial/property coverage, immutable-upstream checks, signature/backend parity, CI and authority constraints, 95.14% branch-aware coverage with a 90% ratchet, 99% observer coverage and 27 OCI checks. No full mutation-testing engine or high-volume stress campaign yet. |
| Operations | 9.1/10 | Atomic quotas/budgets, persistent quarantine, bounded concurrency, separate safety/compatibility verdicts, encrypted-backup and health timer templates, safe defaults and cryptographically gated reversible promotion. An external alert destination and off-device backup are not yet configured. |
| Production readiness | 7.6/10 | The public static product and dedicated zero-write host are live with no restarts or ingress. Upstream availability is currently warning-level; production identity, external alert/backup destinations, intake and public writes remain intentionally incomplete. |

Overall local-MVP quality: **9.4/10**. Current public-production readiness: **7.6/10**.

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

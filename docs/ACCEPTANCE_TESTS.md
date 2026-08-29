# Acceptance tests

## Contracts and registry

- [ ] Unknown fields and schema versions fail closed.
- [ ] Matrix uses only `pass`, `fail`, `skip` and `error` with registered reason codes.
- [ ] Mutable branch, tag-only source or unpinned image is rejected.
- [ ] Public input cannot add/change an adapter, image, command, origin or scenario definition.
- [ ] Unsupported capability yields `skip`, not `pass` or `fail`.

## Identity and signer

- [ ] Known synthetic seed derives expected DID.
- [x] Message signature matches official reference vector.
- [ ] Unicode sweep matches every required category and edge case.
- [ ] Domain-separated bundle signature verifies offline.
- [ ] A message signature cannot verify as a bundle attestation or vice versa.
- [ ] Nonce regression is rejected after restart.
- [ ] Worker environment, arguments, database, reports and logs contain no seed.
- [ ] Signer has no network interface and rejects unknown action kinds.

## Runner isolation

- [ ] Runner is non-root with read-only root and bounded tmpfs.
- [ ] No host mounts, container socket, cloud metadata or secret paths are reachable.
- [ ] Network reaches only the configured local Technocore target in MVP.
- [ ] CPU, memory, process and wall-time limits terminate a hostile fixture.
- [ ] One runner cannot reach another runner or persisted evidence.
- [ ] Unregistered image/commit never starts.

## Scenario semantics

- [ ] Producer and consumer discover capabilities without trusting prose as control.
- [ ] Signed mailbox rejects unsigned request and result.
- [ ] Correlation ID binds one request to one result.
- [ ] Producer confirms the result exactly once after restart.
- [ ] 429 triggers documented bounded backoff.
- [ ] Timeout after write is reconciled by read-before-retry.
- [ ] Duplicate remote record creates no duplicate success.
- [ ] Malformed, oversized and hostile content fails closed.

## Matrix

- [ ] Raw fetch producer -> official MCP consumer passes.
- [ ] Official MCP producer -> Python adapter consumer passes.
- [ ] Python producer -> TypeScript consumer passes.
- [ ] TypeScript producer -> raw fetch consumer passes.
- [ ] Roles can be reversed where capabilities declare support.
- [ ] A deliberately broken canonicalizer fails with stable reason code.
- [ ] Rosetta infrastructure fault is `error`, not an adapter regression.

## Evidence and reproducibility

- [ ] Every cell records exact protocol, adapter, runtime and image versions.
- [ ] Evidence is bounded and configured sensitive values are redacted.
- [ ] Bundle contains run, matrix, evidence, reproduction, summary, checksums and attestation.
- [x] File mutation breaks checksum and bundle attestation verification.
- [ ] Two equivalent fixture runs produce the same deterministic roots.
- [ ] Injected regression generates a self-contained minimal reproduction.
- [ ] Correction bundle references the superseded root and never rewrites history.

## Autonomy and policy

- [ ] Release/adapter trigger deduplication survives restart.
- [ ] No-change observation starts no redundant run or publication.
- [ ] Model is disabled by default and verdict path works without it.
- [ ] If enabled, model can only summarize closed structured results.
- [x] Kill switch blocks scheduler, runner, signer, service and publication boundaries.
- [x] Three configured infrastructure failures force quarantine mode across restart.
- [x] Daily run and monthly cost limits are transactional.

## Discovery and service requests

- [ ] Service room/mailbox names derive deterministically from the DID fingerprint and satisfy Technocore limits.
- [ ] Service card, schema URLs and report base use only the configured publisher origin.
- [ ] Service card artifact attestation verifies offline and expires as declared.
- [ ] A synthetic peer discovers the service through local `/r/events` or `/rooms` and verifies the signed announcement.
- [ ] A valid signed `rosetta.discover.v1` receives one `rosetta.offer.v1` in the validated reply mailbox.
- [ ] Natural-language or unsigned discovery messages produce no automated offer.
- [ ] A valid signed `rosetta.request.v1` receives exactly one acknowledgement and one result.
- [ ] Unsigned, unknown-field, expired, oversized and malformed requests start no runner.
- [ ] Request-supplied URL, code, prompt, commit, image or unknown target profile is rejected.
- [ ] `mb-p-` reply room is rejected because a public request would disclose it.
- [ ] Per-DID, global and queue limits are enforced transactionally.
- [ ] Replayed identical request returns prior state; same ID with changed content yields `duplicate_conflict`.
- [ ] Request cannot force metadata refresh, dependency download or mutable build.
- [ ] Liveness beacon is not emitted before the configured silence threshold.
- [ ] `/r/events` discoveries never cause unsolicited outreach.
- [ ] Kill switch stops intake, acknowledgement, execution, beacons and result publication.

## Publication and claims

- [ ] Publisher is disabled by default.
- [ ] Publisher accepts only a valid signed bundle from the approved spool.
- [ ] Publisher cannot write outside one configured repository/bucket.
- [ ] Same bundle root cannot publish twice.
- [ ] Report language does not claim trust, safety, endorsement, certification or airdrop eligibility.
- [ ] GitHub issue/PR, X, email, wallet and claim actions can only enter approval queue.

## Local integration and deployment readiness

- [x] Pinned official Technocore v0.7.0 runs from an immutable OCI index digest.
- [x] Full four-cell demo runs without public network access.
- [ ] No test contacts public Technocore unless explicitly marked and approved.
- [ ] Backup/restore rehearsal succeeds with synthetic data.
- [ ] Operator can activate kill switch without entering worker or runner.
- [ ] No inbound public agent service exists.

## Public-pilot gate

The system is not ready for a production DID, public write or public report until every applicable item passes, a fresh novelty re-check is recorded and a human approves the exact external scopes.

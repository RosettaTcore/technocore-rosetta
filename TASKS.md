# Implementation backlog

## Build execution status — 26 August 2026

Phases 0–3 are implemented and pass both the deterministic historical fixture suite and the
official upstream v0.10.0 OCI matrix. See `docs/LOCAL_MVP_STATUS.md`, `docs/QUALITY_ASSESSMENT.md` and
`artifacts/upstream-acceptance-authoritative-v2/` for exact evidence. No Phase 4 or later external action was
attempted.

Tasks are ordered. Codex may refine subtasks but must not skip gates.

## Phase 0 — repository and closed contracts

- [ ] Create Python 3.12 project, package layout and locked dependency workflow.
- [ ] Add format, lint, type, unit, integration, adversarial and secret-scan commands.
- [ ] Define versioned schemas for adapter manifest, scenario, run, matrix cell, evidence record, attestation, service card, discovery query/offer, request, acknowledgement and result.
- [ ] Define stable pass/fail/skip reason codes.
- [ ] Implement typed configuration from YAML/environment.
- [ ] Create reviewed adapter registry with immutable source commit and image digest fields.
- [ ] Record pinned Technocore release and protocol assumptions.
- [ ] Add deterministic hostile-content, rate-limit, outage and partial-write fixtures.

Exit gate: contracts reject unknown fields and a clean empty project passes all quality commands.

## Phase 1 — signing and artifact integrity

- [ ] Implement official single-line Unicode sweep and signed-room payload.
- [ ] Implement Ed25519 `did:key`, unpadded base64url and strict nonce rules.
- [ ] Implement domain-separated canonical JSON bundle-root signing.
- [ ] Implement signer Unix-socket request/response schema and action allowlist.
- [ ] Persist monotonic nonce enforcement per signing scope.
- [ ] Ensure signer has no network code or dependencies.
- [ ] Add official compatibility vectors plus external `technocore-conformance` fixture checks without runtime dependency on that repo.
- [ ] Add log redaction and key-material leak tests.

Exit gate: worker can obtain message and bundle attestations without receiving the seed.

## Phase 2 — deterministic interoperability core

- [ ] Implement fixed-origin Technocore client and typed untrusted records.
- [ ] Implement adapter interface: discover, read, signed write, wait, resume and evidence export.
- [ ] Implement raw fetch-only fixture adapter.
- [ ] Implement official MCP adapter harness.
- [ ] Implement minimal Python HTTP adapter harness.
- [ ] Implement minimal TypeScript HTTP adapter harness.
- [ ] Implement scenario compiler and capability-based skip logic.
- [ ] Implement ephemeral runner abstraction with non-root, read-only, resource and network policies.
- [ ] Implement scheduler, trigger deduplication and exact-version resolution.
- [ ] Implement DID-derived service-room and request-mailbox naming.
- [ ] Implement closed discovery gateway with request signature/schema/expiry/idempotency/quota validation.
- [ ] Implement deterministic service-card builder and artifact-domain attestation.
- [ ] Implement acknowledgement/result delivery to validated public signed mailboxes.
- [ ] Implement deterministic assertions; no model in verdict path.
- [ ] Implement local dry-run decision trace and metrics.

Exit gate: all adapters run isolated against fixtures, but no signed write path is enabled.

## Phase 3 — local closed-loop matrix

- [ ] Run a pinned local Technocore service from an immutable image digest.
- [ ] Enable synthetic-key signed transport locally.
- [ ] Implement versioned `signed-mailbox-roundtrip-v1` scenario.
- [ ] Run four required producer/consumer cells from `docs/UNIQUENESS_STRATEGY.md`.
- [ ] Force restart, 429, timeout and uncertain-write reconciliation subscenarios.
- [ ] Implement hash-chained evidence capture with redaction and response-size bounds.
- [ ] Generate run, matrix, evidence, reproduction, summary, checksum and attestation artifacts.
- [ ] Implement baseline comparison and regression fingerprinting.
- [ ] Inject a known regression and generate a minimized reproduction.
- [ ] Prove two equivalent runs produce equivalent deterministic artifacts.
- [ ] Create a synthetic owned service room and signed request mailbox locally.
- [ ] Let a second synthetic DID discover the service card and complete request -> acknowledgement -> result.
- [ ] Test duplicate, conflicting, expired, unsigned, over-quota and private-reply requests.
- [ ] Produce local demo and acceptance report.

Exit gate: all local acceptance tests pass; public network and publisher were never contacted.

## Phase 3.5 — controlled self-evolution proposal lane

- [x] Define closed candidate, evaluation, lineage, approval and attestation contracts.
- [x] Bind parent evidence, registry, complete source tree, policy, evaluator and mutation bytes.
- [x] Add a separate evolution-proposal signature domain.
- [x] Enforce allowlisted paths, protected authority files and byte/file limits.
- [x] Build a pinned networkless, non-root, read-only, resource-bounded evaluator.
- [x] Run fixed format, lint, type, full-test, TypeScript and secret/symlink gates.
- [x] Enforce a 90% branch-aware coverage ratchet without excluding safety paths.
- [x] Require a trusted external operator signature for promotion and rollback; default trust empty.
- [x] Write a durable recovery record and backups before promotion writes.
- [x] Test traversal, protected paths, stale bases, package mutation, atomic preflight and rollback.
- [x] Produce one passing signed local proposal without promoting it.

Exit gate: a verified package is `awaiting_human_approval`, the live project is unchanged and no
candidate can modify or authorize its own authority boundary.

## Phase 4 — cloud read-only staging (explicit approval)

- [ ] Re-run novelty landscape check and record nearest competitors.
- [ ] Define the launch branding system: verify name/handle availability, create logo/avatar and
  repository artwork, document colors/type/voice, and apply it consistently to service cards,
  static reports and public discovery documents.
- [x] Provision dedicated EU VPS/project.
- [ ] Deploy the read-only observer and egress proxy; keep scheduler, runners and signer absent.
- [ ] Verify runner and signer isolation.
- [ ] Configure encrypted backups, alerts, budgets and kill switch.
- [ ] Poll official release/manifest sources read-only for 72 hours.
- [ ] Run public protocol probes only if they are read-only and within published limits.

Exit gate: security review plus explicit approvals for production DID, public test writes and report publication.

## Phase 5 — controlled 14-day pilot (explicit approval)

- [ ] Generate one production DID outside model context and back it up offline.
- [ ] Claim `d-rosetta-<fp>`, create `mb-rosetta-<fp>` and publish the attested service card.
- [ ] Publish static discovery documents and optional DID note.
- [ ] Enable bounded signed request intake and result delivery.
- [ ] Run the matrix only on version/commit changes and bounded manual triggers.
- [ ] Publish only changed reports through the approved static publisher.
- [ ] Post at most one signed Technocore digest per novel regression, fix or matrix change.
- [ ] Produce daily operational summaries and weekly human review.
- [ ] Measure external report/self-test use and maintainer outcomes.

Exit gate: continue, pivot, merge into an equivalent project, freeze or retire using `RESEARCH.md` criteria.

## Phase 6 — optional capability receipts and upstream bridge

- [ ] Extend the MVP service request into expiring multi-step challenge-response without arbitrary code upload.
- [ ] Issue expiring observed-capability receipts with exact scenario/version scope.
- [ ] Add abuse, replay and concurrency controls.
- [ ] Prepare upstream issues/PRs from minimized regressions.
- [ ] Keep every external issue/PR and social post behind human approval.
- [ ] Add no reputation score, wallet, payment or airdrop eligibility claim.

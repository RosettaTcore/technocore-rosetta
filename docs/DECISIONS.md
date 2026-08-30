# Architecture decision log

## ADR-001: Conditional GO

Build a bounded pilot because official signals favor useful workflow integrations, while airdrop eligibility and value remain unknown.

## ADR-002: Pivot from helper to Rosetta

Do not build a generic chat/helper agent. Public research found a heavily saturated set of clients, signers, onboarding tools, dashboards, archives and safety utilities. Build an autonomous cross-runtime interoperability observatory instead.

## ADR-003: Narrow novelty claim

Claim only that no equivalent public indexed project was found at the dated research snapshot. Repeat the landscape search before launch and contribute to an equivalent project if one appears.

## ADR-004: Workflow conformance, not duplicate signature vectors

Reuse official/reference signing behavior and external vector ideas, but differentiate through end-to-end discovery, mailbox, correlation, restart, backoff and cross-adapter scenarios.

## ADR-005: Deterministic verdicts

No LLM determines pass/fail. A model is optional and restricted to summaries of closed structured results.

## ADR-006: Reviewed immutable adapter registry

Only pinned commits, locked dependencies and image digests may execute. Public content cannot select or modify executable inputs.

## ADR-007: Ephemeral isolated runners

Treat every adapter as potentially compromised. Run it non-root, resource-limited, without secrets/host mounts and with minimal network access.

## ADR-008: One identity and separate signer

Use one stable DID. Keep seed material outside worker/model/runner trust boundaries in a networkless signer.

## ADR-009: Two signature domains

Support Technocore message signing and domain-separated Rosetta bundle-root attestation. Signatures must not be cross-domain reusable.

## ADR-010: Immutable evidence source of truth

Local content-addressed bundles are authoritative. SQLite indexes them. Technocore is coordination/announcement only.

## ADR-011: Pin v0.7.0 as initial baseline

Use the latest tagged release observed during research. Never silently track `main`; upgrades must pass the matrix.

## ADR-012: Static publisher separated from agent

If approved later, a narrow publisher can update one dedicated artifact destination after verifying a signed bundle. It cannot open issues, PRs or access the DID seed.

## ADR-013: No trust score or certification language

Observed-capability receipts describe exact scenario/version evidence and expiry only. They make no trust, safety, reputation, endorsement or eligibility claim.

## ADR-014: External actions remain gated

GitHub issues/PRs, X, email, wallets, claims and payments require separate explicit authority. No wallet or financial component exists in this project.

## ADR-015: Useful without an airdrop

The durable product is the compatibility history, regression corpus and reproducible test infrastructure. FLOP eligibility is optional upside.

## ADR-016: Discovery is a core product capability

Rosetta publishes an attested service card, a claimed service room and a public signed request mailbox. A peer can discover, request and receive a result without human coordination or a public inbound Rosetta API.

## ADR-017: Structured offers, no cold outreach

Autonomous promotion is limited to launch, changed capabilities/results/corrections, bounded liveness and responses to explicit signed discovery queries. Rosetta never solicits rooms merely because they appear in `/r/events`.

## ADR-018: Public requests cannot expand execution authority

`rosetta.request.v1` selects only pre-reviewed identifiers and a public signed reply mailbox. It cannot supply code, prompts, URLs, commits, packages, images, secrets or private capability room names.

## ADR-019: Python orchestration with explicit cross-runtime probes

Use typed Python orchestration around independent implementations: Node `http`, the official MCP
0.7.0 Python package, Python `httpx`, and TypeScript/Node `fetch`. The deterministic in-process
fixture remains the fast unit/integration oracle; official acceptance executes real operations in
separate containers. Public input cannot select a command, origin, image or source path.

## ADR-020: Restricted canonical JSON profile

Rosetta uses sorted UTF-8 JSON with no insignificant whitespace, non-string keys, non-finite values
or floating-point numbers. Contracts use integers for all quantitative signed fields. This is an
explicit RFC 8785-compatible subset and avoids cross-runtime number-rendering ambiguity.

## ADR-021: Local signer transport fallback under host sandbox

Production and staging retain the narrow Unix-socket signer service. The current build host forbids
Unix socket binding. The executable local harness therefore starts a fresh networkless signer child
for every request over stdin/stdout, using the same protocol implementation and separate SQLite
nonce state. Key derivation remains inside the child. The Unix-socket path was subsequently verified
inside a networkless, non-root, read-only Docker container, including an actual client signature
request and persistent nonce database.

## ADR-022: Pinned official protocol image is authoritative for Phase 3

Unit and ordinary integration tests use a deterministic behavioral fixture. Final Phase 3
acceptance uses official `ghcr.io/flop-labs/technocore-chat:0.7.0` at OCI index digest
`sha256:6dba57cda1c3d230aeb1d421a7a95e90033f78ca36bc8c7486f6e79ad0525a56`, source commit
`1197c9e9463295fae4670e007a0ffcbac6984ffc`, on an internal-only network with no host port.

## ADR-024: Pinned multi-stage Python and Node runtime image

The local worker image is built from reviewed Python 3.12.5 and Node 20.9.0 base-image digests. Node
is copied from the pinned Node stage so all four runtime probes execute inside the hardened worker.
A separate minimal Node adapter image validates every Node profile independently. Live acceptance
records both immutable local image IDs and rejects mutable image references.

## ADR-023: Publisher exists but is disabled by configuration

The static publisher verifies the complete checksummed and DID-attested bundle, accepts input only
from an approved spool, writes under one approved destination and rejects duplicate roots. Local
and example configuration keep it disabled; enabling it is a Phase 4/5 approval.

## ADR-025: Preserve upstream source and provenance locally

Vendor the exact `v0.7.0` release archive for audit and offline MCP execution. Record the source
archive hash, git commit, dependency-lock hash, OCI index digest and per-platform manifest digests
in `config/upstream.lock.yaml`. Do not create a remote or claim local tree hashes are git commits.

## ADR-026: Official MCP plus explicit signing boundary

The upstream MCP intentionally has no signed-write tool because private keys must not enter model
context. Rosetta uses the exact MCP implementation for discovery/read/wait and sends only a
signer's DID, nonce and signature through a direct HTTP POST for signed writes. The registry names
this transport `official-mcp-0.7.0+signed-http-boundary` so the exception is auditable.

## ADR-027: Faults belong in a proxy, not a modified target

Do not patch the official service to manufacture failures. A local internal-only proxy injects one
429 before forwarding and one connection drop after the official target commits. This preserves
upstream behavior while making retry and uncertain-write reconciliation deterministic.

## ADR-028: One operational gate for every authority boundary

Scheduler, runner, signer, discovery/service and publisher share a fail-closed gate. It enforces an
operator kill switch, atomic daily/monthly budgets, bounded parallelism and persistent component
quarantine after consecutive failures. A restart cannot reset these controls.

## ADR-029: Self-evolution produces proposals, never self-authority

Rosetta may turn observed failures and coverage gaps into closed candidate mutations, but evaluates
them only in a pinned, networkless, non-root, read-only container. Each proposal binds the exact
source tree, registry, parent evidence, policy, evaluator and proposed bytes and is signed in a new
domain. The evolution engine, signer, operational controls, configuration and deployment authority
are protected from candidate changes. Promotion and rollback require exact signatures from an
operator DID listed in protected policy; the default list is empty. No candidate can approve,
commit, deploy or publish itself.

## ADR-030: Launch high, ratchet at 90%, and test behavior rather than lines

Launch with 93.85% branch-aware Python coverage and enforce a 90% minimum in both the host suite
and the immutable evolution evaluator. Do not add exclusions merely to improve the number. The
small gap between baseline and floor permits deliberate refactors and new architecture while still
requiring future candidates to test deterministic success, failure, restart and recovery paths.
Changing the evaluator or its threshold remains a protected, human-reviewed authority change.

## ADR-031: Read-only, SHA-pinned continuous integration

GitHub CI receives only read access to repository contents, persists no checkout credential and
uses no repository secrets. Every external action is pinned to a reviewed full commit SHA. Pull
requests run the deterministic host-side acceptance gate and the minimum supported Python runtime;
they never use `pull_request_target`, deploy, publish, sign with a production identity or run the
privileged OCI acceptance lane. Adversarial tests enforce these workflow authority constraints so
a future self-evolution proposal cannot silently broaden CI permissions.

## ADR-032: Local main-push guard while private rules are unenforced

The free private repository exposes ruleset configuration but does not enforce it. Until the
repository becomes public or moves to a plan that enforces branch rules, a versioned local
`pre-push` hook rejects direct updates to `main` and directs work through feature branches and pull
requests. The hook is installed with repository-local Git configuration, has adversarial tests and
does not restrict feature-branch evolution proposals. It prevents accidents rather than hostile
bypass: server-side rules remain the authoritative control once available.

## ADR-033: Bounded dependency-update proposals

Dependabot may propose individual Node and GitHub Actions updates on staggered weekly schedules.
Routine version releases wait at least seven days, while GitHub security updates remain eligible
immediately. At most two routine pull requests per enabled ecosystem may remain open. Routine pip
version proposals are disabled because Dependabot changes the broad `pyproject.toml` lower bounds
without updating Rosetta's hand-maintained `requirements*.lock`; they may resume only after a
supported deterministic lock generator is adopted. No update is auto-merged, and every proposal
must pass the ordinary CI and human merge path. Docker updates are excluded because reviewed OCI
digests, source provenance and container acceptance are authority changes that require a separate
rebuild and review.

## ADR-034: One-server progression with a network-separated read-only observer

Use the existing small Hetzner server for read-only staging, controlled pilot and eventual live
operation rather than paying for a permanent second host. Phase transitions are configuration and
approval gates, not additional infrastructure. The initial long-running service has no identity,
signer, public request intake, publisher or write capability. Its worker is attached only to an
internal Docker network. A separate dual-homed egress process can issue `GET` requests only to
`https://technocore.chat` on `/healthz`, `/.well-known/agent.json` and `/openapi.json`; it rejects
redirects, queries, arbitrary paths, oversized bodies and every other HTTP method. This keeps the
first live process useful and observable without granting public-write authority.

## ADR-035: Observation changes are evidence, not automatic evolution authority

Hash the raw bytes of the three reviewed metadata endpoints and persist the combined protocol
digest across restarts. An unchanged poll updates only bounded health/state data; a new digest
creates one content-addressed local observation record. A change may later trigger the existing
offline matrix and controlled evolution proposal lane, but it cannot alter code, configuration,
deployment, identity or public behavior by itself. The model remains outside every verdict path.

## ADR-036: Promote v0.10.0 only after immutable provenance and differential acceptance

The first public read-only observation correctly failed closed when technocore.chat advertised
v0.10.0 while staging was pinned to v0.7.0. Do not weaken that release gate. Promote v0.10.0 only
after binding tag `v0.10.0` to verified commit
`9c7df0e3616cf28d17e7c8ebeb0c05de6adf117c`, the exact archived-source and `uv.lock` hashes,
and OCI index `sha256:077d4cb94c8b516a590a404620ec304284525b91cad912a34229627ca98e606b`
with its amd64 and arm64 manifests. Preserve v0.7.0 as historical evidence rather than rewriting
it. The v0.10.0 OpenSSL-to-libsodium verifier change must accept the same official deterministic
vector, and the new 422 duplicate-filter refusal is explicitly non-retryable. A green four-runtime
matrix, fault scenarios, soak and signed evidence bundle are required before staging activation.

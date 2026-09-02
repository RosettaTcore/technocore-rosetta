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

## ADR-037: Universal transitive hash locks are deployment inputs

The former `requirements*.lock` files pinned only direct packages and allowed pip to choose mutable
transitive versions during each build. Use pinned `uv` to compile universal Python 3.10+ lock files
from reviewed `requirements*.in`, include distribution hashes and require hashes in CI and every
Python container build. CI regenerates the locks with existing pins and rejects drift. Dependency
updates remain bounded pull requests and must pass the full acceptance gate; the lock tool itself is
installed from the hash-locked development set.

The launch audit also found published advisories affecting the previous `cryptography`, `h11` and
`pydantic` versions. Runtime inputs were upgraded before pilot packaging rather than preserving
known-vulnerable bytes for superficial reproducibility.

## ADR-038: Production signing keys enter only through a strict credential file

Keep synthetic label-derived identities for deterministic local evidence. A production signer may
instead load exactly 32 raw bytes from a regular, owner-only, signer-owned file opened without
following symlinks. The file path is not secret; seed bytes never enter arguments, environment,
logs, worker state or the repository. The production systemd unit uses an encrypted systemd
credential and retains the existing private network and AF_UNIX-only boundary. Key creation,
backup, provisioning and first use remain explicit operator ceremonies.

## ADR-039: Local health failure and encrypted backup are necessary but not sufficient alerts

Run a fail-closed offline staging validator on a systemd timer. It checks health freshness, dry-run
mode, zero writes, observer safety, content-addressed evidence, SQLite integrity/counts, kill switch
and disk budget. Release drift is reported separately under ADR-042. Create consistent backups with SQLite's backup API and stream the snapshot directly
through Age encryption; the server stores no Age secret key. A systemd failure is durable local
evidence, not an external notification. Pilot launch still requires an independently controlled
alert destination and off-device copy.

## ADR-040: Launch with a static evidence surface, not a public execution surface

Present Rosetta as a read-only interoperability observatory through a dependency-free static site.
The site may distribute a reviewed synthetic reference bundle and verify its checksums, canonical
root and domain-separated Ed25519 attestation entirely in the browser. It has no analytics,
third-party assets, dynamic API, mailbox, scheduler, signer or publisher. The primary interaction
fetches only the bounded evidence path from the page's own origin without credentials or redirects,
then verifies the returned bytes in memory. Strict count and byte limits apply. An advanced
user-selected-file verifier remains networkless for independent copies, but manual download is not
a prerequisite for the product experience.

This makes Rosetta's strongest distinction legible at launch: complete workflow evidence across
independent runtimes, including restart, cursor, rate-limit and uncertain-write behavior, rather
than a broad claim of compatibility or trust. Recorded staging status must be labelled as a
snapshot, not live telemetry. Static publication itself remains a separate operator gate; adding
the files to the repository does not authorize hosting, repository visibility changes or public
Technocore activity.

## ADR-041: Publish the static observatory through CI-gated GitHub Pages

Select `https://rosettatcore.github.io/technocore-rosetta/` as the initial canonical public origin.
The explicit repository-visibility and Pages activation gates were approved and executed on
1 September 2026, after the reachable-history review and green publication PR #22.
Keep it operationally separate from the no-ingress Hetzner observer so static publication does not
open another listener on the staging host or invalidate the 72-hour SSH-only observation period.

The Pages workflow runs only after successful `main` CI or explicit manual dispatch, re-verifies
the exact site artifact, and uploads only `site/`. All actions are pinned to immutable commits and
the deployment uses GitHub's short-lived Pages identity; Rosetta stores no publication secret.
The first publication deployed reviewed `main` commit `8ddaee9` in Pages workflow run
`33446317758`. Future origin, custom-domain or publication-authority changes remain explicit
operator actions.

## ADR-042: Separate Rosetta safety from upstream compatibility

Do not let an upstream release or availability incident erase evidence about Rosetta's own safety
boundary. The observer health record and offline validator expose two independent verdicts:

- `safety_status` covers only locally enforceable invariants: dry-run operation, zero public writes,
  a fresh observer heartbeat, intact local state, bounded evidence, no kill switch and no internal
  observer failure;
- `compatibility_status` is `compatible`, `release_drift`, `unavailable` or `rejected` and records
  the state of the fixed-origin public protocol surface without granting it authority.

A consistent new upstream release is observed and content-addressed only after service identity,
authority links, manifest/OpenAPI version agreement, OpenAPI 3.1 shape, fixed metadata paths,
content type and size limits pass. It is not silently promoted to the tested execution baseline.
HTTP failures and malformed documents produce warnings and retain the last known digest; endpoint
bodies and sensitive exception details remain unpersisted.

Compatibility warnings do not reset an otherwise continuous read-only safety window and do not
take the static observatory offline. They also do not authorize public execution: enabling intake,
signing or Technocore writes still requires a currently reviewed compatibility baseline and the
later launch gates. A Rosetta change that expands methods, destinations, credentials, listeners or
write authority resets the affected safety gate; an upstream version change by itself does not.
No model participates in either verdict.

## ADR-043: Make upstream churn a deterministic launch canary

Add a no-network canary that drives one long-lived observer instance through the reviewed release,
an additive synthetic next release, rate limiting, unavailability, rejected authority metadata and
recovery. Require six durable safety-safe checkpoints, GET-only fixed paths, zero public writes,
intact SQLite state, bounded content-addressed evidence and recovery without process restart.

This canary proves availability and fail-closed behavior, not compatibility with an unknown future
release. Rosetta records a structurally acceptable new version as `release_drift` but never promotes
it into execution. A real upstream tag still needs provenance review, immutable pinning and the
complete cross-runtime differential matrix before any write-capable boundary changes.

## ADR-044: Signed, fail-closed remote releases with automatic rollback

Do not grant the deployment user a shell-equivalent root command or require routine use of the
provider console. A workstation release package contains a Git archive, a closed canonical
manifest binding the exact commit, tree, previous commit, archive digest and read-only deployment
profile, plus an SSH signature in the dedicated `rosetta-release-v1` namespace. The server's
root-owned gate accepts only the fixed repository and profile, verifies that signature against a
root-owned allowlist, rejects links, special files, path traversal, duplicate paths, expansion
bombs and an unexpected current release, and stages the archive under its commit identifier.

The unprivileged `rosetta` account may upload only to an incoming spool and start one fixed systemd
unit. The unit cannot accept caller-supplied commands or paths. It builds the new immutable image
before downtime, validates the rendered container boundary, stops the observer only for a
consistent SQLite/evidence backup and atomic release switch, and then requires a fresh post-switch
health record plus independent host/container/offline checks. Any activation or verification
failure restores the prior symlink, image setting and service automatically. A release-drift
warning is visible but does not fail a safety-safe read-only deployment. No production identity,
public-write authority or self-evolution approval is conveyed by a release signature.

Because the observer database uses SQLite WAL mode, the stopped-state backup copies the database
and any regular, non-symlink WAL/SHM sidecars into the root-only writable backup directory before
calling SQLite's backup API. This preserves the read-only mount over live state while still letting
SQLite create or update shared-memory metadata against the frozen copy. The resulting database must
pass `PRAGMA integrity_check` before activation proceeds.

The upgrade sandbox grants write access to the existing `/etc/rosetta/staging.env` file, never its
parent directory or the release signer allowlist. New environment content is rendered in the
root-only backup directory, bounded and checked as a root-owned, non-linked regular file, then
written through an `O_NOFOLLOW` descriptor to the already allowlisted destination and `fsync`ed.
Rollback restores the prior content through the same narrow primitive. This avoids expanding the
unit's write authority merely to support a sibling temporary file.

## ADR-045: Prove the assembled observer image before creating downtime

A signed source archive is necessary but does not prove that the host assembled the expected
runtime filesystem. During the 2 September 2026 staging upgrade, Docker reported a successful
image build whose egress entrypoint then failed with `No module named rosetta.egress`.
The supervisor restarted it repeatedly, live verification failed closed and ADR-044 restored the
known-good release without unsafe behavior or public writes.

Build every signed staging release without host layer-cache reuse, removing stale cache state as
an ambiguity, and import both staging modules inside the Dockerfile. After resolving the immutable
image ID, run both exact entrypoints with
`--help` as UID/GID 65532 in a read-only, capability-free, no-network container. These checks occur
before the known-good observer is stopped, so an incomplete image causes zero deployment downtime.
CI independently builds the same Dockerfile without cache reuse and repeats both isolated
entrypoint checks, making the assembled production artifact a required change check rather than
relying only on source-level imports.
Live-verification failure also emits its final stable structured reason to the upgrade journal.
The egress health probe must consume and close its response so routine readiness checks do not
produce misleading connection-reset tracebacks.

The first follow-up release proved that cache reuse was not the cause: a no-cache build imported
both modules as root, while the same final image could not resolve `rosetta.egress` as the
production UID. Treat source-tree modes and ownership as untrusted build inputs. The Dockerfile
therefore copies the runtime tree as root, normalizes it to owner-writable/world-readable with
directory traversal and only reviewed executable bits retained, and performs its build-time import
only after switching to UID/GID 65532. CI now builds from a `git archive` tree extracted through
the same bounded release extractor used by the server instead of building directly from the
checkout. The final remote entrypoint checks remain the authoritative pre-downtime gate.

## ADR-046: Drop verifier privileges without an external identity helper

The first permission-normalized release passed its build-time UID 65532 import and both isolated
final-image entrypoint checks. Activation then reached the offline host-state check, where the
external `setpriv` command failed inside the hardened upgrade unit. The verifier reduced that
failure to `command_failed:setpriv`, so it could not distinguish an identity-transition failure
from a deterministic rejection reported by `staging_status.py`. Automatic rollback restored the
known-good release and observer without a restart loop.

Run the fixed offline status command as a child process using Python's numeric `user`, `group` and
empty `extra_groups` parameters. This retains the UID/GID 65532 access check without a shell,
account-name lookup or generic command surface. Accept only bounded JSON with the exact
`rosetta.staging-status.v2` schema. A non-zero result remains fail-closed, but now exposes at most
eight stable checker reasons; malformed, oversized, unavailable or empty failed output has a
stable verifier reason of its own. CI exercises the numeric transition in the final release image
with a read-only root filesystem, no network, `no-new-privileges` and only `SETUID`/`SETGID`
capabilities.

The follow-up release showed that the hardened upgrade unit also rejects Python's native child
identity transition before the checker starts, even though the same transition succeeds in the
isolated image gate. Do not weaken the unit or add ambient host capabilities to accommodate a
redundant identity change. Package the fixed offline checker in the immutable observer image and
execute it inside the already-running observer container as explicit UID/GID 65532. This checks the
exact container view of the mounted state and evidence, while retaining its read-only rootfs,
dropped capabilities, `no-new-privileges` and network boundary. The upgrade and CI gates invoke the
packaged checker with `--help` under the same numeric identity before any staging downtime.

## ADR-047: Keep external alert delivery outside the local verdict boundary

The offline staging validator remains networkless and authoritative. Attach systemd `OnSuccess`
and `OnFailure` hooks to a separate notifier process that can send only an empty POST to one exact
Healthchecks.io check. Load the check capability from a systemd credential rather than an argument,
environment variable or repository file. Reject non-HTTPS schemes, every host except
`hc-ping.com`, ports, user information, queries, fragments, redirects and malformed check IDs.

The notifier receives no health JSON, evidence or database content and cannot modify local state.
Notification failure is visible in its own unit but never rewrites a local health pass into a
different deterministic verdict. A dead-man destination can therefore detect a silent host while
remaining unable to control Rosetta. The one-time operations installer also validates and starts
the encrypted backup before enabling either timer; off-device restore remains a separate Gate D
requirement.

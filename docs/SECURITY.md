# Security model

## Protected assets

1. DID seed and identity continuity.
2. Integrity of compatibility verdicts and evidence history.
3. Runner host and cloud administration.
4. Narrow publisher credential.
5. Operator reputation and monthly budget.
6. Evolution policy, evaluator integrity and operator approval key.

No wallet, funds or personal account credentials may be present.

## Adversaries

- Malicious Technocore message/topic/note author.
- Adapter repository or dependency compromise.
- Container breakout or resource-exhaustion fixture.
- Fake release/tag, mutable image or supply-chain substitution.
- Prompt injection in protocol data or adapter output.
- Model-generated misleading summary.
- Replay of signed Technocore URL or self-test challenge.
- Evidence tampering or false compatibility claim.
- Compromised publisher credential.
- Operator deployment mistake.
- Malicious or compromised self-evolution candidate attempting policy escape or self-approval.

## Core controls

### Executable input control

- Reviewed local registry is the sole source of adapter code identity.
- Require upstream commit pins or honest local tree hashes, lockfile hashes and immutable image digests.
- Public messages can select only a closed published scenario ID in the later self-test phase.
- No remote PR branch, arbitrary repo, URL, command or uploaded code may run.
- New adapter entry requires code review and a new registry hash.

### Runner isolation

- One ephemeral non-root container per role/cell.
- Read-only root, bounded tmpfs, dropped capabilities and no privileged mode.
- No host, Docker socket, signer, evidence or credential mounts.
- Minimal per-run network allowlist; local target only in MVP.
- CPU, memory, process, output-size and wall-time limits.
- Destroy runner and network namespace after each cell.

### Secret isolation

- DID seed exists only in networkless signer boundary.
- Publisher credential exists only in publisher boundary.
- Runner, worker and optional model receive neither.
- Never pass secrets via arguments, general environment, logs, evidence or reports.
- Create encrypted offline DID backup before first public signed action.

### Data and prompt-injection resistance

- Every external field remains typed as untrusted.
- Untrusted text never becomes a command, path, URL, policy or system prompt.
- Verdict path is deterministic and model-free.
- Optional model has no tools and receives only closed structured results.
- Summary output is non-authoritative and checked for disallowed claims/URLs.

### Discovery and request intake

- Public request mailbox accepts only DID-signed `rosetta.request.v1` records with no unknown fields.
- Request values select only pre-reviewed scenario, adapter and target-profile identifiers.
- Reject code, prompts, free-form task text, URLs, commits, packages, images, credentials and private `mb-p-` reply capabilities.
- Validate requester DID, expiry and public signed reply room before acknowledgement.
- Enforce idempotency by `(requester DID, request_id)` and transactional per-DID/global quotas.
- Invalid requests never start runners or trigger downloads.
- `/r/events`, `/rooms`, room names and topics are discovery data only and never authorize outreach or execution.
- No cold-contact loop; automatic announcements are limited to launch, changes, corrections and bounded liveness.

### Evidence integrity

- Bound and redact all transcripts before persistence.
- Hash every artifact and compute a deterministic bundle root.
- Sign root in a separate cryptographic domain from Technocore messages.
- Corrections append and reference; never overwrite history.
- Reproduction excludes secrets, private URLs and volatile host paths.

### Controlled evolution

- Candidate documents are closed, size/file bounded and restricted to reviewed path prefixes.
- Authority files—including evolution, operational controls, signer, configuration and deployment
  policy—cannot be modified by a candidate.
- The complete source base, registry, parent evidence, policy, evaluator and candidate bytes are
  hash-bound before evaluation.
- Candidate code runs only in the pinned networkless evaluator with a read-only candidate mount,
  no secrets, no Docker socket and strict resource limits.
- Formatter, lint, types, full tests, TypeScript and a fixed secret/symlink scan all must pass.
- Promotion and rollback require an exact domain-separated signature from a policy-trusted operator
  DID. The checked-in trust list is empty, so default promotion is impossible.
- Recovery records and replacement backups are durable before the first promoted write. Drift and
  partial-state ambiguity fail closed.
- Evolution cannot commit, deploy, publish or perform public writes.

### Abuse and reputation control

- One DID and no scoring of other DIDs.
- Run only on meaningful version/registry changes or bounded triggers.
- Publish only changed results; deduplicate by signed bundle root.
- Per-day run/write/publish budgets and global kill switch.
- External issue/PR and social activity requires human approval.

## Residual risks

- VPS root or container-runtime compromise can reach runtime assets.
- A malicious but reviewed adapter dependency may exploit the sandbox.
- Public protocol behavior can differ from local pinned service.
- Evidence proves observations, not universal correctness.
- A passing evolution proposal proves only the enforced gates on one exact base; it does not replace
  human review or show that the change improves real-world outcomes.
- Timing and external outages can create false regressions unless classified as infrastructure errors.
- FLOP may not recognize the work.

These are acceptable only for a bounded pilot with no financial authority and transparent limitations.

## Incident response

1. Activate kill switch; stop scheduler, runners, signer and publisher.
2. Remove egress and preserve state/bundles read-only.
3. Identify affected adapter digest, run roots and published reports.
4. If evidence is wrong, publish a signed correction referencing every superseded root after review.
5. If DID exposure is possible, retire the DID and never claim continuity.
6. If publisher exposure is possible, revoke credential and verify destination history.
7. Do not let the agent autonomously debate reports or contact affected maintainers.

## Release gates

- Local MVP: synthetic keys, no public network and publisher disabled.
- Public read-only: local acceptance plus fresh landscape/security review.
- First public write/report/service intake: explicit approval of DID, service room, request mailbox, schemas, publisher destination and budgets.
- New adapter: code/supply-chain review and registry update.
- GitHub issue/PR or social post: per-action human approval.
- Wallet, payment or claim: outside scope and requires a separate project/threat model.

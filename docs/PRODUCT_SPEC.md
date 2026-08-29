# Product specification

## Product

Technocore Rosetta is a bounded autonomous interoperability observatory. It executes one versioned Technocore workflow across a matrix of reviewed adapters, detects behavioral regressions and emits signed reproducible evidence.

## Product goal

Make Technocore integration upgrades safer and faster by replacing “the client says it works” with exact cross-runtime evidence. The product must remain valuable if no FLOP airdrop occurs.

## Non-goals

- General chat assistance or engagement farming.
- Another end-user signer, onboarding guide, social dashboard or archive.
- Security certification, reputation scoring or Sybil judgement.
- Running user-submitted code or arbitrary Git repositories.
- Holding funds, wallets, social accounts or broad developer credentials.
- Automatically opening external GitHub issues/PRs.
- Treating Technocore as durable/private storage.

## Primary users

1. An integrator deciding whether to upgrade Technocore or an adapter.
2. A maintainer receiving a minimal, reproducible regression report.
3. An agent operator wanting an expiring proof of observed interoperability.
4. The Rosetta operator reviewing costs, safety and publication decisions.
5. A peer agent that must discover, request and consume Rosetta's service without human coordination.

## Core user stories

1. I can see exact protocol, adapter, runtime and image versions for every matrix cell.
2. I can reproduce a failed cell locally from the published bundle.
3. I can distinguish unsupported capability (`skip`) from failure (`fail`).
4. I can verify the bundle DID signature and file hashes offline.
5. I can compare current and previous runs without trusting a prose summary.
6. I can stop all tests and public outputs with one kill switch.
7. A peer can discover a signed service card through Technocore and verify it offline.
8. A peer can submit a closed request and receive a signed acknowledgement/result without giving Rosetta code or secrets.

## Autonomous loop

1. Maintain a signed service card, owned service room and public signed request mailbox in approved pilot mode.
2. Observe allowlisted release/adapter metadata and closed-schema service requests read-only.
3. Resolve immutable versions, validate quotas and deduplicate the trigger/request.
4. Compile applicable matrix cells from declared capabilities.
5. Start a pinned local Technocore target and ephemeral isolated runners.
6. Execute deterministic workflow scenarios.
7. Capture bounded, redacted evidence.
8. Assert pass/fail/skip with stable reason codes.
9. Compare against prior baseline and fingerprint changes.
10. Minimize new failures with deterministic reduction rules.
11. Build checksummed bundle and request signer attestation.
12. Publish only a changed signed bundle and return a signed result pointer.
13. Back off or fail read-only on anomalous external state.

## Discovery and service fulfillment

Discovery and autonomous service offering are part of the MVP contract. The full protocol is in `DISCOVERY_AND_SERVICE.md`.

- `d-rosetta-<did fingerprint>` is the claimed service announcement room.
- `mb-rosetta-<did fingerprint>` is the public signed-only request mailbox.
- Static `service-card.json`, `/.well-known/agent.json`, `/skill.md` and JSON Schemas explain use to agents.
- A request can select only an existing scenario, adapter profile and `current` target profile.
- Rosetta returns signed acknowledgement and result messages to a validated public signed mailbox.
- No requester can submit code, prompts, URLs, commits, images or private room capabilities.
- Rosetta never cold-contacts newly discovered rooms; it announces only launch, changed capabilities/results/corrections and bounded liveness.

## MVP scenario

`signed-mailbox-roundtrip-v1`:

- producer discovers supported endpoints;
- producer creates a signed request with correlation ID;
- consumer reads the signed-only mailbox;
- consumer validates request identity and posts a signed result;
- producer confirms the result exactly once;
- scenario injects a restart and a 429;
- uncertain write is reconciled by reading before retrying;
- final evidence proves or disproves each assertion.

Required matrix cells are defined in `UNIQUENESS_STRATEGY.md`.

## Verdict model

Every assertion is deterministic. A cell result is:

- `pass`: every required assertion succeeded;
- `fail`: at least one supported required assertion failed, with stable reason code;
- `skip`: declared capability is absent or prerequisites are explicitly unavailable;
- `error`: Rosetta infrastructure failed before a protocol verdict was possible.

`error` must never be presented as a Technocore or adapter failure.

## Evidence and attestation

The bundle contains exact versions, scenario inputs, redacted transcripts, assertion results, reproduction instructions and file hashes. A domain-separated Ed25519 signature covers the deterministic bundle root.

The attestation proves bundle integrity and Rosetta DID control only. It does not prove that an agent is trustworthy, secure, autonomous or eligible for an airdrop.

## Publication policy

Publish only when:

- a release/adapter version is new;
- a matrix result changed;
- a previous report is corrected;
- an operator explicitly requests a bounded re-run.

Do not publish idle check-ins, repeated green summaries or raw untrusted message content. External issues/PRs remain approval-only.

## Success metrics

- zero secret or sandbox-escape incidents;
- zero execution of unregistered code;
- zero duplicate public reports for the same run root;
- 100% bundle reproducibility for retained fixtures;
- at least one real regression found or one upgrade decision informed;
- at least one external integrator uses a report, reproduction or self-test;
- median release-to-report under 30 minutes for the MVP matrix;
- monthly total cost under 40 EUR;
- no more than one Technocore announcement per novel result;
- at least one external DID discovers the service and completes request -> result during pilot;
- zero unsolicited outreach messages;
- zero runner executions caused by invalid or over-quota discovery requests.

## Target repository structure

```text
src/rosetta/
  config.py
  contracts/
  registry/
  scheduler/
  scenarios/
  runners/
  adapters/
  assertions/
  evidence/
  reports/
  discovery/
  service/
  publishing/
  operations/
src/rosetta_signer/
  canonical.py
  did.py
  nonce_store.py
  protocol.py
  service.py
adapters/
  raw_fetch/
  official_mcp/
  python_http/
  typescript_http/
config/
  adapters.lock.yaml
  scenarios/
tests/
  unit/
  integration/
  adversarial/
deploy/
docs/
```

# Uniqueness strategy

## Positioning

**Technocore Rosetta is an autonomous interoperability observatory.** It proves cross-runtime behavior and publishes reproducible evidence. It is not another client, chat bot, dashboard, archive, trust score, or airdrop check-in tool.

One-sentence value proposition:

> Before an integrator upgrades Technocore or an adapter, Rosetta shows which real agent workflows still pass, where they fail, and how to reproduce the failure.

## The wedge

Start with one difficult but bounded workflow:

```text
discover capabilities
  -> create signed request in a mailbox
  -> second adapter reads and correlates it
  -> second adapter posts signed result
  -> first adapter confirms exactly once
  -> both survive one forced restart and one 429
```

Run the same scenario across a small matrix:

| Producer | Consumer | Transport |
|---|---|---|
| raw fetch-only fixture | official MCP | GET/read + signed POST/write |
| official MCP | Python adapter | MCP + HTTP |
| Python adapter | TypeScript adapter | HTTP + HTTP |
| TypeScript adapter | raw fetch-only fixture | signed HTTP + bounded polling |

MVP adapters are deterministic harnesses, not autonomous LLMs. This makes failures reproducible and cheap. Real runtime integrations can be added only after the core matrix is stable.

## Public artifact

Each run emits an immutable bundle:

```text
run.json                 run identity, trigger and exact versions
matrix.json              pass/fail/skip cells with reason codes
evidence/                bounded request/response transcripts with redaction
reproduce/               exact local replay command and fixtures
summary.md               human-readable result
checksums.txt             file digests
attestation.json          domain-separated Ed25519 signature over bundle root
```

The signature proves which Rosetta DID produced the bundle and that bytes were not changed. It does not prove truth, security, vendor endorsement or airdrop eligibility.

## Discoverable service and agent self-test

The core service lane lets a peer DID discover Rosetta, request an allowlisted matrix run and receive a signed result without submitting code. Exact discovery, request and anti-spam contracts are in `DISCOVERY_AND_SERVICE.md`.

A later opt-in multi-step challenge-response extension lets a peer demonstrate selected behaviors:

1. peer sends a signed request matching a closed schema;
2. Rosetta returns a nonce, correlation ID, expiry and allowed response room;
3. peer completes documented read/write/correlation actions;
4. Rosetta deterministically checks the public transcript;
5. Rosetta issues an “observed capabilities receipt” with evidence pointers.

The receipt must never use `certified`, `trusted`, `safe`, `reputable` or equivalent language. It expires and names the exact protocol/version/scenario.

## Anti-copy strategy

Features are easy to copy. Accumulated evidence is harder. Therefore prioritize:

- stable schemas and run IDs from day one;
- historical results across every tested release;
- high-quality minimized failures;
- contributor-friendly adapter contract;
- report reproducibility in CI;
- transparent corrections when Rosetta is wrong.

Do not compete on visual polish first. Compete on precise evidence and useful regression turnaround.

## Novelty re-check gate

Before the first public announcement and every major roadmap expansion:

1. rerun GitHub and web searches for Technocore interop, compatibility, TCK, runtime matrix and Rosetta;
2. inspect recent official issues/PRs and community repos;
3. record date, queries and nearest competing projects;
4. if an equivalent project exists, contribute an adapter or evidence format there instead of launching a clone;
5. publish a narrow differentiation claim, never “the first” without stronger proof.

The 30 August 2026 launch re-check passed only with narrowed positioning. Technocore Gauntlet now
substantially overlaps static conformance, cross-implementation comparison, bounded chaos and
replayable evidence. Rosetta must lead with end-to-end mailbox state-machine behavior, signed
bundle roots and the closed autonomous service loop. If Gauntlet or another maintained project
adds the same full workflow, collaboration or an adapter/evidence contribution is preferred over
duplicative promotion.

## Expansion path

Only after the core matrix produces value:

- framework adapters for OpenAI Agents SDK, LangGraph, OpenClaw and other active runtimes;
- protocol upgrade canary against release candidates;
- a reusable TCK package for third-party CI;
- signed compatibility badges that link to exact evidence;
- cross-protocol bridges only after a separate threat model.

Do not begin with reputation, payments, wallets, task markets or arbitrary user code execution.

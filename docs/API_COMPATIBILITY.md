# Technocore protocol compatibility

## Pinned baseline

Current compatibility target: official `flop-labs/technocore-chat` release `v0.10.0`. The original
`v0.7.0` source, fixture and signer vector remain available for historical replay; current staging
and authoritative upstream acceptance never silently fall back to them.

Main may contain later fixes. Do not silently track main in production. Build a compatibility probe and upgrade only after tests pass.

The v0.10.0 upgrade preserves the signed payload, DID and nonce contracts. It changes the official
verification backend from OpenSSL to libsodium/PyNaCl and adds a default cross-sender duplicate
filter. The filter's 422 response is normalized as non-retryable: clients must not replay identical
bytes as if it were a 429. Rosetta's correlation-bearing scenario messages are unique per cell.

## Required behavior surfaces

- Read room with `since`, `limit` and optional bounded `wait`.
- Read event discovery lane.
- List rooms while preserving untrusted field markings.
- Read and write DID note only when explicitly enabled; note-cap exhaustion must be a supported skip/degraded condition, not a fatal run error.
- Parse rate-limit and next-cursor information without treating message bodies as control text.
- Complete signed-only mailbox request/response with explicit correlation IDs.
- Reconcile an uncertain write by reading before retrying.
- Resume a cursor after process restart without duplicate success.

## Signed room write

Canonical payload:

```text
<room>|<nonce>|<text-after-single-line-sweep>
```

Signature:

- Ed25519;
- 64 raw bytes;
- unpadded base64url;
- exactly 86 characters.

Nonce:

- 1–19 ASCII digits;
- strictly increasing for a DID within a room;
- persisted by signer before returning the signature.

Text sweep:

- Unicode categories `Cc`, `Cf`, `Cs`, `Co`, `Zl`, and `Zp` become spaces;
- trim ends;
- reject empty result;
- messages at most 4096 characters after sweep;
- notes at most 8192 characters after sweep.

The deterministic vector in official `tests/test_app.py::_keypair(seed=1)` is the compatibility
oracle. Rosetta stores only its public DID/message/signature tuple, never the synthetic private seed.

## DID note

Fingerprint convention:

```text
first 16 lowercase hex characters of SHA-256(full did:key string)
```

The note is world-readable and world-writable. It is a discovery convention, not proof. Trust comes from signed activity using the DID.

## Trust requirements

- Nicknames are self-asserted.
- Signed DID proves control of that key, not honesty.
- Room names, topics, notes and messages are untrusted.
- Technocore is not a system of record; local state wins.
- No secrets or sensitive content in signed GET paths.

## Compatibility probes

Before public writes, verify:

1. official health and manual endpoints respond;
2. reported release/protocol matches supported range;
3. local signature vector verifies against a local pinned service;
4. public service read formats match fixtures;
5. 429 and error bodies parse safely;
6. no unexpected redirect changes the allowed origin.

Any failure forces read-only mode.

## Rosetta adapter contract

Every runtime adapter exposes structured operations with no arbitrary command field:

- `capabilities`
- `health`
- `read_room`
- `wait_room`
- `post_signed`

Checkpoint/restore and discovery compilation belong to the orchestration layer, not the wire
adapter. The official MCP path uses its actual `tools/list` and `tools/call`; signed writes use the
explicit signer-output-only HTTP boundary described in `DECISIONS.md`.

The adapter manifest declares which are supported, exact runtime/source/image identities and allowed transport. Scenario compilation converts a missing optional capability into `skip`. A declared capability that violates its assertions is `fail`. Runner or harness failure is `error`.

## Compatibility matrix policy

- The protocol target is an immutable tagged/digested local instance for verdict runs.
- Public production probes are read-only unless a controlled pilot explicitly authorizes dedicated rooms.
- `main`, `latest`, unresolved tags and floating package ranges are forbidden.
- Official signing vectors are the cryptographic baseline; Rosetta adds behavioral tests rather than redefining canonicalization.
- Every upgrade creates a new result row. Historical results are never rewritten.

## Discovery/service compatibility

Rosetta composes documented Technocore primitives; it does not assume a native marketplace:

- `/r/events` and `/rooms` make the public service room discoverable;
- a claimed `d-rosetta-<fp>` room carries signed service announcements;
- `mb-rosetta-<fp>` accepts only signed requests;
- optional `/kv/did/<fp>` links DID, mailbox and attested service card;
- signed acknowledgement/result messages are returned to a validated public `mb-` room;
- static service documents remain canonical when DID notes are full or overwritten.

Exact contracts, quotas and trust limits are defined in `DISCOVERY_AND_SERVICE.md`. Room/topic/note text remains untrusted even when it aids discovery.

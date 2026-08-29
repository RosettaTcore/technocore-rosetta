# Implementation and rollout plan

## Timeline

### Days 1–2: contracts and integrity core

- Project skeleton, locked tooling and closed schemas.
- Adapter registry and stable reason codes.
- Closed service-card, request, acknowledgement and result schemas.
- Technocore message compatibility plus bundle attestation signer.
- Deterministic fixtures and secret/isolation tests.

### Days 2–4: adapters and runner isolation

- Fixed-origin client and adapter protocol.
- Raw fetch, official MCP, Python and TypeScript harnesses.
- Ephemeral container runner with strict resource/network policy.
- Scenario compiler and capability-based skip behavior.
- Discovery gateway, DID-derived room names, request validation, idempotency and quotas.

### Days 4–6: local interoperability matrix

- Pinned local Technocore.
- `signed-mailbox-roundtrip-v1` across four required cells.
- Restart, 429, timeout and uncertain-write cases.
- Evidence bundle, attestation, baseline comparison and regression fingerprint.
- Local service card/room/mailbox plus a synthetic peer request-to-result flow.

### Days 6–7: regression minimizer and release gate

- Inject known bug and minimize reproduction.
- Reproducibility, adversarial and isolation suite.
- Local demo, acceptance report and deployment artifacts.
- Stop before any public action.

### After explicit approval: cloud read-only staging

- Fresh novelty landscape check.
- Dedicated EU VPS with separated scheduler, runners, signer and egress.
- 72-hour read-only observation of official metadata and public formats.
- Review cost, timeouts, quarantines and protocol drift.

### After second explicit approval: 14-day controlled pilot

- Production DID generation and offline backup.
- Version-triggered matrix runs.
- Signed static reports only when results change.
- Attested discovery documents, owned service room and signed request mailbox.
- Bounded autonomous request fulfillment and Technocore announcements.
- Weekly usefulness and security review.

## Human decisions at gates

Before cloud staging:

- cloud provider/project and billing authorization;
- exact public metadata sources;
- admin access and monitoring destination;
- whether any optional summary model is worth enabling.

Before controlled pilot:

- production name, DID ceremony and room names;
- exact service-card fields, request mailbox quotas and allowed discovery rooms;
- approved adapter registry and test matrix;
- public write budget;
- dedicated report destination and narrow publisher credential;
- exact automatic-publication scope;
- first public introduction and disclosure wording.

Always per-action approval:

- upstream GitHub issue or PR;
- social post or direct outreach;
- any use of external user data beyond public protocol evidence;
- any future wallet, claim or payment integration.

## Cost guardrails

- Infrastructure target: <= 15 EUR/month.
- Optional model target: <= 10 EUR/month.
- Artifact storage/egress target: <= 5 EUR/month.
- Total hard cap: 40 EUR/month.
- Maximum two parallel runners and no automatic horizontal scaling.
- No model call for green routine runs unless specifically enabled.

## Rollback

```text
public run + publish
  -> public read-only metadata
  -> local-only matrix
  -> stopped
```

Kill switch stops request intake, acknowledgements, new runners, beacons, public writes and publication. Already published immutable bundles are not deleted; corrections supersede them by reference. Retiring a compromised DID is explicit and permanent.

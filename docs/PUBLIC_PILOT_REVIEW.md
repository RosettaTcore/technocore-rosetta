# Public pilot activation and external proof review

Date: 13 September 2026

## Outcome

The bounded Technocore Rosetta public-service pilot is active and externally reachable. One
operator-approved deterministic synthetic peer submitted the closed
`signed-mailbox-roundtrip-v1` request through the public Technocore mailbox. Rosetta returned one
signed accepted acknowledgement, one signed passing result and one content-addressed report. The
independent probe verified the service card, both reply signatures, every manifest-listed report
file, the bundle root and its Ed25519 attestation.

This is a recorded operator snapshot, not live telemetry. It proves the approved public workflow
worked once end to end. It does not complete the 14-day pilot, demonstrate organic adoption,
certify Technocore or Rosetta, or authorize broader methods, destinations, schemas or budgets.

## Approved production identity and release

- release commit: `837f041ddc0c0a6be860245690778a173d4de113`;
- immutable pilot image:
  `sha256:17a8bf354344ed57a06dd759dc851402715dd3d18031a4ef1a8d0ab622dcaee5`;
- public DID: `did:key:z6MkjxXjmApUtN4GQY59rj6vbgZ6Cymt2gL7rNMSZTd5ekhn`;
- service room: `d-rosetta-6edb7da59f74cca6`;
- request mailbox: `mb-rosetta-6edb7da59f74cca6`;
- [service card](https://2.28.69.158/service-card.json), canonical digest
  `sha256:769fb33ca816eac1aeac0e45799dedbae7e28d868ff473af714b977e3205bc8f`;
- activation preview digest:
  `sha256:f955881d76d61a49ec45289d437572139e3d23e91db3d801563e924fafa554f2`.

The approved activation reconciled exactly three initial writes: the service-room ownership note,
the owner-only allow-list and the signed service announcement. The public service room was then at
generation 2 with one Rosetta announcement at sequence 2. The room owner and sole allowed DID both
matched the production DID.

## External synthetic peer proof

- probe preview digest:
  `sha256:aebb3542fd19e43e5fb8cf9b77adad9f7b29d1fe8f25d400cb7374ee6fef8025`;
- deterministic synthetic peer:
  `did:key:z6Mkts2zzHhLT6mTK98VJV2NWQapHhaEQFeA2m11fY76GUbK`;
- request ID: `a39124c306ac49289937cbedb2022e95`;
- path: `python-http` producer to `official-mcp` consumer;
- request mailbox sequence: 1;
- signed accepted acknowledgement sequence: 1;
- signed passing result sequence: 2;
- verified bundle root:
  `sha256:cdc65e155102b4a85be064e72c4ac793f1b3899d909aa87cc8fd66e909b5b7e1`;
- verification time: 13 September 2026 19:21:45 UTC;
- public [report summary](https://2.28.69.158/reports/cdc65e155102b4a85be064e72c4ac793f1b3899d909aa87cc8fd66e909b5b7e1/summary.md)
  and [attestation](https://2.28.69.158/reports/cdc65e155102b4a85be064e72c4ac793f1b3899d909aa87cc8fd66e909b5b7e1/attestation.json)
  both returned HTTP 200 after verification.

The probe used only the repository-defined synthetic identity. It did not receive or use the
production seed, signer socket, private mailbox capability or an operator credential.

## Post-run health and boundaries

After the result was verified, the pilot, signer and five-minute pilot health timer were active;
the pilot health helper passed and the service announcement remained present. The separate
read-only observer reported `healthy`, `safety_status: safe`, current observation and
`public_writes: 0`. That counter describes the observer only; the separately approved pilot writes
above are intentionally outside the observer's zero-write boundary. Upstream `v0.13.0` remained a
visible `release_drift` compatibility warning against the observer baseline, not a pilot failure.

The active pilot remains limited to two accepted requests per DID per UTC day, eight external jobs
globally per day, queue depth 16, one parallel runner and a monthly budget of 4000 cents. It has no
inbound application listener, direct worker egress, Docker socket, model verdicts, natural-language
reply loop or cold outreach. Requests cannot supply code, repositories, images, commands or URLs.
Service-room recovery is bounded to one presence write per poll, with a six-hour single-message
anchor and no more than one established-room liveness record every five days.

## Remaining evidence gate

Continue the bounded 14-day pilot with daily health review and weekly human review. Record organic
report use, reproducible regressions or operational failures without broadening the current intake
contract. Any capability, destination, schema, quota, budget, key, listener or authority change
requires a new reviewed release and its own explicit approval.

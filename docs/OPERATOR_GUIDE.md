# Local operator guide

## Trust boundary

Run the worker, local fixtures and synthetic signer only on test data. The local key label is public
fixture metadata, not recovery material. Never replace it with a production seed in a command,
environment variable or repository file. Production identity provisioning requires a separate
operator ceremony and secret mount after explicit approval.

The signer worker interface accepts only Technocore message, artifact-root, service-document and
evolution-proposal actions. It never signs operator approvals. Adapter code never receives identity
material. Public request values can select only the four registry IDs, the single reviewed
scenario, `current`, and a public `mb-` reply room.

## Install and verify

From the repository root:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-dev.lock
.venv/bin/ruff format --check src tests tools
.venv/bin/ruff check src tests tools
.venv/bin/mypy src
PYTHONPATH=src:. .venv/bin/python -m pytest
.venv/bin/python -m coverage erase
PYTHONPATH=src:. .venv/bin/python -m coverage run -m pytest
.venv/bin/python -m coverage json -o artifacts/coverage.json
.venv/bin/python -m coverage report
.venv/bin/python tools/secret_scan.py
```

`requirements.lock` and `requirements-dev.lock` contain the complete transitive resolution and
distribution hashes. Change only `requirements*.in`, run `make lock UV=.venv/bin/uv`, then run
`make lock-check UV=.venv/bin/uv`. CI and all Python container builds reject missing or mismatched
hashes.

## Controlled evolution

Build and inspect the fixed local evaluator, then record its immutable local image ID in
`config/evolution.policy.yaml`:

```sh
docker build -f deploy/Dockerfile.evolution-evaluator \
  -t rosetta/evolution-evaluator:local .
docker image inspect rosetta/evolution-evaluator:local --format '{{.Id}}'
```

Before evaluating a candidate, set its `parent_source_sha256` to the current deterministic base:

```sh
PYTHONPATH=src .venv/bin/python -c \
  'from pathlib import Path; from rosetta.evolution import source_tree_digest; print(source_tree_digest(Path.cwd()))'
```

Evaluate into a new empty artifact directory and verify the signed package:

```sh
PYTHONPATH=src .venv/bin/python -m rosetta.evolution_cli evaluate \
  fixtures/evolution/candidate-add-domain-vector.json artifacts/evolution-demo-v1
PYTHONPATH=src .venv/bin/python -m rosetta.evolution_cli verify \
  artifacts/evolution-demo-v1
```

Evaluation never changes the live candidate files. It uses the global kill switch, persistent daily
run quota and three-infrastructure-failure quarantine. A rejected or interrupted workspace stays
under `local/evolution/` for review and is never accepted as evidence.

Promotion is intentionally disabled in the checked-in profile because `trusted_operator_dids` is
empty. To enable it later, an operator must complete a key ceremony outside Rosetta, add only the
public `did:key` to the protected policy, re-evaluate under that new policy and create a detached
signed `rosetta.evolution-approval.v1` file under ignored `local/`. Never store its private key in
the project. Then:

```sh
PYTHONPATH=src .venv/bin/python -m rosetta.evolution_cli promote \
  artifacts/evolution-demo-v1 local/evolution/promotion-approval.json
```

Keep the returned recovery record. Rollback needs a fresh approval whose action is
`rollback_candidate` and which binds the same candidate ID and evolution root:

```sh
PYTHONPATH=src .venv/bin/python -m rosetta.evolution_cli rollback \
  local/evolution/rollbacks/CANDIDATE_ID/promotion.json \
  local/evolution/rollback-approval.json
```

Any source, registry, policy, evaluator, package or target-file drift requires a new evaluation.
Do not bypass it by editing hashes. Full rationale and approval payload semantics are in
`docs/SELF_EVOLUTION.md`.

Run the end-to-end demo into a new empty directory:

```sh
PYTHONPATH=src .venv/bin/python -m rosetta.cli demo --output artifacts/demo
PYTHONPATH=src .venv/bin/python -m rosetta.cli verify artifacts/demo/bundle
```

Important outputs:

- `demo-report.json`: machine-readable gate summary;
- `ACCEPTANCE_REPORT.md`: human gate summary;
- `bundle/`: successful four-cell observation;
- `regression-bundle/`: stable injected regression and reproduction;
- `determinism-a/` and `determinism-b/`: independently attested equivalent runs;
- `service/`: service card, attestation, well-known manifest, skill and schemas;
- `runner-specs.json`: exact non-root/read-only/no-mount OCI invocations;
- `decision-trace.json` and `metrics.json`: dry-run policy and bounded metrics.

## Evidence verification

The verifier checks every listed file digest, rejects extra or missing payload files, recomputes the
canonical bundle root, parses the closed attestation schema and verifies the domain-separated
Ed25519 signature from the embedded DID. Editing any payload breaks verification.

The signature proves byte integrity and control of the synthetic Rosetta identity only. It does not
claim trust, safety, endorsement, certification or airdrop eligibility.

## Kill switch

Activate a configured explicit switch path without entering a worker or runner:

```sh
.venv/bin/python tools/activate_kill_switch.py local/KILL_SWITCH
```

Request intake, discovery responses and announcements call the switch before writing or starting a
job. Remove the switch only after an operator reviews the incident; the tool intentionally provides
no automated re-enable action.

## Backup rehearsal

After a demo:

```sh
.venv/bin/python tools/backup_rehearsal.py artifacts/demo local/backup-rehearsal
test -f local/backup-rehearsal/RESTORE_OK
```

The rehearsal uses the SQLite backup API, copies immutable evidence, restores to a separate tree
and compares every retained byte digest.

## Configuration and safe defaults

`config/config.local.yaml` is the executable local profile. It permits `dry_run` only, disables
discovery service intake and publishing by default, pins the target release and fixed origin, and
requires strict runner controls. `config.example.yaml` documents later options; do not enable them
without the matching release gate.

`config/config.staging.example.yaml` is the first long-running host profile. It remains `dry_run`,
uses no identity or secret, disables discovery/service/publishing/model access and polls every five
minutes through the fixed-path egress boundary. Validate one local observation against a controlled
fixture with `rosetta-observer --config CONFIG --once`; do not point tests at a public endpoint.

For the deployed observer, inspect `/var/lib/rosetta/state/health.json` from the host. A healthy
record always says `public_writes: 0`. Endpoint bodies are neither logged nor persisted: evidence
contains only byte counts, content types and SHA-256 digests plus the pinned release. The first
appearance of a combined digest creates one file; identical later polls update SQLite counters and
health only, so normal operation has bounded evidence growth.

The staging Docker topology is intentionally asymmetric:

```text
observer -> internal network -> egress-proxy -> https://technocore.chat
```

The observer has no direct outbound network. The egress boundary rejects queries, redirects,
oversized bodies, non-allowlisted paths and every method except `GET`. Neither service publishes a
host port. Full server setup, service supervision, 72-hour acceptance and rollback are documented
in `docs/DEPLOYMENT.md`.

## Container validation gate

Run the official upstream acceptance into a new directory:

```sh
PYTHONPATH=src .venv/bin/python tools/upstream_acceptance.py \
  --output artifacts/upstream-acceptance --soak-iterations 20
```

The tool creates and removes its own internal-only network, target/proxy containers and data
volume. It fails rather than reuse a non-empty output directory. The target is pinned in both
`config/upstream.lock.yaml` and the harness; the adapter images must exactly match
`config/adapters.lock.yaml`.

The deployment templates require an operator-supplied base image reference containing a reviewed
`sha256` digest and publish no ports. The signer uses `network_mode: none`. Before Phase 4, on a host
with a functioning Docker or Podman daemon:

1. build with the reviewed immutable Python base digest;
2. inspect the image digest and record it in the registry;
3. run every adapter non-root, read-only, with all capabilities dropped, bounded tmpfs/CPU/memory/
   PIDs and only the target network;
4. demonstrate denial of host mounts, container socket, metadata endpoints, peer runners, evidence
   and secrets;
5. run the Unix-socket signer with no network namespace and repeat nonce-restart vectors.

The completed live isolation run used:

```sh
.venv/bin/python tools/container_acceptance.py \
  --image sha256:0daac106f36240564ceb8d5d90a044236f8fe5d84ccbf1ebddc233b3858dd447 \
  --node-image sha256:5b03701867f856f375ace1a0cbf63b0f9795ab0a208a975f5e5aa938f5b5d1ce \
  --output artifacts/container-acceptance-coverage-final.json
```

`artifacts/upstream-acceptance-authoritative-v2/` contains the official-target transcript, verified bundle and
live isolation report. Rebuilds create new local image IDs, so update the explicit IDs
only after reviewing the pinned base digests and rerunning every check.

No cloud deployment, production DID or public write is authorized by this guide.

# Controlled launch runbook

## Current state

Rosetta is live as a static observatory and as a no-ingress, read-only observer on the dedicated
Hetzner server. The 1 September 2026 check found zero public writes, zero service restarts, an
SSH-only public listener and bounded disk, while all three watched upstream endpoints returned 503.
That is a green safety boundary with an `unavailable` compatibility warning, not a safety failure.
Scheduler, runners, signer, publisher and public request intake remain absent.

The transitional safety review passed on 3 September 2026 after 73 hours and 34 minutes. It combined
the truthful legacy interval with v2 safety checkpoints as required below: zero public writes, no
unexplained restarts, SSH-only public listeners, bounded disk and a final complete verifier pass.
Upstream releases and availability warnings did not restart that window. Gate B permits the
read-only product to remain live and planning the controlled pilot; it does not authorize a
production identity or a public write.

The signed fixed-path gate is installed and the 3 September release activated reviewed commit
`db810b15954cef1bbecfa8f25e4000ec40d16092`. It independently confirmed two healthy expected
containers, a fresh `safe` observation and zero public writes. Upstream v0.11.3 was recorded as
`release_drift`, as designed. The release completed through the narrow deployment account without
provider-console work, and retained automatic rollback plus the prior immutable release.

## Launch gates

| Gate | Required evidence | Authority |
|---|---|---|
| A — local acceptance | full quality gate, official v0.10.0 matrix, soak, isolation and signed evidence pass | repository review |
| B — read-only staging | continuous safety-safe operation; zero writes; no unexplained restart; SSH-only listener; bounded disk; compatibility warnings recorded | operator review |
| C — identity readiness | production key ceremony, two recoverable encrypted backups, signer credential, DID/public fingerprint recorded, recovery drill | explicit operator approval |
| D — publication readiness | approved static origin, immutable report path, service card, request/reply rooms, limits, alert destination and off-device backup | explicit operator approval |
| E — first public action | exact signed payload preview, destination, budget and rollback reviewed | per-action operator approval |
| F — 14-day pilot | at most two requests per DID/day and eight globally/day; changed reports only; daily status; weekly human review | bounded pilot approval |

No later gate inherits authority from an earlier gate.

## Next-upstream upgrade canary

Before launch and after any observer change, run the deterministic no-network canary into a fresh
output directory:

```sh
PYTHONPATH=src:. .venv/bin/python tools/upgrade_canary.py \
  --output artifacts/upgrade-canary
```

The canary drives one long-lived observer instance through the reviewed baseline, an additive
synthetic next release, HTTP 429, HTTP 503, rejected authority metadata and recovery to the
reviewed baseline. It passes only if every durable checkpoint remains safety-safe, all requests are
GETs to the three fixed metadata paths, public writes remain zero, the observer never requests a
stop, recovery needs no process restart and SQLite integrity remains intact. The synthetic release
does not prove an unknown future protocol compatible; it proves that release churn cannot stop the
read-only product or silently promote a new execution baseline. A real upstream tag still requires
the pinned differential acceptance matrix before any write-capable promotion.

The integration gate also injects an unexpected internal probe exception. The same process must
continue and recover on its next healthy cycle, but the failed cycle remains durably `unsafe` and
therefore resets the affected safety window. Availability never overrides an honest safety verdict.

## 72-hour staging review

Run the offline state validator from the deployed release:

```sh
sudo setpriv --reuid=65532 --regid=65532 --clear-groups \
  python3 /opt/rosetta/current/tools/staging_status.py \
  --state-dir /var/lib/rosetta/state \
  --evidence-dir /var/lib/rosetta/evidence \
  --expected-release v0.10.0 \
  --max-age-seconds 660 \
  --min-observations 800 \
  --max-evidence-bytes 104857600
```

For a fresh v2 deployment, a five-minute interval over 72 hours normally produces about 864 safety
checks. The lower bound of 800 allows a bounded maintenance window without accepting a mostly idle
deployment. During the v1-to-v2 migration, retain the signed/operator-reviewed legacy interval and
combine it with host uptime, restart count and new v2 safety checks; never fabricate historical
rows. Also verify:

```sh
sudo systemctl is-active rosetta-observer.service
sudo systemctl is-enabled rosetta-observer.service
sudo systemctl show rosetta-observer.service -p NRestarts
sudo journalctl -u rosetta-observer.service --since '72 hours ago' --no-pager
sudo ss -lntup
```

Fail the gate on stale or unsafe local health, nonzero public writes, integrity error, unexpected
listener, unexplained restart, kill switch, or evidence budget breach. `release_drift`,
`unavailable` and `rejected` are visible compatibility warnings and do not reset the read-only
safety window. They block promotion of that upstream version into public execution until reviewed.
Only a Rosetta change that expands methods, destinations, credentials, listeners or write authority
resets the affected safety gate.

## Monitoring and encrypted backup

Install `rosetta-healthcheck.service` and `.timer` after reviewing their paths. A failed check is
durable in systemd and the journal. It is not an external alert; an operator-selected destination
must be added before Gate D.

The encrypted backup timer requires Debian's `age` package and a file containing only an approved
Age public recipient at `/etc/rosetta/backup-recipient.txt`. The backup process uses SQLite's backup
API, refuses non-regular evidence files, pipes the snapshot directly into Age and retains no
plaintext snapshot. Copy encrypted archives to an independently controlled off-device destination;
the server copy alone is not a backup.

Both one-shot services run as numeric UID/GID 65532, not root. Before enabling either timer, install
Age, create the destination with that ownership, and install only the public recipient (never its
secret key):

```sh
sudo apt-get install age
sudo install -d -o root -g root -m 0755 /etc/rosetta
sudo install -d -o 65532 -g 65532 -m 0700 /var/backups/rosetta/encrypted
sudo install -o root -g root -m 0644 APPROVED_AGE_PUBLIC_RECIPIENT_FILE \
  /etc/rosetta/backup-recipient.txt
```

Then install and exercise the units:

```sh
sudo install -o root -g root -m 0644 deploy/rosetta-healthcheck.service /etc/systemd/system/
sudo install -o root -g root -m 0644 deploy/rosetta-healthcheck.timer /etc/systemd/system/
sudo install -o root -g root -m 0644 deploy/rosetta-backup.service /etc/systemd/system/
sudo install -o root -g root -m 0644 deploy/rosetta-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start rosetta-healthcheck.service
sudo systemctl start rosetta-backup.service
```

Inspect the one-shot results and restore one encrypted archive on a separate trusted machine before
enabling the timers. Record the restore result and ciphertext hash under ignored operator records.
Never store an Age secret key on the Rosetta server.

## Pilot activation order

1. Pass the safety review and retain its output under ignored `local/`; compatibility warnings are
   allowed for the read-only surface but not for public execution.
2. Approve branding, public contact surface and narrow launch wording.
3. Select the static publisher origin and provision a credential restricted to that one target.
4. Complete `PRODUCTION_KEY_CEREMONY.md`; record only the public DID in reviewed configuration.
5. Build a new immutable image from the reviewed commit and hash-locked dependencies.
6. Re-run host acceptance, official matrix, OCI isolation and secret scan.
7. Generate the service card and exact first announcement locally; verify signatures offline.
8. Take a provider snapshot and encrypted application backup; preserve the prior release/image.
9. Obtain explicit approval for the exact service room, mailbox, publisher origin, budgets and first
   public payload.
10. Enable one boundary at a time: signer, static publication, claimed room, request mailbox, then
    bounded intake. Verify after each boundary and stop on ambiguity.

## Emergency stop and rollback

The host kill switch is primary:

```sh
sudo touch /var/lib/rosetta/state/KILL_SWITCH
sudo systemctl stop rosetta-observer.service
```

For a pilot, also stop discovery, scheduler, signer and publisher units, remove egress, and preserve
state read-only. Do not remove the kill switch until incident review. Roll back by restoring the
previous `/opt/rosetta/current` target and immutable image reference, validating rendered Compose,
then starting only the read-only observer first.

If DID exposure is plausible, retire the DID. Do not claim continuity and do not restore the same
seed to service.

## Inputs still requiring the operator

- approved branding/avatar and whether the Proton address is public;
- Age public recipient and independent off-device backup destination;
- external alert destination with no broad account permissions;
- production key ceremony and recovery custodians;
- static publisher domain/repository/bucket and single-destination credential;
- exact first public payload and authorization for Technocore writes;
- whether the private repository becomes public, which also changes ruleset enforcement.

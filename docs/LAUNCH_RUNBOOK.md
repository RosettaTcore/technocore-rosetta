# Controlled launch runbook

## Current state

Rosetta is live only as a no-ingress, read-only observer on the dedicated Hetzner server. The
deployed release is commit `4d2a374be479e3c539ad16a87237607edf49159c`; the observer and egress
proxy are healthy, and every recorded status has `public_writes: 0`. Scheduler, runners, signer,
publisher and public request intake remain absent.

The first 72-hour review is scheduled for 2 September 2026 at 23:23 Europe/Ljubljana. Passing that
review permits planning the controlled pilot; it does not authorize a production identity or a
public write.

## Launch gates

| Gate | Required evidence | Authority |
|---|---|---|
| A — local acceptance | full quality gate, official v0.10.0 matrix, soak, isolation and signed evidence pass | repository review |
| B — read-only staging | 72 hours healthy; zero writes; no unexplained restart; SSH-only listener; bounded disk; every new protocol digest reviewed | operator review |
| C — identity readiness | production key ceremony, two recoverable encrypted backups, signer credential, DID/public fingerprint recorded, recovery drill | explicit operator approval |
| D — publication readiness | approved static origin, immutable report path, service card, request/reply rooms, limits, alert destination and off-device backup | explicit operator approval |
| E — first public action | exact signed payload preview, destination, budget and rollback reviewed | per-action operator approval |
| F — 14-day pilot | at most two requests per DID/day and eight globally/day; changed reports only; daily status; weekly human review | bounded pilot approval |

No later gate inherits authority from an earlier gate.

## 72-hour staging review

Run the offline state validator from the deployed release:

```sh
sudo -u '#65532' python3 /opt/rosetta/current/tools/staging_status.py \
  --state-dir /var/lib/rosetta/state \
  --evidence-dir /var/lib/rosetta/evidence \
  --expected-release v0.10.0 \
  --max-age-seconds 660 \
  --min-observations 800 \
  --max-evidence-bytes 104857600
```

At a five-minute interval, 72 hours normally produces about 864 observations. The lower bound of
800 allows a bounded maintenance window without accepting a mostly idle deployment. Also verify:

```sh
sudo systemctl is-active rosetta-observer.service
sudo systemctl is-enabled rosetta-observer.service
sudo systemctl show rosetta-observer.service -p NRestarts
sudo journalctl -u rosetta-observer.service --since '72 hours ago' --no-pager
sudo ss -lntup
```

Fail the gate on a stale/unhealthy record, nonzero public writes, an unreviewed digest, integrity
error, unexpected listener, unexplained restart, kill switch, or evidence budget breach.

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

1. Pass the 72-hour review and retain its output under ignored `local/`.
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

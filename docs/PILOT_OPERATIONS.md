# Active pilot operations

## Scope

The pilot makes Rosetta useful to another Technocore agent without a download or Rosetta-hosted
inbound API. A peer reads the HTTPS service card, sends one signed closed-schema request to the
derived public mailbox and receives a signed acknowledgement plus a content-addressed report URL.

The pilot is not a general agent runtime. Public content cannot select code, commands, prompts,
URLs, repositories, commits, images, assertions, private mailboxes or secrets. The only executable
choice is one scenario ID and two adapter IDs from the reviewed local registry. Verdicts are
deterministic and no model participates.

## Deployment boundaries

- The signer remains a separate networkless OCI container and retains the only seed access.
- The pilot receives only the signer Unix socket; the seed is owner-readable by the signer UID.
- The pilot container has an internal network only and no public port.
- A separate egress container can reach only `https://technocore.chat`.
- Egress GETs are limited to reviewed metadata, discovery rooms, the request mailbox, public reply
  mailboxes and the exact ownership note.
- Egress POSTs are limited to the one derived service room, public `mb-*` mailboxes and its exact
  ownership claim; the configured DID and closed body shape must match.
- Static publication is limited to the six attested service documents and verified
  content-addressed evidence bundles under the approved root.
- State, signed outbound bytes, cursors, jobs and quotas survive process restarts in SQLite WAL.

## Install without writing publicly

On the existing no-domain HTTPS host, the recommended first installation is the fixed, no-argument
bootstrap. It reads the already approved public IPv4 address, asks the active networkless signer
for only its public DID, renders the closed configuration, installs the disabled unit and prepares
the exact launch bytes:

```sh
sudo /opt/rosetta/current/deploy/bootstrap-rosetta-pilot.sh
```

The bootstrap refuses an existing config, preview, active service or enabled service. Its final
lines must be `pilot_bootstrap=pass`, `pilot_enabled=no` and `public_writes=0`. It never prints or
copies the seed and does not activate the pilot. Preserve the displayed preview and digest for the
separate approval step below.

The manual alternative is useful when the report origin or approved runtime paths differ from the
standard single-server deployment.

Create `/root/rosetta-pilot.yaml` from `config/config.pilot.example.yaml`. Set only the public DID,
the existing HTTPS IPv4 origin and approved runtime paths. Set `service.enabled: true`; the runtime
still cannot start without the explicit activation token and approved preview digest. Never place a
seed, passphrase, Age identity, SSH key or private mailbox capability in this file.

From the active signed release, install the disabled unit:

```sh
sudo /opt/rosetta/current/deploy/install-rosetta-pilot.sh \
  /opt/rosetta/current \
  /etc/rosetta/staging.env \
  /root/rosetta-pilot.yaml
```

Expected final lines are `pilot_install=pass`, `pilot_enabled=no` and `public_writes=0`.

## Prepare and approve the exact launch

With the production signer active, prepare the launch:

```sh
sudo /usr/local/libexec/prepare-rosetta-pilot
sudo cat /var/lib/rosetta/pilot/activation-preview.json
sudo cat /var/lib/rosetta/pilot/activation-preview.sha256
```

Preparation performs no network write. Review all of the following before approval:

- authority and HTTPS report origin;
- DID, derived `d-rosetta-*` service room and `mb-rosetta-*` request mailbox;
- exact ownership-note and announcement bodies, signatures and nonces;
- service-card digest, adapter list, scenario and quotas;
- automatic polling and response behavior.

Activation is one separately approved action using the exact displayed digest:

```sh
sudo /usr/local/libexec/activate-rosetta-pilot sha256:APPROVED_PREVIEW_DIGEST
```

The activator sends only the two prepared launch writes, starts the continuous service, enables its
five-minute local health timer and waits up to 60 seconds for a fresh healthy state. A crash after an
upstream commit is reconciled using the exact persisted DID, nonce and bytes; it never signs a
replacement merely because the outcome is uncertain.

## Daily checks

```sh
sudo /usr/local/libexec/check-rosetta-pilot
sudo systemctl --no-pager status rosetta-pilot.service
sudo systemctl --no-pager status rosetta-signer.production.service
sudo systemctl list-timers 'rosetta-*'
```

Healthy means: both containers are running, signer socket exists, health is younger than 120
seconds, activation matches the current service room/mailbox and public writes are explicitly
enabled. Operational logs must not contain request bodies, signatures, headers or secrets.

The service card is valid for the complete 14-day pilot. Before extending service beyond that
window, prepare and approve a refreshed card and digest announcement as a new release action.

## Stop, contain and recover

The fastest fail-closed control is:

```sh
sudo install -o 65532 -g 65532 -m 0444 /dev/null /var/lib/rosetta/state/KILL_SWITCH
sudo systemctl stop rosetta-pilot.service
```

This leaves state and bundles intact. Do not remove the switch until the incident is reviewed.
Restore the last encrypted backup into an isolated directory first; verify Age decryption,
checksums, SQLite integrity and evidence roots before replacing any live state. Restart the signer
first, then the read-only observer, and only then re-enable the pilot after a new activation review.

## Upstream upgrades

The read-only observer records release drift without going offline. The active pilot remains on the
last accepted baseline. Run the deterministic upstream upgrade canary against the candidate source
and OCI digest; if the protocol and safety assertions pass, update the pinned baseline through the
normal SSH-signed release gate. A green semantic canary is the promotion criterion—there is no
automatic 48/72-hour pause and no mutable `latest` dependency.

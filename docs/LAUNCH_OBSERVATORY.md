# Static launch observatory

The launch observatory under `site/` is Rosetta's public, read-only presentation layer. It exposes
the bounded launch claim, the four-runtime matrix, a synthetic signed reference bundle and a local
browser verifier. It does not expose a scheduler, signer, mailbox, publisher, dynamic API or live
host telemetry.

## Local preview

From the repository root:

```sh
python3 -m http.server 4173 --directory site
```

Open `http://127.0.0.1:4173/`. The page has no third-party scripts, fonts, analytics or runtime
dependencies. Its content-security policy disables network connections from scripts. The only
external links are ordinary navigational links to this repository.

Run the fail-closed site gate with:

```sh
make site-check
```

The gate checks local resources, active-content restrictions, the content-security policy, the
exact reference bundle root, its Ed25519 attestation, the deterministic download archive and the
same browser verification code against valid, mutated, extra-file and substituted-signature cases.

## Evidence update procedure

The checked-in bundle is synthetic reference evidence, not production evidence. To replace it:

1. produce a fresh reviewed upstream bundle from the pinned acceptance lane;
2. verify it independently with `rosetta.cli verify`;
3. confirm that `run.json` says `dry_run: true` and contains no production DID or secret;
4. copy only the bundle directory into `site/evidence/latest/`;
5. update the exact root and bounded metadata in `site/index.html` and
   `tools/check_launch_site.py`;
6. run `python3 tools/package_launch_evidence.py` to rebuild the deterministic ZIP;
7. run `make site-check`, the full acceptance gate and human review.

Never copy signer state, nonce databases, runtime logs, operator records or staging host state into
the site. A production evidence publication path requires its own approved immutable origin and
single-destination credential.

## Status semantics

The status strip is explicitly a recorded snapshot. It must never look or behave like live
telemetry unless a separately reviewed, privacy-preserving static status publication mechanism is
added. A green recorded snapshot does not imply current availability, protocol safety, trust,
endorsement or certification.

The browser verifier processes user-selected files in memory. It uploads nothing and performs no
network request. It validates byte integrity and the domain-separated signature; it does not judge
the meaning or safety of the observed system.

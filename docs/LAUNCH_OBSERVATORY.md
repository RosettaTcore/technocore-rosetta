# Static launch observatory

The launch observatory under `site/` is Rosetta's public, read-only presentation layer. It exposes
the bounded launch claim, the four-runtime matrix, a synthetic signed reference bundle and two
browser verification paths. The primary path verifies the hosted reference in one click with no
manual download. The advanced path accepts an operator-owned local bundle for independent offline
verification. The site does not expose a scheduler, signer, mailbox, publisher, dynamic API or live
host telemetry.

## Local preview

From the repository root:

```sh
python3 -m http.server 4173 --directory site
```

Open `http://127.0.0.1:4173/`. The page has no third-party scripts, fonts, analytics or runtime
dependencies. Its content-security policy permits script requests only to the page's own origin;
the hosted verifier omits credentials, rejects redirects and applies strict file-count and byte
bounds. The only external links are ordinary navigational links to this repository.

The primary visitor path is deliberately proof-first:

```text
understand the bounded claim -> inspect the reference result
  -> verify the hosted evidence in one click -> inspect implementation/security
```

Downloading, extracting and selecting a bundle remains available under advanced verification. It
is not required for the primary product experience.

Run the fail-closed site gate with:

```sh
make site-check
```

The gate checks local resources, active-content restrictions, the content-security policy, the
exact reference bundle root, its Ed25519 attestation, the deterministic optional archive and the
same browser verification code against valid, mutated, extra-file, cross-origin and
substituted-signature cases.
It also ratchets required launch metadata, the README proof-first narrative, the reusable brand
mark and size limits for loaded artwork.

## Public URL finalization

The repository intentionally contains no guessed canonical site URL. After an immutable public
origin is approved and before announcing it:

1. add an absolute `link[rel=canonical]` and matching `og:url`;
2. replace relative Open Graph and Twitter image references with the absolute 1200×630 card URL;
3. add the public observatory URL to the repository homepage and the README's first-screen actions;
4. update `tools/check_launch_site.py` to require the exact approved origin;
5. verify the rendered social card with at least two preview debuggers without adding their scripts;
6. run `make site-check` and the full acceptance gate again.

Until this step is complete, the local page remains a launch candidate rather than a published
canonical website.

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

Immediately after the 72-hour review, replace the displayed operator-check date and pending state
with the exact reviewed outcome, or remove the strip if no current evidence record can be linked.
Never roll the date forward without the corresponding operator record.

The instant verifier fetches only the reviewed evidence path from the page's own origin without
credentials and validates the returned bytes in memory. This proves that the served files match
their bundle root and domain-separated signature; it does not make the serving origin independent.
The advanced verifier processes user-selected files in memory, uploads nothing and performs no
network request. Neither path judges the meaning or safety of the observed system.

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

## Public origin and deployment

The canonical public origin is:

```text
https://rosettatcore.github.io/technocore-rosetta/
```

GitHub Pages keeps the public static surface separate from the no-ingress Hetzner observer. The
deployment receives only the checked-in `site/` directory. It receives no server state, secret,
signer, publisher credential, mailbox capability or GitHub write credential beyond GitHub's
short-lived Pages deployment token.

`.github/workflows/pages.yml` is deliberately downstream of the `CI` workflow on `main`. It refuses
failed CI runs, checks out the exact CI-reviewed commit, installs hash-locked runtime dependencies,
runs `make site-check`, uploads only `site/`, and deploys through the `github-pages` environment.
Every third-party action is pinned to a full reviewed commit. Manual dispatch runs the same checks.

The initial publication gates were completed on 1 September 2026. The repository was made public
only after a reachable-history privacy review; Pages was set to **GitHub Actions**; publication PR
[#22](https://github.com/RosettaTcore/technocore-rosetta/pull/22) passed both required CI jobs and
was squash-merged as `8ddaee9`; and Pages run
[#1](https://github.com/RosettaTcore/technocore-rosetta/actions/runs/33446317758) re-verified and
deployed the site successfully. Post-deployment browser verification loaded the canonical URL and
assets, then validated all 15 hosted payloads, the exact bundle root and the Ed25519 attestation.

The repository homepage should retain the canonical URL. Social-card previews may be checked with
external debuggers, but their scripts or tracking assets must never be added to this site.

A future custom domain is a new origin change. It requires an updated canonical URL, social image
URLs, sitemap, site ratchet, DNS review and HTTPS verification before announcement.

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

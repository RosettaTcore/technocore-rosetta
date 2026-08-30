# Signed release workflow

GitHub-created squash commits may not carry the contributor's SSH signature. Rosetta therefore
treats green pull-request checks as review evidence and a locally created signed release commit or
signed annotated tag as release identity evidence.

The currently deployed read-only commit
`4d2a374be479e3c539ad16a87237607edf49159c` is a GitHub squash commit without an embedded Git
signature. Its pull-request inputs were signed and CI passed. Do not rewrite published history to
change that fact. Before any public-write image is built, create a new reviewed signed release
commit through the procedure below, or apply an operator-approved signed annotated tag to the exact
reviewed commit.

## Procedure

1. Work on a feature branch; every authored commit is SSH-signed.
2. Push the branch and let all required CI checks pass.
3. Review the exact pull-request head and dependency/container provenance.
4. Create the final commit locally with the dedicated Rosetta identity and SSH signing enabled.
5. Verify the final commit locally with the Rosetta allowed-signers file.
6. Push the exact signed commit only after operator approval. Never force-push `main` for routine
   release work.
7. Verify the remote commit hash, GitHub checks and local signature again.
8. Build from that exact hash, record image digest/SBOM and run acceptance/isolation.
9. Create a signed annotated version tag only after the built artifact passes all gates.

Record the commit, tag, image digest, dependency-lock hashes, evidence bundle root and rollback image
in the deployment record. A Git signature proves authorship of bytes, not correctness; CI and the
acceptance evidence remain separate requirements.

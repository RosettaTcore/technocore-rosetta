# Production identity ceremony

This ceremony is deliberately operator-only. Rosetta, Codex, CI, GitHub and the worker must never
receive the production seed. No production key has been generated or authorized by this document.

## Preconditions

- The 72-hour read-only gate passed.
- The signer release and `rosetta-signer.production.service` were reviewed.
- Two independent encrypted backup destinations and their recovery operators were selected.
- The ceremony machine is trusted, patched, disconnected from network and has no screen sharing,
  shell history capture, cloud sync or clipboard manager.
- The operator has an approved method for generating 32 cryptographically random raw bytes without
  displaying them.

## Ceremony record

Record only:

- date and participants;
- hash and signed commit of the reviewed signer release;
- public `did:key` and its 16-hex Technocore fingerprint;
- encrypted backup file hashes and storage locations;
- successful recovery-test result;
- production signer host credential identifier;
- explicit go/no-go decision.

Never record the seed, passphrase, decrypted key file, recovery plaintext or command output that
contains private material.

## Procedure

1. Verify the reviewed release and signer binary offline.
2. Create exactly 32 raw random bytes in a private memory-backed path with owner-only permissions.
3. Derive and record only the public DID. Confirm a test artifact signature verifies offline.
4. Encrypt two independent backups to operator-controlled recipients. Store them in different
   physical or administrative failure domains.
5. Delete the plaintext, unmount the memory-backed path and power-cycle before recovery testing.
6. Recover one backup in a fresh private session, derive the same public DID, sign a fresh test
   digest and verify it offline. Delete the recovered plaintext and power-cycle again.
7. Provision the server's systemd encrypted credential without placing seed bytes in arguments,
   environment variables, repository files, general logs or persistent plaintext storage.
8. Start only the networkless signer. Confirm `PrivateNetwork=yes`, an AF_UNIX-only socket, owner-only
   nonce state and the expected public DID.
9. Stop the signer. Public writes remain unauthorized until the exact first payload is approved.

The checked-in production unit reads `%d/rosetta.seed` through `LoadCredentialEncrypted`; the path,
not the secret, is passed to the signer. `SeedFileIdentity` rejects symlinks, non-regular files,
wrong ownership, group/other permissions and any length other than 32 bytes.

Before the offline ceremony, install but do not enable the reviewed signer boundary using the
current immutable observer image ID from the root-owned staging environment:

```sh
sudo /opt/rosetta/current/deploy/install-rosetta-signer.sh \
  /opt/rosetta/current /etc/rosetta/staging.env
```

The installer must report `signer_enabled=no` and `public_writes=0`. After the two encrypted
off-device backups and the fresh-session recovery test pass, stream a Base64 transport envelope of
the exact 32 raw seed bytes over an operator-controlled encrypted channel into the provisioner. The
ASCII envelope avoids pseudo-terminal corruption and is decoded only in memory. Do not put either
representation in a command, argument, environment variable, clipboard or persistent server file:

```sh
base64 < PRIVATE_MEMORY_SEED_FILE | \
  ssh -T OPERATOR_APPROVED_DEPLOYMENT_ACCOUNT \
    sudo /usr/local/libexec/provision-rosetta-signer-credential
```

Run that command manually outside Codex and any captured terminal. The provisioner refuses to
overwrite an existing credential, decodes stdin directly into `systemd-creds`, decrypts only into a
byte counter to confirm an exact 32-byte payload and retains no server-side plaintext file.
Installing or provisioning the signer still does not enable it or authorize a public write.

## Recovery and rotation

Restore only during an operator-declared incident or migration. Verify backup ciphertext hash before
decryption, recover in a private session, derive the expected DID and rotate the host credential.
If compromise is possible, do not restore for continued identity claims: retire the DID, publish a
reviewed correction with a new identity and explicitly state that continuity ended.

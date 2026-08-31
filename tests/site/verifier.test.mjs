import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import { readFile, readdir } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { parseChecksums, verifyBundleFiles } from "../../site/verifier.mjs";

globalThis.crypto ??= webcrypto;

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const BUNDLE = path.join(ROOT, "site/evidence/latest");
const EXPECTED_ROOT = "sha256:0b3435df9b0f6eb8b1ac2eaab22120a0b14730764fceaa9d1a701860f43c1b9f";

async function bundleFiles(directory, prefix = "") {
  const files = new Map();
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const relative = prefix ? `${prefix}/${entry.name}` : entry.name;
    const absolute = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      for (const [name, bytes] of await bundleFiles(absolute, relative)) files.set(name, bytes);
    } else if (entry.isFile()) {
      files.set(relative, new Uint8Array(await readFile(absolute)));
    }
  }
  return files;
}

test("browser verifier accepts the checked-in signed reference bundle", async () => {
  const result = await verifyBundleFiles(await bundleFiles(BUNDLE));
  assert.equal(result.root, EXPECTED_ROOT);
  assert.equal(result.entries, 15);
  assert.match(result.did, /^did:key:z6Mk/);
});

test("browser verifier fails closed when a payload byte changes", async () => {
  const files = await bundleFiles(BUNDLE);
  const target = "matrix.json";
  const mutated = files.get(target).slice();
  mutated[0] ^= 1;
  files.set(target, mutated);
  await assert.rejects(verifyBundleFiles(files), /checksum mismatch: matrix\.json/);
});

test("browser verifier rejects extra and unsafe paths", async () => {
  const files = await bundleFiles(BUNDLE);
  files.set("unexpected.json", new Uint8Array([123, 125]));
  await assert.rejects(verifyBundleFiles(files), /file set differs/);
  assert.throws(
    () => parseChecksums(`${"0".repeat(64)}  ../outside.json\n`),
    /unsafe or reserved bundle path/,
  );
});

test("browser verifier rejects a substituted attestation", async () => {
  const files = await bundleFiles(BUNDLE);
  const attestation = JSON.parse(new TextDecoder().decode(files.get("attestation.json")));
  attestation.signature = `${attestation.signature.slice(0, -1)}A`;
  files.set("attestation.json", new TextEncoder().encode(JSON.stringify(attestation)));
  await assert.rejects(verifyBundleFiles(files), /invalid Ed25519 bundle attestation/);
});

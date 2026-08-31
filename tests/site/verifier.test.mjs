import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import { readFile, readdir } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  fetchAndVerifyHostedBundle,
  parseChecksums,
  verifyBundleFiles,
} from "../../site/verifier.mjs";

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

function hostedFetcher(files, mutate = null) {
  return async (url, options) => {
    assert.equal(url.origin, "https://rosetta.example");
    assert.equal(options.cache, "no-store");
    assert.equal(options.credentials, "omit");
    assert.equal(options.redirect, "error");
    const prefix = "/evidence/latest/";
    assert.ok(url.pathname.startsWith(prefix));
    const pathName = url.pathname.slice(prefix.length);
    const source = files.get(pathName);
    if (!source) return { ok: false, redirected: false, arrayBuffer: async () => new ArrayBuffer(0) };
    const bytes = mutate?.(pathName, source) ?? source;
    const copy = bytes.slice();
    return { ok: true, redirected: false, arrayBuffer: async () => copy.buffer };
  };
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

test("hosted verifier fetches and validates the signed reference without a download", async () => {
  const files = await bundleFiles(BUNDLE);
  const result = await fetchAndVerifyHostedBundle({
    baseUrl: "https://rosetta.example/evidence/latest/",
    pageUrl: "https://rosetta.example/",
    fetcher: hostedFetcher(files),
  });
  assert.equal(result.root, EXPECTED_ROOT);
  assert.equal(result.entries, 15);
});

test("hosted verifier fails closed on another origin or a mutated fetched payload", async () => {
  const files = await bundleFiles(BUNDLE);
  await assert.rejects(
    fetchAndVerifyHostedBundle({
      baseUrl: "https://unreviewed.example/evidence/latest/",
      pageUrl: "https://rosetta.example/",
      fetcher: hostedFetcher(files),
    }),
    /must use the page origin/,
  );
  await assert.rejects(
    fetchAndVerifyHostedBundle({
      baseUrl: "https://rosetta.example/evidence/latest/",
      pageUrl: "https://rosetta.example/",
      fetcher: hostedFetcher(files, (pathName, source) => {
        if (pathName !== "matrix.json") return source;
        const mutated = source.slice();
        mutated[0] ^= 1;
        return mutated;
      }),
    }),
    /checksum mismatch: matrix\.json/,
  );
});

test("hosted verifier rejects redirects, oversized files, and ambiguous paths", async () => {
  const options = {
    baseUrl: "https://rosetta.example/evidence/latest/",
    pageUrl: "https://rosetta.example/",
  };
  await assert.rejects(
    fetchAndVerifyHostedBundle({
      ...options,
      fetcher: async () => ({
        ok: true,
        redirected: true,
        arrayBuffer: async () => new ArrayBuffer(0),
      }),
    }),
    /hosted evidence request failed/,
  );
  await assert.rejects(
    fetchAndVerifyHostedBundle({
      ...options,
      fetcher: async () => ({
        ok: true,
        redirected: false,
        headers: { get: () => String(1024 * 1024 + 1) },
        arrayBuffer: async () => assert.fail("oversized response must be rejected before reading"),
      }),
    }),
    /hosted evidence file exceeds size limit/,
  );

  const files = await bundleFiles(BUNDLE);
  const original = new TextDecoder().decode(files.get("checksums.txt"));
  files.set(
    "checksums.txt",
    new TextEncoder().encode(original.replace("matrix.json", "matrix/./result.json")),
  );
  await assert.rejects(
    fetchAndVerifyHostedBundle({ ...options, fetcher: hostedFetcher(files) }),
    /unsafe hosted evidence path/,
  );
});

test("hosted verifier bounds the evidence manifest before fetching payloads", async () => {
  const manifest = Array.from(
    { length: 65 },
    (_, index) => `${"0".repeat(64)}  payload-${index}.json`,
  ).join("\n");
  let requests = 0;
  await assert.rejects(
    fetchAndVerifyHostedBundle({
      baseUrl: "https://rosetta.example/evidence/latest/",
      pageUrl: "https://rosetta.example/",
      fetcher: async () => {
        requests += 1;
        const copy = new TextEncoder().encode(manifest);
        return { ok: true, redirected: false, arrayBuffer: async () => copy.buffer };
      },
    }),
    /hosted evidence lists too many files/,
  );
  assert.equal(requests, 1);
});

const SHA256_PREFIX = "sha256:";
const ARTIFACT_DOMAIN = new TextEncoder().encode("rosetta.artifact.v1\0");
const BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
const MAX_HOSTED_FILES = 64;
const MAX_HOSTED_FILE_BYTES = 1024 * 1024;
const MAX_HOSTED_TOTAL_BYTES = 4 * 1024 * 1024;

export function parseChecksums(text) {
  const entries = [];
  const paths = new Set();
  const lines = text.replace(/\r\n/g, "\n").split("\n");

  for (const line of lines) {
    if (!line) continue;
    const match = /^([0-9a-f]{64})  ([^\0]+)$/.exec(line);
    if (!match) throw new Error("checksums.txt contains a malformed line");
    const [, sha256, path] = match;
    if (
      path.startsWith("/") ||
      path.startsWith("./") ||
      path.includes("\\") ||
      path.split("/").includes("..") ||
      path === "checksums.txt" ||
      path === "attestation.json"
    ) {
      throw new Error(`unsafe or reserved bundle path: ${path}`);
    }
    if (paths.has(path)) throw new Error(`duplicate bundle path: ${path}`);
    paths.add(path);
    entries.push({ path, sha256 });
  }

  if (entries.length === 0) throw new Error("checksums.txt lists no payload files");
  return entries;
}

export async function sha256Hex(bytes) {
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export async function computeBundleRoot(entries) {
  const manifest = [...entries]
    .sort((left, right) => left.path.localeCompare(right.path) || left.sha256.localeCompare(right.sha256))
    .map(({ path, sha256 }) => ({ path, sha256 }));
  const canonical = new TextEncoder().encode(JSON.stringify(manifest));
  return SHA256_PREFIX + await sha256Hex(canonical);
}

function base58Decode(value) {
  if (!value) throw new Error("empty base58btc value");
  const bytes = [0];
  for (const character of value) {
    const digit = BASE58_ALPHABET.indexOf(character);
    if (digit < 0) throw new Error("invalid base58btc character");
    let carry = digit;
    for (let index = 0; index < bytes.length; index += 1) {
      carry += bytes[index] * 58;
      bytes[index] = carry & 0xff;
      carry >>= 8;
    }
    while (carry > 0) {
      bytes.push(carry & 0xff);
      carry >>= 8;
    }
  }
  for (let index = 0; index < value.length - 1 && value[index] === "1"; index += 1) bytes.push(0);
  return Uint8Array.from(bytes.reverse());
}

function base64UrlDecode(value) {
  if (!/^[A-Za-z0-9_-]+$/.test(value) || value.includes("=")) {
    throw new Error("invalid unpadded base64url signature");
  }
  const padded = value.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - value.length % 4) % 4);
  if (typeof atob === "function") return Uint8Array.from(atob(padded), (character) => character.charCodeAt(0));
  return Uint8Array.from(Buffer.from(padded, "base64"));
}

function publicKeyFromDid(did) {
  const prefix = "did:key:z";
  if (typeof did !== "string" || !did.startsWith(prefix)) throw new Error("unsupported DID");
  const decoded = base58Decode(did.slice(prefix.length));
  if (decoded.length !== 34 || decoded[0] !== 0xed || decoded[1] !== 0x01) {
    throw new Error("DID is not an Ed25519 did:key");
  }
  return decoded.slice(2);
}

function artifactPayload(root) {
  if (!/^sha256:[0-9a-f]{64}$/.test(root)) throw new Error("invalid bundle root");
  const digest = new TextEncoder().encode(root);
  const payload = new Uint8Array(ARTIFACT_DOMAIN.length + digest.length);
  payload.set(ARTIFACT_DOMAIN);
  payload.set(digest, ARTIFACT_DOMAIN.length);
  return payload;
}

export async function verifyAttestation(attestation, root) {
  if (
    attestation.schema !== "rosetta.attestation.v1" ||
    attestation.algorithm !== "Ed25519" ||
    attestation.domain !== "rosetta.artifact.v1" ||
    attestation.bundle_root !== root
  ) {
    throw new Error("attestation metadata or bundle root does not match");
  }
  const publicKey = publicKeyFromDid(attestation.did);
  const signature = base64UrlDecode(attestation.signature);
  if (signature.length !== 64 || attestation.signature.length !== 86) throw new Error("invalid signature length");

  let key;
  try {
    key = await crypto.subtle.importKey("raw", publicKey, { name: "Ed25519" }, false, ["verify"]);
  } catch (error) {
    throw new Error("this browser cannot verify Ed25519; use the independent CLI", { cause: error });
  }
  const valid = await crypto.subtle.verify({ name: "Ed25519" }, key, signature, artifactPayload(root));
  if (!valid) throw new Error("invalid Ed25519 bundle attestation");
}

export async function verifyBundleFiles(files) {
  const decoder = new TextDecoder("utf-8", { fatal: true });
  const checksumsBytes = files.get("checksums.txt");
  const attestationBytes = files.get("attestation.json");
  if (!checksumsBytes || !attestationBytes) throw new Error("checksums.txt and attestation.json are required");

  const entries = parseChecksums(decoder.decode(checksumsBytes));
  const expectedPaths = new Set(entries.map(({ path }) => path));
  const actualPaths = [...files.keys()].filter((path) => path !== "checksums.txt" && path !== "attestation.json");
  if (actualPaths.length !== expectedPaths.size || actualPaths.some((path) => !expectedPaths.has(path))) {
    throw new Error("bundle file set differs from checksums.txt");
  }

  for (const entry of entries) {
    const bytes = files.get(entry.path);
    if (!bytes || await sha256Hex(bytes) !== entry.sha256) throw new Error(`checksum mismatch: ${entry.path}`);
  }

  const root = await computeBundleRoot(entries);
  let attestation;
  try {
    attestation = JSON.parse(decoder.decode(attestationBytes));
  } catch (error) {
    throw new Error("attestation.json is not valid UTF-8 JSON", { cause: error });
  }
  await verifyAttestation(attestation, root);
  return { root, did: attestation.did, entries: entries.length };
}

function hostedFileUrl(path, root, expectedOrigin) {
  if (
    !/^[A-Za-z0-9._/-]+$/.test(path) ||
    path.startsWith("/") ||
    path.startsWith("./") ||
    path.split("/").some((segment) => !segment || segment === "." || segment === "..")
  ) {
    throw new Error(`unsafe hosted evidence path: ${path}`);
  }
  const url = new URL(path, root);
  const rootPath = root.pathname.endsWith("/") ? root.pathname : `${root.pathname}/`;
  if (
    url.origin !== expectedOrigin ||
    !url.pathname.startsWith(rootPath) ||
    url.search ||
    url.hash
  ) {
    throw new Error(`hosted evidence path escapes its reviewed origin: ${path}`);
  }
  return url;
}

async function fetchHostedBytes(url, fetcher) {
  const response = await fetcher(url, {
    cache: "no-store",
    credentials: "omit",
    redirect: "error",
  });
  if (!response?.ok || response.redirected) {
    throw new Error(`hosted evidence request failed: ${url.pathname}`);
  }
  const declaredLength = Number(response.headers?.get?.("content-length"));
  if (Number.isFinite(declaredLength) && declaredLength > MAX_HOSTED_FILE_BYTES) {
    throw new Error(`hosted evidence file exceeds size limit: ${url.pathname}`);
  }
  if (!response.body?.getReader) {
    const bytes = new Uint8Array(await response.arrayBuffer());
    if (bytes.length > MAX_HOSTED_FILE_BYTES) {
      throw new Error(`hosted evidence file exceeds size limit: ${url.pathname}`);
    }
    return bytes;
  }

  const reader = response.body.getReader();
  const chunks = [];
  let length = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    length += value.length;
    if (length > MAX_HOSTED_FILE_BYTES) {
      await reader.cancel();
      throw new Error(`hosted evidence file exceeds size limit: ${url.pathname}`);
    }
    chunks.push(value);
  }
  const bytes = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.length;
  }
  return bytes;
}

export async function fetchAndVerifyHostedBundle({
  baseUrl = "evidence/latest/",
  fetcher = globalThis.fetch,
  pageUrl = globalThis.location?.href,
} = {}) {
  if (typeof fetcher !== "function" || !pageUrl) {
    throw new Error("hosted verification requires a browser origin");
  }
  const page = new URL(pageUrl);
  const root = new URL(baseUrl, page);
  if (root.origin !== page.origin) throw new Error("hosted evidence must use the page origin");

  const files = new Map();
  const checksumsUrl = hostedFileUrl("checksums.txt", root, page.origin);
  const checksumsBytes = await fetchHostedBytes(checksumsUrl, fetcher);
  files.set("checksums.txt", checksumsBytes);
  const entries = parseChecksums(new TextDecoder("utf-8", { fatal: true }).decode(checksumsBytes));
  if (entries.length > MAX_HOSTED_FILES) throw new Error("hosted evidence lists too many files");

  const requested = ["attestation.json", ...entries.map(({ path }) => path)];
  let totalBytes = checksumsBytes.length;
  for (const path of requested) {
    const bytes = await fetchHostedBytes(hostedFileUrl(path, root, page.origin), fetcher);
    totalBytes += bytes.length;
    if (totalBytes > MAX_HOSTED_TOTAL_BYTES) throw new Error("hosted evidence exceeds total size limit");
    files.set(path, bytes);
  }
  return verifyBundleFiles(files);
}

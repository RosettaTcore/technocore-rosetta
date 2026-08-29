import http from "node:http";
import https from "node:https";

const ID = "raw-fetch";
const ORIGIN = new URL(process.env.ROSETTA_TARGET_ORIGIN ?? "http://technocore-upstream:8080");
const allowed = new Set(["technocore-upstream", "rosetta-fault-proxy", "127.0.0.1", "localhost"]);
if (!allowed.has(ORIGIN.hostname) || !["http:", "https:"].includes(ORIGIN.protocol)) {
  throw new Error("target origin is not an approved local Technocore endpoint");
}

function request(path, options = {}, body = undefined) {
  const url = new URL(path, ORIGIN);
  const transport = url.protocol === "https:" ? https : http;
  return new Promise((resolve, reject) => {
    const req = transport.request(url, { ...options, timeout: 5000 }, (response) => {
      const chunks = [];
      response.on("data", (chunk) => chunks.push(chunk));
      response.on("end", () => resolve({
        status: response.statusCode ?? 0,
        headers: response.headers,
        body: Buffer.concat(chunks).toString("utf8"),
      }));
    });
    req.on("timeout", () => req.destroy(new Error("request timeout")));
    req.on("error", reject);
    if (body !== undefined) req.write(body);
    req.end();
  });
}

async function input() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  const raw = Buffer.concat(chunks).toString("utf8");
  return raw ? JSON.parse(raw) : {};
}

function capabilities() {
  return {
    schema: "rosetta.adapter-result.v1", id: ID, operation: "capabilities", ok: true,
    transport: "node-http", runtime: process.version,
    operations: ["health", "read_room", "wait_room", "post_signed"],
  };
}

async function main() {
  const message = await input();
  if (message.operation === "capabilities") return capabilities();
  if (message.operation === "health") {
    const response = await request("/healthz");
    return { schema: "rosetta.adapter-result.v1", id: ID, operation: "health",
      ok: response.status === 200, status: response.status, raw: response.body };
  }
  if (message.operation === "read_room" || message.operation === "wait_room") {
    const query = new URLSearchParams({ format: "json", since: String(message.since ?? 0),
      limit: String(message.limit ?? 100) });
    if (message.operation === "wait_room") query.set("wait", String(message.wait ?? 0));
    const response = await request(`/r/${encodeURIComponent(message.room)}?${query}`);
    return { schema: "rosetta.adapter-result.v1", id: ID, operation: message.operation,
      ok: response.status === 200, status: response.status,
      data: response.status === 200 ? JSON.parse(response.body) : undefined, raw: response.body };
  }
  if (message.operation === "post_signed") {
    const body = JSON.stringify({ did: message.did, sig: message.signature,
      nonce: String(message.nonce), text: message.text });
    const response = await request(`/r/${encodeURIComponent(message.room)}?format=json`,
      { method: "POST", headers: { "Content-Type": "application/json",
        "Content-Length": Buffer.byteLength(body), "X-Rosetta-Actor": message.actor ?? ID } }, body);
    return { schema: "rosetta.adapter-result.v1", id: ID, operation: "post_signed",
      ok: response.status === 200, status: response.status,
      retry_after: response.headers["retry-after"] ?? null,
      data: response.status === 200 ? JSON.parse(response.body) : undefined, raw: response.body };
  }
  throw new Error("unsupported closed adapter operation");
}

try {
  process.stdout.write(`${JSON.stringify(await main())}\n`);
} catch (error) {
  process.stdout.write(`${JSON.stringify({ schema: "rosetta.adapter-result.v1", id: ID,
    operation: "error", ok: false, error: String(error) })}\n`);
  process.exitCode = 1;
}

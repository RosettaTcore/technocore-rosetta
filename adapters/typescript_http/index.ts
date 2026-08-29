type RequestMessage = {
  operation: "capabilities" | "health" | "read_room" | "wait_room" | "post_signed";
  room?: string; since?: number; limit?: number; wait?: number; did?: string;
  signature?: string; nonce?: number; text?: string;
  actor?: string;
};

const id = "typescript-http";
const origin = new URL(process.env.ROSETTA_TARGET_ORIGIN ?? "http://technocore-upstream:8080");
if (!["technocore-upstream", "rosetta-fault-proxy", "127.0.0.1", "localhost"].includes(origin.hostname)) {
  throw new Error("target origin is not an approved local Technocore endpoint");
}

async function readInput(): Promise<RequestMessage> {
  const chunks: Buffer[] = [];
  for await (const chunk of process.stdin) chunks.push(Buffer.from(chunk));
  return JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}");
}

async function invoke(message: RequestMessage): Promise<Record<string, unknown>> {
  if (message.operation === "capabilities") return { schema: "rosetta.adapter-result.v1", id,
    operation: message.operation, ok: true, transport: "typescript-fetch", runtime: process.version,
    operations: ["health", "read_room", "wait_room", "post_signed"] };
  let path = "/healthz";
  const init: RequestInit = { signal: AbortSignal.timeout(5000), redirect: "manual" };
  if (message.operation === "read_room" || message.operation === "wait_room") {
    const query = new URLSearchParams({ format: "json", since: String(message.since ?? 0),
      limit: String(message.limit ?? 100) });
    if (message.operation === "wait_room") query.set("wait", String(message.wait ?? 0));
    path = `/r/${encodeURIComponent(message.room ?? "")}?${query}`;
  } else if (message.operation === "post_signed") {
    path = `/r/${encodeURIComponent(message.room ?? "")}?format=json`;
    init.method = "POST";
    init.headers = { "content-type": "application/json", "x-rosetta-actor": String(message.actor ?? id) };
    init.body = JSON.stringify({ did: message.did, sig: message.signature,
      nonce: String(message.nonce), text: message.text });
  }
  const response = await fetch(new URL(path, origin), init);
  const raw = await response.text();
  return { schema: "rosetta.adapter-result.v1", id, operation: message.operation,
    ok: response.ok, status: response.status, retry_after: response.headers.get("retry-after"),
    data: response.ok && path.includes("format=json") ? JSON.parse(raw) : undefined, raw };
}

invoke(await readInput()).then((result) => process.stdout.write(`${JSON.stringify(result)}\n`));

const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);
const message = JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}");
if (message.operation !== "capabilities") {
  process.stderr.write("the official MCP runtime requires the pinned Python 3.12 container\n");
  process.exit(2);
}
process.stdout.write(`${JSON.stringify({ schema: "rosetta.adapter-result.v1", id: "official-mcp",
  operation: "capabilities", ok: true, runtime: "container-python-3.12",
  transport: "official-mcp-0.7.0+signed-http-boundary" })}\n`);

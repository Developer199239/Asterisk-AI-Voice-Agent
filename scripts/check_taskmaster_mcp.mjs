#!/usr/bin/env node
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

async function main() {
  const transport = new StdioClientTransport({
    command: "npx",
    args: ["-y", "--package=task-master-ai", "task-master-ai"],
    cwd: process.cwd(),
    env: process.env,
  });

  const client = new Client({ name: "codex-cli-check", version: "0.1.0" });
  await client.connect(transport);
  const tools = await client.listTools();
  const names = (tools?.tools || []).map(t => t.name);
  console.log(JSON.stringify({ toolCount: names.length, sample: names.slice(0, 10) }, null, 2));
  await client.close();
}

main().catch(err => {
  console.error("check_taskmaster_mcp error:", err?.message || err);
  process.exit(1);
});

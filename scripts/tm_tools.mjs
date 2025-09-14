#!/usr/bin/env node
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

async function connect() {
  const transport = new StdioClientTransport({
    command: "npx",
    args: ["-y", "--package=task-master-ai", "task-master-ai"],
    cwd: process.cwd(),
    env: process.env,
  });
  const client = new Client({ name: "codex-cli", version: "0.1.0" });
  await client.connect(transport);
  return client;
}

async function list() {
  const client = await connect();
  const res = await client.listTools();
  console.log(JSON.stringify(res, null, 2));
  await client.close();
}

async function info(name) {
  const client = await connect();
  const res = await client.listTools();
  const tool = (res.tools || []).find(t => t.name === name);
  if (!tool) {
    console.error(`Tool not found: ${name}`);
    process.exit(1);
  }
  console.log(JSON.stringify(tool, null, 2));
  await client.close();
}

async function call(name, params) {
  const client = await connect();
  const res = await client.callTool({ name, arguments: params }, undefined, { timeout: 300000 });
  console.log(JSON.stringify(res, null, 2));
  await client.close();
}

async function main() {
  const [cmd, name, json] = process.argv.slice(2);
  if (cmd === 'list') return list();
  if (cmd === 'info') return info(name);
  if (cmd === 'call') {
    const params = json ? JSON.parse(json) : {};
    return call(name, params);
  }
  console.error('Usage: node scripts/tm_tools.mjs <list|info <tool>|call <tool> <json-args>>');
  process.exit(1);
}

main();

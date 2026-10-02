// evidence/_agh_rpc.mjs — 直连 AGH daemon RPC，先 initialize 握手，再调用目标方法。
//
// 用途：拿到 capabilityHash（CLI `package status` 不打印，但 packages.list 返回里有）。
// 认证：本地 unix/pipe transport 下 verifyAuth 对 `kind:'local'` 或无 auth 直接放行
// （packages/daemon/src/local/auth.ts:230）。
//
// 用法：node evidence/_agh_rpc.mjs <method> [json-params]
import net from "node:net";
import { createRequire } from "node:module";

const require = createRequire("C:/Users/fyz/.workbuddy/binaries/node/workspace/noop.js");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const discovery = JSON.parse(
  fs.readFileSync(path.join(os.homedir(), ".agh/data/daemon/discovery.json"), "utf-8"),
);
const SOCK = discovery.socketPath;
const method = process.argv[2];
const params = process.argv[3] ? JSON.parse(process.argv[3]) : {};

const sock = net.connect(SOCK);
let buf = "";
let nextId = 1;
const pending = new Map();

function call(m, p) {
  const id = nextId++;
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
    sock.write(JSON.stringify({ jsonrpc: "2.0", id, method: m, params: p }) + "\n");
  });
}

sock.on("data", (d) => {
  buf += d.toString();
  let idx;
  while ((idx = buf.indexOf("\n")) >= 0) {
    const line = buf.slice(0, idx);
    buf = buf.slice(idx + 1);
    if (!line.trim()) continue;
    let msg;
    try {
      msg = JSON.parse(line);
    } catch {
      continue;
    }
    const r = pending.get(msg.id);
    if (!r) continue;
    pending.delete(msg.id);
    msg.error ? r.reject(msg.error) : r.resolve(msg.result);
  }
});

sock.on("connect", async () => {
  try {
    await call("initialize", {
      protocolVersion: 1,
      _meta: { "ai.agnes.harness": { clientId: "evidence-rpc", auth: { kind: "local" } } },
    });
    const result = await call(method, params);
    console.log(JSON.stringify(result, null, 2));
    sock.end();
    process.exit(0);
  } catch (e) {
    console.error("ERROR:", JSON.stringify(e, null, 2));
    sock.end();
    process.exit(1);
  }
});

sock.on("error", (e) => {
  console.error("socket error:", e.message);
  process.exit(1);
});
setTimeout(() => {
  console.error("timeout; partial:", buf.slice(0, 400));
  process.exit(124);
}, 30000);

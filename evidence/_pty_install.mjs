// evidence/_pty_install.mjs — 用真实 PTY 执行 `agh package add`。
//
// 背景：AGH 的安装确认（packages/cli/src/bin.ts:850）要求
//   io.stdin.isTTY === true && io.stdout.isTTY === true，
// 否则一律 resolve(false) → "Installation cancelled."（INV-33：未应答的确认永不被视为同意）。
// 管道（echo y |）永远拿不到 TTY，因此必须用 PTY 驱动。
//
// 用法：node evidence/_pty_install.mjs
import { createRequire } from "node:module";
const require = createRequire(
  "C:/Users/fyz/.workbuddy/binaries/node/workspace/noop.js",
);
const pty = require("node-pty");

const AGH = "D:/黑客松/agnes-harness/packages/cli/dist/local/agnes.mjs";
const NODE = "D:/Node.js/node.exe";
const CWD = "D:/QQ/paper-agent-fix";

const args = process.argv.slice(2);
if (args.length === 0) {
  console.error("usage: node _pty_install.mjs <agh args...>");
  process.exit(2);
}

const term = pty.spawn(NODE, [AGH, ...args], {
  name: "xterm-color",
  cols: 120,
  rows: 40,
  cwd: CWD,
  env: { ...process.env, TERM: "xterm-color" },
});

let out = "";
let answered = false;
const stripAnsi = (s) =>
  s.replace(/\x1b\][^\x07]*\x07/g, "").replace(/\x1b\[[0-9;?]*[A-Za-z]/g, "");

term.onData((d) => {
  out += d;
  process.stdout.write(d);
  // 出现确认提示即回 y（需先剥掉 ANSI 转义序列）
  const clean = stripAnsi(out);
  if (!answered && /\[y\/N\]\s*$/.test(clean.slice(-40))) {
    answered = true;
    setTimeout(() => term.write("y\r"), 250);
  }
});

term.onExit(({ exitCode }) => {
  console.error(`\n[pty] exitCode=${exitCode}`);
  process.exit(exitCode);
});

setTimeout(() => {
  console.error("[pty] timeout");
  term.kill();
  process.exit(124);
}, 180000);

# 证据目录（AGH 参与证明）

本目录承载「**AGH 承担核心科研流程（>=3 连续步骤）**」这一红线的可核验证据。

> **已移除（2026-10-02）**：此前的 `agh-session-sanitized.jsonl` 及其生成脚本
> `record_session.mjs` 已删除。原因是其 JSON 结构（`{seq,type,name,args}`）
> **不是 AGH 真实事件格式**，而是脚本自行定义的简化结构，不能作为 daemon 导出证据。
> AGH 真实信封见 `AGH-真实会话落地报告.md`（`{seq,ts,id,type,actor,origin,trust,
> source_event_seqs,data:{name,args,...},integrity_mode,integrity_prev,integrity_digest}`）。

## 本目录内容

- `AGH-真实会话落地报告.md` — AGH 真实会话的完整打通记录：真实信封格式、
  CLI/daemon 协议修复、PTY 安装确认、`capabilityHash` 取法、`file:` 源路径约束，
  以及当前卡点（第三方工具未暴露给模型）与官方示例复现实验。

### 工具脚本（本次为打通真实会话而写）

- `_pty_install.mjs` — 用 `node-pty` 起真实 PTY 执行 `agh package add`。
  AGH 安装确认要求 `isTTY`（`packages/cli/src/bin.ts:850`，INV-33：未应答的确认
  永不被视为同意），管道（`echo y |`）无法通过。
- `_agh_rpc.mjs` — 直连 daemon RPC（先 `initialize` 握手，再调目标方法），
  用于获取 CLI `package status` 不打印的 `capabilityHash`。

## 真实证据如何取得（打包时归集）

真实参与证据由 AGH daemon 原生写出，落地后从磁盘归集，**不入 git**（含本机绝对路径）：

```bash
# 会话事件库（含完整信封与 integrity 哈希链）
#   ~/.agh/data/sessions.db   —— events 表
# 或导出为标准格式
agnes export <SESSION_ID> --format agnes -o evidence/session.jsonl
```

> 前置：需先在本机跑通 AGH 真实会话（Node 24 + `agnes.mjs`），
> 并把 `plugins/paper-agent-tools` 装入 daemon（见落地报告 §二）。
> 当前卡点：第三方 plugin 行尚未被投影进模型工具集（见落地报告 §三）。

## 打包审计包

```bash
bash audit-pack-template/build_audit_pack.sh <RUN_ID>
# 会拷入 state/events/provenance/conclusions/verification/report +
# evidence/session*.jsonl（若磁盘存在）；开源发布前需人工审查路径脱敏。
```

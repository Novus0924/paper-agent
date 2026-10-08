# demo-kit — paper-agent 交付套件（体检 / 启动 / 演示）

> 目标：把"上手门槛高、演示隐性依赖多"变成**可一键复现**的交付能力。
> 与既有 `demo/*.sh` **并存而非替代**：`demo/*.sh` 做"真链路断言"（`demo_e2e` / `demo_failure` / `demo_trust`），
> 本套件做"开箱即用 / 现场演示"。env 口径统一由 `lib/env.sh` 提供。

零第三方依赖（沿用项目红线）。Git Bash / WSL / macOS / Linux 通用。

---

## 三条命令

```bash
# ① 体检：一条命令跑完环境自检（✓/⚠/✗ + 人话修复指引）
bash demo-kit/health-check.sh

# ② 启动：一键拉起可演示环境（默认 mock，零后端最可靠）
bash demo-kit/bootstrap.sh --mode mock

# ③ 演示：3 分钟现场演示总控（默认 offline，断网可用）
bash demo-kit/demo-script.sh
```

停止服务：`bash demo-kit/bootstrap.sh --stop`（或 `demo-kit/demo-script.sh --stop`）。

---

## 目录结构

```
demo-kit/
├── README.md                 本文件
├── health-check.sh           环境自检（6 项；支持 --json / --quiet / --only）
├── bootstrap.sh              一键启动（--mode mock|live|fake；--port；--stop）
├── demo-script.sh            3 分钟演示总控（--offline 默认 / --live / --stop）
├── lib/
│   ├── env.sh                共享：仓库根/Python/Node/端口/curl 探测（被上面三者 source）
│   ├── report.sh             共享：体检项打印与汇总（✓/⚠/✗ + 修复指引）
│   └── serve.mjs             参数化静态服务（PA_SERVE_ROOT + PORT）
└── fixtures/
    └── session-replay.jsonl  会话回放（从真实 AGH 会话裁剪，覆盖 7 工具）
```

---

## health-check.sh — 环境自检

| 检查项 | 说明 | 取自 |
|---|---|---|
| `python` | 解释器版本（>= 3.10）与绝对路径 | `cli doctor` |
| `root` | 项目根存在且含 `core/paper_agent/` | `cli doctor` |
| `runs` | `runs/` 可写 | `cli doctor` |
| `env` | `paper-agent_ROOT` / `paper-agent_PYTHON` **原始生效值** | Bash `printenv` |
| `ports` | 8787 / 5173 是否可用 | `cli doctor` |
| `agh` | AGH 插件 `desired/actual/trusted`（可选） | `package status` |

- **退出码**：`0` 全绿 / `2` 有 ⚠（可继续）/ `1` 有 ✗（阻断）。
- **机器可读**：`--json`（供 `bootstrap` / CI 复用）；`--quiet` 仅退出码；`--only <项>` 只跑一项。
- **单源**：`python`/`root`/`runs`/`ports` 由 `python -m paper_agent.cli doctor` 的**单行 JSON** 提供，
  避免自检逻辑在 Bash 与 Python 两处各写一份而漂移。`env` 在 Bash 层补齐——因为需读"原始环境变量"
  （能检出 ENV-1 类"失效的持久化变量"：`paper-agent_ROOT` 指向不存在目录时，`doctor` 会在导入期即报错）。
- **AGH 可选**：未装 AGH 时该项降级为 ⚠（不阻断）；node < 24 时跳过插件状态查询并说明。

## bootstrap.sh — 一键启动

三种 `--mode` 与 `web/README.md` 的三种联调方式对齐：

| mode | 起什么 | 打开 |
|---|---|---|
| `mock`（默认） | 仅静态服务 → `演示原型/` | `http://127.0.0.1:5173/` |
| `fake` | `web/mock/server.js`(8788) + 静态服务 → `web/` | `http://127.0.0.1:5173/?mock=0&base=http://127.0.0.1:8788` |
| `live` | `web/server/paper-agent-server.js`(8787) + 静态服务 → `web/` | `http://127.0.0.1:5173/?mock=0&base=http://127.0.0.1:8787` |

- 启动前**先自检**（`--no-check` 可跳过）；有 ✗ 即中止并打印指引。
- 端口占用时：报告占用进程 PID，并给出 `--port` 顺延 / `taskkill` / `--stop` 三种处置。
- `mock` 模式不碰 AGH、不碰真后端、不触网 → 现场最可靠。

## demo-script.sh — 3 分钟演示总控

- 默认 `--offline`：只起静态服务，打印演示主线点击路径 + 讲点（含"降级是橙色非失败"）+ 回放数据自检。
- `--live`（加分）：叠加真后端，用于"真跑一次"。
- 会话回放：`fixtures/session-replay.jsonl`（42 行 = 21 `tool/call` + 21 `tool/result`，
  真实覆盖 7 工具：`sciret_plan/run_step/status/verify/report/cite/resume`），
  供演示原型的「AGH 集成」视图回放，**替代 AGH 实时会话**（剥离模型/代理/TTY 不确定性）。

---

## 环境变量口径（重要）

带连字符的变量（`paper-agent_ROOT` / `paper-agent_PYTHON`）**不能用** `export`（bash 写不了这种名字，
对 Python 是空操作）。本套件一律用 `env "name=value"` 前缀注入，统一入口见 `lib/env.sh` 的 `pa_py`。

**已知环境坑（套件已自行规避）**：
- 若系统里残留失效的 `paper-agent_ROOT` 用户变量，`doctor` 会在导入期明确报错、`health-check` 会将其标注为 ⚠ 并给出
  「重新注入后重启 daemon」的指引（见 `docs/AGH插件安装指南.md`）。
- 若系统设了 `http_proxy`/`https_proxy`，`curl` 到 `127.0.0.1` 也会走代理（返回 502）。套件的本地探测一律用
  `--noproxy '*'`（`lib/env.sh` 的 `pa_curl`）。手工验证时也请加 `--noproxy '*'`。

---

## 与 `demo/*.sh` 的关系

| 套件 | 定位 | 命令 |
|---|---|---|
| `demo/*.sh` | 真链路**断言**（CI/回归） | `demo_e2e.sh` / `demo_failure.sh` / `demo_trust.sh` |
| `demo-kit/` | 开箱**演示** / 环境交付 | `health-check.sh` / `bootstrap.sh` / `demo-script.sh` |

两者 env 口径一致（均 `env "paper-agent_ROOT=..."` 注入），不互相替代。

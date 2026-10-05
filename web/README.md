# paper-agent-web —— 科研工作台前端 + M1 真实后端 + M3 提示词注入

按《对接方案.md》实现的前端、方案 §8 **M1 阶段**的真实后端，以及 §8 **M3 阶段**的系统提示词注入。**与 `paper-agent` 主仓库完全隔离**：独立文件夹、零第三方依赖、不改动任何既有文件。

> 真实后端（`server/paper-agent-server.js`）**会spawn `paper_agent.cli` 真跑流水线**——联网检索、真实耗时约 10s/步。
> 与 `mock/server.js`（返回造的数据、不碰网络）性质完全不同，两者都实现了同一套接口。

## 快速开始

```bash
# ── 方式 A：纯 UI 走查（内联 mock，不发 HTTP，无需后端）──
node mock/serve.js
#   → http://127.0.0.1:5173

# ── 方式 B：真实联调（M1 后端真跑 Python 流水线）──
node server/paper-agent-server.js   # 终端 A：真实后端 8787
node mock/serve.js                  # 终端 B：静态服务 5173
#   → http://127.0.0.1:5173/?mock=0&base=http://127.0.0.1:8787

# ── 方式 C：假后端（验HTTP+SSE 链路但不跑 Python）──
node mock/server.js                 # 8788 假后端
node mock/serve.js
#   → http://127.0.0.1:5173/?mock=0&base=http://127.0.0.1:8788
```

后端环境变量（均有默认值，本机开箱即用）：

| 变量 | 默认 | 说明 |
|---|---|---|
| `PORT` | `8787` | 后端端口（方案 §6 建议值） |
| `PAPER_AGENT_ROOT` | `..`（即仓库根） | paper-agent 仓库根（产物 `runs/` 在这）。本工程已随仓库入库为 `web/`，故默认指向父目录 |
| `PAPER_AGENT_PYTHON` | 自动探测 | Python 解释器路径 |

后端健康检查：`curl http://127.0.0.1:8787/api/health` → 会返回 `agent_root` / `runs_dir` / `python` / `runs_count` / `prompts_archived`，便于排查环境问题。

改过提示词模板后跑一次一致性校验（前后端两份模板必须逐字一致）：

```bash
node server/verify-prompt-parity.mjs   # 一致退出 0，不一致退出 1 并打印逐行差异
```

> ⚠️ **不要直接双击 `index.html`**。ES module 在 `file://` 下会被 CORS 拦住，
> 页面会显示兜底提示。用 `node mock/serve.js` 即可，无需 `npm install`。

## 目录结构

```
paper-agent/                    ← 仓库根（runs/ 在这）
├── plugins/paper-agent-tools/  AGH 插件（薄壳：只 spawn Python）
├── core/paper_agent/           ★ 全部科研能力在这里
└── web/                        ← 本工程
    ├── index.html              入口。含 API 配置开关与启动兜底提示
    ├── package.json            仅 scripts，无任何依赖
    ├── README.md
    ├── public/
    │   └── favicon.svg         与页面 mark 呼应的琥珀色 PA 图标
├── src/
│   ├── main.js             hash 路由 + 页面装配 + 任务列表缓存
│   │   ├── styles/
│   │   │   ├── tokens.css      设计令牌：颜色/间距/字体/动效（唯一真源）
│   │   │   ├── base.css        reset + 排版原子 + toast + 错误条
│   │   │   └── layout.css      三段骨架 + 各页专有布局
│   │   ├── lib/
│   │   │   └── dom.js          h() / icon() / 时间格式化 / 复制 / toast
│   │   ├── api/
│   │   │   ├── client.js       ★ 接口客户端，逐条对应方案 §4
│   │   │   ├── constants.js    步骤 id、工作流、来源、状态枚举、提示词模板
│   │   │   ├── mock.js         内联 mock（拦截 fetch + EventSource）
│   │   │   └── mock-data.js    mock 数据，字段取自真实 runs/ 产物
│   │   ├── components/         6 个可复用组件
│   │   │   ├── rail.js           左侧图标导航
│   │   │   ├── task-list.js      任务列表 + 状态点语义
│   │   │   ├── steps.js          步骤条
│   │   │   ├── tool-card.js      工具调用卡（折叠）
│   │   │   ├── conclusion-card.js 结论卡
│   │   │   └── evidence-card.js  证据页组件（verdict / EV 卡 / 自审 / 绑定）
│   │   └── pages/              3 个页面
│   │       ├── workbench.js      界面一：主工作台
│   │       ├── evidence.js       界面二：证据溯源
│   │       └── new-task.js       界面三：新建任务
    ├── server/
    │   ├── paper-agent-server.js  ★ M1 真实后端（8787），spawn Python CLI
    │   ├── prompt.js               M3 系统提示词生成 + 落盘存档
    │   └── verify-prompt-parity.mjs  ★ 前后端模板一致性校验（改模板后必跑）
    ├── .data/prompts/        提示词存档（运行时产物，已 gitignore）
    └── mock/
        ├── serve.js            静态服务（5173）
        └── server.js           假后端（8788），造数据、不跑 Python
```

> `server/` 与 `mock/` 的区别是**唯一容易混淆的点**：
> `mock/server.js` 返回写死的数据、不联网、秒回，适合纯验链路；
> `server/paper-agent-server.js` 真`spawn python -m paper_agent.cli`，
> 会联网检索文献、单步真实耗时 8–12 秒。

## M1 真实后端

### 接口清单

| 方法 | 路径 | 方案出处 | 实现要点 |
|---|---|---|---|
| GET | `/api/health` | 附加 | 返回 `agent_root` / `runs_dir` / `python` / `runs_count`，环境排查用 |
| GET | `/api/runs` | 附加 | 扫`runs/` 目录，倒序返回，映射成 `{id, goal, workflow, run_status, steps_done, created_at}` |
| POST | `/api/runs` | §4.1 | `spawn cli plan`，返回 `{run_id, goal, workflow, steps, steps_order}`；空 goal → 400 |
| GET | `/api/runs/{id}` | 附加 | 读 `state.json` + `toolcalls/` + `conclusions.jsonl`，工作台首屏快照 |
| GET | `/api/runs/{id}/events` | §4.3 | SSE，`retry:3000` + 心跳 `ping`；连接时补发当前 `step`/`tool`/`conclusion` 快照 |
| POST | `/api/runs/{id}/step` | §4.2 | `spawn cli run-step --step <id>`，校验 step 必须在 `state.steps` 里 |
| POST | `/api/runs/{id}/run-all` | §4.2 | 循环 `run-step`直到无 `PENDING`；同步返回逐事件结果数组 |
| GET | `/api/runs/{id}/evidence` | §4.4 | 装配 provenance + conclusions + factcheck + review + toolcalls |
| GET | `/api/runs/{id}/report` | 附加 | 回传 `report.md` 原文（方案未定义，便于调试与后续导出） |

### 与方案不一致之处（按实测校准，非实现偷懒）

| 方案写法 | 实测真相 | 后端做法 |
|---|---|---|
| §4.1 `lit_source: auto\|arxiv\|crossref\|openalex\|semantic_scholar` | CLI 的 argparse `choices` 只有 `"" / local / arxiv / auto`。传 `crossref` 直接报错退出 code 2 | `resolveLitSource()` 白名单归一化，不支持的降级为 `auto`；前端把三项灰显并标注「CLI 暂不支持」 |
| §4.1 响应含 `goal` | `plan` 的 stdout JSON **不回显 goal** | 从 `runs/<id>/state.json` 读出来补上 |
| `toolcalls/*.json` 含 `sources_status` | 该文件 keys 只有 `input / invoked_at / output / step / tool`，**没有** `sources_status` | 从 `run-step` 的 **stdout JSON** 取，存内存 `stepOutputs`，重启后从工具输出里尽力回填 |
| `conclusions.jsonl` 全程存在 | R1–R3 阶段**还不存在**，R4/R5 之后才陆续写入 | `/evidence` 容错返回 `[]`；`conclusion` 事件**每步跑完都检查并按 `cid` 去重补发** |
| 跑完步骤后`run_status` 自然变`DONE` | `run_all()` 内部会 `finish_run(DONE)`，但那是**整体执行路径**；逐步 `run-step`（模型驱动路径）**不会触发收尾**，6 步全 DONE 时 `run_status` 永远停在 `RUNNING` | 全部步骤终态后调 CLI 的 `finish` 子命令（`finish_if_terminal()`，正是为这条路径准备）。**只改内存副本无效**——`state.json` 不会更新，证据页头部会一直显示「运行中」 |
| 未提及产物缺失的降级 | `semantic_scholar` 本机常连不上，`sources_status` 里 `unavailable:HTTPError` | 这是**正常降级不是失败**，`degraded` 事件透传，前端用橙色而非红色 |

### 安全性

- `run_id` 走正则 `^run-\d{8}-\d{6}-[0-9a-f]{6,}$` 校验，`..%2F..%2Fetc` 与非法 id 均返回 400 `BAD_ID`
- CLI 调用超时 180s，stdout **从后往前逐行试解析** JSON（容忍前置警告行）
- 仅绑定 `127.0.0.1`，方案 §6 已明确本轮不做鉴权

## M3 系统提示词注入

### 为什么不是"往 CLI 塞提示词"

§5.1 实测确认：ACP 的 `session/new` 只有 `cwd` / `additionalDirectories` / `mcpServers` / `_meta`，
**没有 system prompt 字段**；AGH 的系统提示词是内置 section，不开放运行时注入。
所以只能走 §5.2 的「首轮前缀 + 明示」。

而在 Python 主干这条路上，**`goal` 是 `--goal` 参数直传 CLI 的**（比塞进提示词更干净，
见 §5.2 末尾的注）。所以本实现里提示词的 `delivery` 记为 `cli-arg:goal`：
它的作用是**可审计 + 向用户明示**，不是去污染检索查询串。

### 实现

| 环节 | 位置 | 行为 |
|---|---|---|
| 生成 | `server/prompt.js` 的 `buildSystemPrompt()` | 后端唯一真源，含【角色】【硬约束】【工作流】【检索来源】【本次目标】 |
| 落盘 | `<web>/.data/prompts/<run_id>.json` | 创建 run 时同步存档，含 `delivery` / `created_at` / `text` |
| 下发 | `POST /api/runs` 返回 `system_prompt` | 前端创建成功后重渲染即可拿到 |
| 读取 | `GET /api/runs/{id}` 返回 `system_prompt` + `prompt_meta` | 工作台渲染的是**后端存档那份** |
| 预览 | 新建页「系统约束」区| 提交**前**就能看到，随目标/工作流/来源实时变化（§5.2 要求"用户有权知道被加了什么"） |

> ⚠️ 存档刻意**不写进 `paper-agent/runs/<id>/`**：那个目录里的
> `events.jsonl` / `provenance.jsonl` 是 Python 侧的 **append-only 哈希链账本**
> （见 `core/paper_agent/state.py` 与 `chaos.py` 注释），随手加文件可能破坏完整性校验。
> 前端工程的数据放前端工程的目录，互不污染。

### 前后端两份模板必须逐字一致

前端 `src/api/constants.js` 与后端 `server/prompt.js` 各有一份 `buildSystemPrompt()`：
一份用于提交前预览，一份用于真正下发并存档。**两份不一致的话，「明示」就成了欺骗**
（用户看到的约束 ≠ 实际施加的约束）。所以：

- 中文步骤名只在 `constants.js` 的 `STEP_LABELS` 维护一份，后端 `import` 过来用；
- `node server/verify-prompt-parity.mjs` 会跑 10 组用例（2 工作流 × 4 来源 + 空目标 /
  含换行 / 超长 / 非法工作流等边界），**不一致直接退出码 1 并打印逐行差异**。

实测 10 组全部逐字一致，且真实验证过「前端预览 252 字符 == 后端下发 252 字符」。

### 老run 的诚实降级

M3 上线前创建的 run 没有存档。此时 `prompt_meta.injected=false`，
前端显示**橙色「本地重算」徽章** + 明确警示文案，而不是假装成后端下发的内容。

### 界面三 · 新建任务 `#/new`（补充）

除 `POST /api/runs` 外，§5.2 要求的「提交前明示系统约束」也在本页实现：
输入目标后，提示词预览实时更新；切换工作流或检索来源也会跟着变。

## 页面与接口对应关系

### 界面一 · 主工作台 `#/run/<run_id>`

| 功能 | 接口 | 方案出处 |
|---|---|---|
| 初始快照（目标/步骤/工具卡/结论） | `GET /api/runs/{id}` | 附加 |
| 实时事件流（步骤/工具/降级/结论/完成） | `GET /api/runs/{id}/events` (SSE) | §4.3 |
| 执行下一步 | `POST /api/runs/{id}/step` | §4.2 |
| 跑完整个流程 | `POST /api/runs/{id}/run-all` | §4.2 |
| 左侧任务列表 | `GET /api/runs` | 附加 |

SSE 事件 → UI 映射：

| 事件 | UI 表现 |
|---|---|
| `step` | 步骤条状态翻转、当前步骤琥珀高亮、头部 `N/M 步` |
| `tool` | 追加工具调用卡（默认折叠，首张展开），带四源状态标签 |
| `degraded` | 顶部橙色降级条 + 头部「N 源可用 / M 降级」（**橙色而非红色**，降级是特色不是失败） |
| `conclusion` | 追加结论卡，EV 编号可点击跳证据页 |
| `done` | 按钮复位、任务列表刷新、toast 提示 |

### 界面二 · 证据溯源 `#/run/<run_id>/evidence`

| 功能 | 接口 | 方案出处 |
|---|---|---|
| 证据 + 核验 + 自审 + 结论绑定 | `GET /api/runs/{id}/evidence` | §4.4 |

页内含：4 格 verdict（引用一致性 / 自审评分 / 证据条目 / 来源可用）、降级说明、
结论↔证据绑定、自审明细（维度得分 + 阻断项 + 建议动作）、证据条目流（可按 tier 筛选 + 全文搜索）。

支持 `#/run/<id>/evidence/EV-0001` 直接定位并高亮某条证据。

### 界面三 · 新建任务 `#/new`

| 功能 | 接口 | 方案出处 |
|---|---|---|
| 提交任务 | `POST /api/runs` `{goal, workflow, lit_source}` | §4.1 |

提交成功后自动跳工作台并订阅 SSE。「会发生什么」四步说明会随所选工作流实时变化。

## 路由

```
#/workbench                      工作台（默认，最近一个 run）
#/run/<run_id>                   指定 run 的工作台
#/run/<run_id>/evidence          证据溯源
#/run/<run_id>/evidence/<ev_id>  证据溯源并高亮某条证据
#/new                            新建任务
```

## 联调切换

改 `index.html` 里的配置，或用 URL 参数覆盖：

```html
<script>window.__PAPER_API__ = { mock: true, base: '' };</script>
```

| 场景 | mock | base |
|---|---|---|
| 纯 UI 走查 | `true` | `''` |
| 打 mock 后端 | `false` | `http://127.0.0.1:8788` |
| 打真实后端 | `false` | `http://127.0.0.1:8787` |

URL 覆盖：`?mock=0&base=http://127.0.0.1:8787`

## 数据字段来源

mock 字段**不是编的**，全部取自真实产物：

| 前端字段 | 真实来源 |
|---|---|
| `state.steps{}` / `steps_order` / `run_status` / `degraded` | `runs/<id>/state.json` |
| `provenance[].ev_id/kind/tier/ref/sha256/chain_hash/producer_step/meta` | `provenance.jsonl` |
| `conclusions[].cid/text/evidence_ids` | `conclusions.jsonl` |
| `factcheck.citations.consistency_rate` | `factcheck/factcheck.json` |
| `review.final.overall/n_blocking/scores/blocking_issues` | `review/review.json` |
| `toolcalls[].sources_status` | `run-step` 的 **stdout JSON**（不在 `toolcalls/*.json` 里，见上文校准表） |
| 步骤 id `R1_search`… / `P1_lit_search`… | `core/paper_agent/state.py` 的 `WORKFLOWS` |

> **注意字段陷阱**：`fact` / `artifact` 是 **`tier`** 字段的值；
> `kind` 的值是 `literature` / `data` / `note` / `analysis` / `factcheck` / `draft` / `review`（实测全集 7 种）。
> 徽章显示 `tier`，中文标注（文献/数据/笔记/分析/事实核查/草稿/评审）来自 `kind`。
>
> **research 工作流跑完 `artifact` 为 0 是正常状态**：实测 21 条 provenance 全是 `fact`。
> `artifact` 只在「下载并解析本地 PDF 成文件」时产生，纯检索型工作流不会走到那条路径。

## 设计规范

风格：Swiss Modernism 2.0 × AI-Native UI，深色 + 唯一强调色。

| Token | 值 | 对比度（实测） |
|---|---|---|
| `--bg` | `#0B0B0C` | — |
| `--surface` | `#141416` | — |
| `--ink` | `#E8E8E6` | 16.04:1 ✓ |
| `--ink-3` | `#8A8A85` | 5.67:1 ✓ |
| `--amber` | `#D9A441` | 8.75:1 ✓ |
| `--ok` | `#6BBF8A` | 8.85:1 ✓ |
| `--run` | `#7FA8D9` | 7.97:1 ✓ |
| `--warn` | `#D98A5A` | 7.25:1 ✓ |
| `--fail` | `#E5646A` | 5.96:1 ✓ |

全部达 WCAG AA。分隔线 `--line`（约 1.5:1）仅作装饰，**不承载信息边界**——
边界靠卡面底色差区分。间距走 `--s1..--s8` = 4/8/12/16/24/32/48/64px 阶梯，
正文流限宽 820px。所有数值集中在 `tokens.css`，改主题只改这一处。

## 已知边界（诚实说明）

| 项 | 状态 |
|---|---|
| **追问 / 追加指令** | 方案 §4 未定义该接口。输入区做成**显式禁用 + 说明**，不给用户"能发但发不出去"的假输入框。后端补 `POST /api/runs/{id}/message` 后，把 `workbench.js` 里 `userInput` 的 `contenteditable` 改回 `'true'` 并去掉 `.off` 即可。⚠️ 该接口**不必等 M4**——后端直接 spawn CLI 追加一轮即可，不必经AGH |
| **任务列表接口** | `GET /api/runs` 与 `GET /api/runs/{id}` 是方案 §4 未列的**附加接口**，左侧任务栏和刷新恢复必需。真后端已实现 |
| **持久化** | run 产物由 Python 侧持久化（`runs/<id>/`）；任务列表每次刷新从 `GET /api/runs` 重拉；run_id在 URL hash 里可分享 |
| **鉴权/ 多用户** | 未做。方案 §6 已明确本轮不做 |
| **报告正文** | 已加 `GET /api/runs/{id}/report` 返回 `report.md` 原文，但**前端未接入展示**（方案 §4.4 只定义了 evidence 接口）。需要时在证据页加一个导出按钮即可 |
| **`sources_status` 的持久化** | 只存在于**本次后端进程内存**中（来自 `run-step` 的 stdout）。后端重启后历史 run 的来源状态会丢失，此时页面退化为「未知」而非报错——因为 `toolcalls/*.json` 本身就不存这个字段。若要持久化，需在 Python 侧补写 |
| **M4 ACP 增强通道** | 未做，**且已降级**。实测发现 ACP 模式（`--mode acp`）走 `bootLocal` 自建 Host，**根本不装载第三方插件**（`boot/default.ts:25` + `assemble.ts:447`），详见 `../docs/对接方案.md` §2.5。所以 ACP 通道只剩"对已完成的 run 做问答/综述"，模型无法自己调工具查数据。**不影响本工程任何已实现功能**——流水线走 Python CLI，不经过 AGH |
| **M5 修插件装载** | ✅ **已结项，无需修**。查清是诊断口径问题：`agh doctor extensions` 在 tree apply 前触发，grep 不到第三方属正常。daemon 侧 7 个工具每次启动都注册成功（审计日志 154 条 `extension.registered`） |

## 开发过程中踩到的坑（留给后续维护）

1. **`el.append(数组)` 会 toString 成 `[object HTMLButtonElement]`**。
   本项目在证据页筛选栏踩过一次，导致 chip 全部渲染成字符串。
   已提供 `appendAll()`（`src/lib/dom.js`），凡是可能传数组的地方一律用它。
2. **`button` 是 inline-block，`margin-left:auto` 不生效**。
   要右对齐必须加 `display:block`。
3. **`fetch` 拦截拿到的 input 可能是 `Request` 对象**。
   `String(input)` 对 Request 会得到 `"[object Request]"`。本项目 mock 用
   `new URL(String(input), location.origin)`，当前调用方都传字符串，安全；
   若将来改成传 `Request` 需改用 `input.url`。
4. **hash 路由解析要防run_id 与字面量冲突**。
   `run_id` 恒以 `run-` 开头，所以判断 `parts[1] === 'evidence'` 不会误判。
   （正确写法是判`parts[2] === 'evidence'`，因为 `#/run/<id>/evidence` 里
   `parts[1]` 是 run_id —— 踩过一次，证据页永远进不去。）
5. **逐步推进不会自动收敛 `run_status`**。
   `cli.py` 的 `run_all()` 内部会 `finish_run(DONE)`，但走「模型驱动逐步 `run-step`」
   这条路径（也就是插件里的 `sciret_run_step` 循环）**不会触发收尾**，
   6 步全 DONE 后 `state.json` 里 `run_status` 仍是 `RUNNING`。
   必须显式调 `finish` 子命令。**更坑的是**：只把内存里的 `state.run_status` 改成
   `'DONE'` 看起来一切正常，但 `state.json` 没变，下次请求又变回 `RUNNING`——
   症状是「工作台显示已完成，证据页头部显示运行中」。
6. **Puppeteer 不能对 SSE 页面用 `waitUntil: 'networkidle0'`**。
   SSE 长连接永不 idle，会一直卡到 30s 超时。用 `domcontentloaded` + 显式 `setTimeout`。
7. **无头验证脚本要设 `NODE_PATH`**。
   `puppeteer-core` 装在托管 workspace（`~/.workbuddy/binaries/node/workspace/node_modules`），
   本工程零依赖、不装node_modules，所以要
   `NODE_PATH="C:\Users\lenovo\.workbuddy\binaries\node\workspace\node_modules" node xxx.cjs`。
8. **状态变化后要更新所有联动预览，不能只更新一个**。
   M3 时新建页切工作流 / 切来源只调了 `renderPreview()`（「会发生什么」），
   忘了调 `renderPromptPreview()`，结果提示词预览不跟着变——工作流卡上明明白白写着
   `materials`，下面提示词却还是 `research`。凡是绑同一份状态的多个渲染函数，
   状态变更处要一起调。
9. **前后端各写一份模板时，"逐字一致"必须用测试卡住，不能靠注释提醒**。
   本项目前端预览与后端下发各有一份 `buildSystemPrompt()`，
   实测真出现了三处漂移：工作流中文名不一致、缺`【检索来源】`整行、回退路径没传 `lit_source`。
   现在 `server/verify-prompt-parity.mjs` 跑 10 组用例，不一致直接退出码 1。
   单一名词（如步骤中文名）只维护一份，后端 import 前端的。
10. **证据页滚动容器是 `.evwrap`（`overflow:auto`），文档本身不滚**。
    截图底部要滚容器而不是 `window.scrollTo`，否则截到的还是顶部。
11. **Bash 工具里管道会消费变量**。
    `RID=$(curl ... | tee f | node -e "...")` 里 `$RID` 拿到的是最后一个 node 的输出，
    不是 run_id——本项目踩过一次，以为存档没落盘。分步执行或写临时文件更可靠。
12. **目录移进仓库后，相对路径要重算 + 跑一次真实启动验证**。
    本工程原在仓库外（`hkx-v3/paper-agent-web/`），入库为 `paper-agent/web/` 后，
    后端 `AGENT_ROOT` 的默认从 `../paper-agent` 变成 `..`。
    只改代码不够——**必须 `curl /api/health` 确认 `runs_count` 不为 0**，
    路径算错时后端能正常启动、但 `runs/` 找不到，是很容易漏过的静默故障。
13. **移动目录前先停占用它的服务**。
    Windows 上 `mv` 目录会报 `Device or resource busy`；
    本项目三个服务（5173 静态 / 8787 真后端 / 8788 mock）都锁着目录，
    需先按端口找 PID 停掉（`netstat -ano | grep 8787` → `taskkill //PID <pid> //F`）。
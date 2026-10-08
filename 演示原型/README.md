# paper-agent 2.0 · 科研工作台（前端）

> 零构建、零依赖、双击即开。三种运行模式覆盖「离线演示 → 真实联调」全谱。
> 本目录是 paper-agent 2.0 的**工作台前端**（Batch 3 路线 B：由高完成度原型演进为可接真后端的生产前端）。

## 打开方式（三选一）

| 方式 | 命令 | 说明 |
|---|---|---|
| **双击打开** | 双击 `index.html` | 默认 mock 模式：全假数据、离线可跑、100% 可重复 |
| **一键启动** | `bash ../demo-kit/bootstrap.sh --mode mock` | 同上，由 demo-kit 托管（起服务前先跑环境自检） |
| **真实联调** | `bash ../demo-kit/bootstrap.sh --mode live` | 起真后端 8787，浏览器打开 `http://127.0.0.1:5173/?mode=live` |

## 三种模式

| 模式 | 数据来源 | 用途 |
|---|---|---|
| `mock`（默认） | 内嵌假数据 + 模拟推进器（8s/步） | 现场演示 / 走查 UI / 离线可重复 |
| `live` | 真后端 HTTP + SSE（`?mode=live&base=http://127.0.0.1:8787`） | 联调 / 真实 run 的监控·溯源·导出 |
| `fake` | `web/mock/server.js` 内存假后端 | 只验 HTTP+SSE 链路，不跑 Python |

**live 模式要点**：
- 启动即拉真实任务列表（`GET /api/runs`），总览显示**真实 run**；
- 监控页 SSE 实时推进——后端五类事件（`step/tool/degraded/conclusion/done`）归一化进 store，视图层零感知；
- 证据页数据与 `runs/<id>/provenance.jsonl` 等真产物一致，**工具名永远是真实注册名**；
- **不自动开跑**——真实执行需显式点击「执行下一步 / 跑完整个流程」；
- materials 工作流无 review/factcheck 产物 → 证据页如实显示「—」（不造假数据）；
- live 不可用时优雅降级提示（不会白屏），mock 随时可用兜底。

## 目录结构

```
演示原型/
├── index.html            入口（经典 <script src> 顺序加载，file:// 可用）
├── assets/
│   ├── tokens.css        设计令牌（唯一真源：深色 + 琥珀 #D9A441）
│   ├── constants.js      工作流/步骤/路由/提示词模板常量
│   ├── data.js           mock 假数据（字段取自真实 runs/ 产物）
│   ├── components.js     UI 原语（h/icon/卡/步骤条/toast/骨架…）
│   ├── store.js          极简 pub/sub + live run 注册表（单一数据流：api→store→views）
│   ├── api.js            数据/网络适配层（mock|live 双模式；唯一网络出口）
│   ├── views.js          界面渲染（10 路由）
│   └── app.js            应用外壳（导航/路由/顶栏）
└── tests/smoke.mjs       零依赖冒烟测试（`node tests/smoke.mjs`，无需安装任何东西）
```

## 冒烟测试

```bash
node tests/smoke.mjs
# 输出 SMOKE_PASS = true 即全绿（常量/路由/字段形状/工具名真源/mock 行为/live 能力静态断言）
```

## 与 demo-kit 的关系

- `demo-kit/bootstrap.sh --mode mock` 的静态服务直接指向本目录（零构建原型作为演示主场）；
- `demo-kit/health-check.sh` 负责环境自检（变量/端口/解释器/AGH），`bootstrap` 起服务前先跑自检；
- 接口契约见 `web/server/paper-agent-server.js`（M1 真实后端），设计依据见 `../设计规划/03-增量实施任务列表.md`（Batch 3 路线 B）。

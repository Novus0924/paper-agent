# 交接文档（HANDOFF）— paper-agent

> 面向**接手本项目的下一个编程工具 / 工程师**。读完本文即可在无上下文记忆的情况下继续推进。
> 最后更新：**2026-10-03**（真实数据改造 + 第二批增强线之后）。
> **本文以仓库实际状态为准**；若与代码不一致，以 `git log` 与代码为准。

---

## 0. 30 秒速览

- **项目**：`paper-agent` —— 一条**可审计、可复现、可故障恢复**的科研流水线。
  输入是**真实公开数据集**（OBELiX，599 条锂固态电解质的实验实测离子电导率，
  每条带原始论文 DOI），不是人工预制的演示数据。
- **当前档位**：**改造已完成，AGH 会话内链路待实跑**。
  Python 主线（真实数据）**全部验证通过**；AGH 插件 10 个工具代码就绪、单测覆盖，
  但**插件未安装、会话未跑过一次**（赛题指定底座链路缺一次实证）。
- **红线**：密钥只放环境变量 / `.env`（gitignore）；数值只来自公开数据集与本地
  确定性计算，**严禁伪造**；**不抓论文全文**；**判断不得进结论**。

> ### ⚠️ 最重要的未完成项（接手第一件事）
>
> **`paper-agent-tools` 插件未安装，AGH 会话从未实跑，`evidence/session.jsonl` 不存在。**
>
> - 逐步操作手册（含每步预期输出与故障表）：`docs/AGH-SESSION-RUNBOOK.md`
> - 必须由人在交互终端执行（AGH 的 `package add` 走 `io.confirm(preview)`，**无 bypass**）
> - 两个必踩的坑见 §7.3，**先看再动手**

---

## 1. 与改造前的对比（别再按旧口径理解本项目）

| 维度 | 改造前（≤ `8933f5c`） | 现在（`8b0d530`） |
|---|---|---|
| 主数据源 | 人工预制 **7 行**演示 CSV | **OBELiX 599 行**真实数据（562 行可用） |
| 文献来源 | 内置 **5 篇**手写卡片 | 数据集自带 **223 个真实 DOI**；增强线可联网检索 Crossref/OpenAlex |
| 打分口径 | 自拟权重 `0.6/0.25/0.15` | **去掉全部自拟权重**，只按实测值排序 + 族统计 |
| 信任模型 | 二级（证据 / 结论） | **三级：fact / judgment / conclusion**，代码级强制 |
| 判断记录 | 无 | 43 条 judgment（含 36 条被排除项与理由），随快照自包含 |
| 可复现边界 | 声称全链路可复现 | 只承诺"**冻结快照之后**"逐字节可复现 |
| 异常处理 | 仅技术故障重试/降级 | 增加**判断类异常打断**（4 条规则 + 人工确认闸门） |
| 单测 | 39 | **210** |
| AGH 工具 | 7 | **10** |
| AGH 会话 | 声称已闭环（旧机器，证据不在本机） | **本机未安装、未实跑** |

> 旧数据 `data/literature.json` 与 `data/conductivity_raw.csv` **已降级为 legacy 降级路径**，
> 不再参与主线，只用于回归测试（用 `PAPER_AGENT_SNAPSHOT=none` 切换）。
> 新手别误以为它们是主输入。

---

## 2. 提交历史（最新在上）

```
121aae5  docs: HANDOFF 重写为改造后状态（原文档停留在 7 工具/演示数据口径）
c7466ed  fix(sources): 输入数据结构不符时响亮失败（堵住静默产出垃圾的洞）
471477f  docs: AGH 会话内主路径操作手册（含预期输出与故障对照表）
a915614  fix(plugin): Python 解释器多候选回退 + 可操作的错误提示
d64a74d  fix(plugin): 项目根自动推导，不再强依赖环境变量注入
924b505  docs: 判据 2 与反判据的真实模型结论（DeepSeek 实测）
e9f55c3  docs: 第二批文档与验收（含两处实测修正、判据状态如实标注）
9fcb002  feat(freezing): 三段式冻结流程 + CLI 命令 + AGH 插件 3 工具
70e6e6f  feat(judge): 可插拔判断器 + 反判据对比（含 AGH 模型调用路径的实测否证）
ecf1a57  feat(anomaly): 双腿 DOI 对接 + 异常驱动打断（D7）
dcdcbe3  feat(litsearch): 联网文献腿（Crossref / OpenAlex 元数据检索）
7cd47ec  docs: 红线措辞修订 + 入口文档更新（第一批收尾）
22d3f64  demo: 双轨演示（真实数据主线 + legacy 回归）
0148e3d  feat(pipeline): 主链路切换到真实数据集（快照消费 + 真实清洗 + 实测值排序）
fea6757  feat(sources): 外部数据源适配层（OBELiX 数据腿）
80f1535  feat(snapshot): 冻结输入快照机制（复现契约的载体）
98d7e07  feat(provenance): 三级信任模型（fact / judgment / conclusion）
41c2d4e  tools: OBELiX 技术探针通过（改造方案闸门验证）
4429615  docs: 改造设计方案与竖版流程图（10 项决定 + 差异清单 + 红线修订）
8933f5c  Merge pull request #1 from Novus0924/leyon     ← 改造前的原作者提交（已推送）
```

- 分支：`main`；远端：`origin git@github-w:Novus0924/paper-agent.git`
  （SSH 别名 `github-w` → `~/.ssh/id_gh_work` → 认证到 GitHub 账号 **Novus0924**）
- **状态：19 个提交未推送**（按项目纪律，未经明确许可不推送）。
- **提交署名已统一为 `Novus0924 <18014082610@163.com>`**（仓库级 `user.name/user.email`
  已写入 `.git/config`）。此前这 19 个提交曾以另一个身份署名，为保证 GitHub 上
  全部提交都关联到你的账号，已用 `git filter-branch --env-filter` 改写
  `origin/main..HEAD` 范围的作者与提交者；**改写前后内容树指纹一致**
  （`c967a59bff3153547fe181c1c3f9f2434f1cf553`），文件内容一字未变，
  因此上面的 SHA 与改写前不同。已推送的历史（原作者的提交）**未改动**。
- ⚠️ **推送前请删掉备份分支** `backup/pre-author-rewrite`：它是改写前的旧历史，
  若用 `git push --all` / `--mirror` 会把旧署名的历史一起推上去。
  确认无误后执行：`git branch -D backup/pre-author-rewrite`
- 权威设计文档：`docs/redesign-decisions.md`（含决定、被否决方案、**两处实测修正**、判据状态）

---

## 3. 目录结构（真实，精确到文件）

```
paper-agent/
├── core/paper_agent/                 # Python 核心（零第三方依赖，仅标准库）
│   ├── state.py                      #   有限状态机 + run 生命周期 + append-only events
│   ├── provenance.py                 #   三级证据账本；link_conclusion 拒绝非 fact 证据
│   ├── snapshot.py                   #   冻结输入快照（逐文件 SHA-256 + 判断批次自包含）
│   ├── sources.py                    #   OBELiX 适配（列名归一 / 值分类 / **结构守卫**）
│   ├── litsearch.py                  #   联网文献腿（Crossref / OpenAlex 元数据）
│   ├── judge.py                      #   可插拔判断器 RuleJudge / ModelJudge + 反判据对比
│   ├── llm.py                        #   模型客户端（含 AGH 路径的实测结论）
│   ├── anomaly.py                    #   双腿 DOI 对接 + 4 条异常规则 + 确认闸门
│   ├── freezing.py                   #   三段式冻结 prepare → 推理 → commit
│   ├── chaos.py                      #   故障注入
│   ├── steps.py                      #   五步调度（快照主路径 + legacy 回退）
│   ├── verify.py                     #   P4 复现验证器（5 项递归容差比对）
│   ├── report.py                     #   P5 报告（判据 4 硬前置）
│   └── cli.py                        #   CLI 入口（stdout 单 JSON）；含 search / freeze
├── experiments/arrhenius_rank.py     # 确定性实验脚本（双 schema 自适应）
├── tools/
│   ├── freeze_snapshot.py            # 冻结快照（prepare / commit / 规则式一步到位）
│   ├── search_literature.py          # 联网检索 CLI
│   ├── compare_judges.py             # ★ 反判据：退出码即判据（0 有用 / 5 装饰品）
│   └── probe_obelix.py               # 数据源探针（只读、可离线复跑）
├── data/
│   ├── external/obelix/all.csv      # ★ 主数据源（599 行，CC-BY-4.0）+ README 署名
│   ├── literature.json               # legacy 降级路径（5 篇）
│   └── conductivity_raw.csv          # legacy 降级路径（7 行演示数据）
├── snapshots/snap-20261002-065225-5e1fe9/   # ★ 冻结输入快照（已入库，供离线主线）
│   ├── manifest.json                 #   文件清单 + SHA-256 + 聚合 content_sha256
│   ├── literature.json               #   文献腿
│   ├── materials.csv                 #   数据腿（599 行）
│   └── judgments.jsonl               #   判断批次（43 条，tier=judgment）
├── plugins/paper-agent-tools/        # AGH 扩展（10 工具，JS 薄壳）
├── tests/                            # 11 个文件 / 210 用例
├── demo/
│   ├── demo_mainline.sh              # ★ 真实数据主线（14 断言；含判据 4 实测）
│   ├── demo_e2e.sh                   # legacy 路径端到端
│   └── demo_failure.sh               # legacy 路径四大故障用例
├── docs/
│   ├── redesign-decisions.md         # ★ 权威设计文档
│   ├── AGH-SESSION-RUNBOOK.md        # ★ AGH 会话逐步操作手册
│   ├── ai_disclosure.md              # AI 使用边界声明（三级模型口径）
│   ├── sources.md                    # 数据来源声明
│   └── diagrams/                     # 3 张竖版流程图
├── evidence/
│   └── model-judge-comparison.json   # 反判据机读结果（真实模型对比）
├── audit-pack-template/              # 审计交付包模板
├── README.md / HOW-TO-VERIFY.md     # 入口 / 验收手册
└── .env                              # 模型 key（gitignore，绝不入库）
```

---

## 4. 如何验证现状（接手第一步就跑这个）

```bash
cd D:/workBubbyStore/hks/paper-agent
export PYTHONPATH="$PWD/core"
PY="/c/Users/lenovo/.workbuddy/binaries/python/versions/3.13.12/python.exe"

# ⚠️ demo 脚本用 `printenv paper-agent_PYTHON || echo python` 找解释器，
#    而本机 PATH 上**没有 python** → 必须显式传，否则脚本会在第一步就失败。
PYEXP="C:/Users/lenovo/.workbuddy/binaries/python/versions/3.13.12/python.exe"

# ① 单测（210 应全绿）
PYTHONIOENCODING=utf-8 "$PY" -m unittest discover -s tests -p "test_*.py"

# ② 真实数据主线演示（14 断言）
env "paper-agent_PYTHON=$PYEXP" bash demo/demo_mainline.sh

# ③ legacy 回归（demo 脚本内部已自设 PAPER_AGENT_SNAPSHOT=none；
#    外部再设一次是为了双保险，两者都支持）
env "paper-agent_SNAPSHOT=none" "paper-agent_PYTHON=$PYEXP" bash demo/demo_e2e.sh
env "paper-agent_SNAPSHOT=none" "paper-agent_PYTHON=$PYEXP" bash demo/demo_failure.sh

# ④ 反判据自检（应当判定为装饰品 → 退出码 5）
PYTHONPATH="$PWD/core" "$PY" tools/compare_judges.py --goal "sulfide solid electrolyte" --judge-b rule
echo "退出码=$?"   # 期望 5

# ⑤ 快照强校验
"$PY" -c "import sys;sys.path.insert(0,'core');from paper_agent import snapshot as S;print(S.open_snapshot('.').verify())"
# 期望 (True, [])
```

**预期（以上五条均于 2026-10-03 本机实测）**：单测 `Ran 210 tests ... OK`；
② 末行 `DEMO_MAINLINE_OK`（14 passed, 0 failed）；③ `DEMO_E2E_OK` 与
`DEMO_FAILURE_OK`（8 passed, 0 failed）；④ 退出码 `5`；⑤ `(True, [])`。

---

## 5. 设计红线（改代码前必读）

1. **零第三方依赖**：Python 核心只用标准库。新增功能不得 import 非标准库包。
2. **确定性**：相同快照两次运行 `results.csv` 逐字节一致；`summary.json.generated_at`
   是唯一可变字段，**校验时排除**。可用 `paper-agent_MUTATE=1` 触发 P4 FAIL。
3. **append-only 账本**：`events.jsonl` / `provenance.jsonl` / `judgments.jsonl` 只追加不修改。
4. **状态机终态守卫**：DONE / SKIPPED 是终态；FAILED 步骤可重试，FAILED run 不可再 finish。
5. **三级信任模型（新增，最高优先级）**：
   - 只有 `tier=fact` 的证据能支撑结论；`link_conclusion` **代码级拒绝** judgment
   - judgment（含被排除项与理由）只影响流程走向，**不得进结论**
   - 使用快照的 run，**账本缺判断批次则拒绝生成报告**
6. **冻结快照承载复现契约**：判断结果一经产生立即冻结；只承诺"冻结之后"可复现。
   `content_sha256` **不含时间戳**（否则确定性契约自相矛盾）。
7. **异常驱动打断**：判断类异常（零命中 / 两腿交集为零 / 命中率反常 / 自相矛盾）
   必须停下等人工裁决，`--ack <code>` 显式确认，确认动作记入快照清单。
8. **输入结构守卫**：`sources.read_obelix(strict=True)` 在列名对不上时**必须抛
   `SchemaError`**，绝不允许"把不认识的数据当合法的空数据"（真实教训，见 §8.6）。
9. **utf-8-sig + UTF-8 stdout**：读 CSV 用 `encoding="utf-8-sig"`；CLI 强制 UTF-8。
10. **分层解耦**：AGH JS 薄壳只 spawn Python CLI，不 import 工具实现；调用留痕 `toolcalls/`。
11. **合规**：数值只来自公开数据集 + 本地确定性计算，**严禁伪造**；**不抓论文全文**；
    密钥只放环境变量 / `.env`，**绝不写仓库/文档/提交**。

---

## 6. 关键产物指纹

- 冻结快照 `snap-20261002-065225-5e1fe9`
  - `content_sha256` = `5a0071827742be0e719591f78b78be118f9caaf2bf007b02b25b1d3594cf556e`
  - `producer` = `bootstrap_rule_v1`（规则式判断），`judgment_batch.count` = 43
- 数据基线（改数据适配层时用）：599 行 / 562 numeric / 37 上界值 `<x` / 33 空 family / DOI 覆盖 100%（223 唯一）
- 5 项复现校验：`results_csv_sha256 / n_rows / top3_material_id_set / top3_scores_positional / family_mean_log10_cond`
- 插件 integrity（**每次改 `index.mjs` / `package.json` / 插件目录任何文件都会变，
  以实测为准**）：
  ```bash
  cd D:/workBubbyStore/hks/paper-agent
  node D:/agnes-harness-main/packages/cli/dist/local/agnes.mjs package inspect "file:./plugins/paper-agent-tools"
  ```
  最近一次实测（2026-10-03，补齐插件 `README.md` 之后）：
  `sha256-3b308d3b41a0d3011043c67dd3030dc9782befd302b37be4df067daa90e89586`
- **仓库里只有一个插件目录** `plugins/paper-agent-tools/`（10 工具）。
  原先还有一个 `plugins/paper-tools/`，只含一份描述**未实现**工具的 README 存根，
  零代码、全仓库无人引用 → **已删除**。
- **安装前请先跑 `docs/AGH-SESSION-RUNBOOK.md` 的「第 0.5 步 · 安装前自查」**
  （3 条，30 秒）：manifest 的 `files` 与实际文件是否一致、插件能否注册 10 工具、
  inspect 是否只剩 provenance 警告。**别等卡在交互确认框里才发现 manifest 有问题。**
- 反判据结论存档 `evidence/model-judge-comparison.json`（DeepSeek 实测 `model_matters`）

---

## 7. AGH 状态（最重要，新工具重点看这里）

### 7.1 事实（本机实测，不夸大）

- **AGH 源码**：`D:/agnes-harness-main`（已构建 `packages/cli/dist/local/agnes.mjs`）
- **provider 可用**：`AGH doctor provider --probe` → `✓ verified`
  （route `account-acct-1a50785c-…`；`~/.agh/secrets` 下有 `agnes-ai` 与 `deepseek` 两项凭据）
- **插件未安装**：`AGH package status` 只有官方 3 个 helper，**没有 `paper-agent-tools`**
- **会话从未实跑**：`evidence/` 下只有 `model-judge-comparison.json`，**没有 `session.jsonl`**
- 改造前的会话证据（旧机器 `C:\Users\ASUS\...`）**不在本机**，`*.jsonl` 已按红线 gitignore

### 7.2 为什么必须人工跑

AGH 的 `package add` 走 `io.confirm(preview)`，**交互式 TTY 才点头**，无 bypass flag
（装插件 = 以本机权限执行 JS，必须人类确认）。因此 install → trust → enable → 会话
这一环**无法在编程工具的非交互 shell 里代跑**。

### 7.3 两个必踩的坑（本机实测）

1. **相对路径由谁解析**：`file:./plugins/...` 是相对路径。**daemon 在运行时**由
   daemon 的工作目录解析——若 daemon 是从别处启动的，`package inspect` 会报
   `The package source could not be accepted`。**在项目根目录执行命令**即可；
   若 daemon 已在别处启动过，先 `daemon stop` 再从项目根 `daemon start`。
2. **本机 PATH 上没有任何 python**（`python` / `python3` / `py` 全不在）→ 必须先
   ```bash
   export PAPER_AGENT_PYTHON="C:/Users/lenovo/.workbuddy/binaries/python/versions/3.13.12/python.exe"
   ```
   否则 **10 个 AGH 工具全部报 `cannot launch python`**（插件已支持多候选回退并给出
   可操作提示，但显式设置最稳）。
   **同样的坑也影响 `demo/*.sh`**：它们用 `printenv paper-agent_PYTHON || echo python`
   找解释器，所以跑演示脚本也必须显式传 `paper-agent_PYTHON`（见 §4 的 `PYEXP`）。
   连字符名在部分 shell 无法 `export`，用 `env "名字=值" 命令` 的形式传。

### 7.4 怎么跑

见 **`docs/AGH-SESSION-RUNBOOK.md`**（逐步命令 + 每步预期输出 + 8 条故障对照表）。
手册里有两条可直接粘贴的会话 prompt：5A 驱动既有流水线、5B 驱动新的检索/判断/冻结三件套。

---

## 8. 被实测否证的假设 / 已否决的弯路（**别再重走**）

1. **「两腿 DOI 能高重合对接」——否证**。实测文献腿 373 篇 ∩ OBELiX 222 篇 = **仅 8 篇
   （2.1%）**。文献腿给话题全景、数据腿是特定数据集的来源论文，天然只少量重叠。
   → 异常规则已修正为「低对接率只报指标，**只有交集为零**才判异常」，并有回归用例
   `test_low_join_rate_is_NOT_anomaly` 锁死。**别再改回宽松阈值。**
2. **「AGH 能从 Python 当补全 API 用」——否证**。`agh -p` 非交互下会挂起（daemon 启动后
   重测仍 150s 无输出）；`agh serve model-api` 起的是给人用的 Web 控制台
   （`/v1/models` 404、`POST /v1/chat/completions` 405）。→ 模型判断的主路径是
   **AGH 会话内判断**（LLM 调插件工具落盘裁决），会话外自动化用标准 OpenAI 兼容端点。
   **因此本项目不提供 AGH 专用客户端**，别再重写一个会挂起的。
3. **项目内隔离 AGH home（`.agh-home`）——原作者已验证失败**。AGH 的 home 是活运行时
   状态机（credential store / daemon 身份 / sqlite lock 均绑定原路径），搬 home 必报
   `provider host assembly failed`。**不要再尝试搬 home。**
4. **`file:` 源必须相对 `./`**。绝对路径 `file:D:\...` 触发 `ProtocolViolation`。
5. **带连字符的环境变量名**在部分 shell 无法 `export`。插件已同时支持
   `PAPER_AGENT_X` 与 `paper-agent_X` 两种写法；**优先用下划线版本**。
6. **喂错领域的数据会静默成功——已修**。实测把吸附容量 CSV 喂进去，旧实现退出码 0、
   报告 ok=true，却写出"4 行全 invalid、9 列里 8 列未解析"的无意义快照。
   → 已加 `SchemaError` 守卫（退出码 2 + 可操作提示）与 5 条回归用例。**别把守卫删掉。**
7. **Git Bash 的 `/tmp` ≠ Python 的 `/tmp`**。跨语言传路径统一用 `D:/...` 显式形式。

---

## 9. 环境矩阵（本机实测）

| 组件 | 要求 | 本机实际 |
|---|---|---|
| Python | 3.10+，零第三方依赖 | **3.13.14**（WorkBuddy 托管：`C:/Users/lenovo/.workbuddy/binaries/python/versions/3.13.12/python.exe`） |
| Node | AGH 需 ≥24 | **v24.21.0**（`C:/Program Files/nodejs/node.exe`；注意 PATH 里可能先命中托管的 22.x） |
| bash + sha256sum | demo 脚本 | Git Bash |
| AGH 源码 | 已构建 | `D:/agnes-harness-main` |
| 模型端点 | 标准 OpenAI 兼容 | `https://api.deepseek.com` + `deepseek-chat`（key 在 `DEEPSEEK_API_KEY`；已实测连通） |
| 网络 | 仅增强线需要 | 文献检索需联网；主线全程离线 |

### 踩坑备忘（Windows 特有）

- **WSL shim 拦截**：`bash -c "…"` 或带引号路径调 Git Bash 会被 `wsl.exe` 拦截报
  `No such file or directory`。解法：PowerShell 直接调脚本绝对路径，不要嵌套 `-c`。
- **PowerShell 展开 `${VAR}`**：会被外层展开 → 用脚本文件传参。
- **cmd vs PowerShell**：`Get-ChildItem` / `Select-String` 是 PowerShell cmdlet；
  `dir` / `findstr` / `%var%` 是 cmd。
- **中文路径 + 编码**：管道读含中文路径的 JSON 按 cp936/GBK 解码会崩；
  CLI 已加 `_ensure_utf8_stdio`，demo 脚本加 `export PYTHONIOENCODING=utf-8`。
- **文件偶发 `EBUSY`**：编辑时可能被杀软短暂占用，**直接重试同一次编辑**即可。

---

## 10. 未完成清单（下一步做什么）

| # | 事项 | 谁做 | 预估 |
|---|---|---|---|
| 1 | 装插件 + 跑一次 AGH 会话，导出 `evidence/session.jsonl`（≥6 条 tool 交互） | **人**（交互终端） | 15–25 分 |
| 2 | 逐篇论文相关性判断（把判断粒度从 42 个族降到 223 篇论文，**放大模型价值**） | 工具 | 半天 |
| 3 | 领域插件化（分析脚本注册表 + 适配器注册表 + 标准 schema 泛化 `value`/`unit`/`property`） | 工具 | 2–3 天 |
| 4 | 推送 18 个本地提交 | **人**点头后 | 1 分 |
| 5 | 赛事提交材料（项目说明 / 演示视频脚本 / 独立完成声明）复核 | 人 | — |

> 若时间只够做一件事：**做 #1**。它是赛题指定底座链路的唯一实证缺口。
> 若来不及做 #1，交付口径必须写明「插件已就绪，会话内链路待实跑」，
> **不要写成已跑通**。

---

## 11. 一句话交接

> 真实数据改造（第一批）与增强线（第二批）均已落地：599 行真实数据、
> 三级信任模型、冻结快照、异常打断、联网检索、模型判断与反判据，
> 210 项单测与三套演示脚本可复现；**唯一未验证的是 AGH 会话内链路**——
> 代码与契约齐备，但插件未装、会话未跑，这是接手后第一件该做的事。
> 改任何 Python 代码前先读 §5 红线、跑 §4 验证；改插件前先读 §7.3 的两个坑。

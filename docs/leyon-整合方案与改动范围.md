# leyon 分支代码整合方案与改动范围

> 整合依据：统一需求文档《科研智能体需求文档 v0.3（参赛版+量化验证+异常恢复）》
> 整合策略：方案 A（整合而非单选一人代码）
> 目标分支：`leyon`（不改动 `main` / `mike` / `novus`）
> 工作副本：`paper-agent-integ`（已检出 `leyon`，基线提交 `b479e4e`）

---

## 0. 结论前置

- **主干采用 mike 的双工作流实现**：`materials`（P1–P5，向后兼容默认路径）+ `research`（R1–R6，PRD 核心链路），由 `state.py` 的 `WORKFLOWS`/`RESEARCH_STEPS` 决定步骤集合，状态机 / 账本 / 故障恢复协议复用。
- **novus 的可信 / 可复现增强作为可插拔层并入**：三级信任模型（fact / judgment）织入 `provenance.py` 内核；`judge` / `snapshot` / `sources` / `freezing` / `llm` / `anomaly` 作为可用模块保留；novus 的冻结快照版 `materials` 流水线以 `materials_snapshot.py` 保留可切换。
- **三处核心合并文件**：`provenance.py`（合并版）、`litsearch.py`（扩充联网检索腿）、`cli.py`（mike 基 + `freeze` 命令）。
- **验证**：合并后导入冒烟 + 迁移测试共 **137 项全部通过**（见第 7 节）。

---

## 1. 背景与分支关系

仓库 `Novus0924/paper-agent` 含四个相关分支：

| 分支 | 角色 | 状态 |
|------|------|------|
| `main` | 受保护主分支，最新基线 | 最新 |
| `mike` | 队友基于统一文档独立开发（四源检索 + 量化验证 + research 全套） | 贴合 PRD v0.3 |
| `novus` | 队友基于统一文档独立开发（三级信任 + 冻结快照 + 异常恢复） | 贴合 PRD v0.3 |
| `leyon` | 本分支，整合目标 | 原先落后于 `main` |

决策（用户明确）：
1. 不改动 `novus` / `mike` / `main` 三个分支的既有代码；
2. 采用**方案 A**：结合统一文档整合代码；
3. 整合结果推送到 `leyon`；
4. 在 `leyon` 产出配套文档（本文件）。

---

## 2. 整合总体架构（Plan A）

```
                      ┌─────────────────────────────────────┐
                      │            state.py (mike 版)         │
                      │  WORKFLOWS / RESEARCH_STEPS /         │
                      │  MATERIALS_STEPS / LIT_SOURCES        │
                      └───────────────┬─────────────────────┘
                                      │ open_pipeline 按 workflow 分发
                ┌─────────────────────┴─────────────────────┐
                │ 主干：mike 实现                              │
                │  materials: Pipeline  (P1–P5)              │
                │  research : ResearchPipeline (R1–R6)       │
                │  steps.py / research.py / report.py /      │
                │  analyze / writing / factcheck / review /  │
                │  evaluate / pdfparse / litsearch(四源)       │
                └─────────────────────┬─────────────────────┘
                                      │ 可插拔增强层（novus）
                ┌─────────────────────┴─────────────────────┐
                │  provenance.py 三级信任内核（fact/judgment）│
                │  judge / snapshot / sources / freezing /   │
                │  llm / anomaly                             │
                │  materials_snapshot.py（冻结快照版流水线， │
                │  可切换保留，避免与默认 Pipeline 同名冲突） │
                │  cli: freeze 命令                          │
                └───────────────────────────────────────────┘
```

**设计原则**：默认行为完全由 mike 定义（保证 PRD 双工作流可跑、向后兼容）；novus 能力以"不破坏默认路径"的方式叠加，仅通过显式入口（`freeze` 命令、`append_judgment` API、`materials_snapshot` 模块）触发。

---

## 3. 模块取舍与来源映射

| 模块 | 来源 | 处理方式 |
|------|------|----------|
| `__init__.py` | leyon 基线（已正确） | 保持不变 |
| `state.py` | mike | 覆盖（superset：含 `lit_source`/`workflow`/`step_ids`） |
| `chaos.py` | mike | 覆盖（故障注入 `CH` 单例） |
| `steps.py` | mike | 覆盖（默认 `materials` 流水线 + `open_pipeline` 分发） |
| `research.py` | mike | 覆盖（`ResearchPipeline` R1–R6，调用 `ProvenanceLedger(..., root=root)`） |
| `report.py` | mike | 覆盖（`generate_report` + `generate_research_report`） |
| `analyze.py` / `writing.py` / `factcheck.py` / `review.py` / `evaluate.py` / `pdfparse.py` | mike | 新增 |
| `litsearch.py` | mike + novus | **扩充**：mike 四源 `search_papers` 保留，追加 novus 联网腿（`search`/`CROSSREF`/`OPENALEX`/`mailto_from_env`） |
| `provenance.py` | mike + novus | **合并**：mike 宽松 `EVIDENCE_KINDS` + novus 三级信任 API + `root` 形参 |
| `cli.py` | mike + novus | **合并**：mike 全套子命令 + novus `freeze` 命令 |
| `judge.py` / `snapshot.py` / `sources.py` / `freezing.py` / `llm.py` / `anomaly.py` | novus | 新增（仅依赖 stdlib 与包内互引） |
| `materials_snapshot.py` | novus `steps.py` 改名 | 新增（保留 novus 冻结快照版 `materials` 流水线，可切换，避免与 mike `steps.Pipeline` 同名冲突） |
| `verify.py` / `report` 引用 | leyon 基线 | 保留 |

**未采纳项（及理由）**：
- **novus 独立 `search` 命令**：依赖 novus 版 `litsearch.SOURCES` / `litsearch.search`，与 mike 四源 `search_papers` API 冲突。联网多源检索统一走 mike 的 `search-papers` 子命令。
- **novus `steps.py` 直接替换 mike `steps.py`**：两者都有 `Pipeline` 类且语义不同（冻结快照 vs 默认）。改为保留 novus 版为 `materials_snapshot.py`，默认仍用 mike `steps.Pipeline`。

---

## 4. 三处核心合并细节

### 4.1 `provenance.py`（合并版）

- 证据种类 `EVIDENCE_KINDS` = mike 12 型 ∪ novus 3 型 judgment = **15 型全集**。
- 新增 novus 三级信任 API：
  `append_judgment` / `require_judgment_batch` / `check_binding_invariants` / `facts` / `judgments` / `excluded_judgments` / `tier_of`（静态方法）。
- `__init__` 增加 `root=""` 形参，供 mike `research.py` 的 `ProvenanceLedger(..., root=root)` 调用；`_literature_lookup` 支持 `<root>/data/literature.json` 优先、全局 `DATA_DIR` 回退。
- **双轨 tier 赋值**（`_tier_of_kind`）：`query_generation` / `relevance` / `anomaly` → `judgment`；其余（含 mike 的 `note`/`analysis`/`factcheck`/`draft`/`review`/`evaluation`）→ `fact`。
- `link_conclusion` 强制**仅 fact 级可进结论**（三级信任红线）；judgment 不得支撑结论。`cite` 对 judgment 级输出"裁决主体 + 结论 + 理由"。

### 4.2 `litsearch.py`（扩充联网检索腿）

- mike 的四源能力（`search_arxiv` / `load_local_corpus` / `search_papers` / `dedup_documents` / `score_relevance` / `rank_documents` / `filter_by_relevance` / `ref_of` 等）**原样保留**。
- 追加 novus 联网腿原语（语义独立、命名无冲突）：
  `CROSSREF` / `OPENALEX` / `SOURCES` / `DEFAULT_MAILTO` / `DEFAULT_RETRIES` / `BACKOFF` / `SearchError` / `make_record` / `parse_crossref_item` / `parse_openalex_item` / `build_url` / `http_get_json` / `_items_of` / `search_one` / `merge_records` / `search` / `mailto_from_env`。
- 追加 `import time`（mike 原文件未导入，而 novus 联网腿用到 `time.sleep`）。
- 该扩充**仅被 `freezing.py` 的 network 模式消费**；默认 `bootstrap` 模式不触网。

### 4.3 `cli.py`（mike 基 + `freeze`）

- 以 mike `cli.py` 为基（含 `--workflow` / `--lit-source`、`open_pipeline` 按工作流分发、`research` 全套子命令 `search-papers` / `parse-paper` / `analyze-paper` / `verify-facts` / `write-review` / `self-review` / `eval`）。
- 仅追加 novus 的 **`freeze`** 命令：`cmd_freeze` / `_freeze_dispatch`，parser 注册 `--goal` / `--input` / `--literature` / `--prepare` / `--commit` / `--verdicts` / `--judged-by` / `--root` 等；`_HANDLERS["freeze"]` 注册。
- `freezing` / `sources` 在 `cmd_freeze` 内**惰性导入**，避免未使用冻结能力时也强依赖其依赖链。
- 不追加 novus 的 `search` 命令（API 冲突，见第 3 节）。

---

## 5. 关键冲突与解决

| 冲突 | 现象 | 解决 |
|------|------|------|
| `research.py` 调 `ProvenanceLedger(..., root=root)` | novus 版 `__init__` 无 `root` 形参 → TypeError | 合并版 `__init__` 加 `root=""` |
| mike 用 `note`/`analysis`/`factcheck`/`draft`/`review` 证据种类 | novus 版 `FACT_KINDS` 仅 6 型 → `EvidenceError` | 合并版 `EVIDENCE_KINDS` 取 15 型并集，mike 各型默认 fact-tier |
| novus 三级信任红线（judgment 不得进结论） | 与 mike 报告用 judgment 类进结论冲突 | 仅 `query_generation`/`relevance`/`anomaly` 走 judgment-tier；mike 的 `note` 等保持 fact-tier，可正常进结论，红线仅约束真正的判断类 |
| `freezing.py` import 期求值 `litsearch.CROSSREF`/`OPENALEX`，并调用 `litsearch.search`/`mailto_from_env` | mike `litsearch` 无这些名称 → ImportError | 扩充 `litsearch` 联网腿（第 4.2 节） |
| novus `steps.py` 与 mike `steps.py` 都有 `Pipeline` 类 | 直接覆盖会丢失默认 materials 流水线 | novus 版改名 `materials_snapshot.py` 保留可切换 |
| mike `litsearch` 未 `import time` | 并入 novus 联网腿后 `time` 未定义 → NameError | 补 `import time` |

---

## 6. 与 PRD v0.3（参赛版）的对应

- **F-1.1 统一多源检索**：mike `litsearch.search_papers`（arXiv / Semantic Scholar / OpenAlex / CrossRef）+ 去重 / 相关性排序 → `search-papers` 子命令。
- **F-2.x 论文精读 / F-3.x 创新点拆解 / F-4.x 事实验证 / F-5.x 综述写作 / F-6.x 自评审 / F-7.x 量化验证**：`research.py` 的 R1–R6 及对应子命令。
- **三级信任 / 结论‑证据强绑定**（redesign D5）：合并版 `provenance` 的 fact/judgment 双轨 + `link_conclusion` 红线 + `check_binding_invariants` 审计。
- **异常恢复 / 量化验证**：`chaos.py` 故障注入 + `verify.py` + `evaluate.py`；`materials_snapshot` + `freezing` 提供冻结快照可复现路径。
- **可审计 / 可复现**：append-only `provenance.jsonl` / `conclusions.jsonl`，`snapshot` 写内容 `sha256`，全部零三方依赖（仅标准库）。

---

## 7. 测试验证

运行环境：受管 Python 3.13 + pytest 9.x，`PYTHONPATH=core`。

| 测试范围 | 来源 | 结果 |
|----------|------|------|
| leyon 基线 4 个测试文件（`test_provenance` / `test_recovery` / `test_repro` / `test_state`） | integ 自带 | 通过 |
| 三级信任模型（`test_novus_provenance.py`，迁入自 novus） | 迁入 | 通过 |
| 四源检索（`test_mike_litsearch.py`，迁入自 mike） | 迁入 | 通过 |
| 判断器（`test_novus_judge.py`，迁入自 novus） | 迁入 | 通过 |
| 异常检测（`test_novus_anomaly.py`，迁入自 novus） | 迁入 | 通过 |

**合计：137 项测试通过**（62 + 75）。

额外的导入冒烟与功能验证：
- 全部 20 个包模块可导入；`freezing` / `cli` 可导入且 `cli` 注册 19 个子命令（含 `freeze`）。
- `provenance` 三级逻辑实测：fact 可进结论、judgment 红线生效、`cite(judgment)` 输出可读、`EVIDENCE_KINDS` 含 15 型。

**已知限制**：
- **OBELiX 数据集未随 integ 分发**（仅 `data/literature.json` 与 `data/conductivity_raw.csv`）。因此 `freeze` 全链路 E2E（`prepare`/`commit`/`freeze_rule_based`）与 `network` 文献模式需要该数据集（`<root>/data/external/obelix/all.csv` 或仓库内那份），在 integ 内暂不可跑；默认 `bootstrap` 模式离线可用、仅依赖 CSV 列结构。
- novus 独立 `search` 命令未采纳（见第 3 节），故 `cli` 不含 `search` 子命令；联网检索请用 `search-papers`。

---

## 8. 如何运行

```bash
# 任意子命令（stdout 仅单个 JSON）
PYTHONPATH=core python -m paper_agent.cli plan --goal "..." --workflow research
PYTHONPATH=core python -m paper_agent.cli run-all --goal "..." --workflow materials
PYTHONPATH=core python -m paper_agent.cli search-papers --goal "..." --local
PYTHONPATH=core python -m paper_agent.cli freeze --goal "..." --prepare   # 需 OBELiX 数据

# 测试
PYTHONPATH=core python -m pytest tests/ -q
```

---

## 9. 后续迭代建议

1. **补齐 OBELiX 数据集**：将 `data/external/obelix/all.csv` 随 leyon 分发（或提供下载脚本），使 `freeze` 全链路可在 CI 中端到端验证。
2. **统一检索入口**：评估是否将 novus 联网腿的 `search()` 与 mike `search_papers()` 收敛为单一函数，减少两套相似 API 的维护成本（当前刻意并存以隔离风险）。
3. **materials_snapshot 切换机制**：在 `state` / `cli` 暴露显式开关，让调用方在默认 `materials` 与冻结快照版 `materials` 之间选择。
4. **CI 门槛**：将迁入的 novus/mike 测试纳入持续集成，保证后续改动不回退三级信任与检索语义。

# 数据来源声明

本项目**主线不联网**（读仓库内的冻结快照）；**增强线联网时只调元数据接口，
不抓论文全文**（版权红线）。全部数据为公开、可核对、带出处的真实素材。

## 数据源清单

| 来源 | 位置 | 说明 | 许可 / 署名 |
|---|---|---|---|
| **OBELiX 数据集**（数值来源） | `data/external/obelix/all.csv`（599 行快照） | 599 条已合成锂固态电解质材料，含**室温实验实测离子电导率**（S/cm）、化学组成、空间群、晶格参数；**每条带原始实验论文 DOI**（321 条另附 CIF） | **CC-BY-4.0**；Therrien, F. et al. (2025). *OBELiX: A Curated Dataset of Crystal Structures and Experimentally Measured Ionic Conductivities for Lithium Solid-State Electrolytes.* arXiv:2502.14234 |
| **Crossref**（文献腿，联网） | API `api.crossref.org/works` | 论文元数据（DOI / 标题 / 作者 / 年份 / 期刊）；**只取元数据，不取全文** | 公开接口；调用时带 `mailto` 进入 polite pool |
| **OpenAlex**（文献腿，联网） | API `api.openalex.org/works` | 同上，与 Crossref 互补（实测两者结果零重叠） | 公开接口，CC0 |
| 冻结输入快照 | `snapshots/snap-*/` | 数据腿 + 文献腿 + 判断批次；含逐文件 SHA-256 与聚合内容哈希 | 由本项目生成 |
| 演示语料（legacy 降级路径） | `data/literature.json`（5 篇） | 早期演示用文献卡片；**不再参与主线**，仅保留为离线降级路径与回归测试 | 真实 DOI，可回查 |
| 演示数据（legacy 降级路径） | `data/conductivity_raw.csv`（7 行） | 早期演示用带缺陷数据；**不再参与主线** | 见文件内 `as-reported` 标注 |
| 实验计算 | `experiments/arrhenius_rank.py` | 对清洗后数据的本地真实计算，零第三方依赖，无随机源 | 本项目原创代码 |

## OBELiX 数据的关键事实（探针实测，见 `docs/redesign-decisions.md` §8）

- 599 行中 **562 行**含可用数值（93.82%）
- **37 行**为**上界记法**（`<1E-10` / `<1E-8`）：**不作为可比数值参与排序**，
  但**不静默丢弃**——已登记于 `clean/excluded_rows.json` 留证
- DOI 覆盖率 **100%**（599/599），唯一 DOI **223** 个；抽样 10 个在 Crossref
  与 OpenAlex 均为 10/10 可解析
- `Family` 字段为**化学族**（43 个取值），其中 33 行为空，清洗时归入 `unknown`
- 数据源自带质量注记 136 条（如晶格参数与 CIF 不匹配、部分占据修正），
  清洗时标注为 `quality_flag` 但**不删除**，供人工复核

## 明确声明

- **不做论文全文批量抓取**（版权红线）。仅使用公开数据集的**元数据与数值**，
  以及数据集自带的 DOI 作为证据锚点。
- 结论 C1–C5 逐条绑定 `[EV-XXXX]` 证据锚点：事实级证据指向文件哈希或 DOI；
  判断级证据记录对象、裁决与理由（含被排除项），可被复核与反驳。
- **严禁伪造数据**：数值只能来自外部数据集原样搬运与本地确定性计算；
  模型不得生成任何数值进入计算链路。
- 早期 `data/literature.json` 与 `data/conductivity_raw.csv` 中所有数值均标注
  `as-reported`，仅用于演示与回归，**不得作为科研结论引用**。

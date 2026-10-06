# data/external/obelix — 外部数据源快照

本目录存放**外部公开数据集**的原始快照，供离线主线（无需联网）使用。

## OBELiX — 锂固态电解质实测离子电导率数据集

| 项 | 内容 |
|---|---|
| 文件 | `all.csv`（599 行，112 KB） |
| 来源 | `https://raw.githubusercontent.com/NRC-Mila/OBELiX/main/data/downloads/all.csv` |
| 仓库 | https://github.com/NRC-Mila/OBELiX |
| 获取日期 | 2026-10-02 |
| 许可 | **CC-BY-4.0** |
| 内容 | 599 条已合成锂固态电解质材料，含**室温实验实测离子电导率**（S/cm）、化学组成、空间群、晶格参数、每条对应的原始论文 DOI（321 条另附 CIF 结构） |

### 引用要求（CC-BY-4.0）

> Therrien, F., Abou Haibeh, J., Sharma, D., Hendley, R., Hernández-García, A., Sun, S.,
> Tchagang, A., Su, J., Huberman, S., Bengio, Y., Guo, H., & Shin, H. (2025).
> **OBELiX: A Curated Dataset of Crystal Structures and Experimentally Measured Ionic
> Conductivities for Lithium Solid-State Electrolytes.** arXiv:2502.14234.

### 已知数据特征（探针实测，见 `docs/redesign-decisions.md` §8）

- 599 行中 **562 行**有可用数值（93.82%）
- **37 行**为**上界记法**（`<1E-10` / `<1E-8`），不可作为数值参与排序，但必须登记留痕
- DOI 覆盖率 **100%**（599/599），唯一 DOI **223** 个
- `Family` 字段为**化学族**（43 个取值，如 NASICON / garnet / perovskites / argyrodites），其中 33 行为空
- 列名为**人类可读表头**（`Ionic conductivity (S cm-1)`），与第三方镜像的 snake_case 命名不同 → 读取层必须做列名归一

### 更新方式

数据为**固定快照**，不自动更新。需要刷新时手动重新下载并更新本文件的"获取日期"，
同时在 `docs/redesign-decisions.md` 记录变更（快照变更会影响复现基线）。

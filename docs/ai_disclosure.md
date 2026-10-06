# AI 工具使用边界声明（独立完成声明）

- 本项目被研究 / 被评审的 Agent（paper-agent 全部流程）均运行在
  **Agnes Harness（AGH）+ Agnes 模型**上：会话编排模型为 **Agnes 3.0 Flash**
  （`agnes-3.0-flash`，baseUrl `https://api.agnes-ai.cn/v1`；
  route 属账号级标识、随环境而变，故**不在材料中写死**，
  复验方式见下方「复验命令」）；
  模型调用仅限 Agnes 模型，密钥只存 `~/.agh` credential store 与 `.env`（gitignore，绝不入库）。
- **模型不参与科学结论生成**：所有数字均由本地确定性实验脚本（`experiments/arrhenius_rank.py`）
  与复现验证器（`core/paper_agent/verify.py`）产生；LLM 仅做工具编排与中文总结。
- 执行记录可追溯：真实 AGH 会话导出 `evidence/session-6139563e.jsonl`
  （**71 tool/call + 71 tool/result 严格配对，7 个 `sciret_*` 工具全部出现**，
  research 与 materials 两条工作流均跑到，涉 3 个 run 目录且均为 DONE），
  补充证据 `evidence/session-aa3929f6.jsonl`（13/13 配对）；
  每条工具调用另有 run 内 `toolcalls/` 与双账本（`events.jsonl` / `provenance.jsonl`）留痕。
  内容可用 `python evidence/verify_export.py <file>` 复核（逐行数、工具覆盖率、配对完整性）。
- 开发期使用 AI 辅助工具（如 Qoder）辅助编写代码。按赛事指南"独立完成"要求如实声明：
  - 核心逻辑、接口设计与合规审查由团队完成并负责；
  - AI 辅助产生的代码经人工审查、测试（**242/242 单测**，连跑 3 轮全绿
    + 端到端 + 故障用例 + 信任机制演示）后方可入库；
  - 开发期 AI 工具边界：**仅用于代码编写辅助与知识检索，不代替团队做设计决策**。

## 复验命令

```bash
# 1) provider / 模型可用性（输出 "✓ provider ... verified"）
<agnes.mjs> doctor provider --probe --profile <profile>

# 2) 执行证据内容真实性（不是只看文件是否存在）
python evidence/verify_export.py evidence/session-6139563e.jsonl

# 3) 全量单测
python -m unittest discover -s tests -t .
```


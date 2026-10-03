# AI 工具使用边界声明（独立完成声明）

- 本项目被研究 / 被评审的 Agent（paper-agent 全部流程）均运行在
  **Agnes Harness（AGH）+ Agnes 模型**上：会话编排模型为 **Agnes 3.0 Flash**
  （route `account-acct-60077bdf-…`，baseUrl `https://api.agnes-ai.cn/v1`）；
  模型调用仅限 Agnes 模型，密钥只存 `~/.agh` credential store 与 `.env`（gitignore，绝不入库）。
- **模型不参与科学结论生成**：所有数字均由本地确定性模块产生——实验脚本
  （`experiments/arrhenius_rank.py`）、复现验证器（`core/paper_agent/verify.py`），
  以及 research 工作流的本地解析/分析链（`pdfparse.py` / `analyze.py` /
  `factcheck.py` / `writing.py` / `review.py` / `evaluate.py`）；
  LLM 仅做工具编排与中文总结，**不产出文献内容与数值**。
- 执行记录可追溯：真实 AGH 会话导出 `evidence/session.jsonl`（首轮 10+10 条）与
  `evidence/session-full.jsonl`（两轮合计 **21 tool/call + 21 tool/result，7 个
  `sciret_*` 工具全部出现**），session id
  `agnes:local:local-dev:cli:workspace:05d7ffbf5caefe74`；每条工具调用另有 run 内
  `toolcalls/` 与双账本（`events.jsonl` / `provenance.jsonl`）留痕。
- 开发期使用 AI 辅助工具（如 Qoder）辅助编写代码。按赛事指南"独立完成"要求如实声明：
  - 核心逻辑、接口设计与合规审查由团队完成并负责；
  - AI 辅助产生的代码经人工审查、测试（**159/159 单测** + 端到端 + 故障用例 + PRD F-1~F-7 覆盖）后方可入库；
  - 开发期 AI 工具边界：**仅用于代码编写辅助与知识检索，不代替团队做设计决策**。

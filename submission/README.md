# 提交材料索引

| 材料 | 位置 | 状态 |
| --- | --- | --- |
| 项目说明（问题来源 / 目标 / 核心方法 / AGH 执行流程 / 模型名称版本 / 使用环节 / 调用方式 / 验证方法） | `项目说明.md` | ✅ 已就绪 |
| 可运行作品 | 仓库全量代码（`python + node`，零第三方依赖；一键验证见 README / HOW-TO-VERIFY.md） | ✅ 已就绪（单测 **164/164**，连跑 3 轮全绿） |
| 3–5 分钟演示视频 | 脚本：`演示视频脚本.md`（已按真实 run `run-20261004-094544-e4d553` 与真实证据校对）；成片上传后回填链接 | ⬜ 待录制 |
| 运行证据 | `../evidence/session-6139563e.jsonl`（1364 行；**71 次 tool/call + 71 次 tool/result 严格配对**；**7/7 `sciret_*` 工具全覆盖**；两条工作流 research+materials；涉 3 个 run 目录均真实存在且 DONE）；补充 `../evidence/session-aa3929f6.jsonl`（270 行，13/13 配对） | ✅ 已就绪 |
| 证据复核工具 | `../evidence/verify_export.py`（零依赖）。**复验命令**：`python evidence/verify_export.py evidence/session-6139563e.jsonl` —— 逐行解析 + 核对 call/result 配对 + 工具覆盖率，不只看文件是否存在 | ✅ 已就绪 |
| 审计交付包 | `bash audit-pack-template/build_audit_pack.sh <RUN_ID>` → `audit-pack/`（含 run 五件套 + 会话账本 + 复核脚本 + HOW-TO-VERIFY.md） | ✅ 已就绪（实测通过；`audit-pack/` 亦 gitignore，打包时随附） |
| 独立完成声明 | `../docs/ai_disclosure.md` | ✅ 已就绪 |
| 数据来源声明 | `../docs/sources.md` | ✅ 已就绪 |
| 公开发布内容（≥1 条） | GitHub 仓库公开 / 技术分享帖 | ⬜ 团队执行 |
| 分支推送 | `leyon` 分支（本地领先远端 8 个提交） | ⬜ 按用户要求**暂未推送**，需人工决定时机 |

## 打包前必做

- 🔴 `evidence/*.jsonl` 与 `audit-pack/` 均含**本机绝对路径**（`C:\Users\...`、`D:\workBubbyStore\...`），
  按红线不入 git；**开源发布前需人工审查 / 脱敏**。
- 建议交付包内附`evidence/verify_export.py`，让收件人能一键核对证据真伪。


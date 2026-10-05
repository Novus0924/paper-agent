# 提交材料索引

| 材料 | 位置 | 状态 |
| --- | --- | --- |
| 项目说明（问题来源 / 目标 / 核心方法 / AGH 执行流程 / 模型名称版本 / 使用环节 / 调用方式 / 验证方法） | `项目说明.md` | ✅ 已就绪 |
| 可运行作品 | 仓库全量代码（`python + node`，零第三方依赖；一键验证见 README） | ✅ 已就绪 |
| 3–5 分钟演示视频 | 脚本：`演示视频脚本.md`；成片上传后回填链接 | ⬜ 待录制 |
| 运行证据 | `../evidence/session-6139563e.jsonl`（1364 行；**71 次 tool/call + 71 次 tool/result 严格配对**；**7/7 `sciret_*` 工具全覆盖**；两条工作流 research+materials；涉 3 个 run 目录均真实存在且 DONE）；补充 `../evidence/session-aa3929f6.jsonl`（270 行，13/13 配对）。复核：`python _verify_export.py <file>` | ✅ 已就绪（`*.jsonl` 按红线不入 git，打包时从磁盘归集，发布前人工脱敏本机路径） |
| 独立完成声明 | `../docs/ai_disclosure.md` | ✅ 已就绪 |
| 数据来源声明 | `../docs/sources.md` | ✅ 已就绪 |
| 公开发布内容（≥1 条） | GitHub 仓库公开 / 技术分享帖 | ⬜ 团队执行 |

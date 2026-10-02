# tests package marker
#
# 单测强制离线：把 P1 文献检索来源钉在 local，避免 unittest 联网访问 arXiv。
# 好处：① 快；② 逐字节可复现；③ 与「阶段 4 闸门：无 skip 无失败」的离线要求一致。
#
# 需要跑真实在线检索时，显式覆盖本变量即可，例如：
#     paper-agent_LIT_SOURCE=arxiv RUN_ONLINE=1 python -m unittest -v
import os

os.environ.setdefault("paper-agent_LIT_SOURCE", "local")

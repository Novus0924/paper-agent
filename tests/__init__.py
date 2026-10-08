# tests package marker
#
# 离线契约：单测默认强制 lit_source=local（与 core/paper_agent/state.py 注释一致）。
# 没有这行时 default_lit_source() 返回 "auto"，test_recovery 用例 A 的
# attempt=2 会真实请求 arXiv —— 网络抖动会导致 degraded 断言随机失败（flaky）。
# 显式传参的用例（如 test_mike_litsearch 显式传 arxiv/auto）不受此默认值影响。
import os

os.environ.setdefault("paper-agent_LIT_SOURCE", "local")

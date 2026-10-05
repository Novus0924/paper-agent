"""校验 AGH 导出的会话账本（evidence/*.jsonl），确认证据真实、完整、可复核。

为什么需要它
------------
"文件存在"不等于"证据成立"。本脚本核对四件事：
  1. JSONL 每一行都能解析（坏行会让行数虚高）；
  2. tool/call 与 tool/result 靠 data.toolUseId **严格配对**（不靠顺序）；
  3. 7 个 sciret_* 插件工具的覆盖率与逐工具成功/失败数；
  4. 涉及的 run id，便于去 runs/ 目录交叉核对终态。

三个踩过的坑（写在这避免下次重踩）
--------------------------------
  1. 工具名位置不统一：tool/call 在 data.name，tool/result 在 **origin**
     （形如 "tool:sciret_plan"），data 里没有名字字段。
  2. 只有插件工具（走 Python CLI）才返回 data.structured.ok；
     内置工具的 structured 是 null，成败要看 data.isError。
     一律按 structured.ok 判定会把shell/todo/read 全判成失败。
  3. JSONL 里的 "kill_after_p2" 来自 tool_describe 返回的 **schema 枚举文本**，
     不是真实的故障注入执行记录。别把它当成 kill 证据。

用法
----
    python verify_export.py session-6139563e.jsonl
（零第三方依赖，标准库即可。路径用 Windows 形式；MSYS 的 /tmp 原生Python 读不到。）
"""
import json
import re
import sys
from collections import OrderedDict, Counter

path = sys.argv[1]

RUN_RE = re.compile(r"run-\d{8}-\d{6}-[0-9a-f]{6}")
TOOL_RE = re.compile(r"^tool:(.+)$")

calls = OrderedDict()      # toolUseId -> (name, seq, ts)
res_by_id = OrderedDict()  # toolUseId -> (name, seq, ok, exitCode, runids, chaos)
orphan_calls = []
orphan_results = []
bad_json = 0
total = 0
types = Counter()
runs_seen = Counter()
chaos_seen = Counter()
exit_seen = Counter()
tool_stat = OrderedDict()  # name -> [ok, fail]

with open(path, encoding="utf-8") as fh:
    for line in fh:
        line = line.strip()
        if not line:
            continue
        total += 1
        try:
            obj = json.loads(line)
        except Exception:
            bad_json += 1
            continue
        types[obj.get("type")] += 1
        t = obj.get("type")
        data = obj.get("data") or {}
        origin = obj.get("origin") or ""
        m = TOOL_RE.match(origin)
        rname = m.group(1) if m else None

        if t == "tool/call":
            tid = data.get("toolUseId")
            name = data.get("name") or rname or "(无名)"
            calls[tid] = (name, obj.get("seq"), obj.get("ts"))
        elif t == "tool/result":
            tid = data.get("toolUseId")
            st = data.get("structured") or {}
            # ⚠️ 只有插件工具（走 runCli）才返回 structured.ok；
            #    内置工具（shell/todo/read...）的 structured 是 null，
            #    它们的成败要看 isError，不能一律判fail。
            if "ok" in st:
                ok = bool(st.get("ok"))
            else:
                ok = not bool(data.get("isError"))
            st = data.get("structured") or {}
            blob = json.dumps(data, ensure_ascii=False)
            for r in RUN_RE.findall(blob):
                runs_seen[r] += 1
            for c in re.findall(r"kill_after_[a-z0-9]+", blob):
                chaos_seen[c] += 1
            ec = st.get("exitCode")
            if ec is not None:
                exit_seen[ec] += 1
            ok2 = st.get("ok")
            if ok2 is None:
                ok2 = not bool(data.get("isError"))
            res_by_id[tid] = (rname or "(无名)", obj.get("seq"), ok2, ec,
                              set(RUN_RE.findall(blob)))

# 配对
paired, failed = [], []
for tid, (cname, cseq, cts) in calls.items():
    if tid in res_by_id:
        rname, rseq, ok, ec, rruns = res_by_id[tid]
        rec = (cname, cseq, rseq, ok, ec, sorted(rruns))
        paired.append(rec)
        slot = tool_stat.setdefault(cname, [0, 0])
        if ok is True:
            slot[0] += 1
        else:
            slot[1] += 1
    else:
        orphan_calls.append((tid, cname, cseq))
for tid, r in res_by_id.items():
    if tid not in calls:
        orphan_results.append((tid, r[0], r[1]))

print("文件:", path)
print(f"总行数 {total} | JSON 解析失败 {bad_json}")
print(f"tool/call {types.get('tool/call')} | tool/result {types.get('tool/result')}")
print()
print("=== 配对 ===")
print(f"  成功配对 {len(paired)} | 孤立 call {len(orphan_calls)} | 孤立 result {len(orphan_results)}")
print()
print("=== 逐工具成功/失败（data.ok 判定）===")
plugin = [n for n in tool_stat if n.startswith("sciret_")]
ok_total = fail_total = 0
for n in sorted(tool_stat):
    o, f = tool_stat[n]
    ok_total += o
    fail_total += f
    tag = "★" if n.startswith("sciret_") else " "
    print(f"  {tag} {n:24} ok={o:3} fail={f:3}")
print()
print(f"★ 插件工具覆盖: {len(plugin)}/7 -> {sorted(plugin)}")
print(f"★ 插件调用合计: ok={sum(tool_stat[n][0] for n in plugin)} fail={sum(tool_stat[n][1] for n in plugin)}")
print(f"  全部工具: ok={ok_total} fail={fail_total}")
print()
print("=== run id 出现次数 ===")
for r, c in runs_seen.most_common():
    print(f"  {r}  ×{c}")
print()
print("=== 故障注入 ===")
print("  chaos:", dict(chaos_seen) or "无")
print("  exitCode:", dict(exit_seen))
print()
print("=== 失败调用明细（取前3 条错误文本）===")
shown = 0
for ln in open(path, encoding="utf-8"):
    obj = json.loads(ln)
    if obj.get("type") != "tool/result":
        continue
    st = obj.get("data", {}).get("structured") or {}
    ok = st.get("ok")
    if ok is None:
        ok = not bool(obj.get("data", {}).get("isError"))
    if ok:
        continue
    name = (obj.get("origin") or "?").replace("tool:", "")
    txt = json.dumps(obj.get("data", {}), ensure_ascii=False)
    err = st.get("stderr") or ""
    print(f"  [{name}] seq={obj.get('seq')} exit={st.get('exitCode')} {err[:150]}")
    shown += 1
    if shown >= 3:
        break

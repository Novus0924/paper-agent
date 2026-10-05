"""test_plugin_tools.py — AGH 插件层（JS 薄壳）的安全机制单元测试。

存在原因
--------
`docs/评审要点与证据对照映射.md` §4 承诺了"子进程最小权限：环境变量白名单，
绝不透传完整 `process.env`"这一条安全声明，并把
**本文件**列为复验入口。此前该文件缺失（承诺了未兑现的证据）。
2026-10-05 补上。

被测对象：`plugins/paper-agent-tools/index.mjs` 里的
- `validateRunId()`——run_id 路径穿越白名单（JS 侧，与 Python 侧同规则）
- `curatedEnv()` + `ENV_ALLOWLIST`——子进程环境变量白名单

为什么用"抽取源码 → 交给 node 实际执行"而不是正则匹配源码
-----------------------------------------------------------
正则只能证明"代码里写了这句话"，不能证明"这段代码真的这么 behaves"。
本测试把函数源码**原样**从 index.mjs 截取出来，在**干净环境**里用 node 实跑，
把返回值/抛错拿回来断言。行为变了测试就会红——这才是"复验"该有的强度。

Node 不可用时这些用例会 skip 而不是 fail（本项目 Python 核心是标准库，
但插件层是 JS，运行环境未必有 node）。
"""
import json
import os
import re
import subprocess
import sys
import unittest

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(_TEST_DIR, ".."))
PLUGIN = os.path.join(REPO_ROOT, "plugins", "paper-agent-tools", "index.mjs")


def _find_node():
    """找 node：优先 PATH，其次 Windows 常见安装位置。

    ⚠️ 不能用裸 `node -v` 判断本机装了什么版本——Bash 工具的 PATH 里
    WorkBuddy 托管运行时排在系统前面，会解析到 22.x 而不是系统 24.x。
    """
    from shutil import which
    p = which("node")
    if p:
        return p
    for cand in (r"C:\Program Files\nodejs\node.exe",
                 r"C:\Program Files (x86)\nodejs\node.exe"):
        if os.path.exists(cand):
            return cand
    return None


NODE = _find_node()


def _extract(src, start_marker, end_marker):
    """从源码里原样截取一段定义（含 start_marker 起、到 end_marker 前）。"""
    i = src.index(start_marker)
    j = src.index(end_marker, i)
    return src[i:j]


@unittest.skipIf(NODE is None, "node 不可用，跳过 JS 层行为测试")
class TestPluginRunIdWhitelist(unittest.TestCase):
    """validateRunId()：JS 侧 run_id 白名单，须与 Python 侧同规则。"""

    @classmethod
    def setUpClass(cls):
        with open(PLUGIN, encoding="utf-8") as fh:
            src = fh.read()
        snippet = _extract(src, "function validateRunId", "// ---------- spawn")
        script = snippet + """
const cases = [
  "run-20261003-120000-abc123", "run-test", "run-A_1-b",
  "../escape", "run-../../escape", "../../runs/x", "/abs/path",
  "C:/windows/tmp", "..\\\\escape", "run-x/../../y", "", " ", "run-a b",
  "run-..", "run-.", null, undefined, 123, {}, []
];
const out = {};
for (const c of cases) {
  out[String(c)] = validateRunId(c);
}
console.log(JSON.stringify(out));
"""
        cls.out = _run_node(script)

    def test_valid_ids_accepted(self):
        for rid in ("run-20261003-120000-abc123", "run-test", "run-A_1-b"):
            with self.subTest(rid=rid):
                self.assertTrue(self.out[rid], f"合法 run_id 被拒: {rid}")

    def test_traversal_and_absolute_rejected(self):
        for bad in ("../escape", "run-../../escape", "../../runs/x",
                    "/abs/path", "C:/windows/tmp", "..\\escape",
                    "run-x/../../y"):
            with self.subTest(bad=bad):
                self.assertFalse(self.out[bad], f"路径穿越未被拒: {bad}")

    def test_blank_and_dot_rejected(self):
        for bad in ("", " ", "run-a b", "run-..", "run-."):
            with self.subTest(bad=bad):
                self.assertFalse(self.out[bad], f"非法 run_id 被放行: {bad}")

    def test_non_string_rejected(self):
        # JS 侧靠 typeof 判定；Python 侧靠类型判定，两边都应拒非字符串
        for key in ("null", "undefined", "123", "[object Object]", ""):
            with self.subTest(key=key):
                if key in ("", "[object Object]"):
                    # 空串已在上一个用例覆盖；[object Object] 对应 {} 的 String()
                    if key == "[object Object]":
                        self.assertFalse(self.out[key])
                    continue
                self.assertFalse(self.out[key], f"非字符串被放行: {key}")


@unittest.skipIf(NODE is None, "node 不可用，跳过 JS 层行为测试")
class TestPluginEnvAllowlist(unittest.TestCase):
    """curatedEnv()：只透传白名单变量，绝不透传完整 process.env。"""

    @classmethod
    def setUpClass(cls):
        with open(PLUGIN, encoding="utf-8") as fh:
            src = fh.read()
        snippet = _extract(src, "const ENV_ALLOWLIST", "function curatedEnv")
        snippet += _extract(src, "function curatedEnv",
                            "// ---------- 运行期配置自检")
        # 往 process.env 里塞：1 个白名单变量 + 2 个绝不能外泄的敏感变量
        script = snippet + """
process.env["PATH"] = "/usr/bin";
process.env["paper-agent_PYTHON"] = "C:/fake/python.exe";
process.env["AGNES_API_KEY"] = "SECRET-should-never-leak";
process.env["OPENAI_API_KEY"] = "SECRET-openai-should-never-leak";
const env = curatedEnv("/proj/root");
console.log(JSON.stringify({
  keys: Object.keys(env).sort(),
  values: env,
}));
"""
        cls.res = _run_node(script)
        cls.keys = set(cls.res["keys"])

    def test_whitelist_vars_forwarded(self):
        self.assertIn("PATH", self.keys)
        self.assertIn("paper-agent_PYTHON", self.keys)

    def test_secrets_not_leaked(self):
        for k in ("AGNES_API_KEY", "OPENAI_API_KEY"):
            with self.subTest(k=k):
                self.assertNotIn(k, self.keys,
                                 f"敏感变量 {k} 被透传给子进程了！")

    def test_only_allowlist_plus_derived(self):
        """实际键集合必须**恰好**是白名单 ∪ {PYTHONPATH}。

        注意 `paper-agent_ROOT` 同时属于白名单与"派生键"（curatedEnv 会强制
        覆写它），所以它只算白名单成员，不要重复计入 derived——
        否则集合运算会把它误判成"多出来的变量"（本测试第一版就踩了这个）。
        """
        allowed = {
            "PATH", "PATHEXT", "SYSTEMROOT", "COMSPEC", "SYSTEMDRIVE", "WINDIR",
            "LANG", "LC_ALL", "TMP", "TEMP", "TMPDIR",
            "paper-agent_PYTHON", "paper-agent_ROOT", "paper-agent_LIT_SOURCE",
        }
        # curatedEnv 在白名单之外额外注入的键
        derived = {"PYTHONPATH"}
        self.assertEqual(
            self.keys - allowed, derived,
            f"出现了白名单与派生键之外的变量: {self.keys - allowed - derived}")
        # 不做"白名单必须全部出现"的反向断言——curatedEnv 只透传宿主里
        # **已定义**的白名单变量（process.env[k] !== undefined 才拷），
        # 宿主没设的（如类Linux 上的 SYSTEMDRIVE）本就不该出现。

    def test_root_is_forced_not_inherited(self):
        """paper-agent_ROOT 必须被强制设为传入的 root（防环境变量被污染）。"""
        self.assertEqual(self.res["values"]["paper-agent_ROOT"], "/proj/root")

    def test_pythonpath_points_to_core(self):
        """PYTHONPATH 必须指向 <root>/core——插件靠它找到 paper_agent 包。"""
        self.assertEqual(
            self.res["values"]["PYTHONPATH"].replace("\\", "/"),
            "/proj/root/core")


def _run_node(script):
    """跑一段 node 脚本，返回解析后的 JSON。"""
    proc = subprocess.run(
        [NODE, "--input-type=module", "-e", script],
        capture_output=True, text=True, timeout=60,
        # 干净环境：只留 node 自身运行必需的，避免宿主环境干扰断言
        env={"SYSTEMROOT": os.environ.get("SYSTEMROOT", "C:\\Windows"),
             "PATH": os.environ.get("PATH", "")},
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"node 执行失败 (rc={proc.returncode})\n"
            f"stdout: {proc.stdout}\nstderr: {proc.stderr}")
    out = proc.stdout.strip().splitlines()[-1]
    return json.loads(out)


if __name__ == "__main__":
    unittest.main(verbosity=2)

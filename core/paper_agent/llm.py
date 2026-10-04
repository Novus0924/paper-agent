"""llm.py — 模型客户端适配层（judge.py 的 ModelJudge 依赖它）。

## 实测结论：为什么这里没有 AGH 专用客户端

在本机（Windows，AGH 源码构建 `packages/cli/dist/local/agnes.mjs`，daemon 已运行）
实测了两条"从 Python 调模型"的路，**都不可用**，证据如下：

1. ``agh -p "<prompt>"``（打印模式）
   - 第一次：260s 超时（当时 daemon 未启动）
   - daemon 启动后重测：**150s 超时且无任何输出**
   - 结论：打印模式是**完整 agent 会话**，不是单次问答接口；非交互环境下会挂起。
2. ``agh serve model-api``
   - 会启动一个 ``http://127.0.0.1:4177`` 的易用界面；``/`` 返回中文 Web 控制台 HTML
   - ``/v1/models`` → 404、``POST /v1/chat/completions`` → 405、``/openapi.json`` → 404
   - 源码里的 RPC 契约走 ``_agnes/v1/...`` 命名空间（packages.* 等），未发现
     OpenAI 风格的补全路由
   - 结论：它是给人用的控制台，不是文档化的补全 API。

## 因此本项目对"模型从哪来"的立场（对应 redesign-decisions.md D10）

- **设计内的主路径是 AGH 会话内判断**：会话里的大模型读候选 → 自行推理 →
  调用插件工具把裁决写进快照。**这条路上 Python 不调用模型**，
  因此不受上述限制影响；`ModelJudge` 就是该数据契约的实现。
- **会话之外的自动化路径**（跑对比、批处理、CI）需要一个**标准的
  OpenAI 兼容端点**：``OpenAiChatClient``。它不绑定任何厂商，
  由使用者通过环境变量或参数提供 base_url / model / api_key。
- ``CallableClient`` 用于测试与自定义后端（注入任意函数）。

密钥处理：本模块不读取、不落盘任何密钥；``OpenAiChatClient`` 只使用调用方
传入的 ``api_key``（可来自环境变量）。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

ENV_BASE_URL = "PAPER_AGENT_LLM_BASE_URL"
ENV_MODEL = "PAPER_AGENT_LLM_MODEL"
ENV_API_KEY = "PAPER_AGENT_LLM_API_KEY"

DEFAULT_TIMEOUT = 90


class LlmError(RuntimeError):
    """模型调用失败（缺配置 / 网络异常 / 响应格式不符）。"""


def http_post_json(url: str, payload: dict, headers: dict,
                   timeout: int = DEFAULT_TIMEOUT) -> dict:
    """默认传输层：POST JSON 并解析响应（尊重 http(s)_proxy 环境变量）。"""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json",
                                          **headers})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
    return json.loads(body.decode("utf-8"))


class CallableClient:
    """把任意 ``fn(prompt) -> str`` 包成客户端（测试与自定义后端用）。"""

    def __init__(self, fn, name: str = "callable"):
        if fn is None:
            raise LlmError("CallableClient requires a function")
        self.fn = fn
        self.name = name

    def complete(self, prompt: str) -> str:
        return self.fn(prompt)


class OpenAiChatClient:
    """OpenAI 兼容 ``/chat/completions`` 客户端（标准库实现，不绑定厂商）。

    - ``base_url`` 形如 ``https://host/v1``（会拼 ``/chat/completions``）
    - ``transport(url, payload, headers, timeout) -> dict`` 可注入，便于离线测试
    - 温度固定 0，尽量减少同一 prompt 的随机性（判断仍不是逐字节可复现的，
      这正是快照冻结存在的原因）
    """

    def __init__(self, base_url: str, model: str, api_key: str = "",
                 timeout: int = DEFAULT_TIMEOUT, transport=None,
                 name: str = ""):
        base = (base_url or "").strip().rstrip("/")
        if not base:
            raise LlmError(f"{ENV_BASE_URL} (base_url) is required")
        if not (model or "").strip():
            raise LlmError(f"{ENV_MODEL} (model) is required")
        self.base_url = base
        self.model = model.strip()
        self.api_key = api_key or ""
        self.timeout = timeout
        self.transport = transport or http_post_json
        self.name = name or f"openai:{self.model}"

    @property
    def endpoint(self) -> str:
        return self.base_url + "/chat/completions"

    def complete(self, prompt: str) -> str:
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            data = self.transport(self.endpoint, payload, headers, self.timeout)
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:300]
            except Exception:
                pass
            raise LlmError(f"HTTP {e.code} from {self.endpoint}: {detail}") from e
        except Exception as e:
            raise LlmError(f"request failed: {type(e).__name__}: {e}") from e
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as e:
            raise LlmError(f"unexpected response shape: "
                           f"{json.dumps(data)[:300]}") from e


def auto_client() -> object | None:
    """按环境变量尽力构造客户端；缺配置则返回 None（调用方决定是否降级）。"""
    base = os.environ.get(ENV_BASE_URL, "").strip()
    model = os.environ.get(ENV_MODEL, "").strip()
    if not base or not model:
        return None
    try:
        return OpenAiChatClient(base, model,
                                api_key=os.environ.get(ENV_API_KEY, ""))
    except LlmError:
        return None

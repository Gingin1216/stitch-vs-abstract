"""看山工作台 LLM 调用封装（P2）。

三件事：
1. **结构化输出**：优先用 OpenAI 兼容的 `response_format=json_schema` 强约束字段，
   平台不支持时自动降级为「prompt 内约束 + 正则抠 JSON」，上层代码无感。
2. **Tool Calling 循环**：裁判 Agent 自主调用 P3 语义接口，循环直到模型给出终稿。
3. **容错**：超时/连接失败 → AGENT_TIMEOUT；字段不合规 → 重试 1 次后 AGENT_BAD_JSON
   （契约 §1）。
"""
from __future__ import annotations

import json
import os
import re

from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    OpenAI,
)

from errors import AGENT_BAD_JSON, AGENT_TIMEOUT, AgentError

# 契约 §1：>10s 即判超时。留 1s 余量给网络抖动，重试由本模块自己控制。
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "11"))

client = OpenAI(
    base_url=os.environ.get("LLM_BASE_URL", "http://localhost:9999/v1"),
    api_key=os.environ.get("LLM_API_KEY", "none"),
    timeout=LLM_TIMEOUT,
    max_retries=0,  # 重试策略由 chat_json 统一掌握，避免叠加等待超过契约上限
)
MODEL = os.getenv("LLM_MODEL", "default")
STRONG_MODEL = os.getenv("LLM_MODEL_STRONG", MODEL)
TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.8"))
# 裁判判分要可复现（P3 回归评测集靠它），默认比创作类低
JUDGE_TEMPERATURE = float(os.getenv("LLM_JUDGE_TEMPERATURE", "0.3"))

# 平台不支持 function calling 时置 0，裁判改用 prefetch 兜底（见 main.py）
TOOL_CALLING_SUPPORTED = os.getenv("TOOL_CALLING_SUPPORTED", "1") == "1"
# 平台不支持 json_schema 时置 0；运行期探测到不支持也会自动关掉
STRUCTURED_OUTPUT_SUPPORTED = os.getenv("STRUCTURED_OUTPUT_SUPPORTED", "1") == "1"

_UNSUPPORTED_HINTS = ("response_format", "json_schema", "json schema",
                      "unsupported", "not support")


def parse_json(text: str) -> dict:
    """从模型输出中抠出 JSON（容忍 ```json 围栏和首尾废话）。"""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise AgentError(AGENT_BAD_JSON, f"输出中找不到 JSON: {text[:100]}")
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise AgentError(AGENT_BAD_JSON, f"JSON 解析失败: {e}")


def _schema_unsupported(err: Exception) -> bool:
    """区分「平台不支持 json_schema」与「真的请求出错」。"""
    if not isinstance(err, APIStatusError) or err.status_code not in (400, 404, 422):
        return False
    text = str(err).lower()
    return any(h in text for h in _UNSUPPORTED_HINTS)


def _complete(model: str, messages: list, tools: list | None,
              schema: dict | None, temperature: float):
    """单次 completion 调用，顺带做 json_schema 能力探测与降级。"""
    global STRUCTURED_OUTPUT_SUPPORTED
    kwargs: dict = {"model": model, "messages": messages,
                    "temperature": temperature}
    if tools:
        kwargs["tools"] = tools
    use_schema = schema if (schema and STRUCTURED_OUTPUT_SUPPORTED) else None
    if use_schema:
        kwargs["response_format"] = use_schema
    try:
        return client.chat.completions.create(**kwargs)
    except (APITimeoutError, APIConnectionError) as e:
        raise AgentError(AGENT_TIMEOUT, f"LLM 调用超时/不可达: {e}")
    except APIError as e:
        if use_schema and _schema_unsupported(e):
            # 平台不吃 json_schema：永久降级，本次请求立刻用 prompt 约束重试
            STRUCTURED_OUTPUT_SUPPORTED = False
            kwargs.pop("response_format", None)
            try:
                return client.chat.completions.create(**kwargs)
            except (APITimeoutError, APIConnectionError) as e2:
                raise AgentError(AGENT_TIMEOUT, f"LLM 调用超时/不可达: {e2}")
            except APIError as e2:
                raise AgentError(AGENT_TIMEOUT, f"LLM 调用失败: {e2}")
        raise AgentError(AGENT_TIMEOUT, f"LLM 调用失败: {e}")


def chat_json(system: str, user: str, *, strong: bool = False,
              tools: list | None = None, tool_executor=None,
              required_keys: tuple = (), schema: dict | None = None,
              normalizer=None, trace: list | None = None,
              temperature: float | None = None, max_rounds: int = 4) -> dict:
    """带 tool calling 循环的结构化 JSON 对话。

    normalizer：schemas.normalize_*，返回夹到契约区间后的数据；抛 AgentError 则触发重试。
    trace：传入一个 list 时，按序记录模型发起的工具调用（用于 /agents/health 与演示取证）。
    """
    messages: list = [{"role": "system", "content": system},
                      {"role": "user", "content": user}]
    use_tools = tools if (tools and TOOL_CALLING_SUPPORTED) else None
    temp = TEMPERATURE if temperature is None else temperature
    last_err: AgentError | None = None

    for _attempt in range(2):  # 契约 §1：AGENT_BAD_JSON 重试 1 次
        try:
            for _ in range(max_rounds):
                resp = _complete(STRONG_MODEL if strong else MODEL, messages,
                                 use_tools, schema, temp)
                msg = resp.choices[0].message
                if msg.tool_calls and tool_executor:
                    messages.append(msg)
                    for tc in msg.tool_calls:
                        try:
                            args = json.loads(tc.function.arguments or "{}")
                        except json.JSONDecodeError:
                            args = {}
                        result = tool_executor(tc.function.name, args)
                        if trace is not None:
                            trace.append({"tool": tc.function.name,
                                          "arguments": args, "result": result})
                        messages.append({
                            "role": "tool", "tool_call_id": tc.id,
                            "content": json.dumps(result, ensure_ascii=False),
                        })
                    continue
                data = parse_json(msg.content or "")
                missing = [k for k in required_keys if k not in data]
                if missing:
                    raise AgentError(AGENT_BAD_JSON, f"缺字段: {missing}")
                return normalizer(data) if normalizer else data
            raise AgentError(AGENT_BAD_JSON, "tool 循环超限")
        except AgentError as e:
            last_err = e
            if e.code == AGENT_TIMEOUT:
                raise  # 超时重试没意义，直接交给引擎走兜底文案
            messages.append({"role": "user", "content":
                             f"上次输出不合规（{e.message}）。请严格按 schema "
                             "重新输出 JSON，不要输出任何解释文字。"})
    raise last_err or AgentError(AGENT_BAD_JSON, "未知解析失败")

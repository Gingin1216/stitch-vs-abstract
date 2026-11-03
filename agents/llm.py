"""看山工作台 LLM 调用封装（P2）：结构化输出 + tool calling 循环 + 重试。"""
from __future__ import annotations

import json
import os
import re

from openai import OpenAI

client = OpenAI(
    base_url=os.environ.get("LLM_BASE_URL", "http://localhost:9999/v1"),
    api_key=os.environ.get("LLM_API_KEY", "none"),
)
MODEL = os.getenv("LLM_MODEL", "default")
STRONG_MODEL = os.getenv("LLM_MODEL_STRONG", MODEL)
# 平台不支持 function calling 时置 0，裁判改用 prefetch 兜底（见 main.py）
TOOL_CALLING_SUPPORTED = os.getenv("TOOL_CALLING_SUPPORTED", "1") == "1"


class AgentError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def parse_json(text: str) -> dict:
    """从模型输出中抠出 JSON（容忍 ```json 围栏和首尾废话）。"""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise AgentError("AGENT_BAD_JSON", f"输出中找不到 JSON: {text[:100]}")
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise AgentError("AGENT_BAD_JSON", f"JSON 解析失败: {e}")


def chat_json(system: str, user: str, *, strong: bool = False,
              tools: list | None = None, tool_executor=None,
              required_keys: tuple = (), max_rounds: int = 4) -> dict:
    """带 tool calling 循环的 JSON 对话。输出不符合 schema 自动重试一次。"""
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": user}]
    use_tools = tools if (tools and TOOL_CALLING_SUPPORTED) else None
    last_err: Exception | None = None

    for attempt in range(2):  # 契约：AGENT_BAD_JSON 重试 1 次
        try:
            for _ in range(max_rounds):
                resp = client.chat.completions.create(
                    model=STRONG_MODEL if strong else MODEL,
                    messages=messages,
                    tools=use_tools or None,
                    temperature=0.8,
                )
                msg = resp.choices[0].message
                if msg.tool_calls and tool_executor:
                    messages.append(msg)
                    for tc in msg.tool_calls:
                        result = tool_executor(
                            tc.function.name, json.loads(tc.function.arguments))
                        messages.append({
                            "role": "tool", "tool_call_id": tc.id,
                            "content": json.dumps(result, ensure_ascii=False),
                        })
                    continue
                data = parse_json(msg.content or "")
                missing = [k for k in required_keys if k not in data]
                if missing:
                    raise AgentError("AGENT_BAD_JSON", f"缺字段: {missing}")
                return data
            raise AgentError("AGENT_BAD_JSON", "tool 循环超限")
        except AgentError as e:
            last_err = e
            messages.append({"role": "user", "content":
                             "上次输出不符合要求，请重新输出严格 JSON。"})
    raise last_err

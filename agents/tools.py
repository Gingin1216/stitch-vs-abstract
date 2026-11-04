"""Tool Calling 定义与执行器（P2）。

裁判 Agent 判抽象派时，必须通过 `get_semantic_jump` 调 P3 的跳度接口拿硬指标——
这是契约 §0 约定的 agentic 设计：Agent 自己决定何时取数，P2 不替它预估跳度。
`check_word_overlap` 作为可选工具，让裁判发现"换皮重复词"时能自行降分。
"""
from __future__ import annotations

import logging
import os
import time

import httpx

from errors import AGENT_TIMEOUT, AgentError

logger = logging.getLogger("agents.tools")  # handler 由 llm.py 在 import 时挂上

SEMANTIC_URL = os.getenv("SEMANTIC_URL", "http://localhost:8003")
# 工具调用是裁判链路的一环，必须快于契约 §1 的 10s 总预算
SEMANTIC_TIMEOUT = httpx.Timeout(float(os.getenv("SEMANTIC_TIMEOUT", "6")),
                                 connect=3.0)

# OpenAI 兼容的 tools 规范，看山工作台若支持 function calling 直接生效
JUMP_TOOL = {
    "type": "function",
    "function": {
        "name": "get_semantic_jump",
        "description": "计算候选词与当前句子的语义跳度。返回 distance(0-1 余弦距离) 与 jump_score(0-100)。评判抽象派操作前必须调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "sentence": {"type": "string", "description": "当前故事句子"},
                "word": {"type": "string", "description": "玩家选择的词"},
            },
            "required": ["sentence", "word"],
        },
    },
}

OVERLAP_TOOL = {
    "type": "function",
    "function": {
        "name": "check_word_overlap",
        "description": "检查所选词是否与历史已用词近义（换皮重复）。返回 is_duplicate / closest / similarity。怀疑玩家重复用词时调用，近义则应判低分。",
        "parameters": {
            "type": "object",
            "properties": {
                "word": {"type": "string", "description": "玩家选择的词"},
                "history": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "本局已用过的词",
                },
            },
            "required": ["word", "history"],
        },
    },
}

JUDGE_TOOLS = [JUMP_TOOL, OVERLAP_TOOL]


def _post(path: str, payload: dict) -> dict:
    t0 = time.monotonic()
    try:
        r = httpx.post(f"{SEMANTIC_URL}{path}", json=payload,
                       timeout=SEMANTIC_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        logger.info("semantic ok | %s elapsed=%.2fs", path,
                    time.monotonic() - t0)
        return data
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("semantic fail | %s elapsed=%.2fs err=%s", path,
                       time.monotonic() - t0, e)
        raise AgentError(AGENT_TIMEOUT, f"语义层 {path} 调用失败: {e}")


def execute_tool(name: str, args: dict) -> dict:
    """工具执行器：把 Agent 的工具调用转发给语义评估层。

    注意：工具失败不抛给模型以外的调用方——把错误塞回 tool 消息里，
    让裁判知道"跳度拿不到"并自行按保守策略评判，游戏不会因此中断（契约 §1 兜底原则）。
    """
    try:
        if name == "get_semantic_jump":
            sentence, word = args.get("sentence", ""), args.get("word", "")
            if not sentence or not word:
                return {"error": "sentence 与 word 均不能为空"}
            return _post("/semantic/jump", {"sentence": sentence, "word": word})
        if name == "check_word_overlap":
            history = [str(w) for w in (args.get("history") or [])]
            if not history:
                return {"is_duplicate": False, "closest": "", "similarity": 0.0}
            return _post("/semantic/similar", {
                "word": args.get("word", ""), "history": history,
                "threshold": 0.75,
            })
    except AgentError as e:
        return {"error": e.message,
                "hint": "语义层暂不可用，请按你的判断保守评分，jump_score 取 50"}
    return {"error": f"unknown tool: {name}"}


def prefetch_jump(sentence: str, word: str) -> dict:
    """兜底模式：平台不支持 function calling 时，P2 自己先取跳度再塞进 prompt。

    语义层也挂掉时返回中性值 50，保证裁判仍能出分（契约 §1 兜底原则）。
    """
    data = execute_tool("get_semantic_jump", {"sentence": sentence, "word": word})
    if "jump_score" not in data:
        return {"distance": None, "jump_score": 50, "degraded": True}
    return data

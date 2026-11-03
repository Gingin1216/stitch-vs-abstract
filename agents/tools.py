"""Tool Calling 定义与执行器（P2）。裁判 Agent 判抽象派时，通过工具调 P3 的跳度接口。"""
from __future__ import annotations

import json
import os

import httpx

SEMANTIC_URL = os.getenv("SEMANTIC_URL", "http://localhost:8003")

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


def execute_tool(name: str, args: dict) -> dict:
    """工具执行器：把 Agent 的工具调用转发给语义评估层。"""
    if name == "get_semantic_jump":
        r = httpx.post(f"{SEMANTIC_URL}/semantic/jump", json={
            "sentence": args["sentence"], "word": args["word"],
        }, timeout=10.0)
        r.raise_for_status()
        return r.json()
    return {"error": f"unknown tool: {name}"}


def prefetch_jump(sentence: str, word: str) -> dict:
    """兜底模式：平台不支持 function calling 时，引擎侧先算好跳度塞进 prompt。"""
    return execute_tool("get_semantic_jump", {"sentence": sentence, "word": word})

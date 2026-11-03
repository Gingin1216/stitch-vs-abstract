"""P1 对 P2 / P3 的 HTTP 客户端 + 兜底策略。任何 Agent 挂了游戏都要能继续。"""
from __future__ import annotations

import os
import random

import httpx

AGENTS_URL = os.getenv("AGENTS_URL", "http://localhost:8002")
SEMANTIC_URL = os.getenv("SEMANTIC_URL", "http://localhost:8003")
TIMEOUT = httpx.Timeout(12.0, connect=5.0)

FALLBACK_COMMENTS = [
    "裁判被这波操作震撼到说不出话。",
    "刘看山表示需要喝杯茶冷静一下。",
    "此操作的离谱程度已超出计量范围。",
]


class AgentError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _post(base: str, path: str, payload: dict) -> dict:
    try:
        r = httpx.post(base + path, json=payload, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise AgentError("AGENT_TIMEOUT", f"{path} 调用失败: {e}")


# ---------- P2 Agent 层 ----------

def opening() -> str:
    return _post(AGENTS_URL, "/agents/opening", {"theme": "daily"})["sentence"]


def deal(sentence: str, round_: int, used_words: list) -> list:
    data = _post(AGENTS_URL, "/agents/deal", {
        "sentence": sentence, "round": round_,
        "used_words": used_words, "zhihu_flavor": True,
    })
    cards = data.get("cards", [])
    levels = sorted(c.get("level", 1) for c in cards)
    if len(cards) != 5 or levels != [1, 1, 2, 2, 3]:
        # 契约 §2.2：梯度校验失败重试一次
        data = _post(AGENTS_URL, "/agents/deal", {
            "sentence": sentence, "round": round_,
            "used_words": used_words, "zhihu_flavor": True,
        })
        cards = data.get("cards", cards)
    return cards


def judge_abstract(sentence: str, word: str, level: int, round_: int) -> dict:
    try:
        return _post(AGENTS_URL, "/agents/judge_abstract", {
            "sentence": sentence, "picked_word": word,
            "word_level": level, "round": round_,
        })
    except AgentError:
        return {
            "jump_score": 50, "score": 50,
            "comment": random.choice(FALLBACK_COMMENTS),
            "collapse_delta": 15, "invalid_narrative": False,
            "sentence_after": f"{sentence}（{word}）",
        }


def judge_stitch(sentence_before: str, word: str) -> dict:
    try:
        res = _post(AGENTS_URL, "/agents/judge_stitch", {
            "sentence_before": sentence_before, "picked_word": word,
        })
        # 契约 §2.4：引擎按公式复核 score，防 AI 算术翻车
        res["score"] = min(100, res.get("logic", 5) * 4
                           + res.get("fluency", 5) * 3
                           + res.get("surprise", 5) * 3)
        return res
    except AgentError:
        return {
            "logic": 5, "fluency": 5, "surprise": 5, "score": 50,
            "comment": random.choice(FALLBACK_COMMENTS),
            "collapse_delta": -10,
            "sentence_after": f"{sentence_before}（{word}）",
        }


def rewrite(story: str) -> str:
    try:
        s = _post(AGENTS_URL, "/agents/rewrite", {"story": story})["sentence"]
        if len(s) > 30:  # 契约 §2.5：超长截断
            s = s[:30]
        return s
    except AgentError:
        return story[:30]


def commentary(rounds: list, winner: str, final_story: str) -> str:
    try:
        return _post(AGENTS_URL, "/agents/commentary", {
            "rounds": rounds, "winner": winner, "final_story": final_story,
        })["text"]
    except AgentError:
        return "解说员刘看山今日请假，比赛结果依然作数。"


# ---------- P3 语义评估层 ----------

def is_duplicate(word: str, history: list, threshold: float = 0.75) -> bool:
    if not history:
        return False
    try:
        return _post(SEMANTIC_URL, "/semantic/similar", {
            "word": word, "history": history, "threshold": threshold,
        }).get("is_duplicate", False)
    except AgentError:
        return word in history  # 语义层挂了退化为精确匹配

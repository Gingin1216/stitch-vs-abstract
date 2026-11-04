"""P1 对 P2 / P3 的 HTTP 客户端 + 兜底策略。任何 Agent 挂了游戏都要能继续。"""
from __future__ import annotations

import logging
import os
import random

import httpx

logger = logging.getLogger(__name__)

AGENTS_URL = os.getenv("AGENTS_URL", "http://localhost:8002")
SEMANTIC_URL = os.getenv("SEMANTIC_URL", "http://localhost:8003")
TIMEOUT = httpx.Timeout(float(os.getenv("ENGINE_TIMEOUT", "12")), connect=5.0)

# opening/deal 专用超时（8s）；其余调用仍用上面的 TIMEOUT（默认 12s）。
OPENING_DEAL_TIMEOUT = httpx.Timeout(8.0, connect=5.0)

# 写死兜底数据（契约 §2 示例）：Agent 层不可用时返回，保证游戏继续；无 prompt。
DEFAULT_OPENING = "我今天走进了一家便利店。"
DEFAULT_CARDS = [
    {"word": "关东煮", "level": 1, "tag": "日常"},
    {"word": "小票", "level": 1, "tag": "日常"},
    {"word": "量子力学", "level": 2, "tag": "抽象"},
    {"word": "谢邀", "level": 2, "tag": "知乎梗"},
    {"word": "秦始皇", "level": 3, "tag": "违禁"},
]

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

def opening(game_id: str | None = None) -> str:
    try:
        r = httpx.post(f"{AGENTS_URL}/agents/opening",
                       json={"theme": "daily"}, timeout=OPENING_DEAL_TIMEOUT)
        r.raise_for_status()
        return r.json()["sentence"]
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("opening 兜底: Agent 层调用失败 game_id=%s: %s", game_id, e)
        return DEFAULT_OPENING


def deal(sentence: str, round_: int, used_words: list, game_id: str | None = None) -> list:
    payload = {
        "sentence": sentence, "round": round_,
        "used_words": used_words, "zhihu_flavor": True,
    }

    def _fetch() -> list:
        r = httpx.post(f"{AGENTS_URL}/agents/deal", json=payload,
                       timeout=OPENING_DEAL_TIMEOUT)
        r.raise_for_status()
        return r.json().get("cards", [])

    try:
        cards = _fetch()
        if len(cards) != 5 or sorted(c.get("level", 1) for c in cards) != [1, 1, 2, 2, 3]:
            cards = _fetch()  # 契约 §2.2：梯度校验失败重试一次
        if len(cards) != 5 or sorted(c.get("level", 1) for c in cards) != [1, 1, 2, 2, 3]:
            # 契约 §2.2：重试仍不合格 → 离线词库（默认手牌）补位
            logger.warning("deal 兜底: 重试后梯度仍不合格 game_id=%s", game_id)
            return [dict(c) for c in DEFAULT_CARDS]
        return cards
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("deal 兜底: Agent 层调用失败 game_id=%s: %s", game_id, e)
        return [dict(c) for c in DEFAULT_CARDS]

    def _fetch() -> list:
        r = httpx.post(f"{AGENTS_URL}/agents/deal", json=payload,
                       timeout=OPENING_DEAL_TIMEOUT)
        r.raise_for_status()
        return r.json().get("cards", [])

    try:
        cards = _fetch()
        if len(cards) != 5 or sorted(c.get("level", 1) for c in cards) != [1, 1, 2, 2, 3]:
            cards = _fetch()  # 契约 §2.2：梯度校验失败重试一次
        if len(cards) != 5 or sorted(c.get("level", 1) for c in cards) != [1, 1, 2, 2, 3]:
            # 契约 §2.2：重试仍不合格 → 离线词库（默认手牌）补位
            logger.warning("deal 兜底: 重试后梯度仍不合格 game_id=%s", game_id)
            return [dict(c) for c in DEFAULT_CARDS]
        return cards
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("deal 兜底: Agent 层调用失败 game_id=%s: %s", game_id, e)
        return [dict(c) for c in DEFAULT_CARDS]


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

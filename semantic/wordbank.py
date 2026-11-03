"""词库离线预生成与清洗（P3）。

供 P2 发牌 Agent 兜底补位、违禁词/重复选词检测使用。纯逻辑，不依赖 game/prompt。

发牌 Agent 失败时，引擎用 sample_deal_cards() 从本模块维护的词库中随机抽出
固定梯度结构（2 日常 + 2 抽象 + 1 违禁），保证兜底牌面也符合 API.md §2.2 的梯度约束。
"""
from __future__ import annotations

import json
import random
from collections import Counter
from pathlib import Path

WORD_LEVELS = {1: "日常", 2: "抽象", 3: "违禁"}
DEAL_STRUCTURE = {1: 2, 2: 2, 3: 1}  # 每回合固定梯度：2 普通 + 2 抽象 + 1 违禁

DEFAULT_BANK = Path(__file__).with_name("wordbank.json")


def clean_cards(cards: list[dict]) -> list[dict]:
    """去重、规整、校验词卡。保证 word 唯一、level 合法，返回干净词库。"""
    seen: set[str] = set()
    cleaned: list[dict] = []
    for c in cards:
        word = (c.get("word") or "").strip()
        level = c.get("level")
        if not word or word in seen or level not in WORD_LEVELS:
            continue
        seen.add(word)
        cleaned.append(
            {"word": word, "level": level, "tag": (c.get("tag") or WORD_LEVELS[level]).strip()}
        )
    return cleaned


def load_wordbank(path: str | None = None) -> dict:
    raw = json.loads(Path(path or DEFAULT_BANK).read_text("utf-8"))
    raw["cards"] = clean_cards(raw.get("cards", []))
    return raw


def sample_deal_cards(
    cards: list[dict], seed: int = 0, exclude: list[str] | None = None
) -> list[dict]:
    """按梯度结构抽 5 张词卡：2 日常 + 2 抽象 + 1 违禁，排除已用词。"""
    exclude = {w.strip() for w in (exclude or [])}
    pools: dict[int, list[dict]] = {lv: [] for lv in DEAL_STRUCTURE}
    for c in cards:
        if c["word"] not in exclude:
            pools[c["level"]].append(c)
    rng = random.Random(seed)
    picked: list[dict] = []
    for lv, n in DEAL_STRUCTURE.items():
        if len(pools[lv]) < n:
            raise ValueError(f"词库「{WORD_LEVELS[lv]}」档不足 {n} 张，无法兜底发牌")
        picked.extend(rng.sample(pools[lv], n))
    return picked


def validate_deal(cards: list[dict]) -> bool:
    """校验一副牌是否符合 2/2/1 梯度结构（引擎补位校验用）。"""
    if len(cards) != 5 or len({c["word"] for c in cards}) != 5:
        return False
    return Counter(c["level"] for c in cards) == Counter(DEAL_STRUCTURE)


def is_forbidden(card: dict) -> bool:
    """违禁词检测：level==3 即违禁（高风险高收益，AI 可能判「叙述资格失效」）。"""
    return card.get("level") == 3
"""游戏状态与领域模型（P1）。纯逻辑，不依赖任何外部服务。"""
from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, field

TOTAL_ROUNDS = 5
COLLAPSE_START = 50
TURN_STATES = ("A_TURN", "B_TURN")

# 会话清理（惰性扫描，无后台线程）：活跃对局空闲超 GAME_TTL_SECONDS 删除；
# FINISHED 局单独保留 FINISHED_KEEP_SECONDS，供前端拉战报。
GAME_TTL_SECONDS = int(os.getenv("ENGINE_GAME_TTL", "1800"))
FINISHED_KEEP_SECONDS = 15 * 60


def clamp(v: int, lo: int = 0, hi: int = 100) -> int:
    return max(lo, min(hi, v))


def stitch_score(logic: int, fluency: int, surprise: int) -> int:
    """缝合派得分公式（契约 §2.4，引擎复核用）。"""
    return logic * 4 + fluency * 3 + surprise * 3


def sweep(games: dict, now: float | None = None) -> None:
    """惰性会话清理：每次请求时调用。超 TTL 的删除，存活对局刷新 last_active_at。"""
    if now is None:
        now = time.time()
    expired = [gid for gid, g in games.items()
               if now - g.last_active_at
               > (FINISHED_KEEP_SECONDS if g.state == "FINISHED" else GAME_TTL_SECONDS)]
    for gid in expired:
        del games[gid]
    for g in games.values():
        g.last_active_at = now


@dataclass
class Game:
    mode: str = "pvp"
    id: str = field(default_factory=lambda: "g_" + uuid.uuid4().hex[:6])
    round: int = 1
    state: str = "CREATED"
    sentence: str = ""
    collapse: int = COLLAPSE_START
    score_a: int = 0
    score_b: int = 0
    used_words: list = field(default_factory=list)
    cards: list = field(default_factory=list)
    history: list = field(default_factory=list)          # 每回合完整记录
    collapse_curve: list = field(default_factory=lambda: [COLLAPSE_START])
    commentary: str = ""
    last_active_at: float = field(default_factory=time.time)  # 会话清理：上次活跃时间
    _round_buf: dict = field(default_factory=dict)        # 当前回合的暂存（A/B 各半）

    @property
    def first(self) -> str:
        """奇数回合 A 先手，偶数回合 B 先手（交替先手平衡后手优势）。"""
        return "A" if self.round % 2 == 1 else "B"

    @property
    def expected_role(self) -> str | None:
        if self.state in TURN_STATES:
            return self.state[0]
        return None

    def verdict(self) -> str:
        if self.collapse > 70:
            return "世界被抽象毁灭"
        if self.collapse < 30:
            return "逻辑被强行缝合"
        return "半疯状态，平局"

    def winner(self) -> str:
        if self.collapse > 70:
            return "A"
        if self.collapse < 30:
            return "B"
        return "DRAW"

    def snapshot(self) -> dict:
        return {
            "game_id": self.id, "state": self.state, "round": self.round,
            "first": self.first, "sentence": self.sentence, "collapse": self.collapse,
            "score_a": self.score_a, "score_b": self.score_b,
            "cards": self.cards, "history": self.history,
            "collapse_curve": self.collapse_curve,
        }

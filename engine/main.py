"""游戏引擎 API（P1）。对前端暴露契约 §4 的接口。"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import clients
from state import Game, TOTAL_ROUNDS, TURN_STATES, clamp

app = FastAPI(title="崩坏缝合局 · 游戏引擎")
GAMES: dict[str, Game] = {}


class CreateReq(BaseModel):
    mode: str = "pvp"  # pvp 双人同屏 | pve 人机（B 位 AI 扮演缝合大师）


class PickReq(BaseModel):
    role: str
    word: str


def err(code: str, msg: str, status: int = 409):
    raise HTTPException(status, {"error": {"code": code, "message": msg, "retryable": code == "AGENT_TIMEOUT"}})


def _get(game_id: str) -> Game:
    g = GAMES.get(game_id)
    if not g:
        err("NOT_FOUND", "对局不存在", 404)
    return g


def _start_round(g: Game):
    g.cards = clients.deal(g.sentence, g.round, g.used_words)
    g.state = f"{g.first}_TURN"
    g._round_buf = {"round": g.round}
    if g.mode == "pve" and g.first == "B":
        _auto_b(g)


def _auto_b(g: Game):
    """PVE 模式：AI 缝合大师选最普通的词（level 最小），稳中求胜。"""
    card = min(g.cards, key=lambda c: c["level"])
    _apply_pick(g, "B", card["word"])


def _apply_pick(g: Game, role: str, word: str) -> dict:
    level = next((c["level"] for c in g.cards if c["word"] == word), 1)
    if role == "A":
        j = clients.judge_abstract(g.sentence, word, level, g.round)
        g.score_a += j["score"]
        g._round_buf.update(a_word=word, a_score=j["score"], a_comment=j["comment"])
    else:
        j = clients.judge_stitch(g.sentence, word)
        g.score_b += j["score"]
        g._round_buf.update(b_word=word, b_score=j["score"], b_comment=j["comment"])
    g.sentence = j.get("sentence_after") or g.sentence
    g.collapse = clamp(g.collapse + int(j.get("collapse_delta", 0)))
    g.used_words.append(word)
    return j


def _end_round(g: Game):
    g.sentence = clients.rewrite(g.sentence)
    g.history.append(dict(g._round_buf, sentence=g.sentence, collapse=g.collapse))
    g.collapse_curve.append(g.collapse)
    if g.round >= TOTAL_ROUNDS:
        g.state = "FINISHED"
        g.commentary = clients.commentary(g.history, g.winner(), g.sentence)
    else:
        g.round += 1
        _start_round(g)


@app.post("/api/game")
def create_game(req: CreateReq):
    g = Game(mode=req.mode)
    g.sentence = clients.opening()
    GAMES[g.id] = g
    _start_round(g)
    return g.snapshot()


@app.get("/api/game/{game_id}")
def get_game(game_id: str):
    return _get(game_id).snapshot()


@app.post("/api/game/{game_id}/pick")
def pick(game_id: str, req: PickReq):
    g = _get(game_id)
    if g.state not in TURN_STATES or req.role != g.expected_role:
        err("INVALID_STATE", f"当前状态 {g.state} 不允许 {req.role} 选词")
    if req.word not in [c["word"] for c in g.cards]:
        err("INVALID_STATE", "所选词不在本回合词卡中")
    if clients.is_duplicate(req.word, g.used_words):
        err("WORD_DUPLICATE", "该词与历史选词重复或近义，请换一张")

    j = _apply_pick(g, req.role, req.word)
    second = "B" if g.first == "A" else "A"

    if req.role == g.first:
        g.state = f"{second}_TURN"
        if g.mode == "pve" and second == "B":
            _auto_b(g)
            _end_round(g)
    else:
        _end_round(g)

    snap = g.snapshot()
    snap["judge"] = {"score": j["score"], "comment": j.get("comment", ""),
                     "detail": {k: v for k, v in j.items()
                                if k not in ("score", "comment", "sentence_after", "collapse_delta")}}
    return snap


@app.get("/api/game/{game_id}/report")
def report(game_id: str):
    g = _get(game_id)
    if g.state != "FINISHED":
        err("INVALID_STATE", "对局尚未结束")
    a_plays = [(h.get("a_score", 0), h.get("a_word", "")) for h in g.history]
    b_comments = [(h.get("b_score", 0), h.get("b_comment", "")) for h in g.history]
    mvp_word = max(a_plays)[1] if a_plays else ""
    best_comment = max(b_comments)[1] if b_comments else ""
    return {
        "winner": g.winner(), "verdict": g.verdict(),
        "final_story": g.sentence, "collapse_curve": g.collapse_curve,
        "score_a": g.score_a, "score_b": g.score_b,
        "commentary": g.commentary,
        "poster": {"title": "崩坏缝合局 · 战报", "mvp_word": mvp_word,
                   "best_comment": best_comment},
    }

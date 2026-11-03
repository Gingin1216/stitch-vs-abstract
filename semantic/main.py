"""语义评估服务（P3）：跳度计算 + 近义检测。

对外只暴露 API.md §3 的两个接口，不知道游戏存在。
Embedding 失败统一走 API.md §1 的错误结构。
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from embeddings import (
    EmbeddingTimeout,
    EmbeddingUnavailable,
    cosine_distance,
    cosine_similarity,
    embed,
    to_jump,
)

app = FastAPI(title="崩坏缝合局 · 语义评估层", version="1.1")


class JumpReq(BaseModel):
    sentence: str = Field(..., min_length=1)
    word: str = Field(..., min_length=1)


class SimilarReq(BaseModel):
    word: str = Field(..., min_length=1)
    history: list[str] = Field(default_factory=list)
    threshold: float = Field(default=0.75, ge=0.0, le=1.0)


def _error(code: str, message: str, retryable: bool, status: int = 503) -> JSONResponse:
    """API.md §1 统一错误结构。"""
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "retryable": retryable}},
    )


@app.post("/semantic/jump")
def jump(req: JumpReq):
    try:
        v_word = embed(req.word)
        v_sentence = embed(req.sentence)
    except EmbeddingTimeout:
        return _error("AGENT_TIMEOUT", "Embedding 语义服务响应超时", True)
    except EmbeddingUnavailable:
        return _error("AGENT_TIMEOUT", "Embedding 语义服务不可用", True)
    d = cosine_distance(v_word, v_sentence)
    return {"distance": round(d, 4), "jump_score": to_jump(d)}


@app.post("/semantic/similar")
def similar(req: SimilarReq):
    try:
        v_word = embed(req.word)
        vecs = [(h, embed(h)) for h in req.history]
    except EmbeddingTimeout:
        return _error("AGENT_TIMEOUT", "Embedding 语义服务响应超时", True)
    except EmbeddingUnavailable:
        return _error("AGENT_TIMEOUT", "Embedding 语义服务不可用", True)
    best, best_sim = "", 0.0
    for h, v in vecs:
        s = cosine_similarity(v_word, v)
        if s > best_sim:
            best, best_sim = h, s
    return {
        "is_duplicate": best_sim >= req.threshold,
        "closest": best,
        "similarity": round(best_sim, 4),
    }
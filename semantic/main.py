"""语义评估服务（P3）：跳度计算 + 近义检测。"""
from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from embeddings import cosine_distance, embed, to_jump

app = FastAPI(title="崩坏缝合局 · 语义评估层")


class JumpReq(BaseModel):
    sentence: str
    word: str


class SimilarReq(BaseModel):
    word: str
    history: list[str]
    threshold: float = 0.75


@app.post("/semantic/jump")
def jump(req: JumpReq):
    d = cosine_distance(embed(req.word), embed(req.sentence))
    return {"distance": round(d, 4), "jump_score": to_jump(d)}


@app.post("/semantic/similar")
def similar(req: SimilarReq):
    w = embed(req.word)
    best, best_sim = "", 0.0
    for h in req.history:
        sim = 1.0 - cosine_distance(w, embed(h))
        if sim > best_sim:
            best, best_sim = h, sim
    return {"is_duplicate": best_sim >= req.threshold,
            "closest": best, "similarity": round(best_sim, 4)}

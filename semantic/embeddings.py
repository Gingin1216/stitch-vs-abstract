"""Embedding 获取与跳度映射（P3 核心资产：映射公式归本模块所有）。"""
from __future__ import annotations

import hashlib
import os

import numpy as np
from openai import OpenAI

client = OpenAI(
    base_url=os.environ.get("LLM_BASE_URL", "http://localhost:9999/v1"),
    api_key=os.environ.get("LLM_API_KEY", "none"),
)
EMBED_MODEL = os.getenv("EMBED_MODEL", "text-embedding-3-small")
# 离线兜底：无可用 embedding 服务时用确定性伪向量打通链路（无语义，仅供 MOCK 联调）
OFFLINE_FALLBACK = os.getenv("EMBED_OFFLINE", "1") == "1"

_cache: dict[str, np.ndarray] = {}

# 校准区间：语义相关词对的余弦距离约 0.30~0.45，完全无关约 0.75~0.95。
# 换 embedding 模型后必须用 tests/calibrate.py 思路重新标定这两个值。
CALIB_LO, CALIB_HI = 0.30, 0.90


def _hash_embed(text: str, dim: int = 256) -> np.ndarray:
    vec = np.zeros(dim)
    for i, ch in enumerate(text):
        h = int(hashlib.md5(f"{ch}{i}".encode()).hexdigest(), 16)
        vec[h % dim] += 1.0
    norm = np.linalg.norm(vec)
    return vec / norm if norm > 0 else vec


def embed(text: str) -> np.ndarray:
    if text in _cache:
        return _cache[text]
    try:
        resp = client.embeddings.create(model=EMBED_MODEL, input=text)
        vec = np.array(resp.data[0].embedding, dtype=float)
    except Exception:
        if not OFFLINE_FALLBACK:
            raise
        vec = _hash_embed(text)
    _cache[text] = vec
    return vec


def cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 1.0
    return float(1.0 - np.dot(a, b) / (na * nb))


def to_jump(distance: float) -> int:
    """余弦距离 → 0-100 跳度分（归一化线性映射，公式所有权归 P3）。"""
    x = (distance - CALIB_LO) / (CALIB_HI - CALIB_LO)
    return int(round(max(0.0, min(1.0, x)) * 100))

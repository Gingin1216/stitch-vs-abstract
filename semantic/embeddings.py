"""Embedding 获取与跳度映射（P3 核心资产）。

本模块是 P3「硬指标」的唯一来源：`to_jump` 的映射公式所有权归这里，保证
可解释、可复现 —— 不借助 LLM 打分。

离线兜底策略：
- 未配置 LLM_API_KEY（或为 "none"）→ 直接用确定性伪向量，零网络请求，服务秒起。
- 配置了 Key 但 Embedding 接口超时/失败 → 依据 EMBED_OFFLINE 决定降级还是抛错。
  抛错会由 main.py 转成 API.md §1 的 AGENT_TIMEOUT 结构。
"""
from __future__ import annotations

import hashlib
import os

import numpy as np

EMBED_MODEL = os.getenv("EMBED_MODEL", "text-embedding-3-small")
EMBED_TIMEOUT = float(os.getenv("EMBED_TIMEOUT", "10"))
_API_KEY = (os.getenv("LLM_API_KEY") or "").strip()
# 是否配置了真实可用的 Key（排除了示例里的 none 占位）
HAS_KEY = bool(_API_KEY) and _API_KEY.lower() != "none"
# EMBED_OFFLINE=1（默认）：异常时降级到伪向量；=0 时异常上抛，由服务返回统一错误结构。
OFFLINE_FALLBACK = os.getenv("EMBED_OFFLINE", "1") == "1"

# 校准区间：语义相关词对的余弦距离约 0.30~0.45，完全无关约 0.75~0.95。
# 更换 embedding 模型后，请用几组已知「相关 / 无关」词对重新标定这两个常量。
# 伪向量模式下只能用字符重叠近似语义，映射仍可跑通但精度下降（详见 to_jump 说明）。
CALIB_LO, CALIB_HI = 0.30, 0.90

_cache: dict[str, np.ndarray] = {}
_CACHE_MAX = 10_000
_client = None


class EmbeddingTimeout(Exception):
    """Embedding 接口超时。"""


class EmbeddingUnavailable(Exception):
    """Embedding 接口不可用（连接失败 / 其他异常）。"""


def _shingles(text: str):
    """单字 shingle：中文单字即携带语义，字符重叠近似语义（近义词常共享字根）。"""
    for ch in text or "":
        yield ch


def _hash_embed(text: str, dim: int = 256) -> np.ndarray:
    """确定性伪向量：对单字做哈希入桶后 L2 归一化。无语义，仅字符重叠提供弱相似信号。

    离线兜底（Mock 模式）必需：无 Key 时保证 http 链路可跑、near-dup 检测仍有
    字符级近似（如「米粉 / 米线」共享「米」）。
    """
    vec = np.zeros(dim, dtype=np.float64)
    for shingle in _shingles(text):
        h = int(hashlib.md5(shingle.encode("utf-8")).hexdigest(), 16)
        vec[h % dim] += 1.0
    norm = float(np.linalg.norm(vec))
    return vec / norm if norm > 0 else vec


def _get_client():
    """惰性构建 OpenAI 客户端：离线模式不 import openai，也不产生网络连接。"""
    global _client
    if _client is None:
        import openai

        _client = openai.OpenAI(
            base_url=os.getenv("LLM_BASE_URL", "http://localhost:9999/v1"),
            api_key=_API_KEY or "none",
            timeout=EMBED_TIMEOUT,
        )
    return _client


def _embed_real(text: str) -> np.ndarray:
    import openai

    try:
        resp = _get_client().embeddings.create(model=EMBED_MODEL, input=text)
        return np.array(resp.data[0].embedding, dtype=float)
    except (openai.APITimeoutError, TimeoutError) as e:
        raise EmbeddingTimeout(f"embedding 超时(>{EMBED_TIMEOUT}s)") from e
    except (openai.APIConnectionError, OSError) as e:
        raise EmbeddingUnavailable(f"embedding 连接失败: {e}") from e
    except Exception as e:  # 其余视为不可用
        raise EmbeddingUnavailable(f"embedding 失败: {e}") from e


def embed(text: str) -> np.ndarray:
    """取 embedding：真实模式调 API，无 Key / 失败时按策略降级伪向量。"""
    if text in _cache:
        return _cache[text]
    if HAS_KEY:
        try:
            vec = _embed_real(text)
        except (EmbeddingTimeout, EmbeddingUnavailable):
            if not OFFLINE_FALLBACK:
                raise
            vec = _hash_embed(text)
    else:
        vec = _hash_embed(text)
    if len(_cache) >= _CACHE_MAX:
        _cache.clear()
    _cache[text] = vec
    return vec


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    return float(1.0 - cosine_similarity(a, b))


def to_jump(distance: float) -> int:
    """余弦距离 → 0-100 跳度分（映射公式所有权归 P3）。

    设计依据：
    1. 单调性 —— 词与句子越不相关，distance 越大，跳度越高，直接单调映射，杜绝黑箱。
    2. 归一化 —— 用实测校准的 CALIB_LO / CALIB_HI 两档常量：
       distance ≤ CALIB_LO 视为「相关」(跳度 0)，distance ≥ CALIB_HI 视为「完全不相关」(跳度 100)，
       中间线性插值。
    3. 线性 + 截断 —— 分数可复现、可解释，PPT 可写「基于向量语义空间的跳度量化」，
       而非「AI 随便给分」。
    """
    x = (float(distance) - CALIB_LO) / (CALIB_HI - CALIB_LO)
    return int(round(max(0.0, min(1.0, x)) * 100))
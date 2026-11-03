"""各 Agent 的 JSON Schema 与输出规范化（P2）。

职责划分：
- `*_SCHEMA`：给 LLM 的结构化输出约束（OpenAI `response_format=json_schema`），
  平台不支持时 llm.py 会自动降级为 prompt 内约束，两条路径共用同一份字段定义。
- `normalize_*`：服务侧的"最后一道闸"，把模型输出夹到 API.md §2 的取值范围内。
  引擎（P1）仍会按契约复核，这里只保证 P2 永远不往下游吐越界/缺字段的数据。
"""
from __future__ import annotations

from errors import AGENT_BAD_JSON, AgentError

MAX_SENTENCE = 40      # 契约 §2.3 / §2.4：sentence_after ≤40 字
MAX_REWRITE = 30       # 契约 §2.5：压缩句 ≤30 字
MAX_COMMENT = 40       # prompt 约定：点评 ≤40 字
MAX_COMMENTARY = 200   # prompt 约定：解说 ≤200 字
VALID_TAGS = ("日常", "抽象", "知乎梗", "违禁")
LEVEL_GRADIENT = [1, 1, 2, 2, 3]  # 契约 §2.2：2 普通 + 2 抽象 + 1 违禁


def _schema(name: str, properties: dict) -> dict:
    """包装成 OpenAI json_schema 格式（strict：禁止多余字段、全字段必填）。"""
    return {
        "type": "json_schema",
        "json_schema": {
            "name": name,
            "strict": True,
            "schema": {
                "type": "object",
                "properties": properties,
                "required": list(properties),
                "additionalProperties": False,
            },
        },
    }


_INT_0_100 = {"type": "integer", "minimum": 0, "maximum": 100}
_INT_0_10 = {"type": "integer", "minimum": 0, "maximum": 10}

OPENING_SCHEMA = _schema("opening", {"sentence": {"type": "string"}})

DEAL_SCHEMA = _schema("deal", {
    "cards": {
        "type": "array",
        "minItems": 5,
        "maxItems": 5,
        "items": {
            "type": "object",
            "properties": {
                "word": {"type": "string"},
                "level": {"type": "integer", "enum": [1, 2, 3]},
                "tag": {"type": "string", "enum": list(VALID_TAGS)},
            },
            "required": ["word", "level", "tag"],
            "additionalProperties": False,
        },
    },
})

JUDGE_ABSTRACT_SCHEMA = _schema("judge_abstract", {
    "jump_score": _INT_0_100,
    "score": _INT_0_100,
    "comment": {"type": "string"},
    "collapse_delta": {"type": "integer", "minimum": 0, "maximum": 30},
    "invalid_narrative": {"type": "boolean"},
    "sentence_after": {"type": "string"},
})

JUDGE_STITCH_SCHEMA = _schema("judge_stitch", {
    "logic": _INT_0_10,
    "fluency": _INT_0_10,
    "surprise": _INT_0_10,
    "comment": {"type": "string"},
    "collapse_delta": {"type": "integer", "minimum": -30, "maximum": 0},
    "sentence_after": {"type": "string"},
})

REWRITE_SCHEMA = _schema("rewrite", {"sentence": {"type": "string"}})

COMMENTARY_SCHEMA = _schema("commentary", {"text": {"type": "string"}})


# ---------- 通用强制器 ----------

def _as_int(data: dict, key: str, default: int, lo: int, hi: int) -> int:
    """模型常把分数写成 "88" 或 88.0，统一转 int 再夹到区间。"""
    raw = data.get(key, default)
    try:
        value = int(round(float(raw)))
    except (TypeError, ValueError):
        value = default
    return max(lo, min(hi, value))


def _as_text(data: dict, key: str, limit: int, default: str = "") -> str:
    text = data.get(key)
    if not isinstance(text, str) or not text.strip():
        text = default
    return text.strip()[:limit]


def require(data: dict, keys: tuple) -> dict:
    """字段缺失直接报 AGENT_BAD_JSON，交给 llm.chat_json 的重试逻辑。"""
    if not isinstance(data, dict):
        raise AgentError(AGENT_BAD_JSON, f"期望 JSON 对象，实得 {type(data).__name__}")
    missing = [k for k in keys if k not in data or data[k] is None]
    if missing:
        raise AgentError(AGENT_BAD_JSON, f"缺字段: {missing}")
    return data


# ---------- 各接口规范化 ----------

def normalize_opening(data: dict) -> dict:
    require(data, ("sentence",))
    sentence = _as_text(data, "sentence", 20)
    if not sentence:
        raise AgentError(AGENT_BAD_JSON, "开局句为空")
    return {"sentence": sentence}


def normalize_deal(data: dict, used_words: list | None = None) -> dict:
    """校验 5 张词卡 + 梯度 [1,1,2,2,3]；只是标签错位则原地修正，缺卡才重试。"""
    require(data, ("cards",))
    raw = data["cards"]
    if not isinstance(raw, list):
        raise AgentError(AGENT_BAD_JSON, "cards 不是数组")

    used = {w for w in (used_words or []) if isinstance(w, str)}
    cards, seen = [], set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        word = str(item.get("word", "")).strip()
        if not word or word in seen or word in used:
            continue  # 契约 §2.2：不得与 used_words 重复，组内也不许自重复
        seen.add(word)
        level = item.get("level", 1)
        try:
            level = int(level)
        except (TypeError, ValueError):
            level = 1
        tag = item.get("tag") if item.get("tag") in VALID_TAGS else None
        cards.append({"word": word, "level": min(3, max(1, level)), "tag": tag})

    if len(cards) != 5:
        raise AgentError(AGENT_BAD_JSON,
                         f"词卡需恰好 5 张去重且未用过的词，实得 {len(cards)} 张")

    if sorted(c["level"] for c in cards) != LEVEL_GRADIENT:
        # 词本身可用，只是抽象度标注跑偏：按模型给出的 level 排序后重贴梯度
        cards.sort(key=lambda c: c["level"])
        for card, level in zip(cards, LEVEL_GRADIENT):
            card["level"] = level
            card["tag"] = None  # 原 tag 可能与新 level 矛盾，交由下方兜底重填

    default_tag = {1: "日常", 2: "抽象", 3: "违禁"}
    for card in cards:
        if card["tag"] is None or (card["level"] == 3 and card["tag"] != "违禁"):
            card["tag"] = default_tag[card["level"]]
    return {"cards": cards}


def normalize_judge_abstract(data: dict, jump_score: int | None = None) -> dict:
    """抽象派判卷：jump_score 只认工具/预取值，模型自估一律覆盖（契约 §2.3）。"""
    require(data, ("score", "comment", "collapse_delta",
                   "invalid_narrative", "sentence_after"))
    jump = (jump_score if jump_score is not None
            else _as_int(data, "jump_score", 50, 0, 100))
    invalid = bool(data.get("invalid_narrative"))
    out = {
        "jump_score": max(0, min(100, int(jump))),
        "score": 0 if invalid else _as_int(data, "score", jump, 0, 100),
        "comment": _as_text(data, "comment", MAX_COMMENT, "裁判沉默了三秒。"),
        # 契约 §2.3：判定失去叙述资格时固定 +5，否则限制在 8~30
        "collapse_delta": 5 if invalid else _as_int(data, "collapse_delta",
                                                    round(jump * 0.3), 8, 30),
        "invalid_narrative": invalid,
        "sentence_after": _as_text(data, "sentence_after", MAX_SENTENCE),
    }
    if not out["sentence_after"]:
        raise AgentError(AGENT_BAD_JSON, "sentence_after 为空")
    return out


def normalize_judge_stitch(data: dict) -> dict:
    """缝合派判卷：三维度 0-10，score 按契约 §2.4 公式由服务侧算（引擎再复核）。"""
    require(data, ("logic", "fluency", "surprise", "comment",
                   "collapse_delta", "sentence_after"))
    logic = _as_int(data, "logic", 5, 0, 10)
    fluency = _as_int(data, "fluency", 5, 0, 10)
    surprise = _as_int(data, "surprise", 5, 0, 10)
    # logic ≤4 视为"没圆回来"，契约 §2.4 要求此时 collapse_delta = 0
    delta = 0 if logic <= 4 else _as_int(data, "collapse_delta", -15, -30, 0)
    out = {
        "logic": logic, "fluency": fluency, "surprise": surprise,
        "score": min(100, logic * 4 + fluency * 3 + surprise * 3),
        "comment": _as_text(data, "comment", MAX_COMMENT, "裁判表示这一缝很有想法。"),
        "collapse_delta": delta,
        "sentence_after": _as_text(data, "sentence_after", MAX_SENTENCE),
    }
    if not out["sentence_after"]:
        raise AgentError(AGENT_BAD_JSON, "sentence_after 为空")
    return out


def normalize_rewrite(data: dict) -> dict:
    require(data, ("sentence",))
    sentence = _as_text(data, "sentence", MAX_REWRITE)
    if not sentence:
        raise AgentError(AGENT_BAD_JSON, "压缩句为空")
    return {"sentence": sentence}


def normalize_commentary(data: dict) -> dict:
    require(data, ("text",))
    text = _as_text(data, "text", MAX_COMMENTARY)
    if not text:
        raise AgentError(AGENT_BAD_JSON, "解说为空")
    return {"text": text}

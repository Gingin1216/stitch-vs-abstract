"""Agent 服务（P2）。MOCK=1 时返回写死数据（Day1 联调用），否则调 Kimi。

每个路由只做三件事：组装 user 消息 → 调 llm.chat_json（带 schema + normalizer
+ 角色对应的 max_tokens）→ 按契约 §1 把 AgentError 转成统一错误格式。
业务规则写在 prompts.py 与 schemas.py，路由层保持薄，方便 P3 的评测集直接打接口回归。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import llm
import prompts
import schemas
import tools as tool_defs
from errors import AgentError
from llm import (AGENT_TOTAL_BUDGET, JUDGE_TEMPERATURE, MAX_TOKENS_CREATIVE,
                 MAX_TOKENS_JUDGE, MAX_TOKENS_REWRITE, TOOL_CALLING_SUPPORTED,
                 chat_json)

MOCK = os.getenv("MOCK") == "1"
MOCK_PATH = Path(__file__).parent.parent / "mock" / "mock_agents.json"
MOCK_DATA = json.loads(MOCK_PATH.read_text(encoding="utf-8")) if MOCK else {}

app = FastAPI(title="崩坏缝合局 · Agent 层")


@app.exception_handler(AgentError)
def agent_error_handler(_request, exc: AgentError):
    """契约 §1：统一错误格式，引擎据 retryable 决定重试还是用兜底文案。"""
    return JSONResponse(status_code=exc.status_code, content=exc.to_payload())


def mock_or(key: str):
    return MOCK_DATA.get(key, {})


# P4 的完整对局时间线同样是 P2 维护的 mock 资产，这里复用它让 MOCK 模式能跑满 5 回合
MOCK_ROUNDS = (MOCK_DATA.get("_frontend_full_game_mock", {}).get("rounds", [])
               if MOCK else [])
_CARD_GRADIENT = [("日常", 1), ("日常", 1), ("抽象", 2), ("知乎梗", 2), ("违禁", 3)]


def mock_deal(round_: int) -> dict:
    """MOCK 发牌按回合取不同词卡。

    原先每回合都返回同一副牌，第 3 回合起所有词都会被 WORD_DUPLICATE 拦掉，
    MOCK 全链路跑不到 FINISHED。时间线里本来就有 5 组词，直接按回合取用。
    """
    for item in MOCK_ROUNDS:
        if item.get("round") == round_ and len(item.get("cards", [])) == 5:
            return {"cards": [{"word": w, "level": lv, "tag": tag}
                              for w, (tag, lv) in zip(item["cards"], _CARD_GRADIENT)]}
    return mock_or("POST /agents/deal")


def mock_judge(key: str, round_hint: str, word: str, sentence: str) -> dict:
    """MOCK 判卷：优先用时间线里该词的真实评语，保证 5 回合都有差异化文案。"""
    base = dict(mock_or(key))
    for item in MOCK_ROUNDS:
        pick = item.get(round_hint) or {}
        if pick.get("word") != word:
            continue
        base.update(score=pick["score"], comment=pick["comment"],
                    collapse_delta=pick["collapse_delta"])
        after = (item.get("sentence_after_a") if round_hint == "a_pick"
                 else item.get("rewritten"))
        base["sentence_after"] = after or base.get("sentence_after", sentence)
        return base
    # 时间线里没有这个词（玩家选了别的卡）：拼一个保底新句子，别让故事卡住不动
    base["sentence_after"] = f"{sentence.rstrip('。！？')}，{word}闯入了故事。"[:40]
    return base


class OpeningReq(BaseModel):
    theme: str = "daily"
    seed: int = 0


class DealReq(BaseModel):
    sentence: str
    round: int
    used_words: list[str] = []
    zhihu_flavor: bool = True


class JudgeAReq(BaseModel):
    sentence: str
    picked_word: str
    word_level: int = 1
    round: int = 1
    used_words: list[str] = []  # 可选：传入后裁判可自行调工具查换皮重复


class JudgeBReq(BaseModel):
    sentence_before: str
    picked_word: str


class RewriteReq(BaseModel):
    story: str


class CommentaryReq(BaseModel):
    rounds: list
    winner: str
    final_story: str


@app.get("/agents/health")
def health():
    """自检：告诉 P1/P4 当前跑在什么模式下，演示时也用它证明 tool calling 已开。"""
    return {
        "ok": True,
        "mock": MOCK,
        "model": llm.MODEL,
        "model_strong": llm.STRONG_MODEL,
        "tool_calling": TOOL_CALLING_SUPPORTED,
        # 运行期探测到平台不支持 json_schema 时会自动翻成 false
        "structured_output": llm.STRUCTURED_OUTPUT_SUPPORTED,
        "judge_tools": [t["function"]["name"] for t in tool_defs.JUDGE_TOOLS],
        # 耗时治理配置：health 一眼核对预算/轮数/max_tokens 是否生效
        "total_budget": llm.AGENT_TOTAL_BUDGET,
        "max_rounds": llm.MAX_ROUNDS,
        "max_tokens": {"judge": llm.MAX_TOKENS_JUDGE,
                       "creative": llm.MAX_TOKENS_CREATIVE,
                       "rewrite": llm.MAX_TOKENS_REWRITE},
    }


@app.post("/agents/opening")
def opening(req: OpeningReq):
    if MOCK:
        return mock_or("POST /agents/opening")
    return chat_json(prompts.OPENING_SYSTEM,
                     f"主题：{req.theme}\n随机种子：{req.seed}（不同种子请给不同场景）",
                     schema=schemas.OPENING_SCHEMA,
                     required_keys=("sentence",),
                     max_tokens=MAX_TOKENS_CREATIVE,
                     normalizer=schemas.normalize_opening)


@app.post("/agents/deal")
def deal(req: DealReq):
    if MOCK:
        return mock_deal(req.round)
    user = (f"当前句子：{req.sentence}\n回合：{req.round}\n"
            f"已用词（禁止重复/近义）：{req.used_words}\n"
            f"zhihu_flavor：{req.zhihu_flavor}")
    return chat_json(prompts.DEAL_SYSTEM, user,
                     schema=schemas.DEAL_SCHEMA,
                     required_keys=("cards",),
                     max_tokens=MAX_TOKENS_CREATIVE,
                     normalizer=lambda d: schemas.normalize_deal(d, req.used_words))


@app.post("/agents/judge_abstract")
def judge_abstract(req: JudgeAReq):
    if MOCK:
        return mock_judge("POST /agents/judge_abstract", "a_pick",
                          req.picked_word, req.sentence)
    user = (f'句子："{req.sentence}"\n'
            f'所选词："{req.picked_word}"（level {req.word_level}）\n'
            f"回合：{req.round}")
    if req.used_words:
        user += f"\n本局已用词：{req.used_words}"

    if TOOL_CALLING_SUPPORTED:
        # agentic 模式：裁判自主调用 get_semantic_jump / check_word_overlap 取硬指标
        trace: list = []
        data = chat_json(
            prompts.JUDGE_ABSTRACT_SYSTEM, user, strong=True,
            tools=tool_defs.JUDGE_TOOLS, tool_executor=tool_defs.execute_tool,
            temperature=JUDGE_TEMPERATURE, trace=trace,
            schema=schemas.JUDGE_ABSTRACT_SCHEMA,
            max_tokens=MAX_TOKENS_JUDGE,
            required_keys=("jump_score", "score", "comment",
                           "collapse_delta", "invalid_narrative",
                           "sentence_after"),
            normalizer=lambda d: schemas.normalize_judge_abstract(
                d, _jump_from_trace(trace)))
        return data

    # 兜底模式：平台不支持 function calling，P2 先取跳度再塞进 prompt。
    # prefetch 的 HTTP 耗时同样占用本次调用的总预算，剩余部分交给 chat_json。
    t0 = time.monotonic()
    jump = tool_defs.prefetch_jump(req.sentence, req.picked_word)
    left = AGENT_TOTAL_BUDGET - (time.monotonic() - t0)
    user += (f'\n（系统已测定 jump_score={jump["jump_score"]}，'
             "请直接使用，不得修改该值）")
    return chat_json(prompts.JUDGE_ABSTRACT_SYSTEM, user, strong=True,
                     temperature=JUDGE_TEMPERATURE,
                     schema=schemas.JUDGE_ABSTRACT_SCHEMA,
                     max_tokens=MAX_TOKENS_JUDGE,
                     total_budget=max(0.5, left),
                     required_keys=("score", "comment", "collapse_delta",
                                    "invalid_narrative", "sentence_after"),
                     normalizer=lambda d: schemas.normalize_judge_abstract(
                         d, jump["jump_score"]))


def _jump_from_trace(trace: list) -> int | None:
    """契约 §2.3：jump_score 必须来自工具返回，取最后一次成功调用的结果。

    返回 None 表示模型没调工具（或调用全失败），此时沿用模型自报值并由
    normalize_judge_abstract 夹到 0-100——游戏不中断，但 /agents/health
    与回归脚本能看出 tool calling 没生效。
    """
    for call in reversed(trace):
        if call["tool"] == "get_semantic_jump" and "jump_score" in call["result"]:
            return int(call["result"]["jump_score"])
    return None


@app.post("/agents/judge_stitch")
def judge_stitch(req: JudgeBReq):
    if MOCK:
        return mock_judge("POST /agents/judge_stitch", "b_pick",
                          req.picked_word, req.sentence_before)
    user = f'前句："{req.sentence_before}"\n所选词："{req.picked_word}"'
    # 契约 §2.4：score 由 normalize_judge_stitch 按公式预填，引擎再复核
    return chat_json(prompts.JUDGE_STITCH_SYSTEM, user, strong=True,
                     temperature=JUDGE_TEMPERATURE,
                     schema=schemas.JUDGE_STITCH_SCHEMA,
                     max_tokens=MAX_TOKENS_JUDGE,
                     required_keys=("logic", "fluency", "surprise", "comment",
                                    "collapse_delta", "sentence_after"),
                     normalizer=schemas.normalize_judge_stitch)


@app.post("/agents/rewrite")
def rewrite(req: RewriteReq):
    if MOCK:
        return mock_or("POST /agents/rewrite")
    return chat_json(prompts.REWRITE_SYSTEM, f"故事：{req.story}",
                     schema=schemas.REWRITE_SCHEMA,
                     required_keys=("sentence",),
                     max_tokens=MAX_TOKENS_REWRITE,
                     normalizer=schemas.normalize_rewrite)


@app.post("/agents/commentary")
def commentary(req: CommentaryReq):
    if MOCK:
        return mock_or("POST /agents/commentary")
    user = (f"回合记录：{json.dumps(req.rounds, ensure_ascii=False)}\n"
            f"胜者：{req.winner}\n最终故事：{req.final_story}")
    return chat_json(prompts.COMMENTARY_SYSTEM, user, strong=True,
                     schema=schemas.COMMENTARY_SCHEMA,
                     required_keys=("text",),
                     max_tokens=MAX_TOKENS_CREATIVE,
                     normalizer=schemas.normalize_commentary)

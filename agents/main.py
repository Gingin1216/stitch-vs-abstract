"""Agent 服务（P2）。MOCK=1 时返回写死数据（Day1 联调用），否则调看山工作台。"""
from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel

import prompts
import tools as tool_defs
from llm import TOOL_CALLING_SUPPORTED, chat_json

MOCK = os.getenv("MOCK") == "1"
MOCK_PATH = Path(__file__).parent.parent / "mock" / "mock_agents.json"
MOCK_DATA = json.loads(MOCK_PATH.read_text(encoding="utf-8")) if MOCK else {}

app = FastAPI(title="崩坏缝合局 · Agent 层")


def mock_or(key: str):
    return MOCK_DATA.get(key, {})


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


class JudgeBReq(BaseModel):
    sentence_before: str
    picked_word: str


class RewriteReq(BaseModel):
    story: str


class CommentaryReq(BaseModel):
    rounds: list
    winner: str
    final_story: str


@app.post("/agents/opening")
def opening(req: OpeningReq):
    if MOCK:
        return mock_or("POST /agents/opening")
    return chat_json(prompts.OPENING_SYSTEM, "请生成开局句。",
                     required_keys=("sentence",))


@app.post("/agents/deal")
def deal(req: DealReq):
    if MOCK:
        return mock_or("POST /agents/deal")
    user = (f"当前句子：{req.sentence}\n回合：{req.round}\n"
            f"已用词（禁止重复/近义）：{req.used_words}\n"
            f"zhihu_flavor：{req.zhihu_flavor}")
    return chat_json(prompts.DEAL_SYSTEM, user, required_keys=("cards",))


@app.post("/agents/judge_abstract")
def judge_abstract(req: JudgeAReq):
    if MOCK:
        return mock_or("POST /agents/judge_abstract")
    user = f'句子："{req.sentence}"\n所选词："{req.picked_word}"（level {req.word_level}）'

    if TOOL_CALLING_SUPPORTED:
        # agentic 模式：裁判自主调用 get_semantic_jump 工具拿跳度分
        return chat_json(
            prompts.JUDGE_ABSTRACT_SYSTEM, user, strong=True,
            tools=[tool_defs.JUMP_TOOL], tool_executor=tool_defs.execute_tool,
            required_keys=("jump_score", "score", "comment",
                           "collapse_delta", "invalid_narrative", "sentence_after"))
    # 兜底模式：引擎侧先算好跳度塞进 prompt，模型只做创意评判
    jump = tool_defs.prefetch_jump(req.sentence, req.picked_word)
    user += f'\n（系统已测定 jump_score={jump["jump_score"]}，请直接使用，不得修改该值）'
    data = chat_json(prompts.JUDGE_ABSTRACT_SYSTEM, user, strong=True,
                     required_keys=("score", "comment", "collapse_delta",
                                    "invalid_narrative", "sentence_after"))
    data["jump_score"] = jump["jump_score"]
    return data


@app.post("/agents/judge_stitch")
def judge_stitch(req: JudgeBReq):
    if MOCK:
        return mock_or("POST /agents/judge_stitch")
    user = f'前句："{req.sentence_before}"\n所选词："{req.picked_word}"'
    data = chat_json(prompts.JUDGE_STITCH_SYSTEM, user, strong=True,
                     required_keys=("logic", "fluency", "surprise",
                                    "comment", "collapse_delta", "sentence_after"))
    # 契约 §2.4：score = logic*4 + fluency*3 + surprise*3（服务侧预填，引擎复核）
    data["score"] = min(100, data["logic"] * 4 + data["fluency"] * 3
                        + data["surprise"] * 3)
    return data


@app.post("/agents/rewrite")
def rewrite(req: RewriteReq):
    if MOCK:
        return mock_or("POST /agents/rewrite")
    return chat_json(prompts.REWRITE_SYSTEM, f"故事：{req.story}",
                     required_keys=("sentence",))


@app.post("/agents/commentary")
def commentary(req: CommentaryReq):
    if MOCK:
        return mock_or("POST /agents/commentary")
    user = (f"回合记录：{json.dumps(req.rounds, ensure_ascii=False)}\n"
            f"胜者：{req.winner}\n最终故事：{req.final_story}")
    return chat_json(prompts.COMMENTARY_SYSTEM, user, strong=True,
                     required_keys=("text",))

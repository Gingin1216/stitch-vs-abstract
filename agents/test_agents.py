"""Agent 层单元测试（P2 自测，不需要真实 LLM / 不需要语义层在线）。

跑法（仓库根目录或 agents/ 下均可）：
    cd agents && python -m pytest -q

与 tests/run_eval.py 的分工：
- 本文件验证**契约与容错**：字段范围、梯度校验、tool calling 是否真的发生、错误码。
- run_eval.py（P3）验证**判分质量**：改 prompt 后分数有没有漂移，需要真实模型。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent))

import errors  # noqa: E402
import llm  # noqa: E402
import main  # noqa: E402
import schemas  # noqa: E402
import tools as tool_defs  # noqa: E402

client = TestClient(main.app)


# ---------- schemas：输出规范化 ----------

def test_deal_rejects_wrong_card_count():
    with pytest.raises(errors.AgentError) as e:
        schemas.normalize_deal({"cards": [{"word": "关东煮", "level": 1, "tag": "日常"}]})
    assert e.value.code == errors.AGENT_BAD_JSON


def test_deal_drops_used_and_duplicate_words():
    cards = [{"word": w, "level": 1, "tag": "日常"} for w in
             ("关东煮", "关东煮", "小票", "量子力学", "谢邀", "秦始皇")]
    with pytest.raises(errors.AgentError):
        # 去重后只剩 5 张但「秦始皇」已用过 → 实得 4 张，应判 BAD_JSON 触发重试
        schemas.normalize_deal({"cards": cards}, used_words=["秦始皇"])


def test_deal_repairs_level_gradient_and_tags():
    cards = [{"word": w, "level": lv, "tag": "日常"} for w, lv in
             (("关东煮", 1), ("小票", 1), ("量子力学", 2), ("谢邀", 2), ("秦始皇", 2))]
    out = schemas.normalize_deal({"cards": cards})
    assert sorted(c["level"] for c in out["cards"]) == [1, 1, 2, 2, 3]
    assert [c["tag"] for c in out["cards"] if c["level"] == 3] == ["违禁"]


def test_abstract_jump_score_from_tool_overrides_model_guess():
    out = schemas.normalize_judge_abstract(
        {"jump_score": 99, "score": 95, "comment": "x", "collapse_delta": 20,
         "invalid_narrative": False, "sentence_after": "句子"},
        jump_score=14)
    assert out["jump_score"] == 14  # 契约 §2.3：禁止自估跳度


def test_abstract_invalid_narrative_zeroes_score():
    out = schemas.normalize_judge_abstract(
        {"jump_score": 95, "score": 90, "comment": "炸烂了", "collapse_delta": 28,
         "invalid_narrative": True, "sentence_after": "便利店，熵。"})
    assert (out["score"], out["collapse_delta"]) == (0, 5)


def test_abstract_clamps_out_of_range_delta():
    out = schemas.normalize_judge_abstract(
        {"jump_score": 90, "score": 150, "comment": "c", "collapse_delta": 99,
         "invalid_narrative": False, "sentence_after": "s"}, jump_score=90)
    assert out["score"] == 100 and out["collapse_delta"] == 30


def test_abstract_truncates_overlong_sentence():
    out = schemas.normalize_judge_abstract(
        {"jump_score": 50, "score": 50, "comment": "很长" * 50,
         "collapse_delta": 15, "invalid_narrative": False,
         "sentence_after": "字" * 80}, jump_score=50)
    assert len(out["sentence_after"]) == schemas.MAX_SENTENCE
    assert len(out["comment"]) == schemas.MAX_COMMENT


def test_stitch_score_follows_contract_formula():
    out = schemas.normalize_judge_stitch(
        {"logic": 8, "fluency": 7, "surprise": 9, "comment": "妙",
         "collapse_delta": -25, "sentence_after": "缝好了"})
    assert out["score"] == 8 * 4 + 7 * 3 + 9 * 3 == 80


def test_stitch_no_fix_means_zero_collapse_delta():
    out = schemas.normalize_judge_stitch(
        {"logic": 3, "fluency": 5, "surprise": 2, "comment": "没缝上",
         "collapse_delta": -20, "sentence_after": "勉强一句"})
    assert out["collapse_delta"] == 0  # 契约 §2.4：没圆回来不许降崩坏度


def test_stitch_accepts_stringified_numbers():
    out = schemas.normalize_judge_stitch(
        {"logic": "8", "fluency": 7.0, "surprise": 9, "comment": "c",
         "collapse_delta": "-25", "sentence_after": "s"})
    assert out["score"] == 80 and out["collapse_delta"] == -25


def test_rewrite_enforces_30_chars():
    out = schemas.normalize_rewrite({"sentence": "便" * 60})
    assert len(out["sentence"]) == schemas.MAX_REWRITE


def test_missing_field_raises_bad_json():
    with pytest.raises(errors.AgentError) as e:
        schemas.normalize_judge_stitch({"logic": 8, "fluency": 7})
    assert e.value.code == errors.AGENT_BAD_JSON


# ---------- tools：工具执行与降级 ----------

def test_execute_tool_calls_semantic_layer(monkeypatch):
    seen = {}

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"distance": 0.83, "jump_score": 92}

    def fake_post(url, json=None, timeout=None):
        seen["url"], seen["payload"] = url, json
        return Resp()

    monkeypatch.setattr(tool_defs.httpx, "post", fake_post)
    out = tool_defs.execute_tool("get_semantic_jump",
                                 {"sentence": "便利店", "word": "秦始皇"})
    assert out["jump_score"] == 92
    assert seen["url"].endswith("/semantic/jump")
    assert seen["payload"] == {"sentence": "便利店", "word": "秦始皇"}


def test_execute_tool_degrades_when_semantic_down(monkeypatch):
    def boom(*_a, **_kw):
        raise tool_defs.httpx.ConnectError("refused")

    monkeypatch.setattr(tool_defs.httpx, "post", boom)
    out = tool_defs.execute_tool("get_semantic_jump",
                                 {"sentence": "s", "word": "w"})
    assert "error" in out and "hint" in out  # 错误回灌给模型，不中断对局
    assert tool_defs.prefetch_jump("s", "w") == {
        "distance": None, "jump_score": 50, "degraded": True}


def test_unknown_tool_is_reported():
    assert "unknown tool" in tool_defs.execute_tool("nope", {})["error"]


# ---------- llm：tool calling 循环 ----------

class _FakeMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class _FakeToolCall:
    def __init__(self, name, args):
        self.id = "call_1"
        self.function = type("F", (), {"name": name,
                                       "arguments": json.dumps(args)})()


def _fake_client(script):
    """按序返回预设消息，模拟「先调工具，再出终稿」。"""
    calls = iter(script)

    class Completions:
        def create(self, **kwargs):
            msg = next(calls)
            return type("R", (), {"choices": [type("C", (), {"message": msg})()]})()

    return type("Cli", (), {"chat": type("Chat", (), {"completions": Completions()})()})()


def test_chat_json_runs_tool_loop_then_returns_json(monkeypatch):
    script = [
        _FakeMessage(tool_calls=[_FakeToolCall("get_semantic_jump",
                                               {"sentence": "s", "word": "w"})]),
        _FakeMessage(content='```json\n{"jump_score": 92, "score": 88}\n```'),
    ]
    monkeypatch.setattr(llm, "client", _fake_client(script))
    trace: list = []
    out = llm.chat_json("sys", "user", tools=tool_defs.JUDGE_TOOLS,
                        tool_executor=lambda n, a: {"jump_score": 92},
                        trace=trace, required_keys=("jump_score",))
    assert out["score"] == 88
    assert trace[0]["tool"] == "get_semantic_jump"  # tool calling 真的发生了


def test_chat_json_retries_once_on_bad_json(monkeypatch):
    script = [_FakeMessage(content="抱歉我忘了输出 JSON"),
              _FakeMessage(content='{"sentence": "我今天走进了一家便利店。"}')]
    monkeypatch.setattr(llm, "client", _fake_client(script))
    out = llm.chat_json("sys", "user", required_keys=("sentence",),
                        normalizer=schemas.normalize_opening)
    assert out["sentence"] == "我今天走进了一家便利店。"


def test_chat_json_raises_bad_json_after_retry(monkeypatch):
    monkeypatch.setattr(llm, "client",
                        _fake_client([_FakeMessage(content="no json")] * 4))
    with pytest.raises(errors.AgentError) as e:
        llm.chat_json("sys", "user", required_keys=("sentence",))
    assert e.value.code == errors.AGENT_BAD_JSON


# ---------- 路由：契约字段与错误格式 ----------

def test_health_reports_agentic_capabilities():
    body = client.get("/agents/health").json()
    assert body["ok"] is True
    assert "get_semantic_jump" in body["judge_tools"]


# 以下三个路由用例回归的是**真实路径**（chat_json 被 monkeypatch 顶替），
# 与进程级 MOCK 无关：无论 pytest 是否带 MOCK=1 启动，都强制关掉路由的 MOCK 短路。

def test_judge_abstract_route_uses_tool_jump_score(monkeypatch):
    captured = {}
    monkeypatch.setattr(main, "MOCK", False)

    def fake_chat_json(system, user, **kwargs):
        captured["tools"] = [t["function"]["name"] for t in kwargs["tools"]]
        kwargs["trace"].append({"tool": "get_semantic_jump", "arguments": {},
                                "result": {"jump_score": 14}})
        return kwargs["normalizer"]({
            "jump_score": 95, "score": 90, "comment": "强行高分",
            "collapse_delta": 28, "invalid_narrative": False,
            "sentence_after": "便利店里多了一份关东煮。"})

    monkeypatch.setattr(main, "chat_json", fake_chat_json)
    body = client.post("/agents/judge_abstract", json={
        "sentence": "我今天走进了一家便利店。", "picked_word": "关东煮",
        "word_level": 1, "round": 1}).json()
    assert "get_semantic_jump" in captured["tools"]
    assert body["jump_score"] == 14  # 工具值覆盖模型自估


def test_judge_stitch_route_recomputes_score(monkeypatch):
    monkeypatch.setattr(main, "MOCK", False)
    monkeypatch.setattr(main, "chat_json", lambda s, u, **kw: kw["normalizer"]({
        "logic": 8, "fluency": 7, "surprise": 9, "comment": "典故级缝合",
        "collapse_delta": -25, "sentence_after": "秦始皇递来统一度量衡的小票。",
        "score": 999}))
    body = client.post("/agents/judge_stitch", json={
        "sentence_before": "收银台后坐着秦始皇。", "picked_word": "小票"}).json()
    assert body["score"] == 80


def test_agent_error_returns_contract_error_shape(monkeypatch):
    monkeypatch.setattr(main, "MOCK", False)

    def boom(*_a, **_kw):
        raise errors.AgentError(errors.AGENT_TIMEOUT, "裁判 Agent 响应超时")

    monkeypatch.setattr(main, "chat_json", boom)
    resp = client.post("/agents/rewrite", json={"story": "……"})
    assert resp.status_code == 504
    assert resp.json()["error"] == {"code": "AGENT_TIMEOUT",
                                   "message": "裁判 Agent 响应超时",
                                   "retryable": True}


# ---------- mock 一致性：P1/P4 联调靠它 ----------

def test_mock_deal_varies_per_round():
    """MOCK 每回合必须发不同的牌，否则第 3 回合起全被 WORD_DUPLICATE 拦死。"""
    data = json.loads((Path(__file__).parent.parent / "mock" /
                       "mock_agents.json").read_text(encoding="utf-8"))
    timeline = data["_frontend_full_game_mock"]["rounds"]
    decks = [tuple(r["cards"]) for r in timeline]
    assert len(decks) == 5 and len(set(decks)) == 5
    # 跨回合不得有重复词，否则引擎的近义检测仍会卡住
    flat = [w for deck in decks for w in deck]
    assert len(flat) == len(set(flat)) == 25


def test_mock_fixture_matches_v11_contract():
    data = json.loads((Path(__file__).parent.parent / "mock" /
                       "mock_agents.json").read_text(encoding="utf-8"))
    abstract = data["POST /agents/judge_abstract"]
    stitch = data["POST /agents/judge_stitch"]
    # v1.1 新增字段，缺了前端拿不到新句子
    assert abstract["sentence_after"] and stitch["sentence_after"]
    # mock 必须本身就能通过规范化，否则 MOCK=1 与真实模式行为会分叉
    assert schemas.normalize_judge_abstract(dict(abstract))["score"] == abstract["score"]
    assert schemas.normalize_judge_stitch(dict(stitch))["score"] == stitch["score"]
    assert schemas.normalize_deal(dict(data["POST /agents/deal"]))["cards"]
    levels = sorted(c["level"] for c in data["POST /agents/deal"]["cards"])
    assert levels == schemas.LEVEL_GRADIENT

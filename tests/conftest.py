"""P1 引擎测试夹具：Fake Agent 替换 engine/clients.py 的外部调用。

全程禁止真实网络请求；返回值写死、可在测试里改写，
mode 可在 "normal"（正常返回）/ "raise"（抛 AgentError）间切换。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))

import clients  # noqa: E402


class FakeAgents:
    """假 Agent 客户端：签名与 clients.py 一致，返回写死的合法值。

    - mode = "normal"：返回写死值（默认合法，可直接跑完整对局）
    - mode = "raise" ：抛 clients.AgentError，模拟 Agent 挂掉
    - calls 记录每次调用的名字与入参，供断言
    """

    def __init__(self) -> None:
        self.mode = "normal"
        self.calls: list[dict] = []
        # 写死返回值（与契约 §2 示例对齐）
        self.opening_sentence = "我今天走进了一家便利店。"
        self.cards = [
            {"word": "关东煮", "level": 1, "tag": "日常"},
            {"word": "小票", "level": 1, "tag": "日常"},
            {"word": "量子力学", "level": 2, "tag": "抽象"},
            {"word": "谢邀", "level": 2, "tag": "知乎梗"},
            {"word": "秦始皇", "level": 3, "tag": "违禁"},
        ]
        self.abstract_result = {
            "jump_score": 92, "score": 88, "comment": "便利店里坐着秦始皇。",
            "collapse_delta": 22, "invalid_narrative": False,
            "sentence_after": "我今天走进了一家便利店，收银台后坐着秦始皇。",
        }
        self.stitch_result = {
            "logic": 8, "fluency": 7, "surprise": 9, "score": 80,
            "comment": "用统一度量衡的小票圆回秦始皇收银。",
            "collapse_delta": -25,
            "sentence_after": "收银台后的秦始皇递给我一张统一度量衡的小票。",
        }
        self.rewrite_sentence = "便利店秦始皇收银，关东煮在量子隧穿。"

    def _dispatch(self, name: str, **kwargs):
        self.calls.append({"name": name, **kwargs})
        if self.mode == "raise":
            raise clients.AgentError("AGENT_TIMEOUT", f"fake {name} failure")
        attr = {"opening": "opening_sentence", "deal": "cards",
                "judge_abstract": "abstract_result",
                "judge_stitch": "stitch_result",
                "rewrite": "rewrite_sentence"}[name]
        return getattr(self, attr)

    # 以下签名与 clients.py 保持一致

    def opening(self) -> str:
        return self._dispatch("opening")

    def deal(self, sentence: str, round_: int, used_words: list) -> list:
        return self._dispatch("deal", sentence=sentence, round_=round_,
                              used_words=used_words)

    def judge_abstract(self, sentence: str, word: str, level: int, round_: int) -> dict:
        return self._dispatch("judge_abstract", sentence=sentence, word=word,
                              level=level, round_=round_)

    def judge_stitch(self, sentence_before: str, word: str) -> dict:
        return self._dispatch("judge_stitch", sentence_before=sentence_before,
                              word=word)

    def rewrite(self, story: str) -> str:
        return self._dispatch("rewrite", story=story)


@pytest.fixture
def fake_agents(monkeypatch):
    """把 clients 的 opening/deal/judge_abstract/judge_stitch/rewrite
    换成 FakeAgents 的实现，返回该假客户端供测试控制与断言。"""
    fake = FakeAgents()
    monkeypatch.setattr(clients, "opening", fake.opening)
    monkeypatch.setattr(clients, "deal", fake.deal)
    monkeypatch.setattr(clients, "judge_abstract", fake.judge_abstract)
    monkeypatch.setattr(clients, "judge_stitch", fake.judge_stitch)
    monkeypatch.setattr(clients, "rewrite", fake.rewrite)
    return fake

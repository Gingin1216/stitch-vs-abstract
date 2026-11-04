"""P1 引擎测试夹具：隔离加载 engine 模块 + Fake Agent 替换外部调用。

engine/ 是平铺导入（main.py 里 `import clients` / `from state import ...`），
与 agents/ 的 main.py 等共用 sys.modules 的通用键，同一会话必须隔离加载。
全程禁止真实网络请求；FakeAgents 返回值写死、可在测试里改写，
mode 可在 "normal"（正常返回）/ "raise"（抛 AgentError）间切换。
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def load_engine_modules(monkeypatch) -> SimpleNamespace:
    """隔离加载 engine 的 state/clients/main，返回 SimpleNamespace(state=, clients=, main=)。

    加载前把 engine/ 顶到 sys.path 最前，按依赖顺序加载，保证拿到 engine 自己的
    版本；加载后立即从 sys.modules 删掉 state/clients/main 这些通用名——否则
    通用名常驻会与 agents/ 的同名模块互相覆盖（两边都有 main.py），后续任何
    import 同名模块的代码都会串味；原值由 monkeypatch 在测试结束时还原。
    """
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parent.parent / "engine"))
    mods = {}
    for name in ("state", "clients", "main"):  # 依赖顺序：state ← clients ← main
        monkeypatch.delitem(sys.modules, name, raising=False)
        # 加载期间保留在 sys.modules，main.py 的 import clients 才会命中 engine 版本
        mods[name] = importlib.import_module(name)
    for name in mods:
        # 用完即摘：通用名不留存，agents/ 的同名模块对后续 import 不可见、也不被覆盖
        monkeypatch.delitem(sys.modules, name, raising=False)
    return SimpleNamespace(**mods)


@pytest.fixture
def engine_mods(monkeypatch):
    """每个测试单独加载一套 engine 模块（含全新的 FastAPI app 与 GAMES 表）。"""
    return load_engine_modules(monkeypatch)


class FakeAgents:
    """假 Agent 客户端：签名与 clients.py 一致，返回写死的合法值。

    - mode = "normal"：返回写死值（默认合法，可直接跑完整对局）
    - mode = "raise" ：抛 engine 隔离模块的 AgentError，模拟 Agent 挂掉
    - calls 记录每次调用的名字与入参，供断言
    """

    def __init__(self, clients_module) -> None:
        self._agent_error = clients_module.AgentError
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
        self.commentary_text = ("五回合鏖战，选手 A 三度祭出违禁词边缘的宇宙级操作，"
                                "选手 B 的会员积分堪称全场最佳缝合。谢邀，便利店已倒闭。")
        self.is_duplicate_result = False  # P3 近义判定的可控开关，测试里按需改写

    def _dispatch(self, name: str, **kwargs):
        self.calls.append({"name": name, **kwargs})
        if self.mode == "raise":
            raise self._agent_error("AGENT_TIMEOUT", f"fake {name} failure")
        attr = {"opening": "opening_sentence", "deal": "cards",
                "judge_abstract": "abstract_result",
                "judge_stitch": "stitch_result",
                "rewrite": "rewrite_sentence",
                "commentary": "commentary_text"}[name]
        return getattr(self, attr)

    # 以下签名与 clients.py 保持一致

    def opening(self, game_id: str | None = None) -> str:
        return self._dispatch("opening", game_id=game_id)

    def deal(self, sentence: str, round_: int, used_words: list,
             game_id: str | None = None) -> list:
        return self._dispatch("deal", sentence=sentence, round_=round_,
                              used_words=used_words, game_id=game_id)

    def judge_abstract(self, sentence: str, word: str, level: int, round_: int) -> dict:
        return self._dispatch("judge_abstract", sentence=sentence, word=word,
                              level=level, round_=round_)

    def judge_stitch(self, sentence_before: str, word: str) -> dict:
        return self._dispatch("judge_stitch", sentence_before=sentence_before,
                              word=word)

    def rewrite(self, story: str) -> str:
        return self._dispatch("rewrite", story=story)

    def commentary(self, rounds: list, winner: str, final_story: str) -> str:
        return self._dispatch("commentary", rounds=rounds, winner=winner,
                              final_story=final_story)

    def is_duplicate(self, word: str, history: list, threshold: float = 0.75) -> bool:
        # 不走 _dispatch：它模拟 P3 的判定结果而非网络故障，mode="raise" 不影响
        self.calls.append({"name": "is_duplicate", "word": word,
                           "history": history, "threshold": threshold})
        return self.is_duplicate_result


@pytest.fixture
def fake_agents(engine_mods, monkeypatch):
    """把隔离加载的 engine clients 的 opening/deal/judge_abstract/
    judge_stitch/rewrite/commentary/is_duplicate 全部换成 FakeAgents 实现，
    返回假客户端供控制与断言（不留任何真实 HTTP 调用）。"""
    fake = FakeAgents(engine_mods.clients)
    monkeypatch.setattr(engine_mods.clients, "opening", fake.opening)
    monkeypatch.setattr(engine_mods.clients, "deal", fake.deal)
    monkeypatch.setattr(engine_mods.clients, "judge_abstract", fake.judge_abstract)
    monkeypatch.setattr(engine_mods.clients, "judge_stitch", fake.judge_stitch)
    monkeypatch.setattr(engine_mods.clients, "rewrite", fake.rewrite)
    monkeypatch.setattr(engine_mods.clients, "commentary", fake.commentary)
    monkeypatch.setattr(engine_mods.clients, "is_duplicate", fake.is_duplicate)
    return fake

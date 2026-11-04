"""engine 状态机测试（骨架阶段：先验证隔离加载与 Fake Agent 本身）。"""
import sys

import pytest


def test_engine_modules_load_isolated(engine_mods):
    assert engine_mods.state.TOTAL_ROUNDS == 5 and engine_mods.state.COLLAPSE_START == 50
    assert engine_mods.main.app.title == "崩坏缝合局 · 游戏引擎"
    # 通用名不得常驻 sys.modules，否则 agents/ 的同名模块会被覆盖/被看到
    for name in ("state", "clients", "main"):
        assert name not in sys.modules


def test_fake_agents_normal_and_raise(engine_mods, fake_agents):
    assert fake_agents.opening() == "我今天走进了一家便利店。"
    assert sorted(c["level"] for c in fake_agents.deal("s", 1, [])) == [1, 1, 2, 2, 3]
    fake_agents.mode = "raise"
    with pytest.raises(engine_mods.clients.AgentError):
        fake_agents.judge_stitch("s", "w")
    assert fake_agents.calls[-1]["name"] == "judge_stitch"

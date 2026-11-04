"""engine 状态机测试：Fake Agent 替代真实 HTTP，无网络请求。

函数级 fake（conftest.fake_agents）驱动状态机行为；
HTTP 层 fake（monkeypatch _post）驱动真 clients 的公式复核与宕机兜底。
"""
import sys

import pytest
from fastapi.testclient import TestClient

from conftest import FakeAgents


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


# ---------- 对局行为测试 ----------

A_WORD, B_WORD = "秦始皇", "小票"  # fake 词卡里的 level3 / level1


@pytest.fixture
def client(engine_mods):
    return TestClient(engine_mods.main.app)


def create_game(client, mode="pvp"):
    r = client.post("/api/game", json={"mode": mode})
    assert r.status_code == 200, r.text
    return r.json()["game_id"]


def play_round(client, game_id, first):
    """按本回合先手顺序让 A、B 各出一张固定词，返回本回合最后一次响应。"""
    resp = None
    for role in (["A", "B"] if first == "A" else ["B", "A"]):
        resp = client.post(f"/api/game/{game_id}/pick",
                           json={"role": role,
                                 "word": A_WORD if role == "A" else B_WORD})
        assert resp.status_code == 200, resp.text
    return resp


def test_first_player_alternates(client, fake_agents):
    """契约 §4.1：奇数回合 A 先手，偶数回合 B 先手。"""
    game_id = create_game(client)
    snap = client.get(f"/api/game/{game_id}").json()
    assert snap["round"] == 1 and snap["first"] == "A"
    play_round(client, game_id, first="A")
    snap = client.get(f"/api/game/{game_id}").json()
    assert snap["round"] == 2 and snap["first"] == "B"


def test_normal_game_reaches_finished_and_rejects_picks(client, fake_agents):
    game_id = create_game(client)
    for first in ["A", "B", "A", "B", "A"]:
        play_round(client, game_id, first=first)
    snap = client.get(f"/api/game/{game_id}").json()
    assert snap["state"] == "FINISHED"
    assert len(snap["history"]) == 5
    assert client.get(f"/api/game/{game_id}/report").status_code == 200
    r = client.post(f"/api/game/{game_id}/pick", json={"role": "A", "word": A_WORD})
    assert r.status_code == 409
    body = r.json()
    assert body["error"]["code"] == "INVALID_STATE"
    assert body["error"]["retryable"] is False


def test_collapse_clamped_within_0_100(client, fake_agents):
    fake_agents.abstract_result["collapse_delta"] = 1000  # 正常值 22，故意顶穿上限
    fake_agents.stitch_result["collapse_delta"] = -1000   # 正常值 -25，故意跌破下限
    game_id = create_game(client)
    for first in ["A", "B", "A", "B", "A"]:
        for role in (["A", "B"] if first == "A" else ["B", "A"]):
            word = A_WORD if role == "A" else B_WORD
            r = client.post(f"/api/game/{game_id}/pick",
                            json={"role": role, "word": word})
            assert r.status_code == 200, r.text
            assert 0 <= r.json()["collapse"] <= 100
    snap = client.get(f"/api/game/{game_id}").json()
    assert snap["state"] == "FINISHED"
    assert all(0 <= c <= 100 for c in snap["collapse_curve"])


def test_stitch_score_recomputed_by_formula(client, engine_mods, monkeypatch):
    """契约 §2.4：score = logic*4 + fluency*3 + surprise*3，由引擎复核。

    fake 在 HTTP 层（_post）返回 score=999 的错误分，真 judge_stitch 必须纠正为 80。
    """
    fake = FakeAgents(engine_mods.clients)

    def fake_post(base, path, payload):
        if path == "/agents/judge_abstract":
            return dict(fake.abstract_result)
        if path == "/agents/judge_stitch":
            bad = dict(fake.stitch_result)
            bad["score"] = 999  # 模拟裁判算术翻车
            return bad
        if path == "/semantic/similar":
            return {"is_duplicate": False}
        raise AssertionError(f"未打桩的请求: {path}")

    monkeypatch.setattr(engine_mods.clients, "_post", fake_post)
    # opening/deal/rewrite/commentary 走 fake_agents 同款的函数级替换，无需 HTTP
    monkeypatch.setattr(engine_mods.clients, "opening", fake.opening)
    monkeypatch.setattr(engine_mods.clients, "deal", fake.deal)
    monkeypatch.setattr(engine_mods.clients, "rewrite", fake.rewrite)
    monkeypatch.setattr(engine_mods.clients, "commentary", fake.commentary)
    monkeypatch.setattr(engine_mods.clients, "is_duplicate", fake.is_duplicate)

    game_id = create_game(client)
    r = play_round(client, game_id, first="A")  # 返回 B（缝合派）的判卷响应
    judge = r.json()["judge"]
    assert judge["score"] == 8 * 4 + 7 * 3 + 9 * 3 == 80
    assert judge["detail"] == {"logic": 8, "fluency": 7, "surprise": 9}


def test_duplicate_word_rejected_without_penalty(client, fake_agents):
    """契约 §1 错误码表：WORD_DUPLICATE = 选词与历史重复/近义 → 提示重选，不扣回合。"""
    game_id = create_game(client)
    play_round(client, game_id, first="A")  # A 在第 1 回合出过"秦始皇"
    before = client.get(f"/api/game/{game_id}").json()
    assert before["round"] == 2 and before["first"] == "B"

    fake_agents.is_duplicate_result = True  # P3 判定该词与历史重复
    r = client.post(f"/api/game/{game_id}/pick",
                    json={"role": "B", "word": A_WORD})  # "秦始皇"仍在词卡中
    assert r.status_code == 409
    body = r.json()
    assert body["error"]["code"] == "WORD_DUPLICATE"
    assert body["error"]["retryable"] is False

    after = client.get(f"/api/game/{game_id}").json()
    assert after["round"] == before["round"]  # 不扣回合
    assert after["state"] == before["state"]
    assert after["collapse"] == before["collapse"]
    assert after["score_a"] == before["score_a"]
    assert after["score_b"] == before["score_b"]


def test_agent_outage_uses_fallbacks(client, engine_mods, monkeypatch):
    """契约 §1 兜底原则：Agent 宕机游戏必须能继续（引擎写死默认值，无 prompt）。

    opening/deal 在引擎内无兜底分支（与契约 §1 的矛盾已单独报告），
    故只让裁判/压缩/解说/查重四层宕机，命中它们各自的真兜底分支。
    """
    fake = FakeAgents(engine_mods.clients)
    monkeypatch.setattr(engine_mods.clients, "opening", fake.opening)
    monkeypatch.setattr(engine_mods.clients, "deal", fake.deal)

    def boom(base, path, payload):
        raise engine_mods.clients.AgentError("AGENT_TIMEOUT", f"{path} 宕机")
    monkeypatch.setattr(engine_mods.clients, "_post", boom)

    def deck(r):
        return [{"word": f"第{r}波抽象", "level": 2, "tag": "抽象"},
                {"word": f"第{r}件日常", "level": 1, "tag": "日常"}]

    fake.cards = deck(1)  # 建局时发第 1 副
    game_id = create_game(client)
    for round_ in range(1, 6):
        if round_ < 5:
            # is_duplicate 兜底是精确匹配历史，词必须每回合换新；
            # 本回合牌在上一回合 _end_round 已取走，此刻改写不影响本回合
            fake.cards = deck(round_ + 1)
        first = "A" if round_ % 2 == 1 else "B"
        for role in (["A", "B"] if first == "A" else ["B", "A"]):
            word = f"第{round_}波抽象" if role == "A" else f"第{round_}件日常"
            r = client.post(f"/api/game/{game_id}/pick",
                            json={"role": role, "word": word})
            assert r.status_code == 200, r.text
            judge = r.json()["judge"]
            assert judge["score"] == 50  # judge_abstract/judge_stitch 兜底分
            if role == "A":
                assert judge["detail"] == {"jump_score": 50, "invalid_narrative": False}
            else:
                assert judge["detail"] == {"logic": 5, "fluency": 5, "surprise": 5}
    snap = client.get(f"/api/game/{game_id}").json()
    assert snap["state"] == "FINISHED"
    assert snap["score_a"] == 250 and snap["score_b"] == 250  # 5 回合 × 兜底 50
    assert len(snap["sentence"]) <= 30  # rewrite 兜底 story[:30]
    # commentary 不在 snapshot 里，走战报接口断言兜底文案
    report = client.get(f"/api/game/{game_id}/report").json()
    assert report["commentary"] == "解说员刘看山今日请假，比赛结果依然作数。"


def test_pve_auto_b_picks_lowest_level(client, fake_agents):
    """pve：B 位 AI 每回合自动选 level 最小的词，全程无需 B 的外部输入。"""
    game_id = create_game(client, mode="pve")
    for _ in range(5):
        snap = client.get(f"/api/game/{game_id}").json()
        assert snap["state"] == "A_TURN"  # 含 B 先手的偶数回合（死锁修复后轮到 A）
        r = client.post(f"/api/game/{game_id}/pick",
                        json={"role": "A", "word": B_WORD})
        assert r.status_code == 200, r.text
    snap = client.get(f"/api/game/{game_id}").json()
    assert snap["state"] == "FINISHED"
    assert len(snap["history"]) == 5
    # 词卡固定，level 最小的是第一张"关东煮"，B 五回合都由 AI 自动出它
    assert all(h["b_word"] == "关东煮" for h in snap["history"])
    assert all(h["a_word"] == B_WORD for h in snap["history"])


# ---------- 统一错误格式测试（契约 §1 + v1.2 变更记录） ----------

def test_game_id_not_found_returns_404(client):
    """game_id 不存在 → 404 + 统一错误结构。"""
    r = client.get("/api/game/g_nope")
    assert r.status_code == 404
    assert r.json() == {"error": {"code": "NOT_FOUND",
                                  "message": "对局不存在", "retryable": False}}
    r = client.post("/api/game/g_nope/pick", json={"role": "A", "word": "x"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"


def test_wrong_phase_action_returns_409(client, fake_agents):
    """当前阶段不接受该动作（A_TURN 时 B 出词）→ 409 + INVALID_STATE，结构与改动前一致。"""
    game_id = create_game(client)
    r = client.post(f"/api/game/{game_id}/pick", json={"role": "B", "word": B_WORD})
    assert r.status_code == 409
    assert r.json() == {"error": {"code": "INVALID_STATE",
                                  "message": "当前状态 A_TURN 不允许 B 选词",
                                  "retryable": False}}


def test_word_not_in_hand_returns_400(client, fake_agents):
    """出的词不在当前手牌 → 400 + CARD_NOT_IN_HAND（契约 v1.2 新增错误码）。"""
    game_id = create_game(client)
    r = client.post(f"/api/game/{game_id}/pick",
                    json={"role": "A", "word": "不存在的词"})
    assert r.status_code == 400
    assert r.json() == {"error": {"code": "CARD_NOT_IN_HAND",
                                  "message": "所出的词不在当前手牌中",
                                  "retryable": False}}


def test_bad_request_body_returns_400(client):
    """请求体缺字段 → 400 + BAD_REQUEST（原 FastAPI 默认 422 {"detail": ...} 收编）。"""
    r = client.post("/api/game/g_any/pick", json={"role": "A"})  # 缺 word
    assert r.status_code == 400
    body = r.json()
    assert body["error"]["code"] == "BAD_REQUEST"
    assert body["error"]["retryable"] is False


def test_uncaught_exception_returns_500(engine_mods, monkeypatch):
    """未捕获异常 → 500 + INTERNAL_ERROR 统一结构（全局 handler，不改变 err() 路径）。

    Starlette 的 ServerErrorMiddleware 处理完 base Exception 后会原样再上抛一次
    （供服务端日志记录），TestClient 默认 raise_server_exceptions=True 会把这次
    上抛带进测试——故此处显式关掉，只断言已发出的 500 响应体。
    """
    def boom():
        raise RuntimeError("boom")
    monkeypatch.setattr(engine_mods.clients, "opening", boom)
    c = TestClient(engine_mods.main.app, raise_server_exceptions=False)
    r = c.post("/api/game", json={"mode": "pvp"})
    assert r.status_code == 500
    assert r.json() == {"error": {"code": "INTERNAL_ERROR",
                                  "message": "服务器内部错误", "retryable": False}}

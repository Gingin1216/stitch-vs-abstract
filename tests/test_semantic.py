"""P3 纯逻辑单元测试（离线，无网络 / 无服务依赖）。

运行：python3 test_semantic.py    （或 pytest test_semantic.py）
强制走伪向量，验证 embeddings 映射与 wordbank 清洗/发牌的纯逻辑正确性。
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "semantic"))
os.environ["EMBED_OFFLINE"] = "1"
os.environ.pop("LLM_API_KEY", None)

from embeddings import cosine_distance, cosine_similarity, embed, to_jump  # noqa: E402
import wordbank  # noqa: E402


def test_identical_distance_zero():
    v = embed("秦始皇")
    assert cosine_distance(v, v) < 1e-6
    assert cosine_similarity(v, v) > 0.9999


def test_jump_monotonic_and_bounds():
    low = to_jump(cosine_distance(embed("便利店"), embed("我今天走进了一家便利店。")))
    high = to_jump(cosine_distance(embed("秦始皇"), embed("我今天走进了一家便利店。")))
    assert 0 <= low <= high <= 100
    assert to_jump(0.0) == 0
    assert to_jump(1.0) == 100
    for d in (0.0, 0.3, 0.5, 0.9, 1.0):
        assert 0 <= to_jump(d) <= 100


def test_wordbank_structure():
    cards = wordbank.load_wordbank()["cards"]
    words = {c["word"] for c in cards}
    assert len(words) == len(cards), "词库存在重复词"
    assert all(c["level"] in (1, 2, 3) for c in cards)
    deal = wordbank.sample_deal_cards(cards, seed=42)
    assert wordbank.validate_deal(deal), "发牌未满足 2/2/1 梯度结构"


def test_wordbank_clean_and_forbidden():
    raw = [
        {"word": "关东煮", "level": 1},
        {"word": "关东煮", "level": 2},
        {"word": "秦始皇", "level": 3},
        {"word": "", "level": 1},
        {"word": "黑洞", "level": 99},
    ]
    cleaned = wordbank.clean_cards(raw)
    assert len(cleaned) == 2
    assert wordbank.is_forbidden({"word": "秦始皇", "level": 3})
    assert not wordbank.is_forbidden({"word": "关东煮", "level": 1})


def _run() -> int:
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    fails = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            fails += 1
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{'全部通过' if fails == 0 else f'{fails} 项失败'}")
    return fails


if __name__ == "__main__":
    raise SystemExit(1 if _run() else 0)
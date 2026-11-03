"""词库离线预生成与清洗脚本（P3）。

生成 semantic/wordbank.json，供 P2 发牌 Agent 兜底补位使用。用法（在 semantic/ 目录下）：
    python3 generate_wordbank.py
产物是干净词库：去重、level 合法、每档数量足以支撑 2/2/1 梯度发牌。
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from wordbank import clean_cards

OUT = Path(__file__).with_name("wordbank.json")

# 三级梯度：日常(1) / 抽象(2) / 违禁(3)。tag 默认按档位，个别词可覆盖（如知乎梗）。
TAG_OVERRIDE = {"谢邀": "知乎梗", "先问是不是": "知乎梗", "人均985": "知乎梗", "年薪百万": "知乎梗"}

RAW: dict[int, list[str]] = {
    1: [
        "关东煮", "小票", "找零", "收银台", "冰柜", "塑料袋", "矿泉水", "充电宝",
        "报纸", "雨伞", "咖啡", "面包", "牙刷", "拖鞋", "钥匙", "公交卡",
        "外卖", "快递", "抹布", "铅笔", "电梯", "红绿灯", "泡面", "洗衣机",
        "遥控器", "吸管", "创可贴", "橡皮", "台灯", "闹钟",
    ],
    2: [
        "量子力学", "相对论", "平行宇宙", "熵增", "存在主义", "荒诞", "元宇宙",
        "内卷", "躺平", "区块链", "正态分布", "二次元", "梦境", "灵魂",
        "时间悖论", "无限循环", "出圈", "五险一金", "赛博朋克", "概率云",
        "谢邀", "先问是不是", "人均985", "年薪百万",
    ],
    3: [
        "秦始皇", "黑洞", "宇宙大爆炸", "第四面墙", "时空管理局", "平行世界线",
        "坍缩", "母体", "神", "降维打击", "永动机", "规则类怪谈", "克苏鲁",
        "虫洞", "复活", "大家都死了", "世界线收束", "缸中之脑",
    ],
}


def main() -> None:
    cards: list[dict] = []
    default_tag = {1: "日常", 2: "抽象", 3: "违禁"}
    for level, words in RAW.items():
        for w in words:
            cards.append({"word": w, "level": level, "tag": TAG_OVERRIDE.get(w, default_tag[level])})
    cards = clean_cards(cards)

    data = {
        "meta": {"levels": {1: "日常", 2: "抽象", 3: "违禁"}, "structure": {1: 2, 2: 2, 3: 1}},
        "cards": cards,
    }
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    counts = Counter(c["level"] for c in cards)
    print(f"生成 {len(cards)} 张词卡：L1 日常={counts[1]}，L2 抽象={counts[2]}，L3 违禁={counts[3]} → {OUT}")


if __name__ == "__main__":
    main()
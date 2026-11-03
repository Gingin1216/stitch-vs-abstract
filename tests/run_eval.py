"""判分回归脚本（P3）：跑评测集，检查裁判 Agent 输出是否落在预期区间。
用法：先启动 agents 服务（真实模式），再 python3 run_eval.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import httpx

AGENTS_URL = os.getenv("AGENTS_URL", "http://localhost:8002")
EVAL_SET = json.loads((Path(__file__).parent / "eval_set.json").read_text("utf-8"))

failures = 0

for case in EVAL_SET["judge_abstract"]:
    res = httpx.post(f"{AGENTS_URL}/agents/judge_abstract", json={
        "sentence": case["sentence"], "picked_word": case["picked_word"],
        "word_level": case["word_level"], "round": 1,
    }, timeout=30).json()
    for field, (lo, hi) in case["expect"].items():
        v = res.get(field, -1)
        ok = lo <= v <= hi
        failures += 0 if ok else 1
        print(f"[{'OK' if ok else 'FAIL'}] abstract/{case['picked_word']} "
              f"{field}={v} (期望 {lo}-{hi})  # {case['why']}")

for case in EVAL_SET["judge_stitch"]:
    res = httpx.post(f"{AGENTS_URL}/agents/judge_stitch", json={
        "sentence_before": case["sentence_before"],
        "picked_word": case["picked_word"],
    }, timeout=30).json()
    for field, (lo, hi) in case["expect"].items():
        v = res.get(field, -99)
        ok = lo <= v <= hi
        failures += 0 if ok else 1
        print(f"[{'OK' if ok else 'FAIL'}] stitch/{case['picked_word']} "
              f"{field}={v} (期望 {lo}-{hi})  # {case['why']}")

print(f"\n回归结果：{'全部通过' if failures == 0 else f'{failures} 项漂移，需检查 prompt'}")

"""P3 语义层回归脚本（对运行中的服务打 HTTP，校验 §3 契约与跳度/近义行为）。

用法：先启动服务
    cd semantic && python3 -m uvicorn main:app --port 8003
再（在 tests/ 目录下）：
    python3 run_semantic_eval.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import httpx

SEMANTIC_URL = os.getenv("SEMANTIC_URL", "http://localhost:8003")
EVAL_SET = json.loads((Path(__file__).parent / "eval_set.json").read_text("utf-8"))

failures = 0

for case in EVAL_SET.get("semantic", []):
    if case["api"] == "jump":
        res = httpx.post(
            f"{SEMANTIC_URL}/semantic/jump",
            json={"sentence": case["sentence"], "word": case["word"]},
            timeout=30,
        ).json()
        score = res.get("jump_score", -1)
        lo, hi = case["expect"]["jump_score"]
        ok = lo <= score <= hi
        failures += 0 if ok else 1
        print(
            f"[{'OK' if ok else 'FAIL'}] jump/{case['word']} jump_score={score} "
            f"(期望 {lo}-{hi}) distance={res.get('distance')}  # {case['why']}"
        )
    elif case["api"] == "similar":
        res = httpx.post(
            f"{SEMANTIC_URL}/semantic/similar",
            json={
                "word": case["word"],
                "history": case["history"],
                "threshold": case.get("threshold", 0.75),
            },
            timeout=30,
        ).json()
        ok = res.get("is_duplicate") == case["expect"]["is_duplicate"]
        failures += 0 if ok else 1
        print(
            f"[{'OK' if ok else 'FAIL'}] similar/{case['word']} "
            f"is_duplicate={res.get('is_duplicate')} "
            f"(期望 {case['expect']['is_duplicate']}) sim={res.get('similarity')}  # {case['why']}"
        )

print(f"\n回归结果：{'全部通过' if failures == 0 else f'{failures} 项漂移'}")
raise SystemExit(1 if failures else 0)
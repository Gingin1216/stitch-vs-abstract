# 崩坏缝合局（Stitch vs. Abstract）

> 基于多 Agent 协作的语言博弈对抗游戏 —— 知乎黑客松暨第一届"软工菁英"技术创新应用 Agent 开发比赛参赛作品

抽象派玩家负责把句子搞崩坏，缝合派玩家负责把逻辑圆回来，AI 裁判按量化的语义跳度 + 多维 rubric 判卷，刘看山解说员终局复盘。五回合后，世界是被抽象毁灭，还是被强行缝合？

## 系统架构

```
┌──────────┐  HTTP   ┌───────────────┐  HTTP  ┌────────────────┐
│ frontend │ ◄─────► │ engine (8001) │ ◄────► │ agents (8002)  │ ──► 看山工作台 LLM
│  (P4)    │         │ 游戏引擎 P1    │        │ Agent 层 P2     │
└──────────┘         │               │ ◄────► │ semantic(8003) │ ──► Embedding API
                     └───────────────┘        │ 语义评估 P3     │
                                              └────────────────┘
```

四个 Agent：发牌 / 裁判（抽象）/ 裁判（缝合，Tool Calling 调语义跳度）/ 压缩 / 解说。
契约文档见 [API.md](API.md)；接口写死响应见 [mock/mock_agents.json](mock/mock_agents.json)。

## 快速开始（Mock 模式，无需任何 API Key）

```bash
pip install -r requirements.txt

# 终端 1：语义层（离线伪向量兜底，仅用于打通链路）
cd semantic && python3 -m uvicorn main:app --port 8003

# 终端 2：Agent 层（MOCK=1 时直接返回 mock/mock_agents.json 的写死数据）
cd agents && MOCK=1 python3 -m uvicorn main:app --port 8002

# 终端 3：游戏引擎
cd engine && python3 -m uvicorn main:app --port 8001

# 创建一局
curl -X POST localhost:8001/api/game -H 'Content-Type: application/json' -d '{"mode":"pvp"}'
```

## 接入看山工作台（真实模式）

复制 `.env.example` 为 `.env` 并填入看山工作台提供的 API 地址与 Key，然后各服务带环境变量启动（去掉 `MOCK=1`）：

| 变量 | 说明 |
|---|---|
| `LLM_BASE_URL` / `LLM_API_KEY` | 看山工作台对话接口 |
| `LLM_MODEL` / `LLM_MODEL_STRONG` | 快模型（发牌/压缩）/ 旗舰模型（裁判/解说） |
| `EMBED_MODEL` | Embedding 模型名 |
| `EMBED_OFFLINE` | 语义降级开关：默认 `1`（无 Key/异常时降级伪向量），置 `0` 则异常上抛 `AGENT_TIMEOUT` |

## 目录结构

```
├── engine/      # P1 游戏引擎：回合状态机、结算、兜底（不含任何 prompt）
├── agents/      # P2 Agent 层：5 个 Agent 的 prompt、tool calling、结构化输出
├── semantic/    # P3 语义评估：跳度计算、近义检测、离线兜底
├── frontend/    # P4 前端（见 frontend/README.md）
├── mock/        # 写死响应 + 一局完整对局时间线（前端联调用）
├── tests/       # P3 判分评测集与回归脚本（改 prompt 后必跑）
├── API.md       # 四方接口契约（v1.1 已冻结）
└── requirements.txt
```

## P3 语义层约定（改 embedding 模型 / 断网联调必读）

- **跳度映射公式**：`jump_score` 由 `semantic/embeddings.py` 的 `to_jump()` 计算——余弦距离在 `[CALIB_LO, CALIB_HI]=[0.30, 0.90]` 内线性映射到 0-100，距离 ≤0.30 → 0 分、≥0.90 → 100 分。**更换 embedding 模型后必须重新标定这两个常量**（用几组已知「相关/无关」词对实测）。
- **离线伪向量兜底**：`embed()` 在无 `LLM_API_KEY` 或接口失败时降级到确定性单字哈希伪向量（`EMBED_OFFLINE=1`，默认）。语义精度有限，仅供 Mock 联调打通链路；无 Key 时端口 8003 可直接秒起。
- **词库再生成**：`semantic/wordbank.json` 是 `semantic/generate_wordbank.py` 生成的产物，改词库改脚本后重跑，否则会被覆盖：
  ```bash
  cd semantic && python3 generate_wordbank.py
  ```
- **回归命令**（改 `agents/prompts.py` 或 `semantic/` 后必跑）：
  ```bash
  cd tests && python3 test_semantic.py        # P3 纯逻辑单测，离线无前置
  cd tests && python3 run_semantic_eval.py    # 需先起 semantic:8003
  cd tests && python3 run_eval.py             # 需先起 agents:8002（真实模式）
  ```

## 分工

| 成员 | 模块 | 核心技术栈 |
|---|---|---|
| P1 | engine/ | FastAPI、状态机、容错兜底 |
| P2 | agents/ | Prompt 工程、JSON Schema、Tool Calling、看山工作台 |
| P3 | semantic/ + tests/ | Embedding、余弦相似度、评测集回归 |
| P4 | frontend/ | React/Vue、动画、Canvas 战报海报、演示视频 |


成员P2有一点需要同步给队友的：judge_abstract 请求新增了可选字段 used_words，不传完全不影响（契约未破坏），但 P1 传上来后裁判就能自行查换皮重复词，建议 P1 顺手加上。另外 MOCK 模式下用 httpx 自测时记得 trust_env=False，否则本机代理会劫持 localhost 请求。
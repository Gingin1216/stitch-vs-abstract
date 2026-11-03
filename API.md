# API 接口契约（v1.1 · 已冻结）

> 项目：「崩坏缝合局」—— 基于多 Agent 协作的语言博弈对抗游戏
> 本文件是四个模块（前端 P4 / 游戏引擎 P1 / Agent 层 P2 / 语义评估层 P3）之间的**唯一契约**。
> 冻结后任何字段变更必须四人全票通过并更新版本号与变更记录。

## 0. 模块边界

- P1 **不包含任何 prompt**，只调 P2/P3 接口；P2 不知道状态机；P3 不知道游戏存在。
- P2 的裁判 Agent 通过 Tool Calling 调用 P3 的跳度接口（agentic 设计，比赛加分项）。

## 1. 通用约定

- UTF-8 / `application/json`；字段 snake_case；分数均为整数。
- 统一错误格式：

```json
{ "error": { "code": "AGENT_TIMEOUT", "message": "裁判 Agent 响应超时", "retryable": true } }
```

| code | 含义 | 行为 |
|---|---|---|
| `AGENT_TIMEOUT` | Agent 超时（>10s） | 重试 1 次，失败用兜底文案 |
| `AGENT_BAD_JSON` | 输出不符合 Schema | 重试 1 次，失败用兜底 |
| `INVALID_STATE` | 状态机不允许该操作 | 提示并刷新状态 |
| `WORD_DUPLICATE` | 选词与历史重复/近义 | 提示重选，不扣回合 |

- **兜底原则：任何 Agent 挂了，游戏必须能继续**（引擎内置兜底文案库）。

## 2. P1 → P2：Agent 层接口

### 2.1 开局 `POST /agents/opening`
```json
// 请求
{ "theme": "daily", "seed": 42 }
// 响应
{ "sentence": "我今天走进了一家便利店。" }
```

### 2.2 发牌 `POST /agents/deal`
```json
// 请求
{ "sentence": "...", "round": 2, "used_words": ["量子力学"], "zhihu_flavor": true }
// 响应：词卡梯度必须 2 普通 + 2 抽象 + 1 违禁，引擎负责校验，不合格重试一次后从离线词库补位
{ "cards": [
  { "word": "关东煮", "level": 1, "tag": "日常" },
  { "word": "小票",   "level": 1, "tag": "日常" },
  { "word": "量子力学", "level": 2, "tag": "抽象" },
  { "word": "谢邀",   "level": 2, "tag": "知乎梗" },
  { "word": "秦始皇", "level": 3, "tag": "违禁" }
] }
```

### 2.3 裁判（抽象派）`POST /agents/judge_abstract`
```json
// 请求
{ "sentence": "我今天走进了一家便利店。", "picked_word": "秦始皇", "word_level": 3, "round": 1 }
// 响应
{ "jump_score": 92, "score": 88,
  "comment": "便利店里坐着秦始皇，时空管理局已受理本案。",
  "collapse_delta": 22, "invalid_narrative": false,
  "sentence_after": "我今天走进了一家便利店，收银台后坐着秦始皇。" }
```
- `jump_score` 必须由裁判 Agent 通过 Tool Calling 调 §3.1 获得，禁止自估。
- 违禁词（level 3）若 `invalid_narrative=true`：score=0。
- `sentence_after`（v1.1 新增）：把词编进句子后的新句子，≤40 字。

### 2.4 裁判（缝合派）`POST /agents/judge_stitch`
```json
// 请求（v1.1：不再传 sentence_after，由 Agent 生成）
{ "sentence_before": "我今天走进了一家便利店，收银台后坐着秦始皇。", "picked_word": "小票" }
// 响应
{ "logic": 8, "fluency": 7, "surprise": 9, "score": 80,
  "comment": "用'统一度量衡的小票'圆回秦始皇收银，典故级缝合。",
  "collapse_delta": -25,
  "sentence_after": "收银台后的秦始皇递给我一张统一度量衡的小票。" }
```
- `score = logic*4 + fluency*3 + surprise*3`，由引擎按公式复核。
- `collapse_delta`：-30~0；完全没圆回来为 0。

### 2.5 压缩 `POST /agents/rewrite`
```json
// 请求
{ "story": "……完整故事……" }
// 响应：≤30 字，保留离谱元素；引擎校验超长自动截断并重试一次
{ "sentence": "便利店秦始皇收银，关东煮在量子隧穿。" }
```

### 2.6 解说 `POST /agents/commentary`
```json
// 请求
{ "rounds": [ { "round": 1, "a_word": "秦始皇", "a_score": 88, "b_word": "小票", "b_score": 80 } ],
  "winner": "A", "final_story": "便利店找零找出一个宇宙。" }
// 响应（刘看山口吻棋评）
{ "text": "……谢邀，便利店已倒闭。" }
```

## 3. P1 → P3：语义评估层接口

### 3.1 跳度 `POST /semantic/jump`
```json
// 请求
{ "sentence": "我今天走进了一家便利店。", "word": "秦始皇" }
// 响应：distance 为余弦距离；jump_score 的映射公式归 P3 所有
{ "distance": 0.83, "jump_score": 92 }
```

### 3.2 近义检测 `POST /semantic/similar`
```json
// 请求
{ "word": "米线", "history": ["米粉", "尖叫"], "threshold": 0.75 }
// 响应
{ "is_duplicate": true, "closest": "米粉", "similarity": 0.81 }
```

## 4. P1 → P4：前端对局 API

### 4.1 状态机
```
CREATED → {A|B}_TURN → 判卷 → 另一方 TURN → 判卷 → 压缩
        → 下一回合发牌 → … 5 回合 → FINISHED
```
奇数回合 A 先手，偶数回合 B 先手（`first` 字段标记）；前端不得本地推演状态。

### 4.2 接口

**创建对局 `POST /api/game`**
```json
// 请求
{ "mode": "pvp" }
// 响应
{ "game_id": "g_7f3a2", "state": "A_TURN", "round": 1, "first": "A",
  "sentence": "我今天走进了一家便利店。", "collapse": 50, "score_a": 0, "score_b": 0,
  "cards": [ { "word": "关东煮", "level": 1, "tag": "日常" } ] }
```

**拉取状态 `GET /api/game/{game_id}`**：同上结构，另含 `history`、`collapse_curve`。

**选词 `POST /api/game/{game_id}/pick`**
```json
// 请求
{ "role": "A", "word": "秦始皇" }
// 响应
{ "state": "B_TURN", "sentence": "……秦始皇。", "collapse": 72,
  "judge": { "score": 88, "comment": "……", "detail": { "jump_score": 92 } } }
```

**战报 `GET /api/game/{game_id}/report`**
```json
{ "winner": "A", "verdict": "世界被抽象毁灭",
  "final_story": "便利店找零找出一个宇宙。",
  "collapse_curve": [50, 47, 53, 47, 55, 66],
  "score_a": 405, "score_b": 359,
  "commentary": "……",
  "poster": { "title": "崩坏缝合局 · 战报", "mvp_word": "秦始皇",
              "best_comment": "坍缩一次积一分，末日也能攒兑换，格局打开。" } }
```
- 终局 `collapse > 70` → A 胜；`< 30` → B 胜；其间平局（半疯状态）。

## 5. Mock 约定

- `mock/mock_agents.json` 含 §2 全部接口写死响应及一局完整对局时间线（前端联调用）。
- Agent 服务 `MOCK=1` 时读 mock 返回，不调看山工作台。
- Day1 21:00 节点①：MOCK=1 全链路跑通；Day2 上午切真实 Agent。

## 6. 变更记录

| 版本 | 变更 | 通过人 |
|---|---|---|
| v1 | 初版冻结 | 全员 |
| v1.1 | 裁判接口由 Agent 生成并返回 `sentence_after`；缝合判卷请求移除该字段 | 全员 |

"""Kimi（Moonshot）LLM 调用封装（P2）。

五件事：
1. **结构化输出**：优先用 OpenAI 兼容的 `response_format=json_schema` 强约束字段，
   平台不支持时自动降级为「prompt 内约束 + 正则抠 JSON」，上层代码无感。
2. **Tool Calling 循环**：裁判 Agent 自主调用 P3 语义接口，循环直到模型给出终稿。
3. **墙钟总预算**：整次 chat_json（含全部 tool 轮次与 BAD_JSON 重试）不得超过
   AGENT_TOTAL_BUDGET 秒（默认 10，必须 < ENGINE_TIMEOUT=12，给 engine 留 2s 余量）。
   每轮发起前检查剩余预算，单次 completion 的 timeout 传剩余值；预算耗尽立即抛
   AGENT_TIMEOUT，不再发起新 completion——agents 侧保证 10s 内必有响应。
4. **输出长度上限**：max_tokens 按角色收紧（裁判 512 / 创作 1024 / 压缩 256）。
   不设上限时慢模型无限制生成，是首包超时的主要来源。
5. **耗时观测 + 429 退避**：每次 completion 落一条日志（模型/轮次/耗时/max_tokens/
   剩余预算）；429（RPM 限流）按平台提示秒数退避重试（同样吃总预算），
   把瞬时限流转成短等待，而不是立刻 504 让 engine 走兜底。
超时/连接失败 → AGENT_TIMEOUT；字段不合规 → 重试 1 次后 AGENT_BAD_JSON（契约 §1）。
"""
from __future__ import annotations

import json
import logging
import os
import re
import time

from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    OpenAI,
)

from errors import AGENT_BAD_JSON, AGENT_TIMEOUT, AgentError

_logger = logging.getLogger("agents.llm")
_logger.setLevel(logging.INFO)
if not logging.getLogger("agents").handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    logging.getLogger("agents").addHandler(_h)
    logging.getLogger("agents").setLevel(logging.INFO)

# 契约 §1：单次 completion 上限 10s+1s 抖动余量。整次调用的墙钟总预算见
# AGENT_TOTAL_BUDGET——每轮 timeout 取 min(本值, 剩余预算)，二者不叠加。
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "11"))

# 整次调用（含 tool 轮次与重试）的墙钟总预算，必须比 engine 的 ENGINE_TIMEOUT（默认 12s）
# 小，agents 才能先给出确定响应，而不是让 engine 干等到自己的超时。
AGENT_TOTAL_BUDGET = float(os.getenv("AGENT_TOTAL_BUDGET", "10"))

# tool calling 轮次上限：每轮都是一次完整 completion，轮数直接乘总耗时。
MAX_ROUNDS = int(os.getenv("AGENT_MAX_ROUNDS", "3"))

# 429（RPM 限流）退避重试次数。Moonshot 试用档 org 可能只有个位数 RPM，
# 瞬时超限按平台提示等待后重试；等待同样消耗总预算。
RETRY_429_TIMES = int(os.getenv("LLM_429_RETRIES", "2"))

# 模型名 404（resource_not_found_error）重试次数。Moonshot 网关多副本路由表
# 不一致时，合法模型名会随机落到不认识它的副本上返回 404——短等待后换副本重试。
# 真没权限的模型重试到上限后照样失败，不会无限循环。
MODEL_404_RETRIES = int(os.getenv("LLM_404_RETRIES", "3"))

# 输出长度上限（按角色）：裁判只产结构化短 JSON，压缩越短越好。
MAX_TOKENS_JUDGE = int(os.getenv("MAX_TOKENS_JUDGE", "512"))
MAX_TOKENS_CREATIVE = int(os.getenv("MAX_TOKENS_CREATIVE", "1024"))
MAX_TOKENS_REWRITE = int(os.getenv("MAX_TOKENS_REWRITE", "256"))

client = OpenAI(
    base_url=os.environ.get("LLM_BASE_URL", "https://api.moonshot.cn/v1"),
    api_key=os.environ.get("LLM_API_KEY", "none"),
    timeout=LLM_TIMEOUT,
    max_retries=0,  # 重试策略由 chat_json 统一掌握，避免叠加等待超过契约上限
)
# 全链路默认同一个便宜快模型；实测分层后再单独配 LLM_MODEL_STRONG。
# 注意：账号可用模型名以 /models 或实测为准（部分账号裸名 v1 下线、仅有 v1-auto）。
MODEL = os.getenv("LLM_MODEL", "moonshot-v1-auto")
STRONG_MODEL = os.getenv("LLM_MODEL_STRONG", MODEL)
TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.8"))
# 裁判判分要可复现（P3 回归评测集靠它），默认比创作类低
JUDGE_TEMPERATURE = float(os.getenv("LLM_JUDGE_TEMPERATURE", "0.3"))

# 平台不支持 function calling 时置 0，裁判改用 prefetch 兜底（见 main.py）
TOOL_CALLING_SUPPORTED = os.getenv("TOOL_CALLING_SUPPORTED", "1") == "1"
# 平台不支持 json_schema 时置 0；运行期探测到不支持也会自动关掉
STRUCTURED_OUTPUT_SUPPORTED = os.getenv("STRUCTURED_OUTPUT_SUPPORTED", "1") == "1"

_UNSUPPORTED_HINTS = ("response_format", "json_schema", "json schema",
                      "unsupported", "not support")
_RETRY_AFTER_RE = re.compile(r"try again after (\d+) seconds", re.I)


def parse_json(text: str) -> dict:
    """从模型输出中抠出 JSON（容忍 ```json 围栏和首尾废话）。"""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise AgentError(AGENT_BAD_JSON, f"输出中找不到 JSON: {text[:100]}")
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise AgentError(AGENT_BAD_JSON, f"JSON 解析失败: {e}")


def _schema_unsupported(err: Exception) -> bool:
    """区分「平台不支持 json_schema」与「真的请求出错」。"""
    if not isinstance(err, APIStatusError) or err.status_code not in (400, 404, 422):
        return False
    text = str(err).lower()
    return any(h in text for h in _UNSUPPORTED_HINTS)


def _retry_after_seconds(err: Exception) -> float:
    """从 Moonshot 429 message 解析建议等待秒数（缺省 1s，封顶 5s）。"""
    m = _RETRY_AFTER_RE.search(str(err))
    return min(float(m.group(1)) if m else 1.0, 5.0)


def _complete(model: str, messages: list, tools: list | None,
              schema: dict | None, temperature: float,
              timeout: float | None, max_tokens: int | None,
              budget_left: float | None):
    """单次 completion 调用（含 429 退避与 json_schema 能力探测降级）。

    timeout/max_tokens 均为单次请求粒度：timeout 由调用方按剩余预算传入。
    瞬时限流（429）与网关副本路由抖动（model-404）分类退避重试；退避消耗
    budget_left（剩余总预算），不足以退避时直接抛 AGENT_TIMEOUT。
    """
    global STRUCTURED_OUTPUT_SUPPORTED
    kwargs: dict = {"model": model, "messages": messages,
                    "temperature": temperature}
    if tools:
        kwargs["tools"] = tools
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    if timeout:
        kwargs["timeout"] = timeout
    use_schema = schema if (schema and STRUCTURED_OUTPUT_SUPPORTED) else None
    if use_schema:
        kwargs["response_format"] = use_schema
    left = budget_left
    n429 = n404 = 0

    def _sleep(wait: float, why: str, n: int, cap: int) -> None:
        nonlocal left
        if left is not None:
            if left <= wait + 0.1:
                raise AgentError(
                    AGENT_TIMEOUT,
                    f"总预算不足以退避{why}（需 {wait:.1f}s，剩余 {left:.1f}s）")
            left -= wait
        _logger.warning("completion %s | model=%s wait=%.1fs retry=%d/%d",
                        why, model, wait, n, cap)
        time.sleep(wait)

    while True:
        try:
            return client.chat.completions.create(**kwargs)
        except APIStatusError as e:
            text = str(e).lower()
            if e.status_code == 429 and n429 < RETRY_429_TIMES:
                n429 += 1
                _sleep(_retry_after_seconds(e), "429", n429, RETRY_429_TIMES)
                continue
            if (e.status_code == 404 and "not found the model" in text
                    and n404 < MODEL_404_RETRIES):
                n404 += 1
                _sleep(1.0, "model-404", n404, MODEL_404_RETRIES)
                continue
            if use_schema and _schema_unsupported(e):
                # 平台不吃 json_schema：永久降级，立刻用 prompt 约束重试
                STRUCTURED_OUTPUT_SUPPORTED = False
                use_schema = None
                kwargs.pop("response_format", None)
                continue
            raise AgentError(AGENT_TIMEOUT, f"LLM 调用失败: {e}")
        except (APITimeoutError, APIConnectionError) as e:
            raise AgentError(AGENT_TIMEOUT, f"LLM 调用超时/不可达: {e}")


def chat_json(system: str, user: str, *, strong: bool = False,
              tools: list | None = None, tool_executor=None,
              required_keys: tuple = (), schema: dict | None = None,
              normalizer=None, trace: list | None = None,
              temperature: float | None = None,
              max_rounds: int = MAX_ROUNDS,
              max_tokens: int | None = None,
              total_budget: float | None = None) -> dict:
    """带 tool calling 循环的结构化 JSON 对话（受墙钟总预算约束）。

    normalizer：schemas.normalize_*，返回夹到契约区间后的数据；抛 AgentError 则触发重试。
    trace：传入一个 list 时，按序记录模型发起的工具调用（用于 /agents/health 与演示取证）。
    total_budget：整次调用的墙钟上限（秒），默认 AGENT_TOTAL_BUDGET；每轮发起前检查
    剩余预算并作为本轮 timeout，耗尽立即抛 AGENT_TIMEOUT，不再发起新 completion。
    """
    messages: list = [{"role": "system", "content": system},
                      {"role": "user", "content": user}]
    use_tools = tools if (tools and TOOL_CALLING_SUPPORTED) else None
    temp = TEMPERATURE if temperature is None else temperature
    model = STRONG_MODEL if strong else MODEL
    budget = AGENT_TOTAL_BUDGET if total_budget is None else total_budget
    start = time.monotonic()
    deadline = start + budget
    last_err: AgentError | None = None

    def _remaining() -> float:
        return deadline - time.monotonic()

    for _attempt in range(2):  # 契约 §1：AGENT_BAD_JSON 重试 1 次
        try:
            for round_ in range(1, max_rounds + 1):
                remaining = _remaining()
                if remaining <= 0:
                    raise AgentError(
                        AGENT_TIMEOUT,
                        f"总预算 {budget:.0f}s 耗尽（第 {round_} 轮发起前放弃）")
                call_timeout = min(LLM_TIMEOUT, remaining)
                t0 = time.monotonic()
                try:
                    resp = _complete(model, messages, use_tools, schema, temp,
                                     call_timeout, max_tokens, _remaining())
                except AgentError as e:
                    _logger.warning(
                        "completion fail | model=%s round=%d/%d elapsed=%.2fs "
                        "max_tokens=%s err=%s", model, round_, max_rounds,
                        time.monotonic() - t0, max_tokens, e.message)
                    raise
                msg = resp.choices[0].message
                _logger.info(
                    "completion ok | model=%s round=%d/%d elapsed=%.2fs "
                    "max_tokens=%s budget_left=%.2fs tool_calls=%d",
                    model, round_, max_rounds, time.monotonic() - t0,
                    max_tokens, _remaining(), len(msg.tool_calls or []))
                if msg.tool_calls and tool_executor:
                    messages.append(msg)
                    for tc in msg.tool_calls:
                        try:
                            args = json.loads(tc.function.arguments or "{}")
                        except json.JSONDecodeError:
                            args = {}
                        t1 = time.monotonic()
                        result = tool_executor(tc.function.name, args)
                        _logger.info("tool call | %s args=%s elapsed=%.2fs",
                                     tc.function.name,
                                     json.dumps(args, ensure_ascii=False),
                                     time.monotonic() - t1)
                        if trace is not None:
                            trace.append({"tool": tc.function.name,
                                          "arguments": args, "result": result})
                        messages.append({
                            "role": "tool", "tool_call_id": tc.id,
                            "content": json.dumps(result, ensure_ascii=False),
                        })
                    continue
                data = parse_json(msg.content or "")
                missing = [k for k in required_keys if k not in data]
                if missing:
                    raise AgentError(AGENT_BAD_JSON, f"缺字段: {missing}")
                out = normalizer(data) if normalizer else data
                _logger.info("chat_json done | model=%s elapsed=%.2fs "
                             "rounds=%d result=ok", model,
                             time.monotonic() - start, round_)
                return out
            raise AgentError(AGENT_BAD_JSON, "tool 循环超限")
        except AgentError as e:
            last_err = e
            if e.code == AGENT_TIMEOUT:
                _logger.info("chat_json done | model=%s elapsed=%.2fs "
                             "result=%s: %s", model,
                             time.monotonic() - start, e.code, e.message)
                raise  # 超时重试没意义，直接交给引擎走兜底文案
            messages.append({"role": "user", "content":
                             f"上次输出不合规（{e.message}）。请严格按 schema "
                             "重新输出 JSON，不要输出任何解释文字。"})
    _logger.info("chat_json done | model=%s elapsed=%.2fs result=%s: %s",
                 model, time.monotonic() - start, last_err.code,
                 last_err.message)
    raise last_err or AgentError(AGENT_BAD_JSON, "未知解析失败")

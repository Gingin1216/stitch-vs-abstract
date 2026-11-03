"""Agent 层统一错误类型（P2）。独立成模块，避免 llm / schemas / tools 循环依赖。

错误码与 API.md §1 的错误表一一对应：
- AGENT_TIMEOUT：上游（LLM / 语义层）超时或不可用，可重试
- AGENT_BAD_JSON：模型输出不符合 §2 的结构约定，重试 1 次后仍失败
"""
from __future__ import annotations

AGENT_TIMEOUT = "AGENT_TIMEOUT"
AGENT_BAD_JSON = "AGENT_BAD_JSON"

# 契约 §1：retryable 标记由错误码决定，前端/引擎据此决定是否重试
RETRYABLE = {AGENT_TIMEOUT: True, AGENT_BAD_JSON: True}

# 对外 HTTP 状态码：引擎把任何非 2xx 都视作 Agent 不可用并走兜底文案
HTTP_STATUS = {AGENT_TIMEOUT: 504, AGENT_BAD_JSON: 502}


class AgentError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)

    @property
    def status_code(self) -> int:
        return HTTP_STATUS.get(self.code, 500)

    def to_payload(self) -> dict:
        """契约 §1 的统一错误格式。"""
        return {"error": {"code": self.code, "message": self.message,
                          "retryable": RETRYABLE.get(self.code, False)}}

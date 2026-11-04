import {
  GameApiError,
  type GameClient,
  type GameMode,
  type GameReport,
  type GameSnapshot,
  type PickResult,
  type Role,
} from "./types";

const REQUEST_TIMEOUT_MS = 12_000;

interface ApiErrorBody {
  error?: {
    code?: string;
    message?: string;
    retryable?: boolean;
  };
  detail?: {
    error?: {
      code?: string;
      message?: string;
      retryable?: boolean;
    };
  };
}

export class HttpGameClient implements GameClient {
  readonly mode = "remote" as const;
  private readonly baseUrl: string;

  constructor(baseUrl = import.meta.env.VITE_API_BASE_URL ?? "/api") {
    this.baseUrl = baseUrl.replace(/\/$/, "");
  }

  createGame(mode: GameMode): Promise<GameSnapshot> {
    return this.request<GameSnapshot>("/game", {
      method: "POST",
      body: JSON.stringify({ mode }),
    });
  }

  getGame(gameId: string): Promise<GameSnapshot> {
    return this.request<GameSnapshot>(`/game/${encodeURIComponent(gameId)}`);
  }

  pick(gameId: string, role: Role, word: string): Promise<PickResult> {
    return this.request<PickResult>(
      `/game/${encodeURIComponent(gameId)}/pick`,
      {
        method: "POST",
        body: JSON.stringify({ role, word }),
      },
    );
  }

  getReport(gameId: string): Promise<GameReport> {
    return this.request<GameReport>(
      `/game/${encodeURIComponent(gameId)}/report`,
    );
  }

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    const controller = new AbortController();
    const timeout = window.setTimeout(
      () => controller.abort(),
      REQUEST_TIMEOUT_MS,
    );

    try {
      const response = await fetch(`${this.baseUrl}${path}`, {
        ...init,
        headers: {
          "Content-Type": "application/json",
          ...init?.headers,
        },
        signal: controller.signal,
      });

      const data = (await response.json()) as T | ApiErrorBody;
      if (!response.ok) {
        const body = data as ApiErrorBody;
        const apiError = body.error ?? body.detail?.error;
        throw new GameApiError(
          apiError?.code ?? "HTTP_ERROR",
          apiError?.message ?? `请求失败（${response.status}）`,
          response.status,
          apiError?.retryable ?? false,
        );
      }
      return data as T;
    } catch (error) {
      if (error instanceof GameApiError) {
        throw error;
      }
      if (error instanceof DOMException && error.name === "AbortError") {
        throw new GameApiError(
          "AGENT_TIMEOUT",
          "裁判响应超时",
          0,
          true,
        );
      }
      throw new GameApiError("NETWORK_ERROR", "无法连接游戏引擎");
    } finally {
      window.clearTimeout(timeout);
    }
  }
}

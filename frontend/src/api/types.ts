export type GameMode = "pvp" | "pve";
export type Role = "A" | "B";
export type CardLevel = 1 | 2 | 3;

export interface WordCard {
  word: string;
  level: CardLevel;
  tag: string;
}

export interface GameHistoryEntry {
  round: number;
  a_word?: string;
  a_score?: number;
  a_comment?: string;
  b_word?: string;
  b_score?: number;
  b_comment?: string;
  sentence?: string;
  collapse?: number;
}

export interface GameSnapshot {
  game_id: string;
  state: string;
  round: number;
  first: Role;
  sentence: string;
  collapse: number;
  score_a: number;
  score_b: number;
  cards: WordCard[];
  history?: GameHistoryEntry[];
  collapse_curve?: number[];
}

export interface JudgeResult {
  score: number;
  comment: string;
  detail?: Record<string, unknown>;
}

export interface PickResult extends GameSnapshot {
  judge: JudgeResult;
}

export interface GameReport {
  winner: Role | "DRAW";
  verdict: string;
  final_story: string;
  collapse_curve: number[];
  score_a: number;
  score_b: number;
  commentary: string;
  poster: {
    title: string;
    mvp_word: string;
    best_comment: string;
  };
}

export interface GameClient {
  readonly mode: "mock" | "remote";
  createGame(mode: GameMode): Promise<GameSnapshot>;
  getGame(gameId: string): Promise<GameSnapshot>;
  pick(gameId: string, role: Role, word: string): Promise<PickResult>;
  getReport(gameId: string): Promise<GameReport>;
}

export class GameApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly retryable: boolean;

  constructor(
    code: string,
    message: string,
    status = 0,
    retryable = false,
  ) {
    super(message);
    this.name = "GameApiError";
    this.code = code;
    this.status = status;
    this.retryable = retryable;
  }
}

export function expectedRole(snapshot: GameSnapshot): Role | null {
  if (snapshot.state === "A_TURN" || snapshot.state === "B_TURN") {
    return snapshot.state[0] as Role;
  }
  return null;
}

export function errorMessage(error: unknown): string {
  if (error instanceof GameApiError) {
    if (error.code === "WORD_DUPLICATE") {
      return "这张词与历史选词重复，请换一张。";
    }
    if (error.code === "AGENT_TIMEOUT") {
      return "裁判响应超时，当前进度已保留，可以再试一次。";
    }
    if (error.code === "INVALID_STATE") {
      return "对局状态已变化，进度已刷新，请重新选择。";
    }
    return error.message;
  }
  return "连接服务失败，请稍后再试。";
}

import sharedMockData from "../../../mock/mock_agents.json";

import {
  GameApiError,
  type CardLevel,
  type GameClient,
  type GameMode,
  type GameReport,
  type GameSnapshot,
  type PickResult,
  type Role,
  type WordCard,
} from "./types";

interface RecordedPick {
  word: string;
  score: number;
  comment: string;
  collapse_delta: number;
}

interface RecordedRound {
  round: number;
  first: Role;
  opening?: string;
  cards: string[];
  a_pick: RecordedPick;
  sentence_after_a?: string;
  b_pick: RecordedPick;
  rewritten: string;
  collapse: number;
}

interface SharedMock {
  _frontend_full_game_mock: {
    game_id: string;
    rounds: RecordedRound[];
    report: GameReport;
  };
}

interface MockClientOptions {
  latencyMs?: number;
}

const CARD_POSITIONS: Array<{ level: CardLevel; tag: string }> = [
  { level: 1, tag: "日常" },
  { level: 1, tag: "日常" },
  { level: 2, tag: "抽象" },
  { level: 2, tag: "知乎梗" },
  { level: 3, tag: "违禁" },
];

const sharedMock = sharedMockData as unknown as SharedMock;
const rounds = sharedMock._frontend_full_game_mock.rounds;

function clamp(value: number, low = 0, high = 100): number {
  return Math.max(low, Math.min(high, value));
}

function adaptCards(words: string[]): WordCard[] {
  return words.slice(0, 5).map((word, index) => ({
    word,
    level: CARD_POSITIONS[index].level,
    tag: CARD_POSITIONS[index].tag,
  }));
}

function firstRole(round: number): Role {
  return round % 2 === 1 ? "A" : "B";
}

function fallbackJudge(role: Role, card: WordCard): RecordedPick {
  if (role === "A") {
    const score = card.level === 3 ? 86 : card.level === 2 ? 62 : 28;
    return {
      word: card.word,
      score,
      comment: `${card.word}闯进了现场，故事的物理法则开始报警。`,
      collapse_delta: card.level === 3 ? 22 : card.level === 2 ? 14 : 6,
    };
  }

  const score = card.level === 1 ? 76 : card.level === 2 ? 67 : 58;
  return {
    word: card.word,
    score,
    comment: `用${card.word}给这段混乱续了一口气。`,
    collapse_delta: card.level === 1 ? -18 : -11,
  };
}

function cloneSnapshot(snapshot: GameSnapshot): GameSnapshot {
  return {
    ...snapshot,
    cards: snapshot.cards.map((card) => ({ ...card })),
    history: snapshot.history?.map((entry) => ({ ...entry })) ?? [],
    collapse_curve: [...(snapshot.collapse_curve ?? [])],
  };
}

export class MockGameClient implements GameClient {
  readonly mode = "mock" as const;
  private readonly latencyMs: number;
  private gameId = sharedMock._frontend_full_game_mock.game_id;
  private gameMode: GameMode = "pvp";
  private round = 1;
  private state = "A_TURN";
  private sentence = "";
  private collapse = 50;
  private scoreA = 0;
  private scoreB = 0;
  private cards: WordCard[] = [];
  private usedWords = new Set<string>();
  private history: GameSnapshot["history"] = [];
  private collapseCurve: number[] = [50];

  constructor(options: MockClientOptions = {}) {
    this.latencyMs = options.latencyMs ?? 560;
  }

  async createGame(mode: GameMode): Promise<GameSnapshot> {
    this.gameMode = mode;
    this.round = 1;
    this.state = "A_TURN";
    this.sentence = rounds[0].opening ?? "我今天走进了一家便利店。";
    this.collapse = 50;
    this.scoreA = 0;
    this.scoreB = 0;
    this.usedWords.clear();
    this.history = [];
    this.collapseCurve = [50];
    this.cards = this.cardsForRound(1);

    if (mode === "pve" && this.currentFirst === "B") {
      this.applyRecordedPick("B", this.cards[0]);
    }
    return cloneSnapshot(this.snapshot());
  }

  async getGame(_gameId: string): Promise<GameSnapshot> {
    return cloneSnapshot(this.snapshot());
  }

  async getReport(gameId: string): Promise<GameReport> {
    if (gameId !== this.gameId) {
      throw new GameApiError("NOT_FOUND", "对局不存在", 404);
    }
    if (this.state !== "FINISHED") {
      throw new GameApiError("INVALID_STATE", "对局尚未结束", 409);
    }

    const recorded = sharedMock._frontend_full_game_mock.report;
    const mvp = [...rounds]
      .map((round) => round.a_pick)
      .sort((left, right) => right.score - left.score)[0];
    const bestStitch = [...rounds]
      .map((round) => round.b_pick)
      .sort((left, right) => right.score - left.score)[0];

    return {
      ...recorded,
      winner: this.reportWinner,
      verdict: this.reportVerdict,
      final_story: this.sentence,
      collapse_curve: [...this.collapseCurve],
      score_a: this.scoreA,
      score_b: this.scoreB,
      commentary: this.reportCommentary,
      poster: {
        ...recorded.poster,
        mvp_word: mvp?.word ?? "",
        best_comment: bestStitch?.comment ?? recorded.poster.best_comment,
      },
    };
  }

  async pick(gameId: string, role: Role, word: string): Promise<PickResult> {
    if (gameId !== this.gameId) {
      throw new GameApiError("NOT_FOUND", "对局不存在", 404);
    }
    if (this.state.startsWith("FINISHED")) {
      throw new GameApiError("INVALID_STATE", "对局已经结束", 409);
    }
    const currentRole = this.state[0] as Role;
    if (role !== currentRole) {
      throw new GameApiError("INVALID_STATE", "当前不是该玩家回合", 409);
    }

    const card = this.cards.find((item) => item.word === word);
    if (!card) {
      throw new GameApiError("INVALID_STATE", "所选词不在本回合词卡中", 409);
    }
    if (this.usedWords.has(word)) {
      throw new GameApiError("WORD_DUPLICATE", "该词已经使用过", 409);
    }

    if (this.latencyMs > 0) {
      await new Promise((resolve) => window.setTimeout(resolve, this.latencyMs));
    }

    const judge = this.applyRecordedPick(role, card);
    const roundWasFirst = role === this.currentFirst;

    if (roundWasFirst) {
      const nextRole: Role = role === "A" ? "B" : "A";
      this.state = `${nextRole}_TURN`;
      if (this.gameMode === "pve" && nextRole === "B") {
        this.autoStitch();
        this.finishRound();
      }
    } else {
      this.finishRound();
    }

    return {
      ...cloneSnapshot(this.snapshot()),
      judge: {
        score: judge.score,
        comment: judge.comment,
        detail: {
          jump_score:
            role === "A"
              ? card.level === 3
                ? 92
                : card.level === 2
                  ? 66
                  : 24
              : undefined,
        },
      },
    };
  }

  private get currentFirst(): Role {
    return firstRole(this.round);
  }

  private get reportWinner(): Role | "DRAW" {
    if (this.collapse > 70) {
      return "A";
    }
    if (this.collapse < 30) {
      return "B";
    }
    return "DRAW";
  }

  private get reportVerdict(): string {
    if (this.reportWinner === "A") {
      return "世界被抽象毁灭";
    }
    if (this.reportWinner === "B") {
      return "逻辑被强行缝合";
    }
    return "半疯状态，平局";
  }

  private get reportCommentary(): string {
    const result =
      this.reportWinner === "A"
        ? "抽象派成功夺走了解释权，世界规则已经停止工作。"
        : this.reportWinner === "B"
          ? "缝合派不断回收失控设定，故事勉强恢复了因果。"
          : "双方都没能彻底夺走解释权，世界停在半疯状态。";
    return `五回合交锋，A 方累计 ${this.scoreA} 分，B 方累计 ${this.scoreB} 分。最终崩坏度 ${this.collapse}，${this.reportVerdict}。${result}`;
  }

  private cardsForRound(round: number): WordCard[] {
    return adaptCards(rounds[round - 1]?.cards ?? []);
  }

  private applyRecordedPick(role: Role, card: WordCard): RecordedPick {
    const round = rounds[this.round - 1];
    const recorded = role === "A" ? round.a_pick : round.b_pick;
    const judge = recorded.word === card.word ? recorded : fallbackJudge(role, card);

    if (role === "A") {
      this.scoreA += judge.score;
    } else {
      this.scoreB += judge.score;
    }
    this.collapse = clamp(this.collapse + judge.collapse_delta);
    this.usedWords.add(card.word);
    this.sentence = this.sentenceAfter(role, card.word, round);
    return judge;
  }

  private autoStitch(): void {
    const card =
      this.cards.find((item) => item.level === 1) ?? this.cards[0];
    if (card) {
      this.applyRecordedPick("B", card);
      this.state = "A_TURN";
    }
  }

  private sentenceAfter(
    role: Role,
    word: string,
    round: RecordedRound,
  ): string {
    if (role === "A" && word === round.a_pick.word && round.sentence_after_a) {
      return round.sentence_after_a;
    }
    if (role === "B" && word === round.b_pick.word) {
      // v1.1 requires sentence_after from the judge. The shared frontend
      // fixture predates that field, so the compressed sentence is isolated
      // here as a temporary adapter.
      return round.rewritten;
    }
    return `${this.sentence.replace(/[。！？]$/, "")}，${word}闯入了故事。`;
  }

  private finishRound(): void {
    const round = rounds[this.round - 1];
    this.sentence = round.rewritten;
    this.history = [
      ...(this.history ?? []),
      {
        round: this.round,
        sentence: this.sentence,
        collapse: this.collapse,
      },
    ];
    this.collapseCurve = [...this.collapseCurve, this.collapse];

    if (this.round >= 5) {
      this.state = "FINISHED";
      this.cards = [];
      return;
    }

    this.round += 1;
    this.sentence = round.rewritten;
    this.cards = this.cardsForRound(this.round);
    this.state = `${this.currentFirst}_TURN`;

    if (this.gameMode === "pve" && this.currentFirst === "B") {
      this.autoStitch();
    }
  }

  private snapshot(): GameSnapshot {
    return {
      game_id: this.gameId,
      state: this.state,
      round: this.round,
      first: this.currentFirst,
      sentence: this.sentence,
      collapse: this.collapse,
      score_a: this.scoreA,
      score_b: this.scoreB,
      cards: this.cards,
      history: this.history,
      collapse_curve: this.collapseCurve,
    };
  }
}

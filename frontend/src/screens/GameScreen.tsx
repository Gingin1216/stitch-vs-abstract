import {
  Bot,
  Clock3,
  LogOut,
  RotateCcw,
  Sparkles,
  Swords,
  UserRound,
  WifiOff,
} from "lucide-react";

import type { GameMode, Role } from "../api";
import { expectedRole, type GameSnapshot } from "../api";
import type { JudgePresentation } from "../app/App";
import { CollapseMeter } from "../components/CollapseMeter";
import { JudgePanel } from "../components/JudgePanel";
import { StoryText } from "../components/StoryText";
import { WordCardButton } from "../components/WordCardButton";

interface GameScreenProps {
  snapshot: GameSnapshot;
  gameMode: GameMode;
  judge: JudgePresentation | null;
  busy: boolean;
  error: string;
  mode: "mock" | "remote";
  onPick: (role: Role, word: string) => void;
  onDismissJudge: () => void;
  onExit: () => void;
}

function roleLabel(role: Role | null): string {
  if (role === "A") {
    return "抽象派";
  }
  if (role === "B") {
    return "缝合派";
  }
  return "对局结束";
}

function roleHint(role: Role | null): string {
  if (role === "A") {
    return "把句子推向失控";
  }
  if (role === "B") {
    return "把混乱圆回逻辑";
  }
  return "五回合已封存";
}

export function GameScreen({
  snapshot,
  gameMode,
  judge,
  busy,
  error,
  mode,
  onPick,
  onDismissJudge,
  onExit,
}: GameScreenProps) {
  const currentRole = expectedRole(snapshot);
  const isFinished = snapshot.state === "FINISHED" || !currentRole;
  const cardsLocked = busy || Boolean(judge) || isFinished;
  const turnRole = currentRole;

  return (
    <div className="game-shell">
      <header className="game-header">
        <button className="compact-brand" onClick={onExit} type="button">
          <Sparkles size={17} />
          <span>崩坏缝合局</span>
        </button>

        <div className="round-marker">
          <span>ROUND</span>
          <strong>{String(snapshot.round).padStart(2, "0")}</strong>
          <span>/ 05</span>
        </div>

        <div className="game-meta">
          <span className="data-mode compact">
            <span className="data-mode-dot" />
            {mode === "mock" ? "MOCK" : "LIVE"}
          </span>
          <button
            className="icon-button"
            onClick={onExit}
            title="退出当前对局"
            type="button"
          >
            <LogOut size={18} />
            <span className="sr-only">退出当前对局</span>
          </button>
        </div>
      </header>

      <main className="game-main">
        <section className="battle-strip" aria-label="对局状态">
          <ScoreBlock
            active={turnRole === "A"}
            label="抽象派"
            role="A"
            score={snapshot.score_a}
          />

          <div className="turn-core">
            <span className="turn-status">
              {isFinished ? (
                <RotateCcw size={18} />
              ) : busy ? (
                <Clock3 className="spin" size={18} />
              ) : (
                <Swords size={18} />
              )}
              {isFinished ? "FINISHED" : busy ? "JUDGING" : "ACTIVE TURN"}
            </span>
            <strong>{roleLabel(turnRole)}</strong>
            <span>
              {gameMode === "pve" && turnRole === "A"
                ? "B 方自动执行缝合"
                : roleHint(turnRole)}
            </span>
          </div>

          <ScoreBlock
            active={turnRole === "B"}
            label="缝合派"
            role="B"
            score={snapshot.score_b}
          />
        </section>

        <CollapseMeter value={snapshot.collapse} />

        <section className="story-stage" aria-labelledby="story-title">
          <div className="story-heading">
            <span id="story-title">CURRENT STORY</span>
            <span>{snapshot.first} 方先手</span>
          </div>
          <StoryText sentence={snapshot.sentence} />
          <div className="story-foot">
            <span>WORLD LINE {String(snapshot.round).padStart(2, "0")}</span>
            <span>
              {gameMode === "pve" ? (
                <>
                  <Bot size={14} />
                  {snapshot.round % 2 === 0
                    ? "B 方已自动缝合"
                    : "B 方将在本轮自动缝合"}
                </>
              ) : (
                <>NO ROLLBACK</>
              )}
            </span>
          </div>
        </section>

        {error ? (
          <div className="game-error" role="alert">
            <WifiOff size={18} />
            <span>{error}</span>
            <span className="error-kept">进度已保留</span>
          </div>
        ) : null}

        {isFinished ? (
          <section className="finished-panel" aria-labelledby="finished-title">
            <span className="section-code">WORLD LINE SEALED</span>
            <h2 id="finished-title">五回合完成</h2>
            <p>最终崩坏度 {snapshot.collapse}，故事已封存。</p>
            <button className="primary-button" onClick={onExit} type="button">
              <RotateCcw size={18} />
              返回开局
            </button>
          </section>
        ) : (
          <section className="card-dock" aria-labelledby="cards-title">
            <div className="card-dock-heading">
              <div>
                <span className="section-code">WORD DECK · 05</span>
                <h2 id="cards-title">
                  {turnRole === "A" ? "抽取崩坏因子" : "寻找缝合接口"}
                </h2>
              </div>
              <span className={`actor-chip actor-${turnRole}`}>
                {turnRole === "A" ? (
                  <UserRound size={15} />
                ) : gameMode === "pve" && turnRole === "B" ? (
                  <Bot size={15} />
                ) : (
                  <UserRound size={15} />
                )}
                {turnRole} 方操作
              </span>
            </div>

            <div className="word-grid">
              {snapshot.cards.map((card, index) => (
                <WordCardButton
                  card={card}
                  disabled={cardsLocked}
                  index={index}
                  key={`${snapshot.round}-${card.word}`}
                  onPick={(word) => turnRole && onPick(turnRole, word)}
                />
              ))}
            </div>
          </section>
        )}
      </main>

      {judge ? (
        <JudgePanel
          finished={isFinished}
          judge={judge}
          onContinue={onDismissJudge}
        />
      ) : null}
    </div>
  );
}

interface ScoreBlockProps {
  active: boolean;
  label: string;
  role: Role;
  score: number;
}

function ScoreBlock({ active, label, role, score }: ScoreBlockProps) {
  return (
    <div className={`score-block score-${role} ${active ? "is-active" : ""}`}>
      <span>{role}</span>
      <div>
        <strong>{score}</strong>
        <span>{label}</span>
      </div>
    </div>
  );
}

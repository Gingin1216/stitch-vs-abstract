import { ArrowRight, Gavel, Sparkles } from "lucide-react";

import type { JudgePresentation } from "../app/App";

interface JudgePanelProps {
  judge: JudgePresentation;
  finished: boolean;
  onContinue: () => void;
}

export function JudgePanel({
  judge,
  finished,
  onContinue,
}: JudgePanelProps) {
  const jumpScore = judge.detail?.jump_score;

  return (
    <div className="judge-backdrop" role="presentation">
      <section
        className="judge-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="judge-title"
      >
        <div className="judge-kicker">
          <Gavel size={16} />
          REFEREE VERDICT · {judge.actor} 方
        </div>
        <div className="judge-score-row">
          <div>
            <span id="judge-title">本轮得分</span>
            <strong data-testid="judge-score">{judge.score}</strong>
          </div>
          {typeof jumpScore === "number" ? (
            <div className="jump-score">
              <span>语义跳度</span>
              <strong>{jumpScore}</strong>
            </div>
          ) : null}
        </div>
        <p className="judge-comment">{judge.comment}</p>
        <div className="judge-selected">
          <Sparkles size={16} />
          <span>「{judge.word}」已写入故事</span>
        </div>
        <button className="primary-button" onClick={onContinue} type="button">
          {finished ? "查看终局" : "继续对局"}
          <ArrowRight size={18} />
        </button>
      </section>
    </div>
  );
}

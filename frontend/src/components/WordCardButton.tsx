import type { WordCard } from "../api";

interface WordCardButtonProps {
  card: WordCard;
  disabled: boolean;
  index: number;
  onPick: (word: string) => void;
}

// 仅用于无障碍标签（aria-label）；视觉上不展示词属性（日常/抽象/违禁）
const levelMeta = {
  1: "日常",
  2: "抽象",
  3: "违禁",
} as const;

export function WordCardButton({
  card,
  disabled,
  index,
  onPick,
}: WordCardButtonProps) {
  return (
    <button
      aria-label={`${levelMeta[card.level]}词：${card.word}`}
      className="word-card"
      data-testid="word-card"
      disabled={disabled}
      onClick={() => onPick(card.word)}
      style={{ "--card-index": index } as React.CSSProperties}
      type="button"
    >
      <span className="word-card-topline">
        <span className="card-index">0{index + 1}</span>
      </span>
      <strong>{card.word}</strong>
    </button>
  );
}

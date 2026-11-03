import { Atom, ShieldCheck, Skull, Sparkles } from "lucide-react";

import type { WordCard } from "../api";

interface WordCardButtonProps {
  card: WordCard;
  disabled: boolean;
  index: number;
  onPick: (word: string) => void;
}

const levelMeta = {
  1: { label: "日常", Icon: ShieldCheck },
  2: { label: "抽象", Icon: Atom },
  3: { label: "违禁", Icon: Skull },
} as const;

export function WordCardButton({
  card,
  disabled,
  index,
  onPick,
}: WordCardButtonProps) {
  const meta = levelMeta[card.level];
  const Icon = card.level === 3 ? Skull : card.level === 2 ? Atom : ShieldCheck;

  return (
    <button
      aria-label={`${meta.label}词：${card.word}`}
      className={`word-card word-card-level-${card.level}`}
      data-testid="word-card"
      disabled={disabled}
      onClick={() => onPick(card.word)}
      style={{ "--card-index": index } as React.CSSProperties}
      type="button"
    >
      <span className="word-card-topline">
        <span className="risk-label">
          <Icon size={14} strokeWidth={2.2} />
          {meta.label}
        </span>
        <span className="card-index">0{index + 1}</span>
      </span>
      <strong>{card.word}</strong>
      <span className="word-card-tag">{card.tag}</span>
      <span className="word-card-corner" aria-hidden="true">
        {card.level === 3 ? <Sparkles size={40} /> : null}
      </span>
    </button>
  );
}

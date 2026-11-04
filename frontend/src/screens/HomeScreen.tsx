import {
  ArrowRight,
  Bot,
  Radio,
  Sparkles,
  Swords,
} from "lucide-react";

import type { GameMode } from "../api";

interface HomeScreenProps {
  busy: boolean;
  error: string;
  mode: "mock" | "remote";
  onStart: (mode: GameMode) => void;
}

const modes: Array<{
  id: GameMode;
  eyebrow: string;
  title: string;
  description: string;
  icon: typeof Swords;
}> = [
  {
    id: "pvp",
    eyebrow: "LOCAL DUEL",
    title: "双人同屏",
    description: "两名玩家轮流接管抽象与缝合两边。",
    icon: Swords,
  },
  {
    id: "pve",
    eyebrow: "SOLO RUN",
    title: "人机对战",
    description: "你执抽象派，AI 自动完成每一轮缝合。",
    icon: Bot,
  },
];

export function HomeScreen({
  busy,
  error,
  mode,
  onStart,
}: HomeScreenProps) {
  return (
    <div className="home-shell">
      <header className="home-header">
        <a className="brand" href="/" aria-label="崩坏缝合局首页">
          <span className="brand-mark">
            <Sparkles size={18} strokeWidth={2.4} />
          </span>
          <span>崩坏缝合局</span>
        </a>
        <span className="data-mode">
          <span className="data-mode-dot" />
          {mode === "mock" ? "模拟数据" : "真实接口"}
        </span>
      </header>

      <main className="home-main">
        <section className="home-intro" aria-labelledby="game-title">
          <div className="season-label">
            <Radio size={14} />
            <span>FIVE ROUNDS · ONE COLLAPSE</span>
          </div>
          <h1 id="game-title">
            把逻辑<span>拆开</span>
            <br />
            再强行<span>缝上</span>
          </h1>
          <p>
            抽象派制造混乱，缝合派夺回解释权。
            <br />
            五个回合后，只剩一种世界线。
          </p>
        </section>

        <section className="mode-picker" aria-labelledby="mode-title">
          <div className="section-heading">
            <span>SELECT SIDE</span>
            <h2 id="mode-title">选择对战方式</h2>
          </div>

          <div className="mode-options">
            {modes.map(({ id, eyebrow, title, description, icon: Icon }) => (
              <button
                className="mode-card"
                disabled={busy}
                key={id}
                onClick={() => onStart(id)}
                type="button"
              >
                <span className="mode-icon">
                  <Icon size={26} strokeWidth={1.8} />
                </span>
                <span className="mode-copy">
                  <span className="mode-eyebrow">{eyebrow}</span>
                  <strong>{title}</strong>
                  <span>{description}</span>
                </span>
                <ArrowRight className="mode-arrow" size={22} />
              </button>
            ))}
          </div>

          {error ? (
            <p className="inline-error" role="alert">
              {error}
            </p>
          ) : null}

          <p className="home-footnote">
            A 方增加崩坏度 · B 方回收崩坏度 · 第五回合定局
          </p>
        </section>
      </main>
    </div>
  );
}

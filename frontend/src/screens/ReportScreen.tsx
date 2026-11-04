import {
  Activity,
  Download,
  Quote,
  RotateCcw,
  Sparkles,
  Trophy,
} from "lucide-react";
import { useState } from "react";

import type { GameMode, GameReport } from "../api";
import { downloadReportPoster } from "../lib/reportPoster";

interface ReportScreenProps {
  report: GameReport;
  gameMode: GameMode;
  gameId: string;
  mode: "mock" | "remote";
  onRestart: () => void;
}

function winnerLabel(report: GameReport) {
  if (report.winner === "A") {
    return "抽象派获胜";
  }
  if (report.winner === "B") {
    return "缝合派获胜";
  }
  return "平局 · 世界线失衡";
}

function curvePoints(values: number[]) {
  const safeValues = values.length > 0 ? values : [50];
  return safeValues
    .map((value, index) => {
      const x = 12 + (index / Math.max(1, safeValues.length - 1)) * 376;
      const y = 108 - (Math.max(0, Math.min(100, value)) / 100) * 88;
      return `${x},${y}`;
    })
    .join(" ");
}

export function ReportScreen({
  report,
  gameMode,
  gameId,
  mode,
  onRestart,
}: ReportScreenProps) {
  const [downloadState, setDownloadState] = useState<"idle" | "done" | "error">(
    "idle",
  );
  const lastCollapse = report.collapse_curve.at(-1) ?? 50;
  const totalScore = report.score_a + report.score_b;
  const abstractShare =
    totalScore > 0 ? Math.round((report.score_a / totalScore) * 100) : 50;

  function handleDownload() {
    try {
      downloadReportPoster(report, gameId);
      setDownloadState("done");
    } catch {
      setDownloadState("error");
    }
  }

  return (
    <div className={`report-shell winner-${report.winner.toLowerCase()}`}>
      <header className="report-header">
        <div className="compact-brand">
          <Sparkles size={18} />
          <span>崩坏缝合局</span>
        </div>
        <div className="report-header-meta">
          <span className="data-mode compact">
            <span className="data-mode-dot" />
            {mode === "mock" ? "MOCK REPORT" : "LIVE REPORT"}
          </span>
          <span className="report-game-id">{gameId}</span>
        </div>
      </header>

      <main className="report-main">
        <section className="report-hero" aria-labelledby="report-title">
          <div className="report-hero-copy">
            <span className="section-code">FINAL WORLD LINE · 05 ROUNDS</span>
            <h1 id="report-title">{winnerLabel(report)}</h1>
            <p>{report.verdict}</p>
            <span className="report-mode">
              {gameMode === "pve" ? "人机对战" : "双人同屏"}
            </span>
          </div>

          <div className="report-final-score" aria-label="最终比分">
            <div className="report-side-score side-a">
              <span>A</span>
              <strong>{report.score_a}</strong>
              <small>抽象派</small>
            </div>
            <div className="report-score-divider">
              <span>FINAL</span>
              <strong>{lastCollapse}</strong>
              <small>崩坏度</small>
            </div>
            <div className="report-side-score side-b">
              <span>B</span>
              <strong>{report.score_b}</strong>
              <small>缝合派</small>
            </div>
          </div>
        </section>

        <section className="report-story-band" aria-labelledby="story-result">
          <div className="report-section-heading">
            <span className="section-code">SEALED STORY</span>
            <h2 id="story-result">最终故事</h2>
          </div>
          <blockquote>{report.final_story}</blockquote>
        </section>

        <div className="report-insight-grid">
          <section className="report-curve" aria-labelledby="curve-title">
            <div className="report-section-heading inline">
              <div>
                <span className="section-code">COLLAPSE CURVE</span>
                <h2 id="curve-title">五回合崩坏轨迹</h2>
              </div>
              <Activity size={22} />
            </div>
            <svg
              aria-label="崩坏度变化曲线"
              className="curve-chart"
              role="img"
              viewBox="0 0 400 120"
            >
              <line className="curve-midline" x1="12" x2="388" y1="64" y2="64" />
              <polyline className="curve-line" points={curvePoints(report.collapse_curve)} />
              {report.collapse_curve.map((value, index) => {
                const length = Math.max(1, report.collapse_curve.length - 1);
                const x = 12 + (index / length) * 376;
                const y = 108 - (Math.max(0, Math.min(100, value)) / 100) * 88;
                return (
                  <circle
                    className="curve-point"
                    cx={x}
                    cy={y}
                    key={`${index}-${value}`}
                    r="4"
                  />
                );
              })}
            </svg>
            <div className="curve-labels">
              <span>START 50</span>
              <span>FINAL {lastCollapse}</span>
            </div>
          </section>

          <section className="report-commentary" aria-labelledby="commentary-title">
            <Quote size={24} />
            <div className="report-section-heading inline">
              <div>
                <span className="section-code">AI COMMENTARY</span>
                <h2 id="commentary-title">终局解说</h2>
              </div>
            </div>
            <p>{report.commentary}</p>
          </section>
        </div>

        <section className="report-awards" aria-label="本局高光">
          <div className="award-item">
            <Trophy size={20} />
            <span>MVP 词卡</span>
            <strong>{report.poster.mvp_word || "无"}</strong>
          </div>
          <div className="award-item">
            <Sparkles size={20} />
            <span>最佳缝合</span>
            <p>{report.poster.best_comment || report.verdict}</p>
          </div>
          <div className="award-item score-share">
            <span>SCORE SHARE</span>
            <div className="score-share-track" aria-hidden="true">
              <span style={{ width: `${abstractShare}%` }} />
            </div>
            <strong>
              A {abstractShare}% / B {100 - abstractShare}%
            </strong>
          </div>
        </section>

        <div className="report-actions">
          <button className="primary-button" onClick={handleDownload} type="button">
            <Download size={18} />
            {downloadState === "done" ? "海报已下载" : "下载战报海报"}
          </button>
          <button className="secondary-button" onClick={onRestart} type="button">
            <RotateCcw size={18} />
            再来一局
          </button>
          {downloadState === "error" ? (
            <p className="report-download-error" role="alert">
              海报生成失败，请刷新页面后重试。
            </p>
          ) : null}
        </div>
      </main>
    </div>
  );
}

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { GameReport } from "../api";
import { downloadReportPoster } from "../lib/reportPoster";
import { ReportScreen } from "./ReportScreen";

vi.mock("../lib/reportPoster", () => ({
  downloadReportPoster: vi.fn(),
}));

const report: GameReport = {
  winner: "A",
  verdict: "世界被抽象毁灭",
  final_story: "便利店找零找出一个宇宙。",
  collapse_curve: [50, 47, 53, 47, 55, 76],
  score_a: 405,
  score_b: 359,
  commentary: "A 方在最后一回合完成了宇宙级操作，世界线彻底失去解释。",
  poster: {
    title: "崩坏缝合局 · 战报",
    mvp_word: "秦始皇",
    best_comment: "用统一度量衡的小票圆回秦始皇收银。",
  },
};

describe("ReportScreen", () => {
  it("shows the final result, story and commentary", () => {
    render(
      <ReportScreen
        gameId="g_test"
        gameMode="pvp"
        mode="mock"
        onRestart={vi.fn()}
        report={report}
      />,
    );

    expect(
      screen.getByRole("heading", { name: "抽象派获胜" }),
    ).toBeInTheDocument();
    expect(screen.getByText(report.final_story)).toBeInTheDocument();
    expect(screen.getByText(report.commentary)).toBeInTheDocument();
    expect(screen.getByText(report.poster.mvp_word)).toBeInTheDocument();
  });

  it("downloads the generated Canvas poster", () => {
    render(
      <ReportScreen
        gameId="g_test"
        gameMode="pve"
        mode="mock"
        onRestart={vi.fn()}
        report={report}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /下载战报海报/ }));

    expect(vi.mocked(downloadReportPoster)).toHaveBeenCalledWith(
      report,
      "g_test",
    );
    expect(
      screen.getByRole("button", { name: "海报已下载" }),
    ).toBeInTheDocument();
  });
});

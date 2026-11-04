import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { GameSnapshot } from "../api";
import { GameScreen } from "./GameScreen";

const snapshot: GameSnapshot = {
  game_id: "g_test",
  state: "A_TURN",
  round: 1,
  first: "A",
  sentence: "我今天走进了一家便利店。",
  collapse: 50,
  score_a: 0,
  score_b: 0,
  cards: [
    { word: "关东煮", level: 1, tag: "日常" },
    { word: "小票", level: 1, tag: "日常" },
    { word: "量子力学", level: 2, tag: "抽象" },
    { word: "谢邀", level: 2, tag: "知乎梗" },
    { word: "秦始皇", level: 3, tag: "违禁" },
  ],
};

describe("GameScreen", () => {
  it("shows the round, scores, story and five cards", () => {
    render(
      <GameScreen
        busy={false}
        error=""
        gameMode="pvp"
        judge={null}
        mode="mock"
        onDismissJudge={vi.fn()}
        onExit={vi.fn()}
        onPick={vi.fn()}
        onShowReport={vi.fn()}
        reportBusy={false}
        snapshot={snapshot}
      />,
    );

    expect(screen.getAllByText("抽象派")).toHaveLength(2);
    expect(screen.getByText("我今天走进了一家便利店。")).toBeInTheDocument();
    expect(screen.getAllByTestId("word-card")).toHaveLength(5);
  });

  it("forwards the active role and selected word", () => {
    const onPick = vi.fn();
    render(
      <GameScreen
        busy={false}
        error=""
        gameMode="pvp"
        judge={null}
        mode="mock"
        onDismissJudge={vi.fn()}
        onExit={vi.fn()}
        onPick={onPick}
        onShowReport={vi.fn()}
        reportBusy={false}
        snapshot={snapshot}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "违禁词：秦始皇" }));
    expect(onPick).toHaveBeenCalledWith("A", "秦始皇");
  });

  it("locks the deck while judging", () => {
    render(
      <GameScreen
        busy
        error=""
        gameMode="pvp"
        judge={null}
        mode="mock"
        onDismissJudge={vi.fn()}
        onExit={vi.fn()}
        onPick={vi.fn()}
        onShowReport={vi.fn()}
        reportBusy={false}
        snapshot={snapshot}
      />,
    );

    for (const card of screen.getAllByTestId("word-card")) {
      expect(card).toBeDisabled();
    }
  });
});

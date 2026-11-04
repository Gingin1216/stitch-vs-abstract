import { useState } from "react";

import {
  errorMessage,
  GameApiError,
  gameClient as defaultGameClient,
  type GameClient,
  type GameMode,
  type GameReport,
  type GameSnapshot,
  type JudgeResult,
  type Role,
} from "../api";
import { GameScreen } from "../screens/GameScreen";
import { HomeScreen } from "../screens/HomeScreen";
import { ReportScreen } from "../screens/ReportScreen";

interface AppProps {
  client?: GameClient;
}

export interface JudgePresentation extends JudgeResult {
  actor: Role;
  word: string;
}

export function App({ client = defaultGameClient }: AppProps) {
  const [snapshot, setSnapshot] = useState<GameSnapshot | null>(null);
  const [report, setReport] = useState<GameReport | null>(null);
  const [gameMode, setGameMode] = useState<GameMode>("pvp");
  const [judge, setJudge] = useState<JudgePresentation | null>(null);
  const [busy, setBusy] = useState(false);
  const [reportBusy, setReportBusy] = useState(false);
  const [error, setError] = useState("");

  async function startGame(mode: GameMode) {
    setBusy(true);
    setError("");
    try {
      setGameMode(mode);
      setReport(null);
      setSnapshot(await client.createGame(mode));
      setJudge(null);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  async function pickCard(role: Role, word: string) {
    if (!snapshot) {
      return;
    }
    setBusy(true);
    setError("");
    try {
      const result = await client.pick(snapshot.game_id, role, word);
      setSnapshot(result);
      setJudge({ ...result.judge, actor: role, word });
    } catch (cause) {
      setError(errorMessage(cause));

      if (
        cause instanceof GameApiError &&
        cause.code === "INVALID_STATE" &&
        client.mode === "remote"
      ) {
        try {
          setSnapshot(await client.getGame(snapshot.game_id));
        } catch {
          // Keep the last known snapshot when refresh also fails.
        }
      }
    } finally {
      setBusy(false);
    }
  }

  async function showReport(gameId: string) {
    setJudge(null);
    setReportBusy(true);
    setError("");
    try {
      setReport(await client.getReport(gameId));
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setReportBusy(false);
    }
  }

  function resetGame() {
    setSnapshot(null);
    setReport(null);
    setJudge(null);
    setError("");
  }

  if (!snapshot) {
    return (
      <HomeScreen
        busy={busy}
        error={error}
        mode={client.mode}
        onStart={startGame}
      />
    );
  }

  if (report) {
    return (
      <ReportScreen
        gameId={snapshot.game_id}
        gameMode={gameMode}
        mode={client.mode}
        onRestart={resetGame}
        report={report}
      />
    );
  }

  return (
    <GameScreen
      snapshot={snapshot}
      gameMode={gameMode}
      judge={judge}
      busy={busy}
      error={error}
      mode={client.mode}
      onPick={pickCard}
      onDismissJudge={() => {
        if (snapshot.state === "FINISHED") {
          void showReport(snapshot.game_id);
        } else {
          setJudge(null);
        }
      }}
      onExit={resetGame}
      onShowReport={() => void showReport(snapshot.game_id)}
      reportBusy={reportBusy}
    />
  );
}

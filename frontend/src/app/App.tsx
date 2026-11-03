import { useState } from "react";

import {
  errorMessage,
  GameApiError,
  gameClient as defaultGameClient,
  type GameClient,
  type GameMode,
  type GameSnapshot,
  type JudgeResult,
  type Role,
} from "../api";
import { GameScreen } from "../screens/GameScreen";
import { HomeScreen } from "../screens/HomeScreen";

interface AppProps {
  client?: GameClient;
}

export interface JudgePresentation extends JudgeResult {
  actor: Role;
  word: string;
}

export function App({ client = defaultGameClient }: AppProps) {
  const [snapshot, setSnapshot] = useState<GameSnapshot | null>(null);
  const [gameMode, setGameMode] = useState<GameMode>("pvp");
  const [judge, setJudge] = useState<JudgePresentation | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function startGame(mode: GameMode) {
    setBusy(true);
    setError("");
    try {
      setGameMode(mode);
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

  return (
    <GameScreen
      snapshot={snapshot}
      gameMode={gameMode}
      judge={judge}
      busy={busy}
      error={error}
      mode={client.mode}
      onPick={pickCard}
      onDismissJudge={() => setJudge(null)}
      onExit={() => {
        setSnapshot(null);
        setJudge(null);
        setError("");
      }}
    />
  );
}

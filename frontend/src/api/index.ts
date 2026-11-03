import { HttpGameClient } from "./httpClient";
import { MockGameClient } from "./mockClient";
import type { GameClient } from "./types";

export const apiMode: "mock" | "remote" =
  import.meta.env.VITE_API_MODE?.toLowerCase() === "remote" ? "remote" : "mock";

export const gameClient: GameClient =
  apiMode === "remote" ? new HttpGameClient() : new MockGameClient();

export * from "./types";

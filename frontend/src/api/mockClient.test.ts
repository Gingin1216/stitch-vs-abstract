import { describe, expect, it } from "vitest";

import { MockGameClient } from "./mockClient";

function client() {
  return new MockGameClient({ latencyMs: 0 });
}

describe("MockGameClient", () => {
  it("creates an A-first game with a valid five-card deck", async () => {
    const game = await client().createGame("pvp");

    expect(game.state).toBe("A_TURN");
    expect(game.round).toBe(1);
    expect(game.first).toBe("A");
    expect(game.cards.map((card) => card.level)).toEqual([1, 1, 2, 2, 3]);
  });

  it("alternates turns and moves B to the first pick in round two", async () => {
    const gameClient = client();
    const created = await gameClient.createGame("pvp");
    const afterA = await gameClient.pick(
      created.game_id,
      "A",
      created.cards[4].word,
    );

    expect(afterA.state).toBe("B_TURN");
    expect(afterA.score_a).toBeGreaterThan(0);

    const afterB = await gameClient.pick(
      created.game_id,
      "B",
      afterA.cards[0].word,
    );

    expect(afterB.round).toBe(2);
    expect(afterB.first).toBe("B");
    expect(afterB.state).toBe("B_TURN");
    expect(afterB.score_b).toBeGreaterThan(0);
  });

  it("rejects a word already used in the same round", async () => {
    const gameClient = client();
    const created = await gameClient.createGame("pvp");
    const pickedWord = created.cards[0].word;
    await gameClient.pick(created.game_id, "A", pickedWord);

    await expect(
      gameClient.pick(created.game_id, "B", pickedWord),
    ).rejects.toMatchObject({
      code: "WORD_DUPLICATE",
    });
  });

  it("automatically performs B's stitch after A acts in PVE", async () => {
    const gameClient = client();
    const created = await gameClient.createGame("pve");
    const result = await gameClient.pick(
      created.game_id,
      "A",
      created.cards[4].word,
    );

    expect(result.round).toBe(2);
    expect(result.score_b).toBeGreaterThan(0);
    expect(result.state).toBe("A_TURN");
  });
});

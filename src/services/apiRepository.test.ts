import { afterEach, describe, expect, it, vi } from "vitest";
import { apiRepository } from "./apiRepository";

describe("apiRepository groups and games", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("loads memberships with the user's bearer token", async () => {
    const group = {
      id: "group-id",
      name: "City Night",
      publicSlug: "city-night",
      timezone: "Europe/Lisbon",
      role: "owner",
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify([group]), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(apiRepository.listGroups("session-token")).resolves.toEqual([
      group,
    ]);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/groups",
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: "Bearer session-token",
        }),
      }),
    );
  });

  it("creates a game with the server's camel-case request contract", async () => {
    const response = { game: { id: "game-id" }, joinCode: "ABCD1234" };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(response), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const game = {
      gameDate: "2026-11-23",
      startTime: "19:00",
      durationMinutes: 75,
      maxPlayers: 12,
      location: "Riverside Arena",
      courtNumber: "2",
      courtCostCents: 5000,
      currency: "EUR" as const,
      paymentInfo: "",
      playerNotice: "",
    };

    await expect(
      apiRepository.createGame("session-token", "group-id", game),
    ).resolves.toEqual(response);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/groups/group-id/games",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify(game),
        headers: expect.objectContaining({
          Authorization: "Bearer session-token",
        }),
      }),
    );
  });
});

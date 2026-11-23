import { afterEach, describe, expect, it, vi } from "vitest";
import { apiJoinCodes, apiRepository } from "./apiRepository";

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

  it("rotates a group join code and remembers it on this device", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ joinCode: "WXYZ2345" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const store = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => store.set(key, value),
      removeItem: (key: string) => store.delete(key),
    });

    const { joinCode } = await apiRepository.rotateJoinCode("session-token", "group-id");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/groups/group-id/join-code",
      expect.objectContaining({ method: "POST" }),
    );
    apiJoinCodes.save("group-id", joinCode);
    expect(apiJoinCodes.read("group-id")).toBe("WXYZ2345");
    apiJoinCodes.clear();
    expect(apiJoinCodes.read("group-id")).toBeUndefined();
  });

  it("archives a directory player with DELETE and no body", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      apiRepository.archivePlayer("session-token", "group-id", "player-id"),
    ).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/groups/group-id/players/player-id",
      expect.objectContaining({ method: "DELETE" }),
    );
  });
});

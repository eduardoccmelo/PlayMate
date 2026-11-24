import { describe, expect, it } from "vitest";
import { gameFromApi, groupFromApi, localIdForApi } from "./apiMappers";
import type {
  ApiGameDetail,
  ApiParticipant,
  ApiPlayer,
  ApiProfile,
} from "./apiRepository";

const viewer: ApiProfile = {
  id: "user-viewer",
  email: "viewer@example.com",
  displayName: "Alex",
  isStaff: false,
};

const participant = (overrides: Partial<ApiParticipant>): ApiParticipant => ({
  id: "participant-1",
  playerId: "11111111-1111-1111-1111-111111111111",
  userId: null,
  displayName: "Someone",
  status: "confirmed",
  listPosition: 0,
  paid: false,
  paymentDueAt: null,
  team: null,
  ...overrides,
});

const detail = (
  confirmed: ApiParticipant[],
  waitingList: ApiParticipant[] = [],
): ApiGameDetail => ({
  game: {
    id: "99999999-0000-0000-0000-000000000000",
    groupId: "group-1",
    publicSlug: "slug",
    gameDate: "2026-12-01",
    startTime: "19:00:00",
    endTime: null,
    durationMinutes: 90,
    location: "Arena",
    courtNumber: "2",
    courtCostCents: 4550,
    currency: "EUR",
    maxPlayers: 10,
    minPlayers: null,
    status: "active",
    cancelReason: null,
    paymentTrackingEnabled: false,
    paymentDeadlineDays: null,
    paymentInfo: "",
    playerNotice: "",
    createdByUserId: "user-admin",
  },
  viewerAccess: {
    kind: "member",
    status: "active",
    canViewDetails: true,
    canViewGroupPlayers: true,
    canJoin: true,
    canLeave: true,
    canUpdateOwnPayment: true,
    canDrawTeams: false,
    canManageGame: false,
  },
  confirmed,
  waitingList,
});

const directoryPlayer = (overrides: Partial<ApiPlayer>): ApiPlayer => ({
  id: "22222222-2222-2222-2222-222222222222",
  displayName: "Guest",
  ownerUserId: null,
  isGuest: true,
  level: null,
  mobility: null,
  condition: "neutro",
  position: "neutro",
  ...overrides,
});

describe("gameFromApi", () => {
  it("derives the end time from a server start time with seconds", () => {
    const game = gameFromApi(detail([]));
    expect(game.time).toBe("19:00");
    expect(game.endTime).toBe("20:30");
    expect(game.courtCost).toBe(45.5);
    expect(game.createdByUserId).toBe("user-admin");
  });

  it("keeps participant ids, list order and payments keyed by local player id", () => {
    const first = participant({ id: "p-a", playerId: "aaaaaaaa-0000-0000-0000-000000000000", paid: true });
    const second = participant({ id: "p-b", playerId: "bbbbbbbb-0000-0000-0000-000000000000" });
    const waiting = participant({ id: "p-c", playerId: "cccccccc-0000-0000-0000-000000000000", status: "waiting_list" });
    const game = gameFromApi(detail([first, second], [waiting]));

    const [a, b, c] = [first, second, waiting].map((entry) => localIdForApi(entry.playerId));
    expect(game.playerIds).toEqual([a, b]);
    expect(game.waitlistIds).toEqual([c]);
    expect(game.paidPlayerIds).toEqual([a]);
    expect(game.apiParticipantIdsByPlayerId).toEqual({ [a]: "p-a", [b]: "p-b", [c]: "p-c" });
  });
});

describe("gameFromApi payment settings", () => {
  it("keeps tracking on without payment details (PR #10 review)", () => {
    const base = detail([
      participant({
        playerId: "aaaaaaaa-0000-0000-0000-000000000000",
        paymentDueAt: "2026-12-03T19:00:00Z",
      }),
      participant({ id: "p-2", playerId: "bbbbbbbb-0000-0000-0000-000000000000" }),
    ]);
    const game = gameFromApi({
      ...base,
      game: { ...base.game, paymentTrackingEnabled: true, paymentDeadlineDays: 2 },
    });
    expect(game.paymentTrackingEnabled).toBe(true);
    expect(game.paymentDeadlineDays).toBe(2);
    expect(game.paymentInfo).toBe("");
    expect(game.paymentDueAtByPlayerId).toEqual({
      [localIdForApi("aaaaaaaa-0000-0000-0000-000000000000")]: "2026-12-03T19:00:00Z",
    });
  });

  it("reports tracking off even when the game is otherwise identical", () => {
    expect(gameFromApi(detail([])).paymentTrackingEnabled).toBe(false);
  });
});

describe("groupFromApi", () => {
  it("never grants ownership from an equal display name", () => {
    const namesake = participant({ displayName: viewer.displayName, userId: "user-someone-else" });
    const group = groupFromApi({
      membership: { id: "group-1", name: "Night", publicSlug: "night", timezone: "Europe/Lisbon", role: "participant" },
      directory: [],
      details: [detail([namesake])],
      viewer,
    });
    expect(group.players[0].ownerUserId).toBe("user-someone-else");
    expect(group.players[0].ownerUserId).not.toBe(viewer.id);
  });

  it("builds players from the directory and keeps archived participants renderable", () => {
    const own = directoryPlayer({
      id: "33333333-0000-0000-0000-000000000000",
      displayName: "Alex",
      ownerUserId: viewer.id,
      isGuest: false,
      level: 4,
      mobility: "rapido",
    });
    const archived = participant({ playerId: "44444444-0000-0000-0000-000000000000", displayName: "Old guest" });
    const group = groupFromApi({
      membership: { id: "group-1", name: "Night", publicSlug: "night", timezone: "Europe/Lisbon", role: "admin" },
      directory: [own, directoryPlayer({})],
      details: [detail([archived])],
      viewer,
      joinCode: "ABCD2345",
    });

    expect(group.players.map((player) => player.name)).toEqual(["Alex", "Guest", "Old guest"]);
    expect(group.players[0]).toMatchObject({ ownerUserId: viewer.id, level: 4, mobility: "rapido", isGuest: false });
    // Skill data withheld from the viewer falls back to neutral placeholders.
    expect(group.players[1]).toMatchObject({ level: 3, mobility: "neutro", isGuest: true });
    expect(group.players[2]).toMatchObject({ isGuest: true, apiId: archived.playerId });
    expect(group.admins).toEqual([expect.objectContaining({ userId: viewer.id, role: "admin" })]);
    expect(group.publicJoinCode).toBe("ABCD2345");
  });

  it("gives a participant no admin entry", () => {
    const group = groupFromApi({
      membership: { id: "group-1", name: "Night", publicSlug: "night", timezone: "Europe/Lisbon", role: "participant" },
      directory: [],
      details: [],
      viewer,
    });
    expect(group.admins).toEqual([]);
  });
});

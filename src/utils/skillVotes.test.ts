import { describe, expect, it } from "vitest";
import type { PlayerGroup } from "../types";
import {
  averageLevel,
  averageMobility,
  skillVotesFor,
} from "./skillVotes";

const group = (): PlayerGroup => ({
  id: "group",
  name: "Group",
  organizerPasscode: "secret",
  createdAt: "2026-01-01T00:00:00.000Z",
  games: [],
  requests: [],
  admins: [
    { userId: "owner", playerId: 1, displayName: "Owner", role: "owner", joinedAt: "2026-01-01T00:00:00.000Z" },
    { userId: "admin", playerId: 2, displayName: "Admin", role: "admin", joinedAt: "2026-01-01T00:00:00.000Z" },
  ],
  players: [
    { id: 1, name: "Owner", ownerUserId: "owner", level: 5, mobility: "rapido", condition: "neutro", position: "neutro" },
    { id: 2, name: "Admin", ownerUserId: "admin", level: 3, mobility: "neutro", condition: "neutro", position: "neutro" },
  ],
  skillVotes: [
    { playerId: 1, adminUserId: "owner", level: 5, mobility: 3, updatedAt: "2026-01-01T00:00:00.000Z" },
    { playerId: 1, adminUserId: "admin", level: 2, mobility: 1, updatedAt: "2026-01-01T00:00:00.000Z" },
  ],
});

describe("skill voting", () => {
  it("includes each admin ballot in the current player average", () => {
    const votes = skillVotesFor(group(), 1);
    expect(votes).toHaveLength(2);
    expect(averageLevel(votes)).toBe(4);
    expect(averageMobility(votes)).toBe("neutro");
  });

  it("uses neutral defaults when a player has no ballots", () => {
    expect(averageLevel([])).toBe(3);
    expect(averageMobility([])).toBe("neutro");
  });
});

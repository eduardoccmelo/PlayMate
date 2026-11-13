import { describe, expect, it } from "vitest";
import type { Player } from "../types";
import { generateBalancedTeams, playerScoreBreakdown } from "./teamBalancer";

const player = (id: number, overrides: Partial<Player> = {}): Player => ({
  id,
  name: `Player ${id}`,
  level: 3,
  mobility: "neutro",
  condition: "neutro",
  position: "neutro",
  ...overrides,
});

describe("playerScoreBreakdown", () => {
  it("keeps the documented neutral defaults", () => {
    expect(playerScoreBreakdown(player(1))).toEqual({
      level: 3,
      mobility: 0,
      condition: 0,
      total: 3,
    });
  });

  it("uses the goalkeeper-specific level weighting", () => {
    expect(playerScoreBreakdown(player(1, { level: 5, position: "goleiro" }))).toMatchObject({
      level: 5.25,
      total: 5.25,
    });
  });
});

describe("generateBalancedTeams", () => {
  it("assigns every player exactly once and splits two goalkeepers", () => {
    const roster = [
      player(1, { position: "goleiro", level: 5 }),
      player(2, { position: "goleiro", level: 2 }),
      player(3, { position: "defesa", level: 4 }),
      player(4, { position: "defesa", level: 2 }),
      player(5, { position: "ataque", level: 4 }),
      player(6, { position: "ataque", level: 2 }),
    ];

    const teams = generateBalancedTeams(roster);
    const assigned = [...teams.teamA, ...teams.teamB].map(({ id }) => id).sort();

    expect(assigned).toEqual([1, 2, 3, 4, 5, 6]);
    expect(teams.teamA).toHaveLength(3);
    expect(teams.teamB).toHaveLength(3);
    expect(teams.teamA.some(({ position }) => position === "goleiro")).toBe(true);
    expect(teams.teamB.some(({ position }) => position === "goleiro")).toBe(true);
  });

  it("does not treat a team-label swap as a distinct rebalance", () => {
    const roster = [player(1), player(2), player(3), player(4)];
    const previous = {
      teamA: [roster[0], roster[1]],
      teamB: [roster[2], roster[3]],
      sumA: 6,
      sumB: 6,
    };

    const teams = generateBalancedTeams(roster, previous);
    const sameAsPrevious =
      teams.teamA.every((item) => previous.teamA.some(({ id }) => id === item.id)) ||
      teams.teamA.every((item) => previous.teamB.some(({ id }) => id === item.id));

    expect(sameAsPrevious).toBe(false);
  });
});

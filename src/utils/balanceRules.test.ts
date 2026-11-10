import { describe, expect, it } from "vitest";
import type { GameSession, Player } from "../types";
import {
  appendBalanceHistory,
  hasCurrentTeamRoster,
  hasEquivalentBalanceRoster,
  isFinalRebalanceWindow,
  lockBalanceWindow,
  preserveEquivalentTeamAssignments,
  reanchorBalanceWindow,
  standardBalanceLimit,
} from "./balanceRules";

const player = (id: number, overrides: Partial<Player> = {}): Player => ({
  id,
  name: `Player ${id}`,
  level: 3,
  mobility: "neutro",
  condition: "neutro",
  position: "neutro",
  ...overrides,
});

const game = (overrides: Partial<GameSession> = {}): GameSession => ({
  id: 1,
  date: "2026-10-10",
  time: "10:00",
  endTime: "11:15",
  duration: 75,
  location: "Court",
  courtNumber: "1",
  courtCost: 0,
  currency: "EUR",
  maxPlayers: 2,
  minPlayers: null,
  cancellationHours: null,
  cancelled: false,
  paymentInfo: "",
  disclaimer: "",
  playerIds: [1, 2],
  waitlistIds: [],
  paidPlayerIds: [1, 2],
  teams: null,
  ...overrides,
});

describe("balance rules", () => {
  it("keeps distinct standard quotas for admin and participant organizers", () => {
    expect(standardBalanceLimit(game())).toBe(3);
    expect(standardBalanceLimit(game({ createdByRole: "participant" }))).toBe(2);
  });

  it("opens the final balance window exactly fifteen minutes before kickoff", () => {
    const locked = lockBalanceWindow(game());
    const windowStart = new Date(2026, 9, 10, 9, 45).getTime();
    const windowEnd = new Date(2026, 9, 10, 11, 15).getTime();
    expect(locked.balanceWindowStartAt).toBe(new Date(windowStart).toISOString());
    expect(locked.balanceWindowEndAt).toBe(new Date(windowEnd).toISOString());
    expect(isFinalRebalanceWindow(locked, windowStart - 1)).toBe(false);
    expect(isFinalRebalanceWindow(locked, windowStart)).toBe(true);
    expect(isFinalRebalanceWindow(locked, windowEnd)).toBe(false);
  });

  it("moves the final window after a reschedule without changing quota state", () => {
    const rescheduled = reanchorBalanceWindow(
      game({ time: "09:30", endTime: "10:45", balanceCount: 2, lateRebalanceUsed: true }),
    );
    expect(rescheduled.balanceWindowStartAt).toBe(
      new Date(2026, 9, 10, 9, 15).toISOString(),
    );
    expect(rescheduled.balanceWindowEndAt).toBe(
      new Date(2026, 9, 10, 10, 45).toISOString(),
    );
    expect(rescheduled.balanceCount).toBe(2);
    expect(rescheduled.lateRebalanceUsed).toBe(true);
  });

  it("preserves teams only for a genuinely equivalent replacement", () => {
    const original = [player(1), player(2)];
    const replacement = player(3);
    expect(hasEquivalentBalanceRoster([1, 2], [3, 2], [...original, replacement])).toBe(true);
    expect(
      hasEquivalentBalanceRoster(
        [1, 2],
        [3, 2],
        [...original, player(3, { mobility: "rapido" })],
      ),
    ).toBe(false);
  });

  it("replaces an equivalent outgoing player in the previous team assignment", () => {
    const before = game({
      teams: { teamA: [player(1)], teamB: [player(2)], sumA: 3, sumB: 3 },
      playerIds: [3, 2],
    });
    const preserved = preserveEquivalentTeamAssignments(before, [player(2), player(3)]);
    expect(preserved.teams?.teamA.map(({ id }) => id)).toEqual([3]);
    expect(preserved.teams?.teamB.map(({ id }) => id)).toEqual([2]);
  });

  it("caps balance history and refuses stale team snapshots", () => {
    const withHistory = [1, 2, 3, 4, 5].reduce<GameSession>(
      (current, index) => ({
        ...current,
        balanceHistory: appendBalanceHistory(current, {
          triggeredAt: `2026-10-10T0${index}:00:00.000Z`,
          type: "automatic",
        }),
      }),
      game(),
    );
    expect(withHistory.balanceHistory).toHaveLength(4);
    expect(withHistory.balanceHistory?.[0].triggeredAt).toContain("02:00");

    expect(
      hasCurrentTeamRoster(
        game({ teams: { teamA: [player(1)], teamB: [player(1)], sumA: 3, sumB: 3 } }),
      ),
    ).toBe(false);
  });
});

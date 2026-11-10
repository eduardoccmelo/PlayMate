import { describe, expect, it, vi } from "vitest";
import type { GameSession } from "../types";
import {
  durationInMinutes,
  endTimeFromDuration,
  gameEndTimestamp,
  hasGameEnded,
  isVisibleToParticipants,
  today,
} from "./game";

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
  maxPlayers: 4,
  minPlayers: null,
  cancellationHours: null,
  cancelled: false,
  paymentInfo: "",
  disclaimer: "",
  playerIds: [],
  waitlistIds: [],
  paidPlayerIds: [],
  teams: null,
  ...overrides,
});

describe("game time helpers", () => {
  it("calculates end time across midnight", () => {
    expect(endTimeFromDuration("20:00", 75)).toBe("21:15");
    expect(endTimeFromDuration("23:30", 60)).toBe("00:30");
    expect(durationInMinutes("23:30", "00:30")).toBe(60);
  });

  it("uses the end time, not the start time, to close a game", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 9, 10, 10, 30));
    expect(hasGameEnded(game())).toBe(false);
    vi.setSystemTime(new Date(2026, 9, 10, 11, 15));
    expect(hasGameEnded(game())).toBe(true);
    vi.useRealTimers();
  });

  it("keeps a game open until its next-day end time", () => {
    vi.useFakeTimers();
    const overnightGame = game({ time: "23:30", endTime: "00:30", duration: 60 });
    expect(gameEndTimestamp(overnightGame)).toBe(
      new Date(2026, 9, 11, 0, 30).getTime(),
    );
    vi.setSystemTime(new Date(2026, 9, 11, 0, 29));
    expect(hasGameEnded(overnightGame)).toBe(false);
    vi.setSystemTime(new Date(2026, 9, 11, 0, 30));
    expect(hasGameEnded(overnightGame)).toBe(true);
    vi.useRealTimers();
  });

  it("keeps a finished game visible for one day", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 9, 11, 10, 0));
    expect(isVisibleToParticipants(game())).toBe(true);
    vi.setSystemTime(new Date(2026, 9, 11, 11, 16));
    expect(isVisibleToParticipants(game())).toBe(false);
    vi.useRealTimers();
  });

  it("derives today's date from the current local clock", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 4, 4, 12, 0));
    expect(today()).toBe("2026-05-04");
    vi.useRealTimers();
  });
});

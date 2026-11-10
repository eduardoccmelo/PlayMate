import type { BalanceHistoryEntry, GameSession, Player } from "../types";
import { gameTimestamp } from "./game";
import { playerScoreBreakdown } from "./teamBalancer";

export const MAX_STANDARD_BALANCES = 2;
export const FINAL_REBALANCE_WINDOW = 15 * 60 * 1000;

export const isGameReadyForBalancing = (game: GameSession) =>
  game.playerIds.length === game.maxPlayers &&
  game.playerIds.every((playerId) => game.paidPlayerIds.includes(playerId));

export const standardBalanceLimit = (game: GameSession) =>
  game.createdByRole === "participant" ? 1 : MAX_STANDARD_BALANCES;

export const lockedBalanceWindow = (game: GameSession) => {
  const scheduledAt = gameTimestamp(game);
  const startAt = Date.parse(game.balanceWindowStartAt ?? "");
  return {
    start: Number.isFinite(startAt)
      ? startAt
      : scheduledAt - FINAL_REBALANCE_WINDOW,
    // The final attempt opens before kickoff but remains possible during play.
    end: gameTimestamp(game, game.endTime || game.time),
  };
};

export const lockBalanceWindow = (game: GameSession): GameSession => {
  const { start, end } = lockedBalanceWindow(game);
  if (
    Date.parse(game.balanceWindowStartAt ?? "") === start &&
    Date.parse(game.balanceWindowEndAt ?? "") === end
  ) {
    return game;
  }
  return {
    ...game,
    balanceWindowStartAt: new Date(start).toISOString(),
    balanceWindowEndAt: new Date(end).toISOString(),
  };
};

/** A reschedule moves the final-balance window but never restores its quota. */
export const reanchorBalanceWindow = (game: GameSession): GameSession => {
  const scheduledAt = gameTimestamp(game);
  return {
    ...game,
    balanceWindowStartAt: new Date(
      scheduledAt - FINAL_REBALANCE_WINDOW,
    ).toISOString(),
    balanceWindowEndAt: new Date(
      gameTimestamp(game, game.endTime || game.time),
    ).toISOString(),
  };
};

export const isFinalRebalanceWindow = (game: GameSession, now: number) => {
  const { start, end } = lockedBalanceWindow(game);
  return now >= start && now < end;
};

export const balanceCountOf = (game: GameSession) =>
  game.balanceCount ?? game.manualRebalanceCount ?? 0;

export const hasCurrentTeamRoster = (game: GameSession) => {
  if (!game.teams || !isGameReadyForBalancing(game)) return false;
  const assignedIds = [...game.teams.teamA, ...game.teams.teamB].map(
    (player) => player.id,
  );
  return (
    assignedIds.length === game.playerIds.length &&
    new Set(assignedIds).size === assignedIds.length &&
    assignedIds.every((playerId) => game.playerIds.includes(playerId))
  );
};

export const appendBalanceHistory = (
  game: GameSession,
  entry: BalanceHistoryEntry,
) => [...(game.balanceHistory ?? []), entry].slice(-4);

export const samePlayerSet = (first: number[], second: number[]) =>
  first.length === second.length && first.every((id) => second.includes(id));

export const balanceSignatureFor = (player: Player) => {
  const score = playerScoreBreakdown(player);
  return [
    player.position,
    score.level,
    score.mobility,
    score.condition,
    score.total,
  ].join(":");
};

/**
 * A replacement can retain its teams only when every input used by the
 * balancing algorithm is equivalent. IDs and list order are irrelevant.
 */
export const hasEquivalentBalanceRoster = (
  first: number[],
  second: number[],
  allPlayers: Player[],
) => {
  if (first.length !== second.length) return false;
  const signaturesFor = (playerIds: number[]) => {
    const signatures: string[] = [];
    for (const playerId of playerIds) {
      const player = allPlayers.find((candidate) => candidate.id === playerId);
      if (!player) return null;
      signatures.push(balanceSignatureFor(player));
    }
    return signatures.sort();
  };
  const firstSignatures = signaturesFor(first);
  const secondSignatures = signaturesFor(second);
  return (
    firstSignatures !== null &&
    secondSignatures !== null &&
    firstSignatures.every(
      (signature, index) => signature === secondSignatures[index],
    )
  );
};

export const preserveEquivalentTeamAssignments = (
  game: GameSession,
  allPlayers: Player[],
): GameSession => {
  if (!game.teams) return game;
  const currentPlayers = new Map(
    game.playerIds
      .map((playerId) => allPlayers.find((player) => player.id === playerId))
      .filter((player): player is Player => Boolean(player))
      .map((player) => [player.id, player]),
  );
  const assignedIds = new Set([
    ...game.teams.teamA.map((player) => player.id),
    ...game.teams.teamB.map((player) => player.id),
  ]);
  const replacements = [...currentPlayers.values()].filter(
    (player) => !assignedIds.has(player.id),
  );
  const replacePlayer = (player: Player) => {
    const current = currentPlayers.get(player.id);
    if (current) return current;
    const replacementIndex = replacements.findIndex(
      (candidate) => balanceSignatureFor(candidate) === balanceSignatureFor(player),
    );
    return replacementIndex === -1
      ? player
      : replacements.splice(replacementIndex, 1)[0];
  };
  const teamA = game.teams.teamA.map(replacePlayer);
  const teamB = game.teams.teamB.map(replacePlayer);
  const scoreOf = (team: Player[]) =>
    team.reduce((total, player) => total + playerScoreBreakdown(player).total, 0);
  return {
    ...game,
    teams: { teamA, teamB, sumA: scoreOf(teamA), sumB: scoreOf(teamB) },
  };
};

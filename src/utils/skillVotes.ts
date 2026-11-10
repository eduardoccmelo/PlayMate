import type { Mobility, PlayerGroup, PlayerSkillVote } from "../types";

const mobilityFromScore = (score: number): Mobility =>
  score === 1 ? "lento" : score === 3 ? "rapido" : "neutro";

/** A player never contributes to their own rating, even when they are an admin. */
export const isSelfSkillVote = (
  group: Pick<PlayerGroup, "admins" | "players">,
  playerId: number,
  adminUserId: string,
) => {
  const player = group.players.find((candidate) => candidate.id === playerId);
  const admin = group.admins?.find(
    (candidate) => candidate.userId === adminUserId,
  );
  return Boolean(
    player &&
      (player.ownerUserId === adminUserId || admin?.playerId === player.id),
  );
};

export const externalSkillVotesFor = (
  group: Pick<PlayerGroup, "admins" | "players" | "skillVotes">,
  playerId: number,
) =>
  (group.skillVotes ?? []).filter(
    (vote) =>
      vote.playerId === playerId &&
      !isSelfSkillVote(group, playerId, vote.adminUserId),
  );

export const averageLevel = (votes: PlayerSkillVote[], fallback = 3) => {
  const values = votes.flatMap((vote) =>
    vote.level === undefined ? [] : [vote.level],
  );
  return values.length
    ? Math.floor(values.reduce((total, value) => total + value, 0) / values.length + 0.5)
    : fallback;
};

export const averageMobility = (
  votes: PlayerSkillVote[],
  fallback: Mobility = "neutro",
) => {
  const values = votes.flatMap((vote) =>
    vote.mobility === undefined ? [] : [vote.mobility],
  );
  return values.length
    ? mobilityFromScore(
        Math.floor(
          values.reduce((total, value) => total + value, 0) / values.length +
            0.5,
        ),
      )
    : fallback;
};

/** Removes legacy self-ballots and resets affected skills to the neutral default when no outside vote remains. */
export const removeSelfSkillVotes = (group: PlayerGroup): PlayerGroup => {
  const removedPlayerIds = new Set(
    (group.skillVotes ?? [])
      .filter((vote) => isSelfSkillVote(group, vote.playerId, vote.adminUserId))
      .map((vote) => vote.playerId),
  );
  if (!removedPlayerIds.size) return group;

  const skillVotes = (group.skillVotes ?? []).filter(
    (vote) => !isSelfSkillVote(group, vote.playerId, vote.adminUserId),
  );
  return {
    ...group,
    skillVotes,
    players: group.players.map((player) => {
      if (!removedPlayerIds.has(player.id)) return player;
      const votes = skillVotes.filter((vote) => vote.playerId === player.id);
      return {
        ...player,
        level: averageLevel(votes),
        mobility: averageMobility(votes),
      };
    }),
  };
};

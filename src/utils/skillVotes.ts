import type { Mobility, PlayerGroup, PlayerSkillVote } from "../types";

const mobilityFromScore = (score: number): Mobility =>
  score === 1 ? "lento" : score === 3 ? "rapido" : "neutro";

export const skillVotesFor = (
  group: Pick<PlayerGroup, "skillVotes">,
  playerId: number,
) =>
  (group.skillVotes ?? []).filter((vote) => vote.playerId === playerId);

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

import type {
  GameSession,
  GroupAdmin,
  Player,
  PlayerGroup,
  PlayerSkillVote,
} from "../types";
import { endTimeFromDuration } from "../utils/game";
import type {
  ApiGameDetail,
  ApiGroup,
  ApiGuestGame,
  ApiMember,
  ApiParticipant,
  ApiPlayer,
  ApiProfile,
  ApiVote,
} from "./apiRepository";

/**
 * The UI still keys players and games by number (legacy local model), while
 * the server uses UUIDs. Derive a stable number from the UUID and keep the
 * UUID alongside it as `apiId` for every server call.
 */
export const localIdForApi = (id: string) => {
  const prefix = id.replaceAll("-", "").slice(0, 7);
  return Number.parseInt(prefix, 16) || 1;
};

const balanceFromApi = (
  detail: ApiGameDetail,
): Pick<
  GameSession,
  | "balanceCount"
  | "lateRebalanceUsed"
  | "balanceWindowStartAt"
  | "balanceWindowEndAt"
  | "balanceHistory"
  | "lastScheduleChange"
> => {
  const { balance, lastScheduleChange } = detail;
  const latest = balance.latest;
  return {
    balanceCount: balance.standardCount,
    lateRebalanceUsed: balance.lateRebalanceUsed,
    balanceWindowStartAt: balance.windowStartsAt,
    balanceWindowEndAt: balance.windowEndsAt,
    balanceHistory: latest
      ? [
          {
            triggeredAt: latest.generatedAt,
            type: latest.triggerType === "late_rebalance" ? "late-rebalance" : "admin",
            adminName: latest.triggeredByName ?? undefined,
            rescheduledByName: latest.rescheduledByName ?? undefined,
            count: latest.standardBalanceNumber ?? undefined,
          },
        ]
      : [],
    lastScheduleChange: lastScheduleChange ?? undefined,
  };
};

/** The active split, built from each confirmed participant's team. */
const teamsFromApi = (
  detail: ApiGameDetail,
  playersById: Map<number, Player>,
): GameSession["teams"] => {
  if (!detail.game.teamsDrawnAt) return null;
  const side = (team: "A" | "B") =>
    detail.confirmed
      .filter((participant) => participant.team === team)
      .map((participant) => playersById.get(localIdForApi(participant.playerId)))
      .filter((player): player is Player => Boolean(player));
  return {
    teamA: side("A"),
    teamB: side("B"),
    sumA: Number(detail.game.teamAScore ?? 0),
    sumB: Number(detail.game.teamBScore ?? 0),
  };
};

export const gameFromApi = (detail: ApiGameDetail): GameSession => {
  const { game, confirmed, waitingList: waiting } = detail;
  return {
    id: localIdForApi(game.id),
    apiId: game.id,
    date: game.gameDate,
    time: game.startTime.slice(0, 5),
    endTime:
      game.endTime?.slice(0, 5) ??
      endTimeFromDuration(game.startTime.slice(0, 5), game.durationMinutes),
    duration: game.durationMinutes,
    location: game.location,
    courtNumber: game.courtNumber,
    courtCost: game.courtCostCents / 100,
    currency: game.currency,
    maxPlayers: game.maxPlayers,
    minPlayers: game.minPlayers,
    cancellationHours: null,
    cancelled: game.status === "cancelled",
    paymentTrackingEnabled: game.paymentTrackingEnabled,
    paymentDeadlineDays: game.paymentDeadlineDays,
    paymentDueAtByPlayerId: Object.fromEntries(
      [...confirmed, ...waiting].flatMap((participant) =>
        participant.paymentDueAt
          ? [[localIdForApi(participant.playerId), participant.paymentDueAt]]
          : [],
      ),
    ),
    paymentInfo: game.paymentInfo,
    disclaimer: game.playerNotice,
    playerIds: confirmed.map((participant) => localIdForApi(participant.playerId)),
    waitlistIds: waiting.map((participant) => localIdForApi(participant.playerId)),
    apiParticipantIdsByPlayerId: Object.fromEntries(
      [...confirmed, ...waiting].map((participant) => [
        localIdForApi(participant.playerId),
        participant.id,
      ]),
    ),
    paidPlayerIds: confirmed
      .filter((participant) => participant.paid)
      .map((participant) => localIdForApi(participant.playerId)),
    // Filled in by groupFromApi, which knows every player record.
    teams: null,
    ...balanceFromApi(detail),
    createdByUserId: game.createdByUserId,
    createdByRole: game.createdByRole,
  };
};

const mobilityDefault = "neutro" as const;

export const playerFromApi = (player: ApiPlayer): Player => ({
  id: localIdForApi(player.id),
  apiId: player.id,
  name: player.displayName,
  ownerUserId: player.ownerUserId ?? undefined,
  isGuest: player.isGuest,
  accessScope: player.accessScope,
  // Non-admins receive no skill data; neutral placeholders keep the UI typed.
  level: player.level ?? 3,
  mobility: player.mobility ?? mobilityDefault,
  condition: player.condition,
  position: player.position,
});

/**
 * A participant whose profile is not in the active directory (for example an
 * archived guest on a past game) still needs a Player record to render.
 */
export const playerFromParticipant = (participant: ApiParticipant): Player => ({
  id: localIdForApi(participant.playerId),
  apiId: participant.playerId,
  name: participant.displayName,
  ownerUserId: participant.userId ?? undefined,
  isGuest: participant.userId === null,
  accessScope: "group",
  level: 3,
  mobility: mobilityDefault,
  condition: "neutro",
  position: "neutro",
});

/** Merge per-attribute ballots into the UI's one-row-per-admin shape. */
export const skillVotesFromApi = (votes: ApiVote[]): PlayerSkillVote[] => {
  const byKey = new Map<string, PlayerSkillVote>();
  for (const vote of votes) {
    const key = `${vote.playerId}:${vote.adminUserId}`;
    const entry = byKey.get(key) ?? {
      playerId: localIdForApi(vote.playerId),
      adminUserId: vote.adminUserId,
      updatedAt: vote.updatedAt,
    };
    if (vote.attribute === "level") entry.level = vote.value;
    else entry.mobility = vote.value as 1 | 2 | 3;
    if (vote.updatedAt > entry.updatedAt) entry.updatedAt = vote.updatedAt;
    byKey.set(key, entry);
  }
  return [...byKey.values()];
};

export const adminsFromApi = (members: ApiMember[]): GroupAdmin[] =>
  members.flatMap((member) =>
    member.role === "owner" || member.role === "admin"
      ? [
          {
            userId: member.userId,
            playerId: member.playerId ? localIdForApi(member.playerId) : undefined,
            displayName: member.displayName,
            role: member.role,
            joinedAt: member.joinedAt,
          },
        ]
      : [],
  );

export const groupFromApi = ({
  membership,
  directory,
  details,
  viewer,
  joinCode,
  members,
  votes = [],
}: {
  membership: ApiGroup;
  directory: ApiPlayer[];
  details: ApiGameDetail[];
  viewer: ApiProfile;
  joinCode?: string;
  /** Every active member; when absent only the viewer's own role is known. */
  members?: ApiMember[];
  /** Admin ballots; only loaded for admins. */
  votes?: ApiVote[];
}): PlayerGroup => {
  const playersById = new Map<number, Player>(
    directory.map((player) => {
      const mapped = playerFromApi(player);
      return [mapped.id, mapped];
    }),
  );
  for (const detail of details) {
    for (const participant of [...detail.confirmed, ...detail.waitingList]) {
      const id = localIdForApi(participant.playerId);
      if (!playersById.has(id)) playersById.set(id, playerFromParticipant(participant));
    }
  }
  const role = membership.role;
  return {
    id: membership.id,
    apiManaged: true,
    publicJoinCode: joinCode,
    name: membership.name,
    organizerPasscode: "",
    createdAt: "",
    players: [...playersById.values()],
    games: details.map((detail) => ({
      ...gameFromApi(detail),
      teams: teamsFromApi(detail, playersById),
    })),
    requests: [],
    admins: members
      ? adminsFromApi(members)
      : role === "owner" || role === "admin"
        ? [
            {
              userId: viewer.id,
              displayName: viewer.displayName,
              role,
              joinedAt: "",
            },
          ]
        : [],
    skillVotes: skillVotesFromApi(votes),
  };
};

/**
 * A group the viewer reaches only through game codes: just those games, the
 * players on their lists, and the viewer's own entries marked game-only so
 * the group never shows up as a membership.
 */
export const guestGroupFromApi = (
  entries: ApiGuestGame[],
  viewer: ApiProfile,
): PlayerGroup => {
  const playersById = new Map<number, Player>();
  for (const { detail } of entries) {
    for (const participant of [...detail.confirmed, ...detail.waitingList]) {
      const player = playerFromParticipant(participant);
      if (participant.userId === viewer.id) player.accessScope = "game";
      playersById.set(player.id, player);
    }
  }
  return {
    id: entries[0].groupId,
    apiManaged: true,
    guestOnly: true,
    name: entries[0].groupName,
    organizerPasscode: "",
    createdAt: "",
    players: [...playersById.values()],
    games: entries.map(({ detail }) => ({
      ...gameFromApi(detail),
      teams: teamsFromApi(detail, playersById),
    })),
    requests: [],
    admins: [],
    skillVotes: [],
  };
};

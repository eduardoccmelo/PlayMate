import { apiFetch } from "./apiClient";
import { getStoredValue, saveStoredValue } from "./browserStorage";

/** Contracts for endpoints that already exist in the FastAPI service. */
export type ApiProfile = {
  id: string;
  email: string;
  displayName: string;
  isStaff: boolean;
};

export type ApiSession = {
  token: string;
  user: ApiProfile;
};

export type AccessCodeStart = {
  /** Present only outside production while SMTP is not configured. */
  accessCode?: string | null;
};

export type ApiGroup = {
  id: string;
  name: string;
  publicSlug: string;
  timezone: string;
  role: "owner" | "admin" | "participant" | null;
};

export type ApiGame = {
  id: string;
  groupId: string;
  publicSlug: string;
  gameDate: string;
  startTime: string;
  endTime: string | null;
  durationMinutes: number;
  location: string;
  courtNumber: string;
  courtCostCents: number;
  currency: "EUR" | "USD" | "GBP" | "BRL";
  maxPlayers: number;
  minPlayers: number | null;
  status: "active" | "cancelled" | "finished" | "deleted";
  cancelReason: "manual" | "min_players" | null;
  paymentTrackingEnabled: boolean;
  /** 1-7 days each new entry has to pay; null without a deadline. */
  paymentDeadlineDays: number | null;
  paymentInfo: string;
  playerNotice: string;
  createdByUserId: string;
  /** A participant creator organizes only this game. */
  createdByRole: "admin" | "participant";
  /** Set while a team split is active. Scores arrive as decimal strings. */
  teamsDrawnAt: string | null;
  teamAScore: string | number | null;
  teamBScore: string | number | null;
};

export type ApiBalanceSummary = {
  standardCount: number;
  standardLimit: number;
  lateRebalanceUsed: boolean;
  windowStartsAt: string;
  windowEndsAt: string;
  latest: {
    triggerType: "organizer" | "late_rebalance";
    standardBalanceNumber: number | null;
    generatedAt: string;
    /** Only sent to viewers who manage the game. */
    triggeredByName: string | null;
    rescheduledByName: string | null;
  } | null;
};

export type ApiScheduleChange = {
  previousStartsAt: string;
  currentStartsAt: string;
  changedAt: string;
  changedByName: string;
  wasBroughtForward: boolean;
};

export type ApiParticipant = {
  id: string;
  playerId: string;
  /** Owning account; null for manual guests. Never infer ownership from names. */
  userId: string | null;
  displayName: string;
  status: "confirmed" | "waiting_list" | "left" | "removed";
  listPosition: number | null;
  paid: boolean;
  /** This entry's own payment deadline (ISO instant), if the game has one. */
  paymentDueAt: string | null;
  team: "A" | "B" | null;
};

export type ApiGameDetail = {
  game: ApiGame;
  viewerAccess: {
    kind: string;
    status: string | null;
    canViewDetails: boolean;
    canViewGroupPlayers: boolean;
    canJoin: boolean;
    canLeave: boolean;
    canUpdateOwnPayment: boolean;
    canDrawTeams: boolean;
    canManageGame: boolean;
  };
  confirmed: ApiParticipant[];
  waitingList: ApiParticipant[];
  balance: ApiBalanceSummary;
  lastScheduleChange: ApiScheduleChange | null;
};

export type ApiGameDraft = {
  gameDate: string;
  startTime: string;
  durationMinutes: number;
  maxPlayers: number;
  minPlayers?: number | null;
  location: string;
  courtNumber: string;
  courtCostCents: number;
  currency: ApiGame["currency"];
  autoCancellationHours?: number | null;
  paymentTrackingEnabled: boolean;
  paymentDeadlineDays: number | null;
  paymentInfo: string;
  playerNotice: string;
};

export type ApiPlayer = {
  id: string;
  /** "game" for a guest who belongs to one game only. */
  accessScope: "group" | "game";
  displayName: string;
  ownerUserId: string | null;
  isGuest: boolean;
  /** Withheld (null) for non-admin viewers. */
  level: number | null;
  mobility: "rapido" | "neutro" | "lento" | null;
  condition: "boa" | "neutro" | "ruim";
  position: "goleiro" | "defesa" | "ataque" | "neutro";
};

/** A game reached by code, outside the viewer's group memberships. */
export type ApiGuestGame = {
  groupId: string;
  groupName: string;
  detail: ApiGameDetail;
};

export type ApiPlayerDraft = {
  displayName?: string;
  level?: number | null;
  mobility?: NonNullable<ApiPlayer["mobility"]>;
  condition?: ApiPlayer["condition"];
  position?: ApiPlayer["position"];
};

export type ApiMember = {
  userId: string;
  displayName: string;
  role: "owner" | "admin" | "participant";
  joinedAt: string;
  playerId: string | null;
};

/** One admin's ballot for one attribute: level 1-5, mobility 1-3. */
export type ApiVote = {
  playerId: string;
  adminUserId: string;
  attribute: "level" | "mobility";
  value: number;
  updatedAt: string;
};

const withToken = (token: string): HeadersInit => ({
  Authorization: `Bearer ${token}`,
});

const SESSION_KEY = "playmate.api-session.v1";

export const apiRepository = {
  health: () => apiFetch<{ status: string; database?: string }>("/health"),
  startAccessCode: (email: string, displayName?: string) =>
    apiFetch<AccessCodeStart>("/v1/auth/start", {
      method: "POST",
      body: JSON.stringify({ email, displayName }),
    }),
  verifyAccessCode: (email: string, accessCode: string) =>
    apiFetch<ApiSession>("/v1/auth/verify", {
      method: "POST",
      body: JSON.stringify({ email, accessCode }),
    }),
  currentUser: (token: string) =>
    apiFetch<ApiProfile>("/v1/me", {
      headers: { Authorization: `Bearer ${token}` },
    }),
  updateCurrentUser: (token: string, displayName: string) =>
    apiFetch<ApiProfile>("/v1/me", {
      method: "PATCH",
      headers: { Authorization: `Bearer ${token}` },
      body: JSON.stringify({ displayName }),
    }),
  signOut: (token: string) =>
    apiFetch<void>("/v1/sessions/current", {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}` },
    }),
  listGroups: (token: string) =>
    apiFetch<ApiGroup[]>("/v1/groups", { headers: withToken(token) }),
  createGroup: (token: string, name: string, organizerPasscode: string) =>
    apiFetch<{ group: ApiGroup; joinCode: string }>("/v1/groups", {
      method: "POST",
      headers: withToken(token),
      body: JSON.stringify({ name, organizerPasscode }),
    }),
  joinGroup: (
    token: string,
    joinCode: string,
    displayName: string,
    organizerPasscode?: string,
  ) =>
    apiFetch<ApiGroup>("/v1/groups/join", {
      method: "POST",
      headers: withToken(token),
      body: JSON.stringify({
        joinCode,
        displayName,
        role: organizerPasscode ? "admin" : "participant",
        organizerPasscode,
      }),
    }),
  changeGroupPasscode: (
    token: string,
    groupId: string,
    currentPasscode: string,
    newPasscode: string,
  ) =>
    apiFetch<void>(`/v1/groups/${groupId}/passcode`, {
      method: "POST",
      headers: withToken(token),
      body: JSON.stringify({ currentPasscode, newPasscode }),
    }),
  renameGroup: (token: string, groupId: string, name: string) =>
    apiFetch<ApiGroup>(`/v1/groups/${groupId}`, {
      method: "PATCH",
      headers: withToken(token),
      body: JSON.stringify({ name }),
    }),
  /** The server keeps only a hash, so sharing again issues a fresh code. */
  rotateJoinCode: (token: string, groupId: string) =>
    apiFetch<{ joinCode: string }>(`/v1/groups/${groupId}/join-code`, {
      method: "POST",
      headers: withToken(token),
    }),
  listPlayers: (token: string, groupId: string) =>
    apiFetch<ApiPlayer[]>(`/v1/groups/${groupId}/players`, {
      headers: withToken(token),
    }),
  createPlayer: (token: string, groupId: string, player: ApiPlayerDraft) =>
    apiFetch<ApiPlayer>(`/v1/groups/${groupId}/players`, {
      method: "POST",
      headers: withToken(token),
      body: JSON.stringify(player),
    }),
  updatePlayer: (
    token: string,
    groupId: string,
    playerId: string,
    changes: ApiPlayerDraft,
  ) =>
    apiFetch<ApiPlayer>(`/v1/groups/${groupId}/players/${playerId}`, {
      method: "PATCH",
      headers: withToken(token),
      body: JSON.stringify(changes),
    }),
  listMembers: (token: string, groupId: string) =>
    apiFetch<ApiMember[]>(`/v1/groups/${groupId}/members`, {
      headers: withToken(token),
    }),
  /** Admins only. */
  listVotes: (token: string, groupId: string) =>
    apiFetch<ApiVote[]>(`/v1/groups/${groupId}/votes`, {
      headers: withToken(token),
    }),
  /** Record or (value null) withdraw the caller's ballot; returns the player. */
  castVote: (
    token: string,
    groupId: string,
    playerId: string,
    attribute: ApiVote["attribute"],
    value: number | null,
  ) =>
    apiFetch<ApiPlayer>(
      `/v1/groups/${groupId}/players/${playerId}/votes/${attribute}`,
      {
        method: "PUT",
        headers: withToken(token),
        body: JSON.stringify({ value }),
      },
    ),
  archivePlayer: (token: string, groupId: string, playerId: string) =>
    apiFetch<void>(`/v1/groups/${groupId}/players/${playerId}`, {
      method: "DELETE",
      headers: withToken(token),
    }),
  leaveGroup: (token: string, groupId: string) =>
    apiFetch<void>(`/v1/groups/${groupId}/leave`, {
      method: "POST",
      headers: withToken(token),
    }),
  listGames: (token: string, groupId: string) =>
    apiFetch<ApiGame[]>(`/v1/groups/${groupId}/games`, {
      headers: withToken(token),
    }),
  createGame: (token: string, groupId: string, game: ApiGameDraft) =>
    apiFetch<{ game: ApiGame; joinCode: string }>(
      `/v1/groups/${groupId}/games`,
      {
        method: "POST",
        headers: withToken(token),
        body: JSON.stringify(game),
      },
    ),
  readGame: (token: string, gameId: string) =>
    apiFetch<ApiGameDetail>(`/v1/games/${gameId}`, {
      headers: withToken(token),
    }),
  updateGame: (token: string, gameId: string, changes: Partial<ApiGameDraft>) =>
    apiFetch<ApiGame>(`/v1/games/${gameId}`, {
      method: "PATCH",
      headers: withToken(token),
      body: JSON.stringify(changes),
    }),
  /** Organizers only; the previous code stops working. */
  rotateGameJoinCode: (token: string, gameId: string) =>
    apiFetch<{ joinCode: string }>(`/v1/games/${gameId}/join-code`, {
      method: "POST",
      headers: withToken(token),
    }),
  /** Join one game by code; non-members get game-only access. */
  joinGameByCode: (token: string, joinCode: string) =>
    apiFetch<ApiGameDetail>("/v1/games/join", {
      method: "POST",
      headers: withToken(token),
      body: JSON.stringify({ joinCode }),
    }),
  listGuestGames: (token: string) =>
    apiFetch<ApiGuestGame[]>("/v1/me/games", { headers: withToken(token) }),
  /** An organizer's manual guest for one game, put straight on its list. */
  addGameGuest: (
    token: string,
    gameId: string,
    guest: { displayName: string; position: ApiPlayer["position"]; condition: ApiPlayer["condition"] },
  ) =>
    apiFetch<ApiGameDetail>(`/v1/games/${gameId}/guests`, {
      method: "POST",
      headers: withToken(token),
      body: JSON.stringify(guest),
    }),
  /** One manual draw; the server enforces eligibility and the 3 + 1 quota. */
  drawTeams: (token: string, gameId: string) =>
    apiFetch<ApiGameDetail>(`/v1/games/${gameId}/team-balance`, {
      method: "POST",
      headers: withToken(token),
    }),
  deleteGame: (token: string, gameId: string) =>
    apiFetch<void>(`/v1/games/${gameId}`, {
      method: "DELETE",
      headers: withToken(token),
    }),
  cancelGame: (token: string, gameId: string, reason: "manual" | "min_players") =>
    apiFetch<ApiGame>(`/v1/games/${gameId}/cancel`, {
      method: "POST",
      headers: withToken(token),
      body: JSON.stringify({ reason }),
    }),
  joinGame: (token: string, gameId: string, playerId?: string) =>
    apiFetch<ApiGameDetail>(`/v1/games/${gameId}/participants`, {
      method: "POST",
      headers: withToken(token),
      body: JSON.stringify({ playerId }),
    }),
  updatePayment: (token: string, gameId: string, participantId: string, paid: boolean) =>
    apiFetch<ApiParticipant[]>(
      `/v1/games/${gameId}/participants/${participantId}/payment`,
      {
        method: "PATCH",
        headers: withToken(token),
        body: JSON.stringify({ paid }),
      },
    ),
  leaveGame: (token: string, gameId: string, participantId: string) =>
    apiFetch<ApiParticipant[]>(
      `/v1/games/${gameId}/participants/${participantId}/leave`,
      { method: "POST", headers: withToken(token) },
    ),
  removeParticipant: (token: string, gameId: string, participantId: string) =>
    apiFetch<ApiParticipant[]>(
      `/v1/games/${gameId}/participants/${participantId}`,
      { method: "DELETE", headers: withToken(token) },
    ),
  reorderParticipants: (
    token: string,
    gameId: string,
    status: "confirmed" | "waiting_list",
    orderedIds: string[],
  ) =>
    apiFetch<ApiParticipant[]>(
      `/v1/games/${gameId}/participants/reorder`,
      {
        method: "POST",
        headers: withToken(token),
        body: JSON.stringify({ status, orderedIds }),
      },
    ),
  readSession: () => getStoredValue<ApiSession | null>(SESSION_KEY, null),
  saveSession: (session: ApiSession) => saveStoredValue(SESSION_KEY, session),
  clearSession: () => saveStoredValue<ApiSession | null>(SESSION_KEY, null),
};

const JOIN_CODES_KEY = "playmate.api-join-codes.v1";

/**
 * The server stores only a hash of each group's join code and returns the
 * plain code once (on creation or rotation). Keep the last one this device
 * received so an admin can share it again without invalidating it.
 */
export const apiJoinCodes = {
  read: (groupId: string) =>
    getStoredValue<Record<string, string>>(JOIN_CODES_KEY, {})[groupId],
  save: (groupId: string, joinCode: string) =>
    saveStoredValue(JOIN_CODES_KEY, {
      ...getStoredValue<Record<string, string>>(JOIN_CODES_KEY, {}),
      [groupId]: joinCode,
    }),
  clear: () => saveStoredValue<Record<string, string>>(JOIN_CODES_KEY, {}),
};

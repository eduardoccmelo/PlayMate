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
  paymentInfo: string;
  playerNotice: string;
  createdByUserId: string;
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
  paymentInfo: string;
  playerNotice: string;
};

export type ApiPlayer = {
  id: string;
  displayName: string;
  ownerUserId: string | null;
  isGuest: boolean;
  /** Withheld (null) for non-admin viewers. */
  level: number | null;
  mobility: "rapido" | "neutro" | "lento" | null;
  condition: "boa" | "neutro" | "ruim";
  position: "goleiro" | "defesa" | "ataque" | "neutro";
};

export type ApiPlayerDraft = {
  displayName?: string;
  level?: number | null;
  mobility?: NonNullable<ApiPlayer["mobility"]>;
  condition?: ApiPlayer["condition"];
  position?: ApiPlayer["position"];
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

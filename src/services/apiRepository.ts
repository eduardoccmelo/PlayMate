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
  readSession: () => getStoredValue<ApiSession | null>(SESSION_KEY, null),
  saveSession: (session: ApiSession) => saveStoredValue(SESSION_KEY, session),
  clearSession: () => saveStoredValue<ApiSession | null>(SESSION_KEY, null),
};

import { apiFetch } from "./apiClient";

/** Contracts for endpoints that already exist in the FastAPI service. */
export type ApiProfile = {
  id: string;
  email: string;
  displayName: string;
};

export type ApiSession = {
  token: string;
  user: ApiProfile;
};

export type AccessCodeStart = {
  /** Present only outside production while SMTP is not configured. */
  accessCode?: string | null;
};

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
};

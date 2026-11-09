const API_PREFIX = "/api";

type ApiErrorBody = {
  error?: {
    code?: string;
    message?: string;
  };
};

export class ApiError extends Error {
  public readonly status: number;
  public readonly code?: string;

  constructor(
    status: number,
    code?: string,
    message?: string,
  ) {
    super(message ?? `API request failed: ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

export async function apiFetch<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const response = await fetch(`${API_PREFIX}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
  });

  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as ApiErrorBody | null;
    throw new ApiError(
      response.status,
      body?.error?.code,
      body?.error?.message,
    );
  }

  return response.json() as Promise<T>;
}

export function checkBackend() {
  return apiFetch<{ status: string; database?: string }>("/health");
}

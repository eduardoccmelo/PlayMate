import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiFetch } from "./apiClient";

describe("apiFetch", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("preserves the API error status, code, and safe message", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ error: { code: "not_authenticated", message: "Missing bearer token" } }),
          { status: 401, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    await expect(apiFetch("/v1/groups")).rejects.toEqual(
      new ApiError(401, "not_authenticated", "Missing bearer token"),
    );
  });

  it("supports API endpoints that intentionally return no content", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
    await expect(apiFetch<void>("/v1/sessions/current", { method: "DELETE" })).resolves.toBeUndefined();
  });
});

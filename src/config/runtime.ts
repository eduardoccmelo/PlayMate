/**
 * Runtime switches are deliberately opt-in. The browser store remains the
 * default until a complete API-backed vertical slice is enabled.
 */
export type DataSourceMode = "browser" | "api";

const requestedDataSource = import.meta.env.VITE_DATA_SOURCE;

export const runtimeConfig = {
  dataSource: requestedDataSource === "api" ? "api" : "browser",
  /**
   * Seed data is useful locally, but must never appear for a new production
   * user unless a deployment explicitly opts into a demo environment.
   */
  loadDemoSeed:
    import.meta.env.VITE_DEMO_SEED === "true" ||
    (import.meta.env.VITE_DEMO_SEED !== "false" && import.meta.env.DEV),
} as const satisfies {
  dataSource: DataSourceMode;
  loadDemoSeed: boolean;
};

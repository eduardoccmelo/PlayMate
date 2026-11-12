import { describe, expect, it } from "vitest";
import { translations } from "./i18n";

const sourceModules = import.meta.glob("./**/*.{ts,tsx}", {
  eager: true,
  import: "default",
  query: "?raw",
}) as Record<string, string>;

describe("English interface copy", () => {
  it("has an English translation for every static localize call", () => {
    const translatedKeys = new Set(Object.keys(translations.en));
    const usedKeys = Object.entries(sourceModules)
      .filter(([filePath]) => !filePath.endsWith(".test.ts"))
      .flatMap(([, source]) =>
        [...source.matchAll(/localize\(\s*(["'`])([^"'`$]+)\1/g)].map(
          (match) => match[2],
        ),
      );

    expect(
      [...new Set(usedKeys)].filter((key) => !translatedKeys.has(key)),
    ).toEqual([]);
  });
});

import type { CurrentUser, PlayerGroup } from "../types";
import { getStoredValue, saveStoredValue } from "./browserStorage";

export type SavedProfile = {
  user: CurrentUser;
  groups: PlayerGroup[];
  /** Composite `groupId:gameId` keys; game ids alone are group-scoped. */
  guestGameIds: string[];
};

export type BrowserAppState = {
  languagePreference: "pt" | "en" | null;
  groups: PlayerGroup[];
  currentUser: CurrentUser | null;
  savedProfiles: Record<string, SavedProfile>;
  activeGroupId: string | null;
};

const keys = {
  languagePreference: "playmate.language.preference",
  groups: "playmate.groups.v1",
  currentUser: "playmate.current-user.v1",
  savedProfiles: "playmate.saved-profiles.v1",
  activeGroupId: "playmate.active-group.v1",
} as const;

/**
 * The sole adapter for the legacy browser persistence model. Components use
 * the hook built on top of this repository instead of addressing localStorage
 * directly, which gives the API implementation a narrow replacement seam.
 */
export const browserAppRepository = {
  load(): BrowserAppState {
    return {
      languagePreference: getStoredValue(keys.languagePreference, null),
      groups: getStoredValue<PlayerGroup[]>(keys.groups, []),
      currentUser: getStoredValue<CurrentUser | null>(keys.currentUser, null),
      savedProfiles: getStoredValue<Record<string, SavedProfile>>(
        keys.savedProfiles,
        {},
      ),
      activeGroupId: getStoredValue<string | null>(keys.activeGroupId, null),
    };
  },
  save(state: BrowserAppState) {
    saveStoredValue(keys.languagePreference, state.languagePreference);
    saveStoredValue(keys.groups, state.groups);
    saveStoredValue(keys.currentUser, state.currentUser);
    saveStoredValue(keys.savedProfiles, state.savedProfiles);
    saveStoredValue(keys.activeGroupId, state.activeGroupId);
  },
};

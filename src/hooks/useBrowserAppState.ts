import { useEffect, useState, type Dispatch, type SetStateAction } from "react";
import { runtimeConfig } from "../config/runtime";
import {
  browserAppRepository,
  type BrowserAppState,
} from "../services/browserAppRepository";

/**
 * Transitional state boundary. The UI retains its current synchronous browser
 * behaviour while all persisted fields have one repository owner.
 */
export function useBrowserAppState(): [
  BrowserAppState,
  Dispatch<SetStateAction<BrowserAppState>>,
] {
  const usesApi = runtimeConfig.dataSource === "api";
  const [state, setState] = useState<BrowserAppState>(() =>
    usesApi ? browserAppRepository.loadPreferences() : browserAppRepository.load(),
  );

  useEffect(() => {
    if (usesApi) browserAppRepository.savePreferences(state);
    else browserAppRepository.save(state);
  }, [state, usesApi]);

  return [state, setState];
}

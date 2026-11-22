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
  const [state, setState] = useState<BrowserAppState>(() =>
    browserAppRepository.load(),
  );

  useEffect(() => {
    if (runtimeConfig.dataSource === "api") return;
    browserAppRepository.save(state);
  }, [state]);

  return [state, setState];
}

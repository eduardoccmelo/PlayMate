import { useEffect, useState, type Dispatch, type SetStateAction } from "react";
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
    browserAppRepository.save(state);
  }, [state]);

  return [state, setState];
}

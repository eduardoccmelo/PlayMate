import { useEffect, useState, type Dispatch, type SetStateAction } from "react";
import {
  getStoredValue,
  saveStoredValue,
} from "../services/browserStorage";

export function useLocalStorage<T>(
  key: string,
  initialValue: T,
): [T, Dispatch<SetStateAction<T>>] {
  const [value, setValue] = useState<T>(() => getStoredValue(key, initialValue));

  useEffect(() => {
    saveStoredValue(key, value);
  }, [key, value]);

  return [value, setValue];
}

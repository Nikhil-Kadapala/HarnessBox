import { useCallback, useState } from "react";
import { getStoredValue, setStoredValue } from "@/lib/storage";

export function useLocalStorage<T>(key: string, initial: T): [T, (v: T) => void] {
  const [value, setValue] = useState(() => getStoredValue(key, initial));

  const update = useCallback(
    (v: T) => {
      setValue(v);
      setStoredValue(key, v);
    },
    [key],
  );

  return [value, update];
}

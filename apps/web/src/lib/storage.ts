const STORAGE_PREFIX = "harnessbox:";

export function getStoredValue<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(STORAGE_PREFIX + key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

export function setStoredValue<T>(key: string, value: T): void {
  localStorage.setItem(STORAGE_PREFIX + key, JSON.stringify(value));
}

export function removeStoredValue(key: string): void {
  localStorage.removeItem(STORAGE_PREFIX + key);
}

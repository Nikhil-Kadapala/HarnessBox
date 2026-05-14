import type { DetectedWorkspace } from "@/types";
import { getStoredValue, setStoredValue } from "@/lib/storage";

export interface ApiKeyEntry {
  name: string;
  value: string;
}

export interface SessionDefaults {
  provider: string;
  harness: string;
  skip_permissions: boolean;
  sandbox_timeout: number;
  session_timeout: number;
  template: string;
}

const SESSION_DEFAULTS_FALLBACK: SessionDefaults = {
  provider: "e2b",
  harness: "claude-code",
  skip_permissions: false,
  sandbox_timeout: 300,
  session_timeout: 3600,
  template: "",
};

export const appStorage = {
  get sessionDefaults(): SessionDefaults {
    return getStoredValue<SessionDefaults>("defaults", SESSION_DEFAULTS_FALLBACK);
  },
  set sessionDefaults(value: SessionDefaults) {
    setStoredValue("defaults", value);
  },

  get apiKeys(): ApiKeyEntry[] {
    return getStoredValue<ApiKeyEntry[]>("api-keys", []);
  },
  set apiKeys(value: ApiKeyEntry[]) {
    setStoredValue("api-keys", value);
  },

  get detectedRepository(): DetectedWorkspace | null {
    return getStoredValue<DetectedWorkspace | null>("repository", null);
  },
  set detectedRepository(value: DetectedWorkspace | null) {
    setStoredValue("repository", value);
  },
} as const;

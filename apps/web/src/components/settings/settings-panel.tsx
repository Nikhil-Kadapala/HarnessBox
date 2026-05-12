import { useCallback, useState } from "react";
import { ArrowLeft, CheckCircle, Eye, EyeOff, FolderGit2, Plus, RefreshCw, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import { useCredentials } from "@/hooks/use-credentials";
import { useLocalStorage } from "@/hooks/use-local-storage";
import { detectWorkspace } from "@/lib/api";
import type { DetectedWorkspace } from "@/types";

interface StoredKey {
  name: string;
  value: string;
}

interface Defaults {
  provider: string;
  harness: string;
  skipPermissions: boolean;
}

const DEFAULT_KEYS: StoredKey[] = [
  { name: "ANTHROPIC_API_KEY", value: "" },
  { name: "E2B_API_KEY", value: "" },
  { name: "OPENAI_API_KEY", value: "" },
  { name: "GITHUB_TOKEN", value: "" },
];

interface SettingsPanelProps {
  onClose: () => void;
}

const FRIENDLY_NAMES: Record<string, string> = {
  ANTHROPIC_API_KEY: "Anthropic API",
  OPENAI_API_KEY: "OpenAI",
  E2B_API_KEY: "E2B",
  GITHUB_TOKEN: "GitHub Token",
  GOOGLE_API_KEY: "Google",
  GEMINI_API_KEY: "Gemini",
  gh_cli: "GitHub CLI",
  e2b_cli: "E2B CLI",
  claude_code: "Claude Code",
  claude_auth_mode: "Claude Auth",
  aws_credentials: "AWS Credentials",
};

export function SettingsPanel({ onClose }: SettingsPanelProps) {
  const { credentials, loading: credentialsLoading, refresh: refreshCredentials } = useCredentials();
  const [storedKeys, setStoredKeys] = useLocalStorage<StoredKey[]>("api-keys", DEFAULT_KEYS);
  const [defaults, setDefaults] = useLocalStorage<Defaults>("defaults", {
    provider: "e2b",
    harness: "claude-code",
    skipPermissions: true,
  });
  const [visibleKeys, setVisibleKeys] = useState<Set<number>>(new Set());
  const [repoPath, setRepoPath] = useState("");
  const [detectedRepo, setDetectedRepo] = useLocalStorage<DetectedWorkspace | null>("repository", null);
  const [detecting, setDetecting] = useState(false);
  const [detectError, setDetectError] = useState<string | null>(null);

  const toggleVisibility = (index: number) => {
    setVisibleKeys((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  };

  const updateKey = useCallback(
    (index: number, field: "name" | "value", val: string) => {
      setStoredKeys(storedKeys.map((k, i) => (i === index ? { ...k, [field]: val } : k)));
    },
    [storedKeys, setStoredKeys],
  );

  const addKey = useCallback(() => {
    setStoredKeys([...storedKeys, { name: "", value: "" }]);
  }, [storedKeys, setStoredKeys]);

  const removeKey = useCallback(
    (index: number) => {
      setStoredKeys(storedKeys.filter((_, i) => i !== index));
      setVisibleKeys((prev) => {
        const next = new Set<number>();
        for (const v of prev) {
          if (v < index) next.add(v);
          else if (v > index) next.add(v - 1);
        }
        return next;
      });
    },
    [storedKeys, setStoredKeys],
  );

  const handleDetectRepo = useCallback(async () => {
    if (!repoPath.trim()) return;
    setDetecting(true);
    setDetectError(null);
    try {
      const detected = await detectWorkspace(repoPath.trim());
      setDetectedRepo(detected);
      setDetectError(null);
    } catch (err) {
      setDetectError(err instanceof Error ? err.message : "Failed to detect repository");
      setDetectedRepo(null);
    } finally {
      setDetecting(false);
    }
  }, [repoPath, setDetectedRepo]);

  const configuredCount = storedKeys.filter((k) => k.name && k.value).length;

  return (
    <div className="flex flex-1 flex-col min-h-0 overflow-y-auto">
      <div className="max-w-2xl mx-auto w-full p-6 space-y-8">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="sm" className="h-8 w-8 p-0" onClick={onClose}>
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div>
            <h2 className="text-lg font-semibold">Settings</h2>
            <p className="text-sm text-muted-foreground">
              API keys and session defaults
            </p>
          </div>
        </div>

        <Separator />

        {/* Repository */}
        <section className="space-y-4">
          <div>
            <h3 className="text-sm font-medium">Repository</h3>
            <p className="text-xs text-muted-foreground">
              Local git repo path — auto-fills workspace config for new sessions
            </p>
          </div>

          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <Input
                className="h-8 text-xs font-mono flex-1"
                placeholder="/Users/username/myrepo"
                value={repoPath}
                onChange={(e) => setRepoPath(e.target.value)}
              />
              <Button
                variant="outline"
                size="sm"
                className="h-8 text-xs"
                onClick={handleDetectRepo}
                disabled={detecting || !repoPath.trim()}
              >
                <FolderGit2 className={`h-3 w-3 mr-1 ${detecting ? "animate-pulse" : ""}`} />
                Detect
              </Button>
            </div>

            {detectError && (
              <p className="text-xs text-destructive">{detectError}</p>
            )}

            {detectedRepo && (
              <div className="rounded-md border border-accent/30 bg-accent/5 p-3 space-y-2">
                <div className="flex items-center gap-2">
                  <CheckCircle className="h-3 w-3 text-accent shrink-0" />
                  <span className="text-xs font-medium">{detectedRepo.name}</span>
                </div>
                <div className="space-y-1 text-xs text-muted-foreground font-mono pl-5">
                  <div>Remote: {detectedRepo.remote}</div>
                  <div>Branch: {detectedRepo.default_branch}</div>
                </div>
              </div>
            )}
          </div>
        </section>

        <Separator />

        {/* API Keys */}
        <section className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-sm font-medium">API Keys</h3>
              <p className="text-xs text-muted-foreground">
                Stored in your browser. Auto-injected as env vars when creating sessions.
              </p>
            </div>
            <Badge variant="secondary" className="text-[10px]">
              {configuredCount} configured
            </Badge>
          </div>

          <div className="space-y-2">
            {storedKeys.map((k, i) => (
              <div key={i} className="flex items-center gap-2">
                <Input
                  className="h-8 text-xs font-mono w-48 shrink-0"
                  placeholder="KEY_NAME"
                  value={k.name}
                  onChange={(e) => updateKey(i, "name", e.target.value)}
                />
                <div className="relative flex-1">
                  <Input
                    className="h-8 text-xs font-mono pr-8"
                    placeholder="value"
                    type={visibleKeys.has(i) ? "text" : "password"}
                    value={k.value}
                    onChange={(e) => updateKey(i, "value", e.target.value)}
                  />
                  <Button
                    variant="ghost"
                    size="sm"
                    className="absolute right-0 top-0 h-8 w-8 p-0"
                    onClick={() => toggleVisibility(i)}
                  >
                    {visibleKeys.has(i) ? (
                      <EyeOff className="h-3 w-3 text-muted-foreground" />
                    ) : (
                      <Eye className="h-3 w-3 text-muted-foreground" />
                    )}
                  </Button>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-8 w-8 p-0 shrink-0"
                  onClick={() => removeKey(i)}
                >
                  <Trash2 className="h-3 w-3 text-muted-foreground hover:text-destructive" />
                </Button>
              </div>
            ))}
          </div>

          <Button variant="outline" size="sm" onClick={addKey} className="text-xs">
            <Plus className="h-3 w-3 mr-1" />
            Add Key
          </Button>
        </section>

        <Separator />

        {/* Server Credentials */}
        <section className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-sm font-medium">Server Credentials</h3>
              <p className="text-xs text-muted-foreground">
                Detected on the machine running the HarnessBox server
              </p>
            </div>
            <Button
              variant="ghost"
              size="sm"
              className="h-7 text-xs"
              onClick={refreshCredentials}
              disabled={credentialsLoading}
            >
              <RefreshCw className={`h-3 w-3 mr-1 ${credentialsLoading ? "animate-spin" : ""}`} />
              Refresh
            </Button>
          </div>

          {(() => {
            const available = credentials.filter((p) => p.available);
            if (credentialsLoading) {
              return (
                <p className="text-xs text-muted-foreground">Checking...</p>
              );
            }
            if (credentials.length === 0) {
              return (
                <p className="text-xs text-muted-foreground">
                  Could not reach the server. Start it with: cd sdk && uv run uvicorn harnessbox.server:create_app --factory --port 8000
                </p>
              );
            }
            if (available.length === 0) {
              return (
                <p className="text-xs text-muted-foreground">
                  No credentials detected. Set API keys above or configure env vars on the server.
                </p>
              );
            }
            return (
              <div className="flex flex-wrap gap-2">
                {available.map((probe) => (
                  <div
                    key={probe.name}
                    className="flex items-center gap-2 rounded-full border border-accent/30 bg-accent/5 px-3 py-1.5"
                  >
                    <CheckCircle className="h-3 w-3 text-accent shrink-0" />
                    <span className="text-xs font-mono">
                      {FRIENDLY_NAMES[probe.name] ?? probe.name}
                    </span>
                  </div>
                ))}
              </div>
            );
          })()}
        </section>

        <Separator />

        {/* Defaults */}
        <section className="space-y-4">
          <div>
            <h3 className="text-sm font-medium">Session Defaults</h3>
            <p className="text-xs text-muted-foreground">
              Pre-filled when creating new sessions
            </p>
          </div>

          <div className="flex items-center gap-4 flex-wrap">
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">Provider</Label>
              <Select
                value={defaults.provider}
                onValueChange={(v) => v && setDefaults({ ...defaults, provider: v })}
              >
                <SelectTrigger className="w-[140px] h-8 text-sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="e2b">e2b</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">Harness</Label>
              <Select
                value={defaults.harness}
                onValueChange={(v) => v && setDefaults({ ...defaults, harness: v })}
              >
                <SelectTrigger className="w-[160px] h-8 text-sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="claude-code">claude-code</SelectItem>
                  <SelectItem value="codex">codex</SelectItem>
                  <SelectItem value="gemini-cli">gemini-cli</SelectItem>
                  <SelectItem value="opencode">opencode</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="flex items-center gap-2">
              <Switch
                checked={defaults.skipPermissions}
                onCheckedChange={(v) => setDefaults({ ...defaults, skipPermissions: v })}
              />
              <Label className="text-xs text-muted-foreground">Skip permissions</Label>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}

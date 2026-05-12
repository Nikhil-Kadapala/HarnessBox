import { useCallback, useState } from "react";
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
import { Switch } from "@/components/ui/switch";
import type { CreateSessionRequest } from "@/types";

const PROVIDERS = ["e2b"] as const;
const HARNESSES = ["claude-code", "codex", "gemini-cli", "opencode"] as const;

interface NewSessionPanelProps {
  onSubmit: (config: CreateSessionRequest) => void;
  onCancel: () => void;
  disabled?: boolean;
}

export function NewSessionPanel({ onSubmit, onCancel, disabled }: NewSessionPanelProps) {
  const [provider, setProvider] = useState("e2b");
  const [harness, setHarness] = useState("claude-code");
  const [skipPermissions, setSkipPermissions] = useState(true);
  const [secrets, setSecrets] = useState<{ key: string; value: string }[]>([
    { key: "ANTHROPIC_API_KEY", value: "" },
    { key: "E2B_API_KEY", value: "" },
  ]);

  const addSecret = () => setSecrets((prev) => [...prev, { key: "", value: "" }]);
  const removeSecret = (i: number) => setSecrets((prev) => prev.filter((_, idx) => idx !== i));
  const updateSecret = (i: number, field: "key" | "value", val: string) =>
    setSecrets((prev) => prev.map((s, idx) => (idx === i ? { ...s, [field]: val } : s)));

  const handleSubmit = useCallback(() => {
    const env_vars: Record<string, string> = {};
    for (const s of secrets) {
      if (s.key && s.value) env_vars[s.key] = s.value;
    }
    onSubmit({ provider, harness, env_vars, skip_permissions: skipPermissions });
  }, [provider, harness, skipPermissions, secrets, onSubmit]);

  return (
    <div className="flex flex-1 items-center justify-center p-8">
      <div className="w-full max-w-lg space-y-6">
        <div>
          <h2 className="text-lg font-semibold">New Session</h2>
          <p className="text-sm text-muted-foreground">
            Configure and launch a sandboxed coding agent
          </p>
        </div>

        <div className="space-y-4 rounded-lg border border-border bg-card p-4">
          <div className="flex items-center gap-3 flex-wrap">
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">Provider</Label>
              <Select value={provider} onValueChange={(v) => v && setProvider(v)} disabled={disabled}>
                <SelectTrigger className="w-[140px] h-8 text-sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PROVIDERS.map((p) => (
                    <SelectItem key={p} value={p}>{p}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">Harness</Label>
              <Select value={harness} onValueChange={(v) => v && setHarness(v)} disabled={disabled}>
                <SelectTrigger className="w-[160px] h-8 text-sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {HARNESSES.map((h) => (
                    <SelectItem key={h} value={h}>{h}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="flex items-center gap-2 ml-auto">
              <Switch
                id="skip-perms"
                checked={skipPermissions}
                onCheckedChange={setSkipPermissions}
                disabled={disabled}
              />
              <Label htmlFor="skip-perms" className="text-xs text-muted-foreground">
                Skip permissions
              </Label>
            </div>
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label className="text-xs text-muted-foreground">API Keys</Label>
              <Button variant="ghost" size="sm" onClick={addSecret} disabled={disabled} className="h-6 text-xs">
                + Add
              </Button>
            </div>
            {secrets.map((s, i) => (
              <div key={i} className="flex items-center gap-2">
                <Input
                  className="h-8 text-sm font-mono flex-1"
                  placeholder="KEY"
                  value={s.key}
                  onChange={(e) => updateSecret(i, "key", e.target.value)}
                  disabled={disabled}
                />
                <Input
                  className="h-8 text-sm font-mono flex-[2]"
                  placeholder="value"
                  type="password"
                  value={s.value}
                  onChange={(e) => updateSecret(i, "value", e.target.value)}
                  disabled={disabled}
                />
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => removeSecret(i)}
                  disabled={disabled}
                  className="h-8 w-8 p-0 text-muted-foreground hover:text-destructive"
                >
                  x
                </Button>
              </div>
            ))}
          </div>
        </div>

        <div className="flex gap-2">
          <Button onClick={handleSubmit} disabled={disabled} className="flex-1">
            Create Session
          </Button>
          <Button variant="ghost" onClick={onCancel} disabled={disabled}>
            Cancel
          </Button>
        </div>
      </div>
    </div>
  );
}

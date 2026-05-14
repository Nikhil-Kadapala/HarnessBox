import { useCallback, useState } from "react";
import { ChevronDown, ChevronRight, Plus, Sparkles, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
import { useDiscovery } from "@/hooks/use-discovery";
import { appStorage } from "@/lib/storage-schema";
import { fetchWorkspaceName } from "@/lib/api";
import type { CreateSessionRequest } from "@/types";

interface SessionConfigPanelProps {
  onSubmit: (config: CreateSessionRequest) => void;
  onCancel: () => void;
  disabled?: boolean;
  defaultRepoUrl?: string;
}

export function SessionConfigPanel({ onSubmit, onCancel, disabled, defaultRepoUrl }: SessionConfigPanelProps) {
  const { harnesses, providers, guards, loading: discoveryLoading } = useDiscovery();

  const storedDefaults = appStorage.sessionDefaults;

  const [provider, setProvider] = useState(storedDefaults.provider);
  const [harness, setHarness] = useState(storedDefaults.harness);
  const [skipPermissions, setSkipPermissions] = useState(storedDefaults.skip_permissions);
  const [sandboxTimeout, setSandboxTimeout] = useState(30);
  const [sessionTimeout, setSessionTimeout] = useState(15);
  const [template, setTemplate] = useState("");

  const [envVars, setEnvVars] = useState<{ key: string; value: string }[]>(
    appStorage.apiKeys
      .filter((k) => k.name && k.value)
      .map((k) => ({ key: k.name, value: k.value })),
  );

  const [securityOpen, setSecurityOpen] = useState(false);
  const [denyNetwork, setDenyNetwork] = useState(false);
  const [allGuards, setAllGuards] = useState(true);
  const [selectedGuards, setSelectedGuards] = useState<Set<string>>(new Set());
  const [deniedTools, setDeniedTools] = useState("");

  const detectedRepo = appStorage.detectedRepository;
  const hasDetectedRepo = !!detectedRepo || !!defaultRepoUrl;
  const [workspaceOpen, setWorkspaceOpen] = useState(hasDetectedRepo);
  const [repoUrl, setRepoUrl] = useState(defaultRepoUrl ?? detectedRepo?.remote ?? "");
  const [branch, setBranch] = useState(detectedRepo?.default_branch ?? "main");
  const [authToken, setAuthToken] = useState("");
  const [cloneDepth, setCloneDepth] = useState("");
  const [workspaceName, setWorkspaceName] = useState<string>("");
  const [generatingName, setGeneratingName] = useState(false);
  const [nameRequested, setNameRequested] = useState(false);

  const generateName = useCallback(() => {
    if (!workspaceName && repoUrl && !nameRequested) {
      setNameRequested(true);
      setGeneratingName(true);
      fetchWorkspaceName()
        .then(setWorkspaceName)
        .catch(() => setWorkspaceName(""))
        .finally(() => setGeneratingName(false));
    }
  }, [workspaceName, repoUrl, nameRequested]);

  // Auto-generate name when workspace is initially open with detected repo
  if (hasDetectedRepo && workspaceOpen && !workspaceName && !nameRequested) {
    generateName();
  }

  const handleWorkspaceToggle = useCallback(() => {
    const newOpen = !workspaceOpen;
    setWorkspaceOpen(newOpen);
    if (newOpen && repoUrl && !workspaceName) {
      generateName();
    }
  }, [workspaceOpen, repoUrl, workspaceName, generateName]);

  const addEnvVar = () => setEnvVars((prev) => [...prev, { key: "", value: "" }]);
  const removeEnvVar = (i: number) => setEnvVars((prev) => prev.filter((_, idx) => idx !== i));
  const updateEnvVar = (i: number, field: "key" | "value", val: string) =>
    setEnvVars((prev) => prev.map((e, idx) => (idx === i ? { ...e, [field]: val } : e)));

  const toggleGuard = (name: string) => {
    setSelectedGuards((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  const handleSubmit = useCallback(() => {
    const env: Record<string, string> = {};
    for (const e of envVars) {
      if (e.key && e.value) env[e.key] = e.value;
    }

    const config: CreateSessionRequest = {
      provider,
      harness,
      env_vars: env,
      skip_permissions: skipPermissions,
      sandbox_timeout: sandboxTimeout * 60,
      session_timeout: sessionTimeout * 60,
      template: template || undefined,
    };

    if (securityOpen) {
      config.security_policy = {
        deny_network: denyNetwork,
        credential_guards: allGuards ? true : [...selectedGuards],
        denied_tools: deniedTools
          .split(",")
          .map((t) => t.trim())
          .filter(Boolean),
      };
    }

    if (workspaceOpen && repoUrl) {
      config.workspace = {
        remote: repoUrl,
        branch,
        auth_token: authToken || undefined,
        clone_depth: cloneDepth ? parseInt(cloneDepth, 10) : undefined,
        clone_dir_name: workspaceName || undefined,
      };
    }

    onSubmit(config);
  }, [
    provider, harness, skipPermissions, sandboxTimeout, sessionTimeout, template, envVars,
    securityOpen, denyNetwork, allGuards, selectedGuards, deniedTools,
    workspaceOpen, repoUrl, branch, authToken, cloneDepth, workspaceName, onSubmit,
  ]);

  const providerOptions = providers.length > 0 ? providers : [{ name: "e2b" }];
  const harnessOptions =
    harnesses.length > 0
      ? harnesses
      : [
          { name: "claude-code" },
          { name: "codex" },
          { name: "opencode" },
        ].map((h) => ({ ...h, cli_command: "", supports_persistent: false, default_template: null, workspace_root: "/workspace" }));

  return (
    <div className="flex flex-1 flex-col min-h-0 overflow-y-auto">
      <div className="max-w-2xl mx-auto w-full p-6 space-y-6">
        <div>
          <h2 className="text-lg font-semibold">New Session</h2>
          <p className="text-sm text-muted-foreground">
            Configure and launch a sandboxed coding agent
            {discoveryLoading && " — loading server config..."}
          </p>
        </div>

        {/* Basics */}
        <section className="space-y-4 rounded-lg border border-border bg-card p-4">
          <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Basics</h3>
          <div className="flex items-center gap-3 flex-wrap">
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">Provider</Label>
              <Select value={provider} onValueChange={(v) => v && setProvider(v)} disabled={disabled}>
                <SelectTrigger className="w-[140px] h-8 text-sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {providerOptions.map((p) => (
                    <SelectItem key={p.name} value={p.name}>{p.name}</SelectItem>
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
                  {harnessOptions.map((h) => (
                    <SelectItem key={h.name} value={h.name}>{h.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">Sandbox (min)</Label>
              <Input
                className="h-8 text-sm w-[70px]"
                type="number"
                value={sandboxTimeout}
                onChange={(e) => setSandboxTimeout(parseInt(e.target.value, 10) || 30)}
                disabled={disabled}
              />
            </div>
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">Idle (min)</Label>
              <Input
                className="h-8 text-sm w-[70px]"
                type="number"
                value={sessionTimeout}
                onChange={(e) => setSessionTimeout(parseInt(e.target.value, 10) || 15)}
                disabled={disabled}
              />
            </div>
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">Template</Label>
              <Input
                className="h-8 text-sm w-[120px]"
                placeholder="default"
                value={template}
                onChange={(e) => setTemplate(e.target.value)}
                disabled={disabled}
              />
            </div>
            <div className="flex items-center gap-2 ml-auto">
              <Switch checked={skipPermissions} onCheckedChange={setSkipPermissions} disabled={disabled} />
              <Label className="text-xs text-muted-foreground">Skip permissions</Label>
            </div>
          </div>
        </section>

        {/* Environment Variables */}
        <section className="space-y-3 rounded-lg border border-border bg-card p-4">
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
              Environment Variables
            </h3>
            <Button variant="ghost" size="sm" onClick={addEnvVar} disabled={disabled} className="h-6 text-xs">
              <Plus className="h-3 w-3 mr-1" />
              Add
            </Button>
          </div>
          {envVars.length === 0 && (
            <p className="text-xs text-muted-foreground">
              No env vars. Keys from Settings are auto-injected.
            </p>
          )}
          {envVars.map((e, i) => (
            <div key={i} className="flex items-center gap-2">
              <Input
                className="h-8 text-xs font-mono flex-1"
                placeholder="KEY"
                value={e.key}
                onChange={(ev) => updateEnvVar(i, "key", ev.target.value)}
                disabled={disabled}
              />
              <Input
                className="h-8 text-xs font-mono flex-2"
                placeholder="value"
                type="password"
                value={e.value}
                onChange={(ev) => updateEnvVar(i, "value", ev.target.value)}
                disabled={disabled}
              />
              <Button variant="ghost" size="sm" className="h-8 w-8 p-0" onClick={() => removeEnvVar(i)} disabled={disabled}>
                <Trash2 className="h-3 w-3 text-muted-foreground" />
              </Button>
            </div>
          ))}
        </section>

        {/* Security Policy (collapsible) */}
        <section className="rounded-lg border border-border bg-card">
          <button
            className="flex items-center gap-2 w-full p-4 text-left"
            onClick={() => setSecurityOpen(!securityOpen)}
          >
            {securityOpen ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
            <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Security Policy</h3>
          </button>
          {securityOpen && (
            <div className="px-4 pb-4 space-y-4">
              <Separator />
              <div className="flex items-center gap-2">
                <Switch checked={denyNetwork} onCheckedChange={setDenyNetwork} disabled={disabled} />
                <Label className="text-xs">Deny network access</Label>
              </div>

              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <Checkbox
                    checked={allGuards}
                    onCheckedChange={(v) => setAllGuards(!!v)}
                    disabled={disabled}
                  />
                  <Label className="text-xs font-medium">All credential guards</Label>
                </div>
                {!allGuards && (
                  <div className="grid grid-cols-2 gap-1 pl-6">
                    {guards.map((g) => (
                      <div key={g.name} className="flex items-center gap-2">
                        <Checkbox
                          checked={selectedGuards.has(g.name)}
                          onCheckedChange={() => toggleGuard(g.name)}
                          disabled={disabled}
                        />
                        <Label className="text-xs">
                          {g.name}
                          <span className="text-muted-foreground ml-1">
                            ({g.bash_deny_count + g.read_deny_count} rules)
                          </span>
                        </Label>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="space-y-1">
                <Label className="text-xs text-muted-foreground">Denied tools (comma-separated)</Label>
                <Input
                  className="h-8 text-xs font-mono"
                  placeholder="WebFetch, WebSearch, Agent"
                  value={deniedTools}
                  onChange={(e) => setDeniedTools(e.target.value)}
                  disabled={disabled}
                />
              </div>
            </div>
          )}
        </section>

        {/* Workspace (collapsible) */}
        <section className="rounded-lg border border-border bg-card">
          <button
            className="flex items-center gap-2 w-full p-4 text-left"
            onClick={handleWorkspaceToggle}
          >
            {workspaceOpen ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
            <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Workspace</h3>
          </button>
          {workspaceOpen && (
            <div className="px-4 pb-4 space-y-3">
              <Separator />
              {workspaceName && (
                <div className="rounded-md border border-accent/30 bg-accent/5 p-2 flex items-center gap-2">
                  <Sparkles className="h-3 w-3 text-accent shrink-0" />
                  <span className="text-xs font-medium">Workspace: {workspaceName}</span>
                </div>
              )}
              {generatingName && (
                <p className="text-xs text-muted-foreground animate-pulse">Generating workspace name...</p>
              )}
              <div className="space-y-1">
                <Label className="text-xs text-muted-foreground">Repository URL</Label>
                <Input
                  className="h-8 text-xs font-mono"
                  placeholder="https://github.com/owner/repo.git"
                  value={repoUrl}
                  onChange={(e) => setRepoUrl(e.target.value)}
                  disabled={disabled}
                />
              </div>
              <div className="flex gap-3">
                <div className="space-y-1 flex-1">
                  <Label className="text-xs text-muted-foreground">Branch</Label>
                  <Input
                    className="h-8 text-xs font-mono"
                    value={branch}
                    onChange={(e) => setBranch(e.target.value)}
                    disabled={disabled}
                  />
                </div>
                <div className="space-y-1 w-[80px]">
                  <Label className="text-xs text-muted-foreground">Depth</Label>
                  <Input
                    className="h-8 text-xs"
                    type="number"
                    placeholder="full"
                    value={cloneDepth}
                    onChange={(e) => setCloneDepth(e.target.value)}
                    disabled={disabled}
                  />
                </div>
              </div>
              <div className="space-y-1">
                <Label className="text-xs text-muted-foreground">Auth token (PAT)</Label>
                <Input
                  className="h-8 text-xs font-mono"
                  type="password"
                  placeholder="ghp_..."
                  value={authToken}
                  onChange={(e) => setAuthToken(e.target.value)}
                  disabled={disabled}
                />
              </div>
            </div>
          )}
        </section>

        {/* Actions */}
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

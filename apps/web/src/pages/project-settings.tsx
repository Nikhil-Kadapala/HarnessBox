import { useEffect, useState } from "react";
import { useNavigate, useParams } from "@tanstack/react-router";
import { ArrowLeft, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useDiscovery } from "@/hooks/use-discovery";
import { getProject, updateProject } from "@/lib/api";
import type { Project, ProjectWorkspaceSettings } from "@/types";

export function ProjectSettingsPage() {
  const { projectId } = useParams({ from: "/projects/$projectId/settings" });
  const navigate = useNavigate();
  const { providers, harnesses, loading: discoveryLoading } = useDiscovery();
  const [project, setProject] = useState<Project | null>(null);
  const [settings, setSettings] = useState<ProjectWorkspaceSettings | null>(null);
  const [branch, setBranch] = useState("");
  const [deniedTools, setDeniedTools] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    getProject(projectId)
      .then((value) => {
        setProject(value);
        setSettings(value.workspace_settings);
        setBranch(value.default_branch);
        setDeniedTools((value.workspace_settings.security_policy.denied_tools ?? []).join(", "));
      })
      .catch((cause) => setError(cause instanceof Error ? cause.message : "Could not load Project."))
      .finally(() => setLoading(false));
  }, [projectId]);

  function updateSettings(patch: Partial<ProjectWorkspaceSettings>) {
    setSettings((current) => current ? { ...current, ...patch } : current);
    setSaved(false);
  }

  async function handleSave(event: React.FormEvent) {
    event.preventDefault();
    if (!settings) return;
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const updated = await updateProject(projectId, {
        default_branch: branch.trim(),
        workspace_settings: {
          ...settings,
          security_policy: {
            ...settings.security_policy,
            denied_tools: deniedTools.split(",").map((tool) => tool.trim()).filter(Boolean),
          },
        },
      });
      setProject(updated);
      setSettings(updated.workspace_settings);
      setBranch(updated.default_branch);
      setSaved(true);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save Project settings.");
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <div className="flex flex-1 items-center justify-center"><Loader2 className="h-5 w-5 animate-spin" /></div>;
  if (!project || !settings) return <div className="mx-auto max-w-2xl p-6"><p role="alert" className="text-sm text-destructive">{error ?? "Project not found."}</p></div>;

  return (
    <div className="flex-1 overflow-y-auto">
      <form onSubmit={handleSave} className="mx-auto w-full max-w-3xl space-y-6 p-6">
        <div className="flex items-start gap-3">
          <Button type="button" variant="ghost" size="icon" aria-label="Back to projects" onClick={() => navigate({ to: "/" })}>
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div><h1 className="text-xl font-semibold">{project.name} settings</h1><p className="mt-1 text-sm text-muted-foreground">Defaults used for new workspaces and conversations. Existing workspaces are unchanged.</p></div>
        </div>

        <section className="space-y-4 rounded-lg border bg-card p-5">
          <h2 className="text-sm font-semibold">Repository</h2>
          <div className="space-y-2"><Label htmlFor="project-remote">Git remote</Label><Input id="project-remote" value={project.remote} readOnly className="font-mono text-sm" /></div>
          <div className="space-y-2"><Label htmlFor="project-base-branch">Default base branch</Label><Input id="project-base-branch" value={branch} onChange={(event) => { setBranch(event.target.value); setSaved(false); }} required /></div>
        </section>

        <section className="space-y-4 rounded-lg border bg-card p-5">
          <h2 className="text-sm font-semibold">Workspace defaults</h2>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2"><Label>Sandbox provider</Label><Select value={settings.provider} onValueChange={(value) => value && updateSettings({ provider: value })} disabled={discoveryLoading}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{(providers.length ? providers : [{ name: settings.provider }]).map((provider) => <SelectItem key={provider.name} value={provider.name}>{provider.name}</SelectItem>)}</SelectContent></Select></div>
            <div className="space-y-2"><Label>Default harness</Label><Select value={settings.default_harness} onValueChange={(value) => value && updateSettings({ default_harness: value })} disabled={discoveryLoading}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{(harnesses.length ? harnesses : [{ name: settings.default_harness }]).map((harness) => <SelectItem key={harness.name} value={harness.name}>{harness.name}</SelectItem>)}</SelectContent></Select></div>
            <div className="space-y-2"><Label htmlFor="sandbox-timeout">Sandbox lifetime (minutes)</Label><Input id="sandbox-timeout" type="number" min={1} max={1440} value={Math.round(settings.sandbox_timeout / 60)} onChange={(event) => updateSettings({ sandbox_timeout: Math.max(60, Number(event.target.value) * 60 || 60) })} /></div>
            <div className="space-y-2"><Label htmlFor="idle-timeout">Idle timeout (minutes)</Label><Input id="idle-timeout" type="number" min={0} max={1440} value={Math.round(settings.session_timeout / 60)} onChange={(event) => updateSettings({ session_timeout: Math.max(0, Number(event.target.value) * 60 || 0) })} /></div>
          </div>
          <div className="flex items-center justify-between rounded-md border p-3"><div><Label htmlFor="skip-permissions">Skip agent permission prompts</Label><p className="text-xs text-muted-foreground">Applies to new workspaces for this Project.</p></div><Switch id="skip-permissions" checked={settings.skip_permissions} onCheckedChange={(value) => updateSettings({ skip_permissions: value })} /></div>
        </section>

        <section className="space-y-4 rounded-lg border bg-card p-5">
          <h2 className="text-sm font-semibold">Security defaults</h2>
          <div className="flex items-center justify-between rounded-md border p-3"><div><Label htmlFor="deny-network">Deny network tools</Label><p className="text-xs text-muted-foreground">Block WebFetch and WebSearch in the agent harness.</p></div><Switch id="deny-network" checked={!!settings.security_policy.deny_network} onCheckedChange={(value) => updateSettings({ security_policy: { ...settings.security_policy, deny_network: value } })} /></div>
          <div className="space-y-2"><Label htmlFor="denied-tools">Additional denied tools</Label><Input id="denied-tools" value={deniedTools} onChange={(event) => { setDeniedTools(event.target.value); setSaved(false); }} placeholder="WebFetch, Agent" /><p className="text-xs text-muted-foreground">Separate tool names with commas. Credential guards remain enabled by default.</p></div>
        </section>

        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        {saved && <p role="status" className="text-sm text-green-600">Settings saved.</p>}
        <div className="flex justify-end gap-2"><Button type="button" variant="ghost" onClick={() => navigate({ to: "/" })}>Back</Button><Button type="submit" disabled={busy || !branch.trim()}>{busy ? "Saving…" : "Save settings"}</Button></div>
      </form>
    </div>
  );
}

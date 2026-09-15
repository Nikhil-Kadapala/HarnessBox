import { useState } from "react";
import { Check, FolderGit2, FolderOpen, Globe, PencilLine } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { detectWorkspace } from "@/lib/api";
import type { Project } from "@/types";

interface LocalProjectSource {
  name: string;
  remote: string;
  default_branch: string;
}

interface DirectoryPickerHandle {
  name: string;
  getDirectoryHandle(name: string): Promise<DirectoryPickerHandle>;
  getFileHandle(name: string): Promise<{ getFile(): Promise<{ text(): Promise<string> }> }>;
}

type DirectoryPickerWindow = Window & {
  showDirectoryPicker?: (options?: { mode?: "read" }) => Promise<DirectoryPickerHandle>;
};

function findOrigin(config: string): string | null {
  const sections = config.matchAll(/^\s*\[remote\s+"([^"]+)"\]\s*([\s\S]*?)(?=^\s*\[|$)/gim);
  for (const [, name, body] of sections) {
    if (name.toLowerCase() !== "origin") continue;
    const match = body.match(/^\s*url\s*=\s*(?:"([^"]+)"|'([^']+)'|(.+?))\s*$/im);
    const remote = match?.[1] ?? match?.[2] ?? match?.[3]?.trim();
    if (!remote) return null;
    try {
      const url = new URL(remote);
      url.username = "";
      url.password = "";
      url.search = "";
      url.hash = "";
      return url.toString().replace(/\/$/, "");
    } catch {
      // Preserve SCP-style SSH remotes, while stripping URL-like query fragments.
      return remote.replace(/[?#].*$/, "");
    }
  }
  return null;
}

async function readRemoteDefaultBranch(gitDir: DirectoryPickerHandle): Promise<string> {
  try {
    const refs = await gitDir.getDirectoryHandle("refs");
    const remotes = await refs.getDirectoryHandle("remotes");
    const origin = await remotes.getDirectoryHandle("origin");
    const head = await (await origin.getFileHandle("HEAD")).getFile().then((file) => file.text());
    return head.match(/refs\/remotes\/origin\/(.+)/)?.[1]?.trim() || "main";
  } catch {
    return "main";
  }
}

interface CreateProjectDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreate: (project: Pick<Project, "name" | "remote" | "default_branch">) => Promise<void>;
}

function repoNameFromUrl(url: string): string {
  const leaf = url.trim().replace(/\.git$/, "").split(/[/:]/).filter(Boolean).at(-1);
  return leaf || "";
}

export function CreateProjectDialog({ open, onOpenChange, onCreate }: CreateProjectDialogProps) {
  const [source, setSource] = useState<"remote" | "local">("remote");
  const [name, setName] = useState("");
  const [repoUrl, setRepoUrl] = useState("");
  const [localPath, setLocalPath] = useState("");
  const [localRepo, setLocalRepo] = useState<LocalProjectSource | null>(null);
  const [showManualPath, setShowManualPath] = useState(false);
  const [branch, setBranch] = useState("main");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function reset() {
    setName("");
    setRepoUrl("");
    setLocalPath("");
    setLocalRepo(null);
    setShowManualPath(false);
    setBranch("main");
    setError(null);
  }

  async function chooseLocalFolder() {
    setError(null);
    const picker = (window as DirectoryPickerWindow).showDirectoryPicker;
    if (!picker) {
      setShowManualPath(true);
      setError("Folder selection isn’t supported by this browser. Enter the repository path instead.");
      return;
    }

    try {
      const folder = await picker.call(window, { mode: "read" });
      const gitDir = await folder.getDirectoryHandle(".git");
      const config = await (await gitDir.getFileHandle("config")).getFile().then((file) => file.text());
      const remote = findOrigin(config);
      if (!remote) throw new Error("This folder has no Git remote named origin.");
      const default_branch = await readRemoteDefaultBranch(gitDir);
      setLocalRepo({ name: folder.name, remote, default_branch });
      setLocalPath("");
      setBranch(default_branch);
    } catch (cause) {
      if (cause instanceof DOMException && cause.name === "AbortError") return;
      setLocalRepo(null);
      setError(cause instanceof Error ? cause.message : "Could not read this Git repository.");
    }
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const detected = source === "local"
        ? localRepo ?? (localPath.trim() ? await detectWorkspace(localPath.trim()) : null)
        : null;
      const remote = detected?.remote ?? repoUrl.trim();
      const defaultBranch = detected?.default_branch ?? branch.trim();
      const projectName = name.trim() || detected?.name || repoNameFromUrl(remote);
      if (!projectName || !remote || !defaultBranch) {
        throw new Error("Enter a project name and a valid Git repository.");
      }
      await onCreate({ name: projectName, remote, default_branch: defaultBranch });
      reset();
      onOpenChange(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not create project.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader><DialogTitle>Create project</DialogTitle></DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="project-name">Project name</Label>
            <Input id="project-name" value={name} onChange={(event) => setName(event.target.value)} placeholder="my-project" />
          </div>
          <div className="flex gap-2">
            <Button type="button" variant={source === "remote" ? "secondary" : "ghost"} onClick={() => setSource("remote")}>
              <Globe className="mr-2 h-4 w-4" /> Git URL
            </Button>
            <Button type="button" variant={source === "local" ? "secondary" : "ghost"} onClick={() => setSource("local")}>
              <FolderGit2 className="mr-2 h-4 w-4" /> Local repository
            </Button>
          </div>
          {source === "remote" ? (
            <div className="space-y-2">
              <Label htmlFor="project-git-url">Git URL</Label>
              <Input id="project-git-url" value={repoUrl} onChange={(event) => setRepoUrl(event.target.value)} placeholder="https://github.com/user/repo.git" autoFocus />
              <Label htmlFor="project-branch">Default branch</Label>
              <Input id="project-branch" value={branch} onChange={(event) => setBranch(event.target.value)} />
            </div>
          ) : (
            <div className="space-y-2">
              <Button type="button" variant="outline" onClick={chooseLocalFolder} className="w-full justify-start">
                <FolderOpen className="mr-2 h-4 w-4" />
                {localRepo ? "Choose a different folder" : "Choose folder…"}
              </Button>
              {localRepo && (
                <div className="space-y-1 rounded-md border p-3 text-sm">
                  <div className="flex items-center gap-2 font-medium"><Check className="h-4 w-4 text-green-500" />{localRepo.name}</div>
                  <p className="truncate text-xs text-muted-foreground">{localRepo.remote}</p>
                  <p className="text-xs text-muted-foreground">Default branch: {localRepo.default_branch}</p>
                </div>
              )}
              {!showManualPath ? (
                <button type="button" className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground" onClick={() => setShowManualPath(true)}>
                  <PencilLine className="h-3 w-3" /> Enter a path manually
                </button>
              ) : (
                <div className="space-y-1">
                  <Label htmlFor="project-local-path">Repository path</Label>
                  <Input id="project-local-path" value={localPath} onChange={(event) => { setLocalPath(event.target.value); setLocalRepo(null); }} placeholder="/Users/me/code/project" />
                </div>
              )}
              <p className="text-xs text-muted-foreground">This saves the project record in local HarnessBox storage. Set workspace defaults in Project settings, then click + beside the project to create a workspace immediately.</p>
            </div>
          )}
          {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="submit" disabled={busy || (source === "remote" ? !repoUrl.trim() : !localRepo && !localPath.trim())}>
              {busy ? "Creating…" : "Create project"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

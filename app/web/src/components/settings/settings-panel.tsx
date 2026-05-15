import { useCallback, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import useMeasure from "react-use-measure";
import {
  Box,
  CheckCircle,
  Eye,
  EyeOff,
  FolderGit2,
  KeyRound,
  Plus,
  Settings2,
  ShieldAlert,
  SquareTerminal,
  Trash2,
} from "lucide-react";
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
import { Switch } from "@/components/ui/switch";
import { useCredentials } from "@/hooks/use-credentials";
import { useDiscovery } from "@/hooks/use-discovery";
import { useGitHubProfile } from "@/hooks/use-github-profile";
import { useLocalStorage } from "@/hooks/use-local-storage";
import { detectWorkspace } from "@/lib/api";
import type { DetectedWorkspace } from "@/types";

// --- Types ---

interface StoredKey {
  name: string;
  value: string;
}

interface Defaults {
  provider: string;
  harness: string;
  skipPermissions: boolean;
}

interface ModelPreferences {
  defaultModel: string;
  thinkingEffort: string;
}

// --- Constants ---

const TABS = ["General", "Harnesses", "Providers", "Secrets", "Repos"] as const;
type TabId = (typeof TABS)[number];

const TAB_ICONS: Record<TabId, typeof SquareTerminal> = {
  General: Settings2,
  Harnesses: SquareTerminal,
  Providers: Box,
  Secrets: KeyRound,
  Repos: FolderGit2,
};

const MODEL_OPTIONS = [
  "Opus 4.7",
  "Opus 4.6",
  "Opus 4.6 1M",
  "Sonnet 4.6",
  "Sonnet 4.6 1M",
  "Haiku 4.5",
  "GPT-5.5",
  "GPT-5.4",
  "GPT-5.3-Codex-Spark",
  "GPT-5.3-Codex",
] as const;

const THINKING_OPTIONS = [
  "Low",
  "Medium",
  "High",
  "Extra High",
  "Max",
] as const;

const DEFAULT_KEYS: StoredKey[] = [
  { name: "ANTHROPIC_API_KEY", value: "" },
  { name: "E2B_API_KEY", value: "" },
  { name: "OPENAI_API_KEY", value: "" },
  { name: "GITHUB_TOKEN", value: "" },
];

const HARNESS_CONFIG: Record<string, { icon: string; text: string } | undefined> = {
  "claude-code": { icon: "/icons/claudecode-color.svg", text: "/icons/claudecode-text.svg" },
  "codex": { icon: "/icons/codex-color.svg", text: "/icons/codex-text.svg" },
  "opencode": { icon: "/icons/opencode-color.svg", text: "/icons/opencode-text.svg" },
};

const PROVIDER_CONFIG: Record<string, { icon: string; text: string }> = {
  e2b: { icon: "/icons/e2b.png", text: "E2B" },
  daytona: { icon: "/icons/daytona.png", text: "Daytona" },
  modal: { icon: "/icons/modal.png", text: "Modal" },
};


// --- Animation config ---

const springTransition = { type: "spring" as const, stiffness: 350, damping: 30, mass: 0.8 };

const contentVariants = {
  enter: (direction: number) => ({
    x: direction > 0 ? 80 : -80,
    opacity: 0,
  }),
  center: {
    x: 0,
    opacity: 1,
    transition: springTransition,
  },
  exit: (direction: number) => ({
    x: direction > 0 ? -80 : 80,
    opacity: 0,
    transition: { duration: 0.15 },
  }),
};

const itemFadeIn = {
  hidden: { opacity: 0, y: 8 },
  show: { opacity: 1, y: 0 },
};

const staggerContainer = {
  show: {
    transition: { staggerChildren: 0.05, delayChildren: 0.1 },
  },
};

// --- Component ---

export function SettingsPanel() {
  const { credentials } = useCredentials();
  const { harnesses, providers, loading: discoveryLoading } = useDiscovery();
  const { profile, loading: profileLoading } = useGitHubProfile();
  const [storedKeys, setStoredKeys] = useLocalStorage<StoredKey[]>("api-keys", DEFAULT_KEYS);
  const [defaults, setDefaults] = useLocalStorage<Defaults>("defaults", {
    provider: "e2b",
    harness: "claude-code",
    skipPermissions: true,
  });
  const [modelPrefs, setModelPrefs] = useLocalStorage<ModelPreferences>("model-preferences", {
    defaultModel: "Sonnet 4.6",
    thinkingEffort: "High",
  });
  const [visibleKeys, setVisibleKeys] = useState<Set<number>>(new Set());
  const [repoPath, setRepoPath] = useState("");
  const [detectedRepo, setDetectedRepo] = useLocalStorage<DetectedWorkspace | null>("repository", null);
  const [detecting, setDetecting] = useState(false);
  const [detectError, setDetectError] = useState<string | null>(null);

  const [activeTab, setActiveTab] = useState<TabId>("General");
  const [direction, setDirection] = useState(0);
  const [measureRef, bounds] = useMeasure();
  const containerRef = useRef<HTMLDivElement>(null);

  const switchTab = (tab: TabId) => {
    const oldIndex = TABS.indexOf(activeTab);
    const newIndex = TABS.indexOf(tab);
    setDirection(newIndex > oldIndex ? 1 : -1);
    setActiveTab(tab);
  };

  // --- Key management ---

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

  // --- Tab content renderers ---

  const renderHarnesses = () => (
    <motion.div className="grid gap-3" variants={staggerContainer} initial="hidden" animate="show">
      {discoveryLoading ? (
        <p className="text-xs text-muted-foreground animate-pulse">Loading agents...</p>
      ) : harnesses.length === 0 ? (
        <p className="text-xs text-muted-foreground">No agents detected. Is the server running?</p>
      ) : (
        harnesses
          .map((h) => {
            const cred = credentials.find(
              (c) => c.name === h.name.replace("-", "_") || c.name === `${h.name.replace("-", "_")}_auth_mode`,
            );
            const isAuthenticated = cred?.available ?? false;
            const harnessCfg = HARNESS_CONFIG[h.name];

            return (
              <motion.div
                key={h.name}
                variants={itemFadeIn}
                className="flex items-center justify-between rounded-lg border border-border p-4"
              >
                <div className="flex items-center gap-3">
                  {harnessCfg ? (
                    <>
                      <img src={harnessCfg.icon} alt="" className="h-8 w-8" />
                      {h.name === "codex" ? (
                        <img src={harnessCfg.text} alt={h.name} className="h-4" />
                      ) : (
                        <img src={harnessCfg.text} alt={h.name} className="h-6" />
                      )}
                    </>
                  ) : (
                    <span className="text-sm font-medium">{h.name}</span>
                  )}
                </div>
                <div className="flex items-center gap-3">
                  {isAuthenticated ? (
                    <div className="flex items-center gap-1.5 text-xs">
                      <CheckCircle className="h-3 w-3 text-green-300" />
                      <span className="font-medium">Authenticated</span>
                    </div>
                  ) : (
                    <>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-8 px-2"
                        onClick={() => {}}
                      >
                        Connect
                      </Button>
                    </>
                  )}
                </div>
              </motion.div>
            );
          })
      )}

      <motion.div variants={itemFadeIn} className="pt-3 flex items-center gap-2">
        <Switch
          checked={defaults.skipPermissions}
          onCheckedChange={(v) => setDefaults({ ...defaults, skipPermissions: v })}
        />
        <Label className="text-xs">Skip tool permission prompts</Label>
      </motion.div>
    </motion.div>
  );

  const renderProviders = () => (
    <motion.div className="grid gap-3" variants={staggerContainer} initial="hidden" animate="show">
      {discoveryLoading ? (
        <p className="text-xs text-muted-foreground animate-pulse">Loading providers...</p>
      ) : providers.length === 0 ? (
        <p className="text-xs text-muted-foreground">No providers detected.</p>
      ) : (
        providers.map((p) => {
          const cred = credentials.find(
            (c) => c.name === `${p.name}_cli` || c.name === `${p.name}_api_key`,
          );
          const isAuthenticated = cred?.available ?? false;
          const providerCfg = PROVIDER_CONFIG[p.name];

          return (
            <motion.div
              key={p.name}
              variants={itemFadeIn}
              className="flex items-center justify-between rounded-lg border border-border p-4"
            >
              <div className="flex items-center gap-3">
                {providerCfg ? (
                  <>
                    <img src={providerCfg.icon} alt={p.name} className="h-8 w-8" />
                    <span className="text-sm font-medium">{providerCfg.text}</span>
                  </>
                ) : (
                  <span className="text-sm font-medium">{p.name}</span>
                )}
              </div>
              <div className="flex items-center gap-3">
                {isAuthenticated ? (
                  <div className="flex items-center gap-1.5 text-xs text-green-500">
                    <CheckCircle className="h-3 w-3" />
                    <span className="font-medium">Configured</span>
                  </div>
                ) : (
                  <>
                    <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                      <ShieldAlert className="h-3 w-3 text-red-600" />
                      <span>Not configured</span>
                    </div>
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-6 text-[10px] px-2"
                      onClick={() => {}}
                    >
                      Connect
                    </Button>
                  </>
                )}
              </div>
            </motion.div>
          );
        })
      )}
    </motion.div>
  );

  const renderSecrets = () => (
    <motion.div className="space-y-5" variants={staggerContainer} initial="hidden" animate="show">
      

      {/* API key inputs */}
      <motion.div variants={itemFadeIn} className="space-y-3">
        <div className="flex items-center justify-between">
          <Label className="text-xs text-muted-foreground">API Keys & Tokens</Label>
          <Badge variant="secondary" className="text-[10px]">
            {configuredCount} configured
          </Badge>
        </div>
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
        <Button variant="outline" size="sm" onClick={addKey} className="text-xs">
          <Plus className="h-3 w-3 mr-1" />
          Add Key
        </Button>
      </motion.div>
    </motion.div>
  );

  const renderRepos = () => (
    <motion.div className="space-y-5" variants={staggerContainer} initial="hidden" animate="show">
      <motion.p variants={itemFadeIn} className="text-xs text-muted-foreground">
        Local git repos — auto-fills workspace config for new sessions
      </motion.p>

      <motion.div variants={itemFadeIn} className="space-y-3">
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
          <div className="rounded-lg border border-green-500/30 bg-green-500/5 p-4 space-y-2">
            <div className="flex items-center gap-2">
              <img src="/icons/github.png" alt="Github" className="h-4 w-4 shrink-0" />
              <span className="text-xs font-medium">{detectedRepo.name}</span>
            </div>
            <div className="space-y-1 text-xs text-muted-foreground font-mono pl-5">
              <div>Remote: {detectedRepo.remote}</div>
              <div>Branch: {detectedRepo.default_branch}</div>
            </div>
          </div>
        )}
      </motion.div>
    </motion.div>
  );

  const renderGeneral = () => (
    <motion.div
      className="space-y-8"
      initial="hidden"
      animate="show"
      variants={{ show: { transition: { staggerChildren: 0.08, delayChildren: 0.05 } } }}
    >
      {/* Account */}
      <motion.div
        variants={{ hidden: { opacity: 0, y: 12 }, show: { opacity: 1, y: 0, transition: springTransition } }}
        className="space-y-4"
      >
        <h3 className="text-sm font-medium">Account</h3>
        {profileLoading ? (
          <p className="text-xs text-muted-foreground animate-pulse">Loading profile...</p>
        ) : profile ? (
          <div className="flex items-center gap-4 rounded-lg border border-border p-4">
            <img
              src={profile.avatar_url}
              alt={profile.login}
              className="h-10 w-10 rounded-full"
            />
            <div>
              <p className="text-sm font-medium">{profile.name || profile.login}</p>
              {profile.email && (
                <p className="text-xs text-muted-foreground">{profile.email}</p>
              )}
              {profile.name && (
                <p className="text-xs text-muted-foreground">@{profile.login}</p>
              )}
            </div>
          </div>
        ) : (
          <div className="rounded-lg border border-border p-4">
            <p className="text-xs text-muted-foreground">
              GitHub CLI not connected. Install and authenticate with <code className="font-mono text-[11px] bg-muted px-1 py-0.5 rounded">gh auth login</code> to see your profile.
            </p>
          </div>
        )}
      </motion.div>

      {/* Models */}
      <motion.div
        variants={{ hidden: { opacity: 0, y: 12 }, show: { opacity: 1, y: 0, transition: springTransition } }}
        className="space-y-4"
      >
        <h3 className="text-sm font-medium">Models</h3>
        <motion.div
          className="grid grid-cols-2 gap-4"
          initial="hidden"
          animate="show"
          variants={{ show: { transition: { staggerChildren: 0.06, delayChildren: 0.12 } } }}
        >
          <motion.div
            variants={{ hidden: { opacity: 0, y: 8 }, show: { opacity: 1, y: 0, transition: springTransition } }}
            className="space-y-2 rounded-lg border border-border p-4"
          >
            <Label className="text-xs text-muted-foreground">Default Model</Label>
            <Select
              value={modelPrefs.defaultModel}
              onValueChange={(v) => v && setModelPrefs({ ...modelPrefs, defaultModel: v })}
            >
              <SelectTrigger className="w-full h-8 text-sm cursor-pointer">
                <SelectValue />
              </SelectTrigger>
              <SelectContent side="bottom" alignItemWithTrigger={false}>
                {MODEL_OPTIONS.map((m) => (
                  <SelectItem key={m} value={m}>{m}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </motion.div>
          <motion.div
            variants={{ hidden: { opacity: 0, y: 8 }, show: { opacity: 1, y: 0, transition: springTransition } }}
            className="space-y-2 rounded-lg border border-border p-4"
          >
            <Label className="text-xs text-muted-foreground">Thinking Effort</Label>
            <Select
              value={modelPrefs.thinkingEffort}
              onValueChange={(v) => v && setModelPrefs({ ...modelPrefs, thinkingEffort: v })}
            >
              <SelectTrigger className="w-full h-8 text-sm cursor-pointer">
                <SelectValue />
              </SelectTrigger>
              <SelectContent side="bottom" alignItemWithTrigger={false}>
                {THINKING_OPTIONS.map((t) => (
                  <SelectItem key={t} value={t}>{t}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </motion.div>
        </motion.div>
      </motion.div>
    </motion.div>
  );

  const tabContent: Record<TabId, () => React.ReactNode> = {
    General: renderGeneral,
    Harnesses: renderHarnesses,
    Providers: renderProviders,
    Secrets: renderSecrets,
    Repos: renderRepos,
  };

  return (
    <div className="flex flex-1 flex-col min-h-0" ref={containerRef}>
      <div className="sticky top-0 z-10 mb-10 bg-background items-center">
        {/* Tab bar */}
        <div className="max-w-4xl mx-auto px-6 pb-3 flex gap-6 mt-10 items-center">
          {TABS.map((tab) => {
            const Icon = TAB_ICONS[tab];
            const isActive = activeTab === tab;

            return (
              <motion.button
                key={tab}
                onClick={() => switchTab(tab)}
                whileTap={{ scaleY: 0.8 }}
                className={`relative flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium cursor-pointer transition-colors ${
                  isActive
                    ? "text-foreground"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {isActive && (
                  <motion.div
                    layoutId="settings-tab-bg"
                    className="absolute inset-0 rounded-md bg-muted"
                    transition={springTransition}
                  />
                )}
                <span className="relative z-10 flex items-center gap-1.5">
                  <Icon className="h-5 w-5" />
                  <motion.span
                    initial={false}
                    animate={{ opacity: 1 }}
                    transition={{ ...springTransition, delay: isActive ? 0.08 : 0 }}
                    className="text-sm"
                  >
                    {tab}
                  </motion.span>
                </span>
              </motion.button>
            );
          })}
        </div>
      </div>

      {/* Tab content with height animation */}
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-4xl mx-auto w-full px-6 py-6">
          <motion.div
            animate={{ height: bounds.height > 0 ? bounds.height : "auto" }}
            transition={springTransition}
            className="relative overflow-hidden"
          >
            <AnimatePresence mode="popLayout" custom={direction} initial={false}>
              <motion.div
                key={activeTab}
                ref={measureRef}
                custom={direction}
                variants={contentVariants}
                initial="enter"
                animate="center"
                exit="exit"
              >
                {tabContent[activeTab]()}
              </motion.div>
            </AnimatePresence>
          </motion.div>
        </div>
      </div>
    </div>
  );
}

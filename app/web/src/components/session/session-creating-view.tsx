import { motion } from "framer-motion";
import { DotmSquare12 } from "@/components/ui/dotm-square-12";
import type { SessionEntry } from "@/types";

interface SessionCreatingViewProps {
  session: SessionEntry;
}

export function SessionCreatingView({ session }: SessionCreatingViewProps) {
  return (
    <motion.div
      className="flex flex-1 flex-col items-center justify-center gap-6"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.3 }}
    >
      <DotmSquare12 size={48} dotSize={6} speed={1.2} animated />

      {session.workspaceName && (
        <p className="text-sm font-medium text-foreground">
          {session.workspaceName}
        </p>
      )}

      {session.error ? (
        <div className="max-w-sm text-center space-y-1">
          <p className="text-xs text-destructive">{session.error}</p>
          <p className="text-xs text-muted-foreground">
            Destroy this session from the sidebar and try again.
          </p>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground animate-pulse">
          Setting up workspace...
        </p>
      )}
    </motion.div>
  );
}

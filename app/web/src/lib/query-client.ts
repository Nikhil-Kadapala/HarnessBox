import { QueryClient } from "@tanstack/react-query";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60 * 1000,
      gcTime: 10 * 60 * 1000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

export const queryKeys = {
  discovery: {
    harnesses: ["harnesses"] as const,
    providers: ["providers"] as const,
    guards: ["guards"] as const,
  },
  credentials: ["credentials"] as const,
  githubProfile: ["github-profile"] as const,
} as const;

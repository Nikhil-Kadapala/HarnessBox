import type { UniversalEvent } from "@/types";

export function isAuthenticationFailure(event: UniversalEvent): boolean {
  const metadata = event.message.metadata;
  const details = [
    event.message.error_message,
    metadata?.error,
    metadata?.error_type,
    metadata?.message,
  ]
    .filter((value): value is string => typeof value === "string")
    .join(" ")
    .toLowerCase();

  return /authentication[_\s-]?failed|invalid[_\s-]?api[_\s-]?key|unauthorized|\b401\b/.test(
    details,
  );
}

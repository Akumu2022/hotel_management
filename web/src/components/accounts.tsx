/** Shared bits for people: star ratings (D28) and admin password resets (D28). */
import { useMutation } from "@tanstack/react-query";
import { KeyRound, Star } from "lucide-react";

import { api } from "../lib/api";
import { ErrorNote } from "./ui";

export function Stars({ rating, count }: { rating: number | null; count: number }) {
  if (!count) return <span className="text-xs text-muted">No ratings yet</span>;
  return (
    <span className="inline-flex items-center gap-1 text-sm font-semibold">
      <Star className="size-4 fill-warn text-warn" /> {rating?.toFixed(1)} <span className="font-normal text-muted">({count})</span>
    </span>
  );
}

/** Reset someone's password and show the temporary one once. */
export function ResetPassword({ url, name }: { url: string; name: string }) {
  const reset = useMutation({ mutationFn: () => api.post<{ temp_password: string }>(url) });
  if (reset.data)
    return (
      <span className="rounded-lg bg-ok-soft px-2 py-1 text-xs text-ok">
        Temporary password: <b className="money select-all tracking-wider">{reset.data.temp_password}</b> (tell {name.split(" ")[0]}; they choose a new one at login)
      </span>
    );
  return (
    <span className="inline-flex flex-col items-end">
      <button
        onClick={() => window.confirm(`Reset ${name}'s password? They'll be logged out everywhere.`) && reset.mutate()}
        disabled={reset.isPending}
        className="inline-flex items-center gap-1 rounded-lg border border-line px-2 py-1 text-xs font-semibold text-muted hover:bg-subtle hover:text-ink"
      >
        <KeyRound className="size-3.5" /> Reset password
      </button>
      <ErrorNote error={reset.error} />
    </span>
  );
}


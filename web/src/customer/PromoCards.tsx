import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { Check } from "lucide-react";
import { useState } from "react";

import { api } from "../lib/api";
import { toast } from "./bits";
import type { PublicPromo } from "./types";

const KEY = "hm.promo"; // the code checkout applies for them

function saved(): string {
  try {
    return localStorage.getItem(KEY) ?? "";
  } catch {
    return "";
  }
}

/** Promo codes the hotel shows to everyone: tap Claim and checkout applies it. */
export function PromoCards({ slug }: { slug: string }) {
  const promos = useQuery({ queryKey: ["promos", slug], queryFn: () => api.get<PublicPromo[]>(`/hotels/${slug}/promos`) });
  const [claimed, setClaimed] = useState(saved);
  if (!promos.data?.length) return null;

  function claim(code: string) {
    try {
      localStorage.setItem(KEY, code);
    } catch {
      /* private mode: they can still type it at checkout */
    }
    setClaimed(code);
    toast(`Code ${code} saved. We'll apply it at checkout.`);
  }

  return (
    <section className="mt-5">
      <h2 className="mb-3 flex items-center gap-2 text-lg font-extrabold">🎟 Promo codes</h2>
      <div className="flex flex-col gap-3 sm:grid sm:grid-cols-2">
        {promos.data.map((p) => {
          const mine = claimed === p.code;
          return (
            <div key={p.code} className="flex items-center gap-3 rounded-2xl border-2 border-dashed border-brand/50 bg-brand/5 p-4">
              <div className="min-w-0 flex-1">
                <p className="text-lg leading-tight font-extrabold">{p.worth}</p>
                <p className="mt-1 text-sm text-muted">
                  Code <span className="font-extrabold tracking-wider text-ink">{p.code}</span>
                  {p.ends_at ? ` · until ${new Date(p.ends_at).toLocaleDateString("en-KE", { day: "numeric", month: "short" })}` : ""}
                </p>
              </div>
              <button
                type="button"
                onClick={() => claim(p.code)}
                className={clsx(
                  "flex h-10 shrink-0 items-center gap-1 rounded-xl px-4 text-sm font-bold",
                  mine ? "bg-ok-soft text-ok" : "bg-brand text-white",
                )}
              >
                {mine ? (
                  <>
                    <Check className="size-4" /> Claimed
                  </>
                ) : (
                  "Claim"
                )}
              </button>
            </div>
          );
        })}
      </div>
    </section>
  );
}

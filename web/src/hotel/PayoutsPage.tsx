/** Money Chakula pays the hotel: one payment a day, listed order by order. */
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { CheckCircle2, ChevronDown, Clock, FlaskConical, HelpCircle, XCircle } from "lucide-react";
import { useState } from "react";

import { Skeleton } from "../components/ui";
import { api } from "../lib/api";
import { money } from "../lib/format";
import { dateLabel } from "./BillingPage";

export type HotelPayouts =
  | { enabled: false }
  | {
      enabled: true;
      practice: boolean;
      coming: number;
      ready: number;
      settlements: {
        id: string;
        date: string;
        amount: number;
        status: "queued" | "submitted" | "succeeded" | "failed" | "unknown" | "manual_review";
        to: string;
        channel: "till" | "phone";
        code: string | null;
        orders: { code: string | null; amount: number }[];
      }[];
    };

export function useHotelPayouts() {
  return useQuery({ queryKey: ["hotel", "payouts"], queryFn: () => api.get<HotelPayouts>("/hotel/settlements"), refetchInterval: 60_000 });
}

const STATUS: Record<string, { label: string; tone: string; icon: typeof Clock }> = {
  queued: { label: "On its way", tone: "text-warn", icon: Clock },
  submitted: { label: "On its way", tone: "text-warn", icon: Clock },
  succeeded: { label: "Paid", tone: "text-ok", icon: CheckCircle2 },
  failed: { label: "Failed, will be tried again", tone: "text-bad", icon: XCircle },
  unknown: { label: "Checking with M-Pesa", tone: "text-warn", icon: HelpCircle },
  manual_review: { label: "Being checked by Chakula", tone: "text-warn", icon: HelpCircle },
};

export function PayoutsPage() {
  const q = useHotelPayouts();
  const [open, setOpen] = useState<string | null>(null);
  if (!q.data) return <Skeleton className="h-64 rounded-3xl" />;
  const d = q.data;
  if (!d.enabled) return <p className="rounded-2xl border border-dashed border-line py-10 text-center text-muted">Daily payouts are not switched on yet.</p>;

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-5">
      {d.practice ? (
        <p className="flex items-start gap-3 rounded-2xl bg-warn-soft px-4 py-3 text-sm text-warn">
          <FlaskConical className="mt-0.5 size-5 shrink-0" />
          <span><strong>Practice mode.</strong> This shows how your daily payouts will look. No real money is sent yet.</span>
        </p>
      ) : null}

      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-3xl bg-brand p-5 text-white shadow-lg shadow-brand/20">
          <p className="text-sm font-semibold text-white/85">Paid to you tomorrow morning</p>
          <p className="money mt-1 whitespace-nowrap text-2xl font-extrabold sm:text-3xl">{money(d.ready)}</p>
          <p className="mt-1 text-sm text-white/85">Orders finished before today</p>
        </div>
        <div className="rounded-3xl bg-surface p-5 shadow-sm">
          <p className="text-sm font-semibold text-muted">Coming after the order is done</p>
          <p className="money mt-1 whitespace-nowrap text-2xl font-extrabold sm:text-3xl">{money(d.coming)}</p>
          <p className="mt-1 text-sm text-muted">Paid for, not yet delivered or collected</p>
        </div>
      </div>

      <section>
        <h2 className="mb-3 text-lg font-bold">Daily payouts</h2>
        {d.settlements.length === 0 ? (
          <p className="rounded-2xl border border-dashed border-line py-10 text-center text-sm text-muted">Nothing yet. Your first payout appears the morning after your first paid order is done.</p>
        ) : (
          <ul className="flex flex-col gap-3">
            {d.settlements.map((s) => {
              const st = STATUS[s.status] ?? STATUS.queued;
              const isOpen = open === s.id;
              return (
                <li key={s.id} className="rounded-3xl bg-surface shadow-sm">
                  <button onClick={() => setOpen(isOpen ? null : s.id)} className="flex w-full items-center gap-3 p-5 text-left">
                    <span className="min-w-0 flex-1">
                      <span className="block font-bold">{dateLabel(s.date)}</span>
                      <span className={clsx("flex items-center gap-1.5 text-sm font-semibold", st.tone)}><st.icon className="size-4" /> {st.label}</span>
                      <span className="block text-sm text-muted">
                        {s.channel === "till" ? `To your Till ${s.to}` : `To your M-Pesa 0•••• ${s.to}`}
                        {s.code ? ` · ${s.code}` : ""}
                      </span>
                    </span>
                    <span className="money text-xl font-extrabold">{money(s.amount)}</span>
                    <ChevronDown className={clsx("size-5 text-muted transition-transform", isOpen && "rotate-180")} />
                  </button>
                  {isOpen ? (
                    <ul className="divide-y divide-line border-t border-line px-5 text-sm">
                      {s.orders.map((o, i) => (
                        <li key={i} className="flex justify-between py-2.5">
                          <span>Order <strong>#{o.code ?? "?"}</strong></span>
                          <span className="money font-semibold">{money(o.amount)}</span>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}

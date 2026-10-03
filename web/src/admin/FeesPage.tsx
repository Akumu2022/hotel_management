/** Super admin: commission tiers and customer bonuses (DECISIONS D19). */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Gift, Percent, Plus, Stamp, Trash2, Truck, Wallet } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import { ErrorNote, Skeleton } from "../components/ui";
import { api } from "../lib/api";
import { money } from "../lib/format";

type Tier = { up_to: number; fee: number };
type FeeSettings = {
  commission_mode: "tiers" | "percent";
  commission_tiers: Tier[];
  commission_step: number;
  commission_step_fee: number;
  commission_percent: number;
  service_fee: number;
  stamp_every: number;
  stamp_reward: number;
  free_delivery_min_food: number;
  bonus_daily_budget: number;
};

/** Same rule as the server (settings.tier_fee). */
function tierFee(food: number, s: FeeSettings) {
  if (food <= 0) return 0;
  if (s.commission_mode === "percent") return Math.floor((s.commission_percent * 100 * food) / 10_000);
  for (const t of s.commission_tiers) if (food <= t.up_to) return Math.min(t.fee, food);
  const last = s.commission_tiers[s.commission_tiers.length - 1];
  return Math.min(last.fee + Math.ceil((food - last.up_to) / s.commission_step) * s.commission_step_fee, food);
}

function Num({ value, onChange, label, prefix = "KES", width = "w-28" }: { value: number; onChange: (n: number) => void; label: string; prefix?: string; width?: string }) {
  return (
    <label className={clsx("flex h-11 items-center gap-1.5 rounded-xl border border-line bg-surface px-3 focus-within:border-brand", width)}>
      {prefix ? <span className="text-xs font-semibold text-muted">{prefix}</span> : null}
      <input aria-label={label} inputMode="numeric" value={value || value === 0 ? String(value) : ""} onChange={(e) => onChange(Number(e.target.value.replace(/\D/g, "")) || 0)} className="money w-full min-w-0 bg-transparent font-bold outline-none" />
    </label>
  );
}

/** Keeps the typed text (so "12." can become "12.5") and reports the number. */
function PercentInput({ value, onChange }: { value: number; onChange: (n: number) => void }) {
  const [text, setText] = useState(String(value));
  return (
    <label className="flex h-11 w-28 items-center gap-1.5 rounded-xl border border-line bg-surface px-3 focus-within:border-brand">
      <input
        aria-label="Commission percent"
        inputMode="decimal"
        value={text}
        onChange={(e) => {
          const t = e.target.value.replace(/[^0-9.]/g, "");
          setText(t);
          onChange(Number(t) || 0);
        }}
        className="money w-full min-w-0 bg-transparent font-bold outline-none"
      />
      <span className="text-xs font-semibold text-muted">%</span>
    </label>
  );
}

function Card({ icon, title, sub, children }: { icon: ReactNode; title: string; sub: string; children: ReactNode }) {
  return (
    <section className="rounded-3xl border border-line bg-surface p-5">
      <h2 className="flex items-center gap-2 text-[1rem] font-bold"><span className="text-brand">{icon}</span> {title}</h2>
      <p className="mb-4 text-sm text-muted">{sub}</p>
      {children}
    </section>
  );
}

export function FeesPage() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["admin", "settings"], queryFn: () => api.get<FeeSettings>("/admin/settings") });
  const [s, setS] = useState<FeeSettings | null>(null);
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    if (q.data && !s) setS(q.data);
  }, [q.data, s]);

  const save = useMutation({
    mutationFn: (v: FeeSettings) =>
      api.put<FeeSettings>("/admin/settings", {
        commission_mode: v.commission_mode,
        commission_tiers: v.commission_tiers,
        commission_step: v.commission_step,
        commission_step_fee: v.commission_step_fee,
        commission_percent: v.commission_percent,
        service_fee: v.service_fee,
        stamp_every: v.stamp_every,
        stamp_reward: v.stamp_reward,
        free_delivery_min_food: v.free_delivery_min_food,
        bonus_daily_budget: v.bonus_daily_budget,
      }),
    onSuccess: (v) => {
      qc.setQueryData(["admin", "settings"], v);
      setS(v);
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    },
  });

  if (!s) return <div className="p-6"><Skeleton className="h-96 rounded-3xl" /></div>;
  const set = (patch: Partial<FeeSettings>) => setS({ ...s, ...patch });
  const setTier = (i: number, patch: Partial<Tier>) => set({ commission_tiers: s.commission_tiers.map((t, j) => (j === i ? { ...t, ...patch } : t)) });
  const ascending = s.commission_tiers.every((t, i, a) => i === 0 || t.up_to > a[i - 1].up_to);
  const examples = [300, 700, 1500, 4500, 6500];

  return (
    <div className="flex flex-col gap-5 p-4 sm:p-6">
      <div>
        <h1 className="text-2xl font-bold">Fees & bonuses</h1>
        <p className="text-sm text-muted">What the platform charges hotels, and the rewards that bring customers back. Changes apply to new orders only.</p>
      </div>

      <div className="grid gap-5 xl:grid-cols-2">
        <Card icon={<Percent className="size-5" />} title="Commission" sub="Charged to the hotel on the food total only. Rider fees and the service fee are never included.">
          <div className="mb-4 grid grid-cols-2 gap-1 rounded-xl bg-subtle p-1 text-sm font-semibold">
            {(["tiers", "percent"] as const).map((m) => (
              <button key={m} onClick={() => set({ commission_mode: m })} className={clsx("h-9 rounded-lg", s.commission_mode === m ? "bg-surface shadow-sm" : "text-muted")}>
                {m === "tiers" ? "Flat fee by order size" : "Percentage"}
              </button>
            ))}
          </div>
          {s.commission_mode === "tiers" ? (
            <>
              <ul className="flex flex-col gap-2">
                {s.commission_tiers.map((t, i) => (
                  <li key={i} className="flex flex-wrap items-center gap-2 text-sm">
                    <span className="w-24 text-muted">{i === 0 ? "Food up to" : `${money(s.commission_tiers[i - 1].up_to + 1)} –`}</span>
                    <Num label={`Tier ${i + 1} up to`} value={t.up_to} onChange={(n) => setTier(i, { up_to: n })} />
                    <span className="text-muted">pays</span>
                    <Num label={`Tier ${i + 1} fee`} value={t.fee} onChange={(n) => setTier(i, { fee: n })} width="w-24" />
                    <button aria-label="Remove tier" disabled={s.commission_tiers.length === 1} onClick={() => set({ commission_tiers: s.commission_tiers.filter((_, j) => j !== i) })} className="flex size-9 items-center justify-center rounded-lg text-muted hover:bg-bad-soft hover:text-bad disabled:opacity-30">
                      <Trash2 className="size-4" />
                    </button>
                  </li>
                ))}
              </ul>
              <button
                onClick={() => {
                  const last = s.commission_tiers[s.commission_tiers.length - 1];
                  set({ commission_tiers: [...s.commission_tiers, { up_to: last.up_to + s.commission_step, fee: last.fee + s.commission_step_fee }] });
                }}
                className="mt-2 flex h-9 items-center gap-1.5 rounded-lg px-2 text-sm font-semibold text-brand hover:bg-brand-soft"
              >
                <Plus className="size-4" /> Add a tier
              </button>
              {!ascending ? <p className="mt-2 text-sm font-medium text-bad">Each tier must end higher than the one before.</p> : null}
              <p className="mt-3 flex flex-wrap items-center gap-2 border-t border-line pt-3 text-sm">
                Above {money(s.commission_tiers[s.commission_tiers.length - 1].up_to)}: add
                <Num label="Extra fee per step" value={s.commission_step_fee} onChange={(n) => set({ commission_step_fee: n })} width="w-24" />
                for every
                <Num label="Step size" value={s.commission_step} onChange={(n) => set({ commission_step: Math.max(n, 1) })} />
              </p>
            </>
          ) : (
            <p className="flex flex-wrap items-center gap-2 text-sm">
              Commission of
              <PercentInput value={s.commission_percent} onChange={(n) => set({ commission_percent: n })} />
              of the food total.
            </p>
          )}
          <p className="mt-3 text-xs text-muted">A hotel with its own percentage deal (set on the hotel) always uses that instead.</p>
          <div className="mt-4 rounded-2xl bg-subtle p-3">
            <p className="mb-2 text-xs font-semibold tracking-wide text-muted uppercase">Examples</p>
            <div className="grid grid-cols-5 gap-2 text-center text-sm">
              {examples.map((f) => (
                <div key={f}>
                  <p className="money text-muted">{money(f)}</p>
                  <p className="money font-bold">{money(tierFee(f, s))}</p>
                </div>
              ))}
            </div>
          </div>
          <p className="mt-4 flex flex-wrap items-center gap-2 text-sm">
            Service fee paid by the customer:
            <Num label="Service fee" value={s.service_fee} onChange={(n) => set({ service_fee: n })} width="w-24" />
          </p>
        </Card>

        <div className="flex flex-col gap-5">
          <Card icon={<Stamp className="size-5" />} title="Stamp card" sub="Rewards loyal customers. Only real completed orders count, so new phone numbers can't farm it.">
            <p className="flex flex-wrap items-center gap-2 text-sm">
              Every
              <Num label="Orders per reward" value={s.stamp_every} onChange={(n) => set({ stamp_every: Math.min(n, 100) })} prefix="" width="w-20" />
              completed orders, the next one gets
              <Num label="Stamp reward" value={s.stamp_reward} onChange={(n) => set({ stamp_reward: n })} width="w-28" />
              off.
            </p>
            <p className="mt-2 text-xs text-muted">Set either number to 0 to turn the stamp card off.</p>
          </Card>
          <Card icon={<Truck className="size-5" />} title="Free delivery" sub="Encourages bigger orders. Applies when the customer pays everything by M-Pesa (the rider is paid as usual).">
            <p className="flex flex-wrap items-center gap-2 text-sm">
              Free delivery when food reaches
              <Num label="Free delivery minimum" value={s.free_delivery_min_food} onChange={(n) => set({ free_delivery_min_food: n })} width="w-32" />
            </p>
            <p className="mt-2 text-xs text-muted">0 turns free delivery off.</p>
          </Card>
          <Card icon={<Wallet className="size-5" />} title="Daily bonus budget" sub="The most the platform spends on bonuses per day, all hotels together. Once it's used up, bonuses pause until midnight.">
            <Num label="Daily bonus budget" value={s.bonus_daily_budget} onChange={(n) => set({ bonus_daily_budget: n })} width="w-36" />
          </Card>
          <p className="flex items-start gap-2 rounded-2xl bg-brand-soft p-4 text-sm">
            <Gift className="mt-0.5 size-4 shrink-0 text-brand" />
            <span>Bonuses are paid by the platform: the customer pays less and the hotel is credited the difference on its statement, so hotels never lose. One bonus per order, whichever is bigger. Hotels run their own happy hours under Discounts.</span>
          </p>
        </div>
      </div>

      <div className="sticky bottom-0 z-20 -mx-4 -mb-4 border-t border-line bg-surface/95 px-4 py-3 backdrop-blur sm:-mx-6 sm:-mb-6 sm:px-6">
        <div className="flex items-center justify-end gap-3">
          <ErrorNote error={save.error} />
          {saved ? <span className="text-sm font-semibold text-ok">Saved</span> : null}
          <button onClick={() => save.mutate(s)} disabled={save.isPending || !ascending} className="h-11 rounded-xl bg-brand px-6 font-semibold text-white shadow-md shadow-brand/25 disabled:opacity-60">
            {save.isPending ? "Saving…" : "Save changes"}
          </button>
        </div>
      </div>
    </div>
  );
}

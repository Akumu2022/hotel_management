/** Rider wallet: one big number, three plain steps, and a list of what was added. */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ArrowDownLeft, Banknote, CheckCircle2, Clock, FlaskConical, KeyRound, Smartphone, Wallet, X } from "lucide-react";

import { Button, ErrorNote, Skeleton } from "../components/ui";
import { ApiError, api, request } from "../lib/api";
import { money } from "../lib/format";

export type WalletData =
  | { enabled: false }
  | {
      enabled: true;
      practice: boolean;
      available: number;
      pending: number;
      paid: number;
      min_payout: number;
      payout_time: string;
      mpesa_last4: string;
      can_withdraw: boolean;
      extra_charge: number;
      activity: { id: string; amount: number; code: string | null; hotel: string | null; at: string }[];
    };

export function useWallet() {
  return useQuery({ queryKey: ["rider", "wallet"], queryFn: () => api.get<WalletData>("/rider/wallet"), refetchInterval: 30_000 });
}

const dayFmt = new Intl.DateTimeFormat("en-KE", { weekday: "long", day: "numeric", month: "short", timeZone: "Africa/Nairobi" });
const timeFmt = new Intl.DateTimeFormat("en-KE", { hour: "numeric", minute: "2-digit", hour12: true, timeZone: "Africa/Nairobi" });
const keyFmt = new Intl.DateTimeFormat("en-CA", { timeZone: "Africa/Nairobi" });

function dayLabel(iso: string): string {
  const d = new Date(iso);
  const today = keyFmt.format(new Date());
  const yesterday = keyFmt.format(new Date(Date.now() - 86_400_000));
  const k = keyFmt.format(d);
  return k === today ? "Today" : k === yesterday ? "Yesterday" : dayFmt.format(d);
}

type Withdrawn = { status: string; amount: number; charge: number };

/** Bottom sheet: confirm with your password; a second withdrawal in a day shows its charge first. */
function WithdrawSheet({ w, onClose }: { w: Extract<WalletData, { enabled: true }>; onClose: () => void }) {
  const qc = useQueryClient();
  const [key] = useState(() => crypto.randomUUID());
  const [password, setPassword] = useState("");
  const [charge, setCharge] = useState<{ charge: number; youGet: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState<Withdrawn | null>(null);

  const send = async (acceptCharge: boolean) => {
    setBusy(true);
    setError(null);
    try {
      const r = await request<Withdrawn>("POST", "/rider/wallet/withdraw", { password, accept_charge: acceptCharge }, { headers: { "Idempotency-Key": key } });
      setDone(r);
      void qc.invalidateQueries({ queryKey: ["rider", "wallet"] });
    } catch (e) {
      if (e instanceof ApiError && e.code === "charge_needed") {
        const x = (e.extra ?? {}) as { charge?: number; you_get?: number };
        setCharge({ charge: x.charge ?? w.extra_charge, youGet: x.you_get ?? 0 });
      } else {
        setError(e);
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 sm:items-center" role="dialog" aria-modal="true" onClick={onClose}>
      <div className="w-full max-w-md rounded-t-3xl bg-surface p-6 shadow-xl sm:rounded-3xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-start justify-between gap-3">
          <h2 className="text-xl font-extrabold">{done ? "On its way" : "Withdraw now"}</h2>
          <button onClick={onClose} aria-label="Close" className="flex size-9 items-center justify-center rounded-xl text-muted hover:bg-subtle"><X className="size-5" /></button>
        </div>

        {done ? (
          <>
            <p className="flex size-14 items-center justify-center rounded-2xl bg-ok-soft text-ok"><CheckCircle2 className="size-8" /></p>
            <p className="money mt-3 text-3xl font-extrabold">{money(done.amount)}</p>
            <p className="mt-1 text-muted">is being sent to your M-Pesa 0•••• {w.mpesa_last4}. You'll get the M-Pesa message in a moment.</p>
            <Button size="lg" className="mt-5 w-full" onClick={onClose}>Done</Button>
          </>
        ) : charge ? (
          <>
            <p className="rounded-2xl bg-warn-soft p-4 text-warn">
              You already took money out today, so this one costs <strong>{money(charge.charge)}</strong>. Waiting until tonight's payout is free.
            </p>
            <dl className="mt-4 grid grid-cols-[1fr_auto] gap-y-1 text-[0.9375rem]">
              <dt className="text-muted">You have</dt><dd className="money text-right font-bold">{money(w.available)}</dd>
              <dt className="text-muted">Charge</dt><dd className="money text-right font-bold">− {money(charge.charge)}</dd>
              <dt className="font-bold">You get</dt><dd className="money text-right text-lg font-extrabold text-ok">{money(charge.youGet)}</dd>
            </dl>
            <ErrorNote error={error} />
            <div className="mt-5 grid grid-cols-2 gap-3">
              <Button variant="secondary" size="lg" onClick={onClose}>Wait for tonight</Button>
              <Button size="lg" busy={busy} onClick={() => void send(true)}>Pay and withdraw</Button>
            </div>
          </>
        ) : (
          <>
            <p className="text-muted">You'll receive</p>
            <p className="money text-3xl font-extrabold">{money(w.available)}</p>
            <p className="mb-4 text-sm text-muted">to your M-Pesa 0•••• {w.mpesa_last4}. The first one each day is free.</p>
            <label className="block text-sm font-semibold" htmlFor="wd-password">Type your password to confirm</label>
            <input
              id="wd-password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1.5 h-12 w-full rounded-xl border border-line bg-page px-4 text-[1rem] outline-none focus:border-brand"
            />
            <ErrorNote error={error} />
            <Button size="lg" className="mt-5 w-full" busy={busy} disabled={!password} onClick={() => void send(false)}>
              Withdraw {money(w.available)}
            </Button>
          </>
        )}
      </div>
    </div>
  );
}

const STEPS = [
  { icon: KeyRound, title: "Deliver", text: "Enter the customer's 4-digit code." },
  { icon: Wallet, title: "Money lands here", text: "Your fee shows up at once." },
  { icon: Smartphone, title: "Paid to M-Pesa", text: "Sent to your phone every night." },
];

export function WalletPage({ w }: { w: Extract<WalletData, { enabled: true }> }) {
  const groups: { label: string; rows: typeof w.activity }[] = [];
  for (const a of w.activity) {
    const label = dayLabel(a.at);
    const last = groups[groups.length - 1];
    if (last && last.label === label) last.rows.push(a);
    else groups.push({ label, rows: [a] });
  }
  const belowMin = w.available < w.min_payout;
  const [open, setOpen] = useState(false);

  return (
    <div className="flex flex-col gap-5">
      {w.practice ? (
        <p className="flex items-start gap-3 rounded-2xl bg-warn-soft px-4 py-3 text-sm text-warn">
          <FlaskConical className="mt-0.5 size-5 shrink-0" />
          <span><strong>Practice mode.</strong> You can see how your wallet will work. No real money is paid out yet.</span>
        </p>
      ) : null}

      {open ? <WithdrawSheet w={w} onClose={() => setOpen(false)} /> : null}

      {/* The one number */}
      <section className="rounded-3xl bg-brand p-6 text-white shadow-lg shadow-brand/25">
        <p className="flex items-center gap-2 text-sm font-semibold text-white/85"><Wallet className="size-4" /> Your money</p>
        <p className="money mt-1 text-4xl font-extrabold tracking-tight">{money(w.available)}</p>
        <p className="mt-1 text-sm text-white/85">
          {w.available > 0 ? `Goes to your M-Pesa 0•••• ${w.mpesa_last4} tonight at ${w.payout_time}.` : "Finish a delivery and your fee appears here."}
        </p>
        <button
          disabled={!w.can_withdraw || belowMin}
          onClick={() => setOpen(true)}
          className="mt-5 h-12 w-full rounded-2xl bg-white font-bold text-brand disabled:cursor-not-allowed disabled:opacity-60"
        >
          {w.can_withdraw ? (belowMin ? `Need ${money(w.min_payout)} to withdraw` : "Withdraw now") : "Withdraw now · coming soon"}
        </button>
      </section>

      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-2xl bg-surface p-4 shadow-sm">
          <span className="flex size-9 items-center justify-center rounded-xl bg-ok-soft text-ok"><CheckCircle2 className="size-5" /></span>
          <p className="money mt-2 text-xl font-extrabold">{money(w.paid)}</p>
          <p className="text-sm text-muted">Already sent to M-Pesa</p>
        </div>
        <div className="rounded-2xl bg-surface p-4 shadow-sm">
          <span className="flex size-9 items-center justify-center rounded-xl bg-brand-soft text-brand"><Clock className="size-5" /></span>
          <p className="money mt-2 text-xl font-extrabold">{w.payout_time}</p>
          <p className="text-sm text-muted">Daily payout. Minimum {money(w.min_payout)}.</p>
        </div>
      </div>

      {/* How it works */}
      <section className="rounded-3xl bg-surface p-5 shadow-sm">
        <h2 className="mb-3 text-lg font-bold">How you get paid</h2>
        <ol className="flex flex-col gap-3">
          {STEPS.map((s, i) => (
            <li key={s.title} className="flex items-center gap-3">
              <span className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-brand-soft text-brand"><s.icon className="size-5" /></span>
              <span>
                <span className="block font-bold">{i + 1}. {s.title}</span>
                <span className="block text-sm text-muted">{s.text}</span>
              </span>
            </li>
          ))}
        </ol>
      </section>

      {/* Activity */}
      <section>
        <h2 className="mb-3 text-lg font-bold">Money in</h2>
        {groups.length === 0 ? (
          <p className="rounded-2xl border border-dashed border-line py-8 text-center text-sm text-muted">
            <Banknote className="mx-auto mb-2 size-6" />
            Nothing yet. Your first delivery will show up here.
          </p>
        ) : (
          groups.map((g) => (
            <div key={g.label} className="mb-4">
              <p className="mb-2 px-1 text-sm font-semibold text-muted">{g.label}</p>
              <ul className="divide-y divide-line rounded-3xl bg-surface px-5 shadow-sm">
                {g.rows.map((a) => (
                  <li key={a.id} className="flex items-center gap-3 py-3.5">
                    <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-ok-soft text-ok"><ArrowDownLeft className="size-5" /></span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-semibold">{a.hotel ?? "Delivery"}</span>
                      <span className="block text-sm text-muted">{a.code ? `#${a.code} · ` : ""}{timeFmt.format(new Date(a.at))}</span>
                    </span>
                    <span className="money font-extrabold text-ok">+{money(a.amount)}</span>
                  </li>
                ))}
              </ul>
            </div>
          ))
        )}
      </section>
    </div>
  );
}

export function WalletLoading() {
  return <Skeleton className="h-64 rounded-3xl" />;
}

/** Rider jobs (DECISIONS D21): go online, take a job, follow the steps, prove delivery with the
 * customer's 4-digit code. Big buttons for one-handed use on a bike. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { AlertTriangle, Banknote, Bike, CheckCircle2, MapPin, Navigation, Phone, Power, Store } from "lucide-react";
import { useState } from "react";

import { useAlarm } from "../lib/alarm";

import { ErrorNote, Skeleton } from "../components/ui";
import { api } from "../lib/api";
import { money } from "../lib/format";
import { useLive } from "../lib/live";
import type { RiderMe } from "./RiderHome";

type Job = {
  id: string;
  code: string;
  status: string;
  hotel_name: string;
  hotel_phone: string;
  hotel_lat: number | null;
  hotel_lng: number | null;
  distance_km: number | null;
  rider_fee: number;
  collect_cash_fee: boolean;
  fee_with_food: boolean;
  items: string[];
  prep_minutes: number | null;
  accepted_at: string | null;
  ready_at: string | null;
  closed_at: string | null;
  mine: boolean;
  customer_name: string | null;
  customer_phone: string | null;
  lat: number | null;
  lng: number | null;
  landmark: string | null;
  seen: boolean;
  fee_rider_confirmed: boolean;
  fee_not_paid: boolean;
  code_attempts_left: number | null;
};

const FAIL_REASONS: [string, string][] = [
  ["customer_unreachable", "Customer not answering at the pin"],
  ["customer_refused", "Customer refused the order"],
  ["wrong_location", "Wrong or unreachable location"],
  ["accident", "Accident or food damaged"],
  ["other", "Something else"],
];

const directions = (lat: number | null, lng: number | null) => (lat != null && lng != null ? `https://www.google.com/maps/dir/?api=1&destination=${lat},${lng}&travelmode=driving` : null);
const tel = (phone: string | null) => (phone ? `tel:+${phone}` : undefined);

function readyIn(j: Job) {
  if (j.status === "ready") return "Food is ready";
  if (!j.accepted_at || !j.prep_minutes) return "Being prepared";
  const left = Math.round((new Date(j.accepted_at).getTime() + j.prep_minutes * 60_000 - Date.now()) / 60_000);
  return left > 0 ? `Ready in about ${left} min` : "Should be ready now";
}

function BigButton({ children, onClick, tone = "brand", disabled }: { children: React.ReactNode; onClick: () => void; tone?: "brand" | "ok" | "ghost"; disabled?: boolean }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={clsx(
        "flex h-14 w-full items-center justify-center gap-2 rounded-2xl text-[1rem] font-bold disabled:opacity-50",
        tone === "brand" && "bg-brand text-white shadow-md shadow-brand/25",
        tone === "ok" && "bg-ok text-white shadow-md shadow-ok/25",
        tone === "ghost" && "border-2 border-line text-ink",
      )}
    >
      {children}
    </button>
  );
}

function LinkButton({ href, icon, label }: { href?: string | null; icon: React.ReactNode; label: string }) {
  if (!href) return null;
  return (
    <a href={href} target={href.startsWith("http") ? "_blank" : undefined} rel="noreferrer" className="flex h-12 flex-1 items-center justify-center gap-2 rounded-xl border border-line bg-surface text-sm font-semibold hover:bg-subtle">
      {icon} {label}
    </a>
  );
}

function MyJob({ j, act }: { j: Job; act: (path: string, body?: unknown) => Promise<unknown> }) {
  const [code, setCode] = useState("");
  const [ask, setAsk] = useState<"pickup_fee" | "cash_fee" | "fail" | null>(null);
  const [error, setError] = useState<unknown>(null);
  const run = async (path: string, body?: unknown) => {
    setError(null);
    try {
      await act(path, body);
      setAsk(null);
    } catch (e) {
      setError(e);
    }
  };
  const goingToHotel = ["accepted", "preparing", "ready"].includes(j.status);

  return (
    <article className="overflow-hidden rounded-3xl border-2 border-brand bg-surface shadow-lg shadow-brand/10">
      <header className="flex items-center justify-between bg-brand px-5 py-3 text-white">
        <span className="text-lg font-extrabold">#{j.code}</span>
        <span className="rounded-full bg-white/20 px-3 py-1 text-sm font-semibold">
          {goingToHotel ? "Go to the hotel" : j.status === "picked_up" ? "Food collected" : "On the way"}
        </span>
      </header>
      <div className="flex flex-col gap-4 p-5">
        {/* Where to now */}
        {goingToHotel ? (
          <div>
            <p className="flex items-center gap-2 text-sm font-semibold text-muted"><Store className="size-4" /> Pick up from</p>
            <p className="text-xl font-bold">{j.hotel_name}</p>
            <p className={clsx("text-sm font-semibold", j.status === "ready" ? "text-ok" : "text-warn")}>{readyIn(j)}</p>
            <div className="mt-3 flex gap-2">
              <LinkButton href={directions(j.hotel_lat, j.hotel_lng)} icon={<Navigation className="size-4" />} label="Directions" />
              <LinkButton href={tel(j.hotel_phone)} icon={<Phone className="size-4" />} label="Call hotel" />
            </div>
          </div>
        ) : (
          <div>
            <p className="flex items-center gap-2 text-sm font-semibold text-muted"><MapPin className="size-4" /> Deliver to</p>
            <p className="text-xl font-bold">{j.customer_name}</p>
            {j.landmark ? <p className="mt-1 rounded-xl bg-subtle px-3 py-2 text-[0.9375rem]">📍 {j.landmark}</p> : null}
            <div className="mt-3 flex gap-2">
              <LinkButton href={directions(j.lat, j.lng)} icon={<Navigation className="size-4" />} label="Directions" />
              <LinkButton href={tel(j.customer_phone)} icon={<Phone className="size-4" />} label="Call customer" />
            </div>
          </div>
        )}

        <ul className="rounded-2xl bg-subtle p-3 text-sm">
          {j.items.map((it, i) => <li key={i} className="font-medium">{it}</li>)}
        </ul>

        <div className="flex items-center justify-between rounded-2xl border border-line px-4 py-3">
          <span className="text-sm text-muted">{j.distance_km != null ? `${j.distance_km} km · ` : ""}Your fee</span>
          <span className="money text-xl font-extrabold">{money(j.rider_fee)}</span>
        </div>
        <p className="flex items-start gap-2 text-sm">
          <Banknote className="mt-0.5 size-4 shrink-0 text-ok" />
          {j.collect_cash_fee
            ? `Collect ${money(j.rider_fee)} cash from the customer at the door.`
            : j.fee_with_food
              ? `The hotel gives you ${money(j.rider_fee)} with the food.`
              : "Paid to you in the weekly payout."}
        </p>

        {/* Hotel tapped "Handed to rider" first: the rider still confirms the fee. */}
        {!goingToHotel && j.fee_with_food && !j.fee_rider_confirmed ? (
          <div className="rounded-2xl border-2 border-warn/40 bg-warn-soft p-4">
            <p className="font-bold">Did the hotel give you {money(j.rider_fee)}?</p>
            <p className="text-sm text-muted">The hotel says it handed over your fee with the food.</p>
            <div className="mt-3 grid grid-cols-2 gap-2">
              <button onClick={() => void run(`/rider/jobs/${j.id}/picked-up`, { fee_received: true })} className="h-11 rounded-xl bg-ok font-semibold text-white">Yes, I got it</button>
              <button onClick={() => void run(`/rider/jobs/${j.id}/picked-up`, { fee_received: false })} className="h-11 rounded-xl border-2 border-line bg-surface font-semibold">No</button>
            </div>
          </div>
        ) : null}

        {/* The next step */}
        {goingToHotel ? (
          <>
            <BigButton tone="ok" disabled={j.status !== "ready"} onClick={() => (j.fee_with_food ? setAsk("pickup_fee") : void run(`/rider/jobs/${j.id}/picked-up`, {}))}>
              <CheckCircle2 className="size-5" /> {j.status === "ready" ? "I have the food" : "Wait for the food"}
            </BigButton>
            <button onClick={() => void run(`/rider/jobs/${j.id}/release`)} className="text-sm font-semibold text-muted hover:text-bad">Drop this job</button>
          </>
        ) : j.status === "picked_up" ? (
          <BigButton onClick={() => void run(`/rider/jobs/${j.id}/on-the-way`)}><Bike className="size-5" /> Start the trip</BigButton>
        ) : null}

        {!goingToHotel ? (
          <div className="flex flex-col gap-3 rounded-2xl border-2 border-dashed border-line p-4">
            <label className="text-sm font-bold" htmlFor={`code-${j.id}`}>At the door: ask for the customer's 4-digit code</label>
            <input
              id={`code-${j.id}`}
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 4))}
              inputMode="numeric"
              autoComplete="one-time-code"
              placeholder="• • • •"
              className="money h-16 rounded-2xl border-2 border-line bg-surface text-center text-3xl font-extrabold tracking-[0.5em] outline-none focus:border-brand"
            />
            {j.code_attempts_left != null && j.code_attempts_left < 5 ? <p className="text-sm font-semibold text-bad">{j.code_attempts_left} tries left</p> : null}
            <BigButton tone="ok" disabled={code.length !== 4} onClick={() => (j.collect_cash_fee ? setAsk("cash_fee") : void run(`/rider/jobs/${j.id}/delivered`, { code }))}>
              <CheckCircle2 className="size-5" /> Delivered
            </BigButton>
            <button onClick={() => setAsk("fail")} className="flex items-center justify-center gap-1.5 text-sm font-semibold text-muted hover:text-bad">
              <AlertTriangle className="size-4" /> I can't deliver this
            </button>
          </div>
        ) : null}
        <ErrorNote error={error} />
      </div>

      {/* Questions */}
      {ask ? (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 p-4 sm:items-center" onClick={() => setAsk(null)}>
          <div role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()} className="w-full max-w-sm rounded-3xl bg-surface p-6">
            {ask === "pickup_fee" ? (
              <>
                <h2 className="text-xl font-bold">Did the hotel give you {money(j.rider_fee)}?</h2>
                <p className="mt-1 text-sm text-muted">Your delivery fee comes with the food for this order.</p>
                <div className="mt-5 flex flex-col gap-2">
                  <BigButton tone="ok" onClick={() => void run(`/rider/jobs/${j.id}/picked-up`, { fee_received: true })}>Yes, I got {money(j.rider_fee)}</BigButton>
                  <BigButton tone="ghost" onClick={() => void run(`/rider/jobs/${j.id}/picked-up`, { fee_received: false })}>No, not yet</BigButton>
                </div>
              </>
            ) : ask === "cash_fee" ? (
              <>
                <h2 className="text-xl font-bold">Did the customer pay you {money(j.rider_fee)}?</h2>
                <p className="mt-1 text-sm text-muted">If not, Chakula asks the customer and pays you in the weekly payout if they didn't.</p>
                <div className="mt-5 flex flex-col gap-2">
                  <BigButton tone="ok" onClick={() => void run(`/rider/jobs/${j.id}/delivered`, { code, cash_fee_received: true })}>Yes, I got the cash</BigButton>
                  <BigButton
                    tone="ghost"
                    onClick={async () => {
                      setError(null);
                      try {
                        await act(`/rider/jobs/${j.id}/delivered`, { code, cash_fee_received: false });
                        await act(`/rider/jobs/${j.id}/fee-not-paid`);
                        setAsk(null);
                      } catch (e) {
                        setError(e);
                      }
                    }}
                  >
                    No, they didn't pay
                  </BigButton>
                </div>
              </>
            ) : (
              <>
                <h2 className="text-xl font-bold">Why can't you deliver?</h2>
                <p className="mt-1 text-sm text-muted">Call the customer first. The Chakula team reviews every failed delivery.</p>
                <div className="mt-4 flex flex-col gap-2">
                  {FAIL_REASONS.map(([value, label]) => (
                    <button key={value} onClick={() => void run(`/rider/jobs/${j.id}/failed`, { reason: value })} className="h-12 rounded-xl border border-line text-sm font-semibold hover:border-bad/40 hover:bg-bad-soft hover:text-bad">
                      {label}
                    </button>
                  ))}
                </div>
              </>
            )}
            <ErrorNote error={error} />
            <button onClick={() => setAsk(null)} className="mt-3 h-11 w-full rounded-xl text-sm font-semibold text-muted">Cancel</button>
          </div>
        </div>
      ) : null}
    </article>
  );
}

type Earnings = { owed: number; payouts: { id: string; amount: number; mpesa_code: string; paid_at: string }[] };

const paidOn = new Intl.DateTimeFormat("en-KE", { weekday: "short", day: "numeric", month: "short", timeZone: "Africa/Nairobi" });

/** Fees the platform holds for the rider (weekly payout, compensation) and what it has sent. */
function EarningsCard({ e }: { e: Earnings }) {
  if (!e.owed && !e.payouts.length) return null;
  return (
    <section className="rounded-3xl bg-surface p-5 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-sm text-muted">Owed to you</p>
          <p className="money text-2xl font-extrabold text-ok">{money(e.owed)}</p>
        </div>
        <p className="max-w-[11rem] text-right text-xs text-muted">Weekly-paid fees and compensation, sent to your M-Pesa.</p>
      </div>
      {e.payouts.length ? (
        <ul className="mt-3 divide-y divide-line border-t border-line text-sm">
          {e.payouts.slice(0, 5).map((p) => (
            <li key={p.id} className="flex items-center justify-between gap-2 py-2.5">
              <span><strong className="money tracking-wide">{p.mpesa_code}</strong> · {paidOn.format(new Date(p.paid_at))}</span>
              <span className="money font-bold">{money(p.amount)}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

export function JobsPage({ me }: { me: RiderMe }) {

  const qc = useQueryClient();
  const jobs = useQuery({ queryKey: ["rider", "jobs"], queryFn: () => api.get<Job[]>("/rider/jobs"), refetchInterval: 20_000 });
  const history = useQuery({ queryKey: ["rider", "history"], queryFn: () => api.get<Job[]>("/rider/jobs/history") });
  const earnings = useQuery({ queryKey: ["rider", "earnings"], queryFn: () => api.get<Earnings>("/rider/earnings") });
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["rider"] });
  };
  useLive("/rider/events", refresh, { staff: true });

  const online = useMutation({
    mutationFn: (v: boolean) => api.post<RiderMe>("/rider/online", { online: v }),
    onSuccess: (data) => qc.setQueryData(["rider", "me"], data),
  });
  const claim = useMutation({
    mutationFn: (id: string) => api.post(`/rider/jobs/${id}/claim`),
    onSuccess: refresh,
  });
  const act = async (path: string, body?: unknown) => {
    try {
      await api.post(path, body);
    } finally {
      refresh();
    }
  };

  const mine = (jobs.data ?? []).filter((j) => j.mine);
  const open = (jobs.data ?? []).filter((j) => !j.mine);
  const assignedNew = mine.filter((j) => !j.seen);
  // Ring until the action is done (D22): a job given to you until "Got it"; open jobs while
  // you're online and free until you (or another rider) take one.
  useAlarm("rider-assigned", assignedNew.length, "job", "New job for you");
  useAlarm("rider-open", me.is_online && mine.length === 0 ? open.length : 0, "job", "Delivery job waiting");
  const today = new Date().toDateString();
  const doneToday = (history.data ?? []).filter((j) => j.status === "delivered" && j.closed_at && new Date(j.closed_at).toDateString() === today);

  return (
    <div className="flex flex-col gap-5">
      {/* Online switch */}
      <button
        onClick={() => online.mutate(!me.is_online)}
        disabled={online.isPending}
        className={clsx("flex items-center gap-4 rounded-3xl p-5 text-left shadow-sm transition-colors", me.is_online ? "bg-ok text-white" : "bg-surface")}
      >
        <span className={clsx("flex size-14 items-center justify-center rounded-2xl", me.is_online ? "bg-white/20" : "bg-subtle text-muted")}>
          <Power className="size-7" />
        </span>
        <span className="flex-1">
          <span className="block text-xl font-extrabold">{me.is_online ? "You're online" : "You're offline"}</span>
          <span className={clsx("block text-sm", me.is_online ? "text-white/85" : "text-muted")}>{me.is_online ? "New jobs appear below. Tap to go offline." : "Tap to go online and start taking jobs."}</span>
        </span>
      </button>
      <ErrorNote error={online.error} />

      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-2xl bg-surface p-4 text-center shadow-sm">
          <p className="text-2xl font-extrabold">{doneToday.length}</p>
          <p className="text-sm text-muted">Deliveries today</p>
        </div>
        <div className="rounded-2xl bg-surface p-4 text-center shadow-sm">
          <p className="money text-2xl font-extrabold">{money(doneToday.reduce((s, j) => s + j.rider_fee, 0))}</p>
          <p className="text-sm text-muted">Earned today</p>
        </div>
      </div>

      {earnings.data ? <EarningsCard e={earnings.data} /> : null}

      {jobs.isLoading ? <Skeleton className="h-48 rounded-3xl" /> : null}
      {assignedNew.map((j) => (
        <div key={`ack-${j.id}`} className="flex animate-pulse items-center gap-3 rounded-3xl bg-brand p-5 text-white shadow-lg">
          <Bike className="size-8 shrink-0" />
          <div className="flex-1">
            <p className="text-lg font-extrabold">New job for you: #{j.code}</p>
            <p className="text-sm text-white/85">Pick up from {j.hotel_name}</p>
          </div>
          <button onClick={() => void act(`/rider/jobs/${j.id}/seen`)} className="h-12 rounded-xl bg-white px-5 font-bold text-brand">Got it</button>
        </div>
      ))}
      {mine.map((j) => <MyJob key={j.id} j={j} act={act} />)}

      <section>
        <h2 className="mb-3 flex items-center justify-between text-lg font-bold">
          Open jobs <span className="rounded-full bg-subtle px-2.5 py-0.5 text-sm">{open.length}</span>
        </h2>
        {!me.is_online ? (
          <p className="rounded-2xl border border-dashed border-line py-8 text-center text-sm text-muted">Go online to see and take jobs.</p>
        ) : open.length === 0 ? (
          <p className="rounded-2xl border border-dashed border-line py-8 text-center text-sm text-muted">No open jobs right now. New ones appear here by themselves.</p>
        ) : (
          <ul className="flex flex-col gap-3">
            {open.map((j) => (
              <li key={j.id} className="rounded-3xl bg-surface p-5 shadow-sm">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-lg font-bold">{j.hotel_name}</p>
                    <p className="text-sm text-muted">{j.items.length} item{j.items.length === 1 ? "" : "s"} · {readyIn(j)}</p>
                  </div>
                  <div className="text-right">
                    <p className="money text-2xl font-extrabold whitespace-nowrap text-ok">{money(j.rider_fee)}</p>
                    <p className="text-sm text-muted">{j.distance_km != null ? `${j.distance_km} km` : ""}{j.collect_cash_fee ? " · cash" : ""}</p>
                  </div>
                </div>
                <button onClick={() => claim.mutate(j.id)} disabled={claim.isPending} className="mt-4 h-13 w-full rounded-2xl bg-brand py-3.5 text-[1rem] font-bold text-white shadow-md shadow-brand/25 disabled:opacity-60">
                  Take this job
                </button>
              </li>
            ))}
          </ul>
        )}
        <ErrorNote error={claim.error} />
      </section>

      {history.data?.length ? (
        <section>
          <h2 className="mb-3 text-lg font-bold">Recent deliveries</h2>
          <ul className="divide-y divide-line rounded-3xl bg-surface px-5 shadow-sm">
            {history.data.slice(0, 10).map((j) => (
              <li key={j.id} className="flex items-center justify-between gap-2 py-3 text-sm">
                <span><strong>#{j.code}</strong> · {j.hotel_name}{j.fee_not_paid ? <span className="text-bad"> · fee not paid (reported)</span> : null}</span>
                <span className={clsx("money font-bold", j.status === "delivered" ? "text-ok" : "text-bad")}>{j.status === "delivered" ? money(j.rider_fee) : "Failed"}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}

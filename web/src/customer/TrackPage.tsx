/**
 * Tracking without login: the long random token in the URL is the access.
 * Doubles as the pay screen while the order awaits payment. Polls every 10 s until live
 * updates (SSE) arrive with the hotel order screen.
 */
import { useMutation, useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowLeft, Check, ChefHat, Copy, Phone, ReceiptText, RotateCcw, ShieldCheck, Smartphone, Star, Store, Timer, XCircle } from "lucide-react";
import { type ReactNode, Suspense, lazy, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { ErrorNote, Skeleton } from "../components/ui";
import { api } from "../lib/api";
import { money } from "../lib/format";
import { useAlarm } from "../lib/alarm";
import { useLive } from "../lib/live";
import { tr, useT } from "../lib/i18n";
import { TopBar } from "./CustomerLayout";
import { ConfirmDialog, HelpButton, JourneySteps, toast } from "./bits";
import { useConfig } from "./OrderPanel";
import { FoodImage } from "./FoodImage";
const RiderMap = lazy(() => import("./RiderMap")); // map library loads only once a rider is live
import { orderAgain } from "./store";
import type { Track } from "./types";

const DELIVERY_STEPS = ["paid", "accepted", "preparing", "ready", "picked_up", "on_the_way", "delivered"];
const PICKUP_STEPS = ["paid", "accepted", "preparing", "ready", "collected"];
const LABELS: Record<string, string> = {
  awaiting_payment: "Waiting for payment",
  checking_payment: "Checking payment",
  paid: "Payment received",
  accepted: "Hotel accepted",
  preparing: "Being prepared",
  ready: "Ready",
  picked_up: "Rider picked up",
  on_the_way: "On the way",
  delivered: "Delivered",
  collected: "Collected",
  expired: "Expired: not paid in time",
  rejected: "The hotel couldn't take this order",
  cancelled: "Order cancelled",
  failed_delivery: "Delivery failed",
};
const ENDED = ["expired", "rejected", "cancelled", "failed_delivery"];

function useCountdown(iso: string | null) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!iso) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [iso]);
  if (!iso) return null;
  const left = Math.max(0, new Date(iso).getTime() - now);
  return { left, text: `${Math.floor(left / 60000)}:${String(Math.floor((left % 60000) / 1000)).padStart(2, "0")}` };
}

function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <section className={clsx("rounded-2xl border border-line bg-surface", className)}>{children}</section>;
}

function CopyButton({ text }: { text: string }) {
  const t = useT();
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setDone(true);
          setTimeout(() => setDone(false), 1500);
        } catch {
          /* clipboard blocked (plain http): the number is on screen */
        }
      }}
      className="flex h-10 items-center gap-1.5 rounded-xl border border-line bg-surface px-3 text-sm font-semibold hover:bg-subtle"
    >
      {done ? <Check className="size-4 text-ok" /> : <Copy className="size-4" />} {done ? t("Copied") : t("Copy")}
    </button>
  );
}

/** Step 4 of paying: the customer types the M-Pesa code from their confirmation SMS. */
function CodeEntry({ token, onDone }: { token: string; onDone: () => void }) {
  const tt = useT();
  const [code, setCode] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const submit = useMutation({
    mutationFn: () => api.post<{ result: string; message: string }>(`/track/${token}/payment-code`, { code }),
    onSuccess: (r) => {
      setMsg({ ok: r.result === "paid" || r.result === "pending" || r.result === "overpaid", text: r.message });
      onDone();
    },
    onError: (e) => setMsg({ ok: false, text: e instanceof Error ? e.message : "Something went wrong" }),
  });
  const clean = code.replace(/\s+/g, "").toUpperCase();
  const valid = /^[A-Z0-9]{10}$/.test(clean);
  return (
    <div className="mt-5 rounded-2xl border-2 border-dashed border-brand/40 bg-brand-soft/40 p-4">
      <label htmlFor="mpesa-code" className="text-sm font-semibold">{tt("Paid? Enter the M-Pesa code")}</label>
      <p className="mb-2.5 text-xs text-muted">{tt("It's at the start of your M-Pesa message, e.g. SJK3ABC12D")}</p>
      <div className="flex gap-2">
        <input
          id="mpesa-code"
          value={code}
          onChange={(e) => {
            setCode(e.target.value.toUpperCase());
            setMsg(null);
          }}
          maxLength={14}
          autoCapitalize="characters"
          autoComplete="off"
          spellCheck={false}
          placeholder="SJK3ABC12D"
          className="money h-12 min-w-0 flex-1 rounded-xl border border-line bg-surface px-4 text-lg font-bold tracking-widest uppercase outline-none placeholder:font-normal placeholder:tracking-normal placeholder:text-stone-400 focus:border-brand focus:ring-4 focus:ring-brand/10"
        />
        <button
          onClick={() => submit.mutate()}
          disabled={!valid || submit.isPending}
          className="h-12 shrink-0 rounded-xl bg-brand px-5 font-semibold text-white disabled:bg-line disabled:text-muted"
        >
          {submit.isPending ? "…" : tt("Send")}
        </button>
      </div>
      {code && !valid ? <p className="mt-2 text-xs text-muted">{tt("M-Pesa codes have 10 letters and numbers.")}</p> : null}
      {msg ? <p className={clsx("mt-2 text-sm font-medium", msg.ok ? "text-ok" : "text-bad")}>{msg.text}</p> : null}
    </div>
  );
}

function PayCard({ t, token, onCode }: { t: Track; token: string; onCode: () => void }) {
  const tt = useT();
  const countdown = useCountdown(t.expires_at);
  if (t.payment_method === "cash") {
    return (
      <Card className="p-5">
        <div className="flex items-center gap-3">
          <span className="flex size-11 items-center justify-center rounded-xl bg-brand-soft text-brand"><Store className="size-5" /></span>
          <div>
            <p className="text-sm text-muted">Pay at the counter when you collect</p>
            <p className="money text-2xl font-bold">{money(t.till_amount)}</p>
          </div>
        </div>
        <p className="mt-3 text-sm text-muted">The hotel may call to confirm your order first.</p>
      </Card>
    );
  }
  const urgent = countdown && countdown.left < 5 * 60_000;
  return (
    <Card className="overflow-hidden">
      <div className="flex items-center justify-between gap-3 border-b border-line px-5 py-4">
        <div className="flex items-center gap-3">
          <span className="flex size-11 items-center justify-center rounded-xl bg-ok text-white"><Smartphone className="size-5" /></span>
          <div>
            <p className="text-sm text-muted">{tt("Pay with M-Pesa")}</p>
            <p className="money text-2xl font-bold">{money(t.till_amount)}</p>
          </div>
        </div>
        {countdown ? (
          <div className={clsx("flex items-center gap-2 rounded-xl px-3 py-2", urgent ? "bg-bad-soft text-bad" : "bg-subtle")}>
            <Timer className="size-4" />
            <span className="money text-lg font-bold">{countdown.text}</span>
          </div>
        ) : null}
      </div>
      <div className="p-5">
        <div className="flex items-center justify-between rounded-xl bg-subtle p-4">
          <div>
            <p className="text-xs font-medium tracking-wide text-muted uppercase">{tt("Buy Goods Till number")}</p>
            <p className="money mt-0.5 text-3xl font-extrabold tracking-wider">{t.till_number}</p>
            {t.till_name ? (
              <p className="mt-1 text-sm">{tt("M-Pesa will show")}: <strong>{t.till_name}</strong></p>
            ) : (
              <p className="text-xs text-muted">{t.hotel_name}</p>
            )}
          </div>
          <CopyButton text={t.till_number} />
        </div>
        {t.till_name ? (
          <p className="mt-3 flex items-start gap-2 rounded-xl bg-ok-soft px-4 py-3 text-sm text-ok">
            <ShieldCheck className="mt-0.5 size-4 shrink-0" />
            <span>
              {tt("Before you enter your PIN, check that M-Pesa shows this name. If it shows a different name, don't pay: call the hotel on")}{" "}
              <a href={`tel:+${t.hotel_phone}`} className="font-bold underline">0{t.hotel_phone.slice(3)}</a>.
            </span>
          </p>
        ) : null}
        <ol className="mt-4 flex flex-col gap-2.5 text-sm">
          {[
            <>Open M-Pesa → Lipa na M-Pesa → <strong>Buy Goods and Services</strong></>,
            <>Till <strong className="money">{t.till_number}</strong>, amount <strong className="money">{money(t.till_amount)}</strong> exactly</>,
            <>Enter your PIN and keep the M-Pesa message</>,
          ].map((step, i) => (
            <li key={i} className="flex gap-3">
              <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-brand text-xs font-bold text-white">{i + 1}</span>
              <span className="pt-0.5">{step}</span>
            </li>
          ))}
        </ol>
        <CodeEntry token={token} onDone={onCode} />
        <p className="mt-4 text-sm text-muted">{tt("This page updates by itself once the hotel confirms your payment.")}</p>
        {t.rider_fee_cash ? (
          <p className="mt-3 rounded-xl bg-warn-soft px-4 py-3 text-sm text-warn">
            Also have <strong className="money">{money(t.rider_fee_cash)}</strong> cash ready for the rider.
          </p>
        ) : null}
      </div>
    </Card>
  );
}

function Timeline({ t }: { t: Track }) {
  useT();
  const steps = t.type === "delivery" ? DELIVERY_STEPS : PICKUP_STEPS;
  const at = new Map(t.events.map((e) => [e.status, e.at]));
  const currentIdx = steps.indexOf(t.status);
  const time = (iso?: string) => (iso ? new Intl.DateTimeFormat("en-KE", { hour: "2-digit", minute: "2-digit", timeZone: "Africa/Nairobi" }).format(new Date(iso)) : "");
  return (
    <ol className="relative flex flex-col">
      {steps.map((s, i) => {
        const done = i <= currentIdx;
        const current = i === currentIdx;
        return (
          <li key={s} className="relative flex gap-3 pb-5 last:pb-0">
            {i < steps.length - 1 ? <span className={clsx("absolute top-7 left-[0.8125rem] h-[calc(100%-20px)] w-0.5", i < currentIdx ? "bg-ok" : "bg-line")} /> : null}
            <span className={clsx("relative z-10 flex size-7 shrink-0 items-center justify-center rounded-full border-2", done ? "border-ok bg-ok text-white" : "border-line bg-surface", current && "ring-4 ring-ok/15")}>
              {done ? <Check className="size-3.5" /> : null}
            </span>
            <span className="flex flex-1 justify-between pt-0.5">
              <span className={clsx("text-sm", current ? "font-semibold" : done ? "" : "text-muted")}>{tr(t.type === "eat_in" && s === "collected" ? "Served" : LABELS[s])}</span>
              <span className="text-xs text-muted">{time(at.get(s))}</span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}

/** The rider reported the cash delivery fee unpaid; the customer is asked once. */
function FeeQuestion({ token, fee, onDone }: { token: string; fee: number; onDone: () => void }) {
  const tt = useT();
  useAlarm("customer-fee-question", 1, "payment", tt("Did you pay the rider {amount}?", { amount: money(fee) }));
  const answer = useMutation({ mutationFn: (paid: boolean) => api.post(`/track/${token}/rider-fee-answer`, { paid }), onSuccess: onDone });
  return (
    <Card className="border-2 border-warn/40 p-5">
      <p className="text-lg font-bold">{tt("Did you pay the rider {amount}?", { amount: money(fee) })}</p>
      <p className="mt-1 text-sm text-muted">{tt("The rider says the delivery fee wasn't paid. Please tell us honestly.")}</p>
      <div className="mt-4 grid grid-cols-2 gap-2">
        <button onClick={() => answer.mutate(true)} disabled={answer.isPending} className="h-12 rounded-xl bg-ok font-semibold text-white">{tt("Yes, I paid")}</button>
        <button onClick={() => answer.mutate(false)} disabled={answer.isPending} className="h-12 rounded-xl border-2 border-line font-semibold">{tt("No, I didn't")}</button>
      </div>
      <ErrorNote error={answer.error} />
    </Card>
  );
}

function StarRow({ label, value, onChange }: { label: string; value: number; onChange: (n: number) => void }) {
  return (
    <div>
      <p className="mb-1 text-sm font-medium">{label}</p>
      <div className="flex gap-1" role="radiogroup" aria-label={label}>
        {[1, 2, 3, 4, 5].map((n) => (
          <button key={n} type="button" role="radio" aria-checked={value === n} aria-label={`${n}`} onClick={() => onChange(n)} className="p-0.5">
            <Star className={clsx("size-8 transition-colors", n <= value ? "fill-warn text-warn" : "text-line")} />
          </button>
        ))}
      </div>
    </div>
  );
}

/** Once the food is in hand, rate the hotel (and the rider on deliveries). Once per order. */
function RateCard({ t, token, onDone }: { t: Track; token: string; onDone: () => void }) {
  const tt = useT();
  const [hotel, setHotel] = useState(0);
  const [rider, setRider] = useState(0);
  const [comment, setComment] = useState("");
  const needsRider = t.type === "delivery";
  const send = useMutation({
    mutationFn: () => api.post(`/track/${token}/rating`, { hotel_stars: hotel, rider_stars: needsRider ? rider : null, comment: comment.trim() || null }),
    onSuccess: onDone,
  });
  return (
    <Card className="flex flex-col gap-4 p-5">
      <p className="text-lg font-bold">{tt("How was it?")}</p>
      <StarRow label={t.hotel_name} value={hotel} onChange={setHotel} />
      {needsRider ? <StarRow label={tt("Your rider {name}", { name: t.rider_name ?? "" })} value={rider} onChange={setRider} /> : null}
      <textarea
        aria-label={tt("Anything to add? (optional)")}
        placeholder={tt("Anything to add? (optional)")}
        value={comment}
        onChange={(e) => setComment(e.target.value)}
        maxLength={500}
        rows={2}
        className="rounded-xl border border-line bg-surface p-3 text-sm outline-none focus:border-brand"
      />
      <button
        onClick={() => send.mutate()}
        disabled={!hotel || (needsRider && !rider) || send.isPending}
        className="h-12 rounded-xl bg-brand font-semibold text-white disabled:bg-line disabled:text-muted"
      >
        {tt("Send rating")}
      </button>
      <ErrorNote error={send.error} />
    </Card>
  );
}

export function TrackPage() {
  const tt = useT();
  const { token = "" } = useParams();
  const track = useQuery({
    queryKey: ["track", token],
    queryFn: () => api.get<Track>(`/track/${token}`),
    refetchInterval: (query) => (query.state.data && ["delivered", "collected", ...ENDED].includes(query.state.data.status) ? false : 30_000),
  });
  const [ping, setPing] = useState<{ lat: number; lng: number; at: string } | null>(null);
  useLive(token ? `/track/${token}/events` : null, (e) => {
    // A rider position only moves the map; every other change reloads the order.
    if (e.type === "rider_location" && typeof e.lat === "number" && typeof e.lng === "number") setPing({ lat: e.lat, lng: e.lng, at: String(e.at) });
    else void track.refetch();
  });
  const cancel = useMutation({ mutationFn: () => api.post(`/track/${token}/cancel`), onSuccess: () => track.refetch() });
  const [confirmCancel, setConfirmCancel] = useState(false);
  const navigate = useNavigate();
  const config = useConfig();

  if (track.isLoading) return (<><TopBar /><div className="p-6"><Skeleton className="h-64 rounded-2xl" /></div></>);
  if (track.error || !track.data) return (<><TopBar /><div className="p-6"><ErrorNote error={track.error} /></div></>);
  const t = track.data;
  const ended = ENDED.includes(t.status);
  const awaiting = t.status === "awaiting_payment";
  const done = t.status === "delivered" || t.status === "collected";

  return (
    <>
      <TopBar />
      <div className="flex flex-1 flex-col gap-5 px-4 py-5 pb-10 sm:px-6 lg:flex-row lg:items-start">
        <div className="flex min-w-0 flex-1 flex-col gap-4">
          <div className="flex flex-wrap items-center gap-2">
            <Link to="/" className="flex h-10 items-center gap-2 rounded-xl border border-line bg-surface px-3.5 text-sm font-semibold hover:bg-subtle">
              <ArrowLeft className="size-4" /> {tt("Home")}
            </Link>
            <Link to="/orders" className="flex h-10 items-center gap-2 rounded-xl border border-line bg-surface px-3.5 text-sm font-semibold hover:bg-subtle">
              <ReceiptText className="size-4" /> {tt("My orders")}
            </Link>
          </div>
          {!ended ? (
            <div className="rounded-3xl border border-line bg-surface p-4 sm:p-5">
              <JourneySteps step={awaiting || t.status === "checking_payment" ? 2 : 3} />
            </div>
          ) : null}
          {/* Status header */}
          <section className={clsx("relative overflow-hidden rounded-2xl px-6 py-6 text-white", ended ? "bg-ink" : done ? "bg-ok" : "bg-brand")}>
            <p className="text-sm font-medium text-white/80">{tt("Order #{code}", { code: t.code })} · {t.hotel_name}</p>
            <h1 className="mt-1 text-2xl font-bold">{tt(t.type === "eat_in" && t.status === "collected" ? "Served" : (LABELS[t.status] ?? t.status))}</h1>
            {t.reason && ended ? <p className="mt-1 text-sm text-white/80">{t.reason}</p> : null}
            {t.type === "eat_in" && t.arrive_at && !ended && !done ? (
              <p className="mt-1 text-sm font-semibold text-white/90">
                🍽️ {tt("Eat in · arriving about {time}", { time: new Intl.DateTimeFormat("en-KE", { hour: "numeric", minute: "2-digit", timeZone: "Africa/Nairobi" }).format(new Date(t.arrive_at)) })}
              </p>
            ) : null}
            {t.prep_minutes && ["accepted", "preparing"].includes(t.status) ? <p className="mt-1 text-sm text-white/85">{tt("Ready in about {min} min", { min: t.prep_minutes })}</p> : null}
            <span className="pointer-events-none absolute -right-2 -bottom-4 hidden opacity-25 sm:block">
              {ended ? <XCircle className="size-28" /> : <ChefHat className="size-28" />}
            </span>
          </section>

          {awaiting ? <PayCard t={t} token={token} onCode={() => track.refetch()} /> : null}
          {t.status === "expired" && t.payment_method === "mpesa" ? (
            <Card className="p-5">
              <p className="font-semibold">{tt("Already paid?")}</p>
              <p className="text-sm text-muted">{tt("Enter your M-Pesa code and the hotel will check it.")}</p>
              <CodeEntry token={token} onDone={() => track.refetch()} />
            </Card>
          ) : null}
          {t.can_cancel ? (
            <button
              onClick={() => setConfirmCancel(true)}
              className="flex h-12 items-center justify-center gap-2 rounded-2xl border-2 border-line bg-surface text-[0.9375rem] font-semibold text-muted transition-colors hover:border-bad/40 hover:bg-bad-soft hover:text-bad"
            >
              <XCircle className="size-5" /> {tt("Cancel order")}
            </button>
          ) : null}
          <ErrorNote error={cancel.error} />
          {t.status === "checking_payment" ? (
            <Card className="flex items-center gap-4 p-5">
              <span className="size-10 shrink-0 animate-spin rounded-full border-4 border-brand/20 border-t-brand" />
              <div>
                <p className="font-semibold">{tt("Checking your payment")}</p>
                <p className="text-sm text-muted">
                  {tt("Code {code}. The hotel is confirming it, usually within a few minutes.", { code: t.customer_trans_code ?? "" })}
                </p>
              </div>
            </Card>
          ) : null}

          {t.live && t.rider_name ? (
            <Suspense fallback={<div className="h-56 animate-pulse rounded-2xl bg-subtle" />}>
              <RiderMap token={token} live={t.live} ping={ping} riderName={t.rider_name} />
            </Suspense>
          ) : null}

          {t.type !== "delivery" && t.delivery_code && !awaiting && !ended && !done ? (
            <Card className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="font-semibold">{t.type === "eat_in" ? tt("Eat-in PIN") : tt("Pickup PIN")}</p>
                <p className="text-sm text-muted">{tt("Tell the hotel this PIN when you get there. They only hand over your food once you give it.")}</p>
              </div>
              <div className="flex gap-1.5">
                {t.delivery_code.split("").map((d, i) => (
                  <span key={i} className="money flex h-14 w-11 items-center justify-center rounded-xl bg-brand-soft text-3xl font-extrabold text-brand">{d}</span>
                ))}
              </div>
            </Card>
          ) : null}

          {t.type === "delivery" && t.delivery_code && !ended && !done ? (
            <Card className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="font-semibold">{tt("Delivery code")}</p>
                <p className="text-sm text-muted">{tt("Give it to the rider when your food arrives")}</p>
              </div>
              <div className="flex gap-1.5">
                {t.delivery_code.split("").map((d, i) => (
                  <span key={i} className="money flex h-14 w-11 items-center justify-center rounded-xl bg-brand-soft text-3xl font-extrabold text-brand">{d}</span>
                ))}
              </div>
            </Card>
          ) : null}

          {!awaiting && !ended ? (
            <Card className="p-5">
              <h2 className="mb-4 text-[0.9375rem] font-semibold">{tt("Progress")}</h2>
              <Timeline t={t} />
            </Card>
          ) : null}

          {t.rider_name ? (
            <Card className="flex items-center gap-4 p-5">
              {t.rider_photo_url ? <img src={t.rider_photo_url} alt="" className="size-14 rounded-full object-cover ring-2 ring-brand/30" /> : <span className="flex size-14 items-center justify-center rounded-full bg-brand-soft text-2xl">🛵</span>}
              <div className="min-w-0 flex-1">
                <p className="text-sm text-muted">{tt("Your rider")}</p>
                <p className="text-lg font-bold">{t.rider_name}</p>
                <p className="text-xs text-muted">{tt("Verified by Chakula")}</p>
              </div>
              <a href={`tel:+${t.rider_phone}`} className="flex h-11 items-center gap-2 rounded-xl bg-brand px-4 font-semibold text-white"><Phone className="size-4" /> {tt("Call")}</a>
            </Card>
          ) : null}

          {t.fee_question ? <FeeQuestion token={token!} fee={t.rider_fee} onDone={() => void track.refetch()} /> : null}
          {t.can_rate ? (
            <RateCard
              t={t}
              token={token!}
              onDone={() => {
                void track.refetch();
                // Rated = order finished: take them back to the hotels after a moment to read the thanks.
                setTimeout(() => navigate("/", { replace: true }), 1800);
              }}
            />
          ) : null}
          {t.rated ? <p className="text-center text-sm text-muted">{tt("Thanks for rating this order!")}</p> : null}
        </div>

        {/* Order summary */}
        <aside className="flex w-full flex-col gap-4 lg:sticky lg:top-5 lg:w-[23.75rem] lg:shrink-0">
          <Card>
            <div className="flex items-center justify-between border-b border-line px-5 py-4">
              <h2 className="text-[0.9375rem] font-semibold">{tt("Order details")}</h2>
              <a href={`tel:+${t.hotel_phone}`} className="flex items-center gap-1.5 text-sm font-semibold text-brand"><Phone className="size-4" /> {tt("Call hotel")}</a>
            </div>
            <ol className="flex flex-col gap-3 px-5 py-4">
              {t.items.map((i, n) => (
                <li key={n} className="flex items-center gap-3">
                  <span className="size-12 shrink-0 overflow-hidden rounded-lg"><FoodImage src={i.thumb_url} name={i.name} emojiSize="text-2xl" /></span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{i.quantity}x {i.name}</p>
                    {i.options.length ? <p className="truncate text-xs text-muted">{i.options.join(", ")}</p> : null}
                  </div>
                  <span className="money text-sm font-semibold">{money(i.line_total)}</span>
                </li>
              ))}
            </ol>
            <div className="flex flex-col gap-2 border-t border-line px-5 py-4 text-sm">
              {t.order_discount ? <div className="flex justify-between"><span className="text-muted">{tt("Discount")}</span><span className="money text-ok">−{money(t.order_discount)}</span></div> : null}
              <div className="flex justify-between"><span className="text-muted">{tt("Service fee")}</span><span className="money">{money(t.service_fee - t.eat_in_fee)}</span></div>
              {t.eat_in_fee ? <div className="flex justify-between"><span className="text-muted">{tt("Eat-in booking")}</span><span className="money">{money(t.eat_in_fee)}</span></div> : null}
              {t.rider_fee && !t.rider_fee_cash ? (
                <div className="flex justify-between">
                  <span className="text-muted">
                    {tt("Delivery")}
                    {t.distance_km != null ? ` · ${t.distance_km} km` : ""}
                  </span>
                  <span className="money">{money(t.rider_fee)}</span>
                </div>
              ) : null}
              {t.platform_bonus ? (
                <div className="flex justify-between font-medium text-ok">
                  <span>{t.bonus_kind === "free_delivery" ? tt("Free delivery") : tt("Stamp card reward")}</span>
                  <span className="money">−{money(t.platform_bonus)}</span>
                </div>
              ) : null}
              <div className="flex items-center justify-between pt-1"><span className="font-semibold">{tt("Total")}</span><span className="money text-lg font-bold">{money(t.till_amount)}</span></div>
              {t.rider_fee_cash ? <div className="flex justify-between text-muted"><span>{tt("+ cash to the rider")}{t.distance_km != null ? ` · ${t.distance_km} km` : ""}</span><span className="money">{money(t.rider_fee_cash)}</span></div> : null}
            </div>
            {t.landmark ? <p className="border-t border-line px-5 py-3 text-sm text-muted">{tt("Deliver to:")} {t.landmark}</p> : null}
          </Card>

          <HelpButton number={config.data?.support_whatsapp} message={`Hello Chakula, I need help with order #${t.code} from ${t.hotel_name}.`} />
          {ended || done ? (
            <button
              onClick={() => {
                orderAgain(t);
                toast(tr("Your order is back in the basket"));
                navigate("/checkout");
              }}
              className="flex h-12 items-center justify-center gap-2 rounded-xl bg-brand font-semibold text-white shadow-lg shadow-brand/25 hover:bg-brand-hover"
            >
              <RotateCcw className="size-4" /> {tt("Order this again")}
            </button>
          ) : null}
        </aside>
      </div>
      <ConfirmDialog
        open={confirmCancel}
        emoji="🗑️"
        title={tt("Cancel this order?")}
        body={t.status === "paid" ? "The hotel will refund your payment to your M-Pesa." : "The hotel won't prepare it. If you haven't paid, there's nothing more to do."}
        confirm={tt("Yes, cancel order")}
        cancel={tt("Keep order")}
        danger
        onConfirm={() => cancel.mutate()}
        onClose={() => setConfirmCancel(false)}
      />
    </>
  );
}

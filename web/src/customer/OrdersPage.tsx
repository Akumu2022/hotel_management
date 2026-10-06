/** Order history for this phone (no accounts): every order placed here, with what
 * was paid, filterable. The phone keeps the orders' tracking tokens; the server answers for all of
 * them in one request. */
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowLeft, ChevronRight, RotateCcw, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { api } from "../lib/api";
import { money } from "../lib/format";
import { tr, useT } from "../lib/i18n";
import { TopBar } from "./CustomerLayout";
import { HelpButton, toast } from "./bits";
import { useConfig } from "./OrderPanel";
import { orderAgain, useRecentOrders } from "./store";
import type { Track } from "./types";

type HistoryRow = {
  token: string;
  code: string;
  hotel_name: string;
  hotel_slug: string;
  status: string;
  type: "delivery" | "pickup" | "eat_in";
  payment_method: "mpesa" | "cash";
  created_at: string;
  till_amount: number;
  paid: number;
  refunded: number;
  platform_bonus: number;
  items: string[];
};

const STATUS: Record<string, { label: string; tone: "brand" | "ok" | "muted" | "bad" }> = {
  awaiting_payment: { label: "Waiting for payment", tone: "brand" },
  checking_payment: { label: "Checking payment", tone: "brand" },
  paid: { label: "Paid", tone: "brand" },
  accepted: { label: "Accepted", tone: "brand" },
  preparing: { label: "Being prepared", tone: "brand" },
  ready: { label: "Ready", tone: "brand" },
  picked_up: { label: "With the rider", tone: "brand" },
  on_the_way: { label: "On the way", tone: "brand" },
  delivered: { label: "Delivered", tone: "ok" },
  collected: { label: "Collected", tone: "ok" },
  expired: { label: "Expired", tone: "muted" },
  rejected: { label: "Not accepted", tone: "bad" },
  cancelled: { label: "Cancelled", tone: "muted" },
  failed_delivery: { label: "Delivery failed", tone: "bad" },
};
const DONE = ["delivered", "collected"];
const ENDED = ["cancelled", "expired", "rejected", "failed_delivery"];

const FILTERS = [
  { id: "all", label: "All" },
  { id: "active", label: "Active" },
  { id: "done", label: "Completed" },
  { id: "ended", label: "Cancelled" },
] as const;
type Filter = (typeof FILTERS)[number]["id"];

const PERIODS = [
  { id: 0, label: "Any time" },
  { id: 30, label: "Last 30 days" },
  { id: 90, label: "Last 3 months" },
] as const;

const when = new Intl.DateTimeFormat("en-KE", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "Africa/Nairobi" });

export function OrdersPage() {
  const t = useT();
  const recent = useRecentOrders();
  const navigate = useNavigate();
  const config = useConfig();
  const tokens = recent.map((r) => r.token);
  const history = useQuery({
    queryKey: ["history", tokens],
    queryFn: () => api.post<HistoryRow[]>("/track/history", { tokens }),
    enabled: tokens.length > 0,
    staleTime: 15_000,
  });
  const [filter, setFilter] = useState<Filter>("all");
  const [hotel, setHotel] = useState("");
  const [days, setDays] = useState(0);
  const [q, setQ] = useState("");

  const rows = history.data ?? [];
  const hotels = [...new Map(rows.map((r) => [r.hotel_slug, r.hotel_name])).entries()];
  const shown = useMemo(() => {
    const since = days ? Date.now() - days * 86400_000 : 0;
    const needle = q.trim().toLowerCase();
    return rows.filter(
      (r) =>
        (filter === "all" || (filter === "done" ? DONE.includes(r.status) : filter === "ended" ? ENDED.includes(r.status) : !DONE.includes(r.status) && !ENDED.includes(r.status))) &&
        (!hotel || r.hotel_slug === hotel) &&
        new Date(r.created_at).getTime() >= since &&
        (!needle || r.code.toLowerCase().includes(needle) || r.hotel_name.toLowerCase().includes(needle) || r.items.some((i) => i.toLowerCase().includes(needle))),
    );
  }, [rows, filter, hotel, days, q]);

  const completed = rows.filter((r) => DONE.includes(r.status));
  const spent = rows.reduce((sum, r) => sum + r.paid - r.refunded, 0);
  const saved = rows.reduce((sum, r) => sum + (ENDED.includes(r.status) ? 0 : r.platform_bonus), 0);

  async function again(r: HistoryRow) {
    const tk = await api.get<Track>(`/track/${r.token}`);
    orderAgain(tk);
    toast(tr("Your order is back in the basket"));
    navigate("/checkout");
  }

  return (
    <>
      <TopBar />
      <div className="mx-auto w-full max-w-2xl flex-1 px-4 py-5 pb-24 sm:px-6">
        <div className="mb-5 flex items-center gap-3">
          <Link to="/" className="flex h-11 items-center gap-2 rounded-xl border border-line bg-surface px-3.5 text-sm font-semibold hover:bg-subtle">
            <ArrowLeft className="size-4" /> {t("Home")}
          </Link>
          <h1 className="text-2xl font-bold">{t("My orders")}</h1>
        </div>

        {recent.length === 0 ? (
          <div className="flex flex-col items-center gap-2 rounded-3xl border border-dashed border-line py-16 text-center">
            <span className="text-6xl">🧾</span>
            <p className="text-lg font-bold">{t("No orders yet")}</p>
            <p className="text-sm text-muted">{t("Orders you place on this phone will show here.")}</p>
            <Link to="/" className="mt-3 rounded-xl bg-brand px-5 py-3 font-semibold text-white">{t("Browse hotels")}</Link>
          </div>
        ) : (
          <>
            {/* Totals */}
            <div className="mb-4 grid grid-cols-3 gap-2.5">
              {[
                [t("Orders"), String(rows.length)],
                [t("Completed"), String(completed.length)],
                [t("Total paid"), money(spent)],
              ].map(([label, value]) => (
                <div key={label} className="rounded-2xl bg-surface p-3.5 text-center shadow-sm">
                  <p className="money text-lg font-extrabold sm:text-xl">{value}</p>
                  <p className="text-xs font-medium text-muted sm:text-sm">{label}</p>
                </div>
              ))}
            </div>
            {saved ? <p className="mb-4 rounded-xl bg-ok-soft px-4 py-2.5 text-sm font-semibold text-ok">🎁 {t("You've saved {amount} with Chakula rewards", { amount: money(saved) })}</p> : null}

            {/* Filters */}
            <div className="mb-4 flex flex-col gap-2.5">
              <div className="flex gap-1 rounded-xl bg-subtle p-1" role="radiogroup" aria-label={t("Status")}>
                {FILTERS.map((f) => (
                  <button key={f.id} role="radio" aria-checked={filter === f.id} onClick={() => setFilter(f.id)} className={clsx("h-10 min-w-0 flex-1 rounded-lg px-1.5 text-[0.8125rem] font-semibold whitespace-nowrap sm:px-3 sm:text-sm", filter === f.id ? "bg-surface shadow-sm" : "text-muted")}>
                    {t(f.label)}
                  </button>
                ))}
              </div>
              <div className="grid grid-cols-2 gap-2">
                <select aria-label={t("Hotel")} value={hotel} onChange={(e) => setHotel(e.target.value)} className="h-11 min-w-0 rounded-xl border border-line bg-surface px-3 text-sm font-medium">
                  <option value="">{t("All hotels")}</option>
                  {hotels.map(([slug, name]) => <option key={slug} value={slug}>{name}</option>)}
                </select>
                <select aria-label={t("Period")} value={days} onChange={(e) => setDays(Number(e.target.value))} className="h-11 min-w-0 rounded-xl border border-line bg-surface px-3 text-sm font-medium">
                  {PERIODS.map((p) => <option key={p.id} value={p.id}>{t(p.label)}</option>)}
                </select>
              </div>
              <label className="flex h-11 items-center gap-2 rounded-xl border border-line bg-surface px-3 focus-within:border-brand">
                <Search className="size-4 text-muted" />
                <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("Search a dish, hotel or order number")} className="w-full min-w-0 bg-transparent text-sm outline-none" />
              </label>
            </div>

            {history.isLoading ? (
              <div className="flex flex-col gap-3">{[0, 1, 2].map((i) => <div key={i} className="h-24 animate-pulse rounded-2xl bg-subtle" />)}</div>
            ) : shown.length === 0 ? (
              <p className="rounded-2xl border border-dashed border-line py-10 text-center text-sm text-muted">{t("No orders match these filters.")}</p>
            ) : (
              <ul className="flex flex-col gap-3">
                {shown.map((r) => {
                  const s = STATUS[r.status];
                  return (
                    <li key={r.token} className="rounded-2xl border border-line bg-surface p-2 transition-shadow hover:shadow-md">
                      <Link to={`/o/${r.token}`} className="flex min-w-0 items-start gap-3.5 rounded-xl p-2">
                        <span className="flex size-12 shrink-0 items-center justify-center rounded-xl bg-brand-soft text-2xl">{r.type === "pickup" ? "🏪" : r.type === "eat_in" ? "🍽️" : "🛵"}</span>
                        <span className="min-w-0 flex-1">
                          <span className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
                            <span className="font-bold">{r.hotel_name}</span>
                            {s ? (
                              <span className={clsx("shrink-0 rounded-full px-2.5 py-0.5 text-xs font-semibold", s.tone === "brand" && "bg-brand-soft text-brand", s.tone === "ok" && "bg-ok-soft text-ok", s.tone === "muted" && "bg-subtle text-muted", s.tone === "bad" && "bg-bad-soft text-bad")}>
                                {t(s.label)}
                              </span>
                            ) : null}
                          </span>
                          <span className="mt-0.5 block truncate text-sm">{r.items.join(", ")}</span>
                          <span className="mt-1 block text-xs text-muted">#{r.code} · {when.format(new Date(r.created_at))}</span>
                          <span className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
                            <span className="money font-bold">{r.paid ? `${t("Paid")} ${money(r.paid)}` : money(r.till_amount)}</span>
                            {r.paid ? <span className="text-xs text-muted">{r.payment_method === "cash" ? t("Cash") : "M-Pesa"}</span> : null}
                            {r.refunded ? <span className="money text-xs font-semibold text-ok">{t("Refunded")} {money(r.refunded)}</span> : null}
                            {r.platform_bonus && !ENDED.includes(r.status) ? <span className="money text-xs font-semibold text-ok">🎁 −{money(r.platform_bonus)}</span> : null}
                          </span>
                        </span>
                        <ChevronRight className="mt-3 size-5 shrink-0 text-muted" />
                      </Link>
                      {DONE.includes(r.status) || ENDED.includes(r.status) ? (
                        <button onClick={() => void again(r)} className="mt-1 flex h-10 w-full items-center justify-center gap-2 rounded-xl bg-brand-soft text-sm font-semibold text-brand hover:bg-brand-tint">
                          <RotateCcw className="size-4" /> {t("Order again")}
                        </button>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            )}
            <p className="mt-4 text-center text-xs text-muted">{t("Your history is kept on this phone. Clearing the browser removes it from here.")}</p>
          </>
        )}
        <div className="mt-6">
          <HelpButton number={config.data?.support_whatsapp} message="Hello Chakula, I need help with one of my orders." />
        </div>
      </div>
    </>
  );
}

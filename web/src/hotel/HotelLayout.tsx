/** Hotel staff shell in the D.CC reference style: store card, sidebar nav, user card. */
import clsx from "clsx";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, BadgePercent, ClipboardList, KeyRound, LayoutDashboard, LogOut, Megaphone, Receipt, Settings, UtensilsCrossed, Wallet } from "lucide-react";
import { Link, NavLink, Navigate, Outlet, useLocation } from "react-router-dom";

import { Button, Switch } from "../components/ui";
import { NotificationBell } from "../components/NotificationBell";
import { ThemeToggle } from "../customer/CustomerLayout";
import { AlarmBanner } from "../components/AlarmBanner";
import { useAlarm } from "../lib/alarm";
import { api, auth } from "../lib/api";
import { useLive } from "../lib/live";
import { money } from "../lib/format";
import type { HotelBilling } from "./BillingPage";
import { keys, useHotelSettings, useMe, useSave } from "./hooks";

const MAIN = [
  { to: "dashboard", label: "Dashboard", icon: LayoutDashboard },
  { to: "orders", label: "Orders", icon: ClipboardList },
  { to: "payments", label: "Payments", icon: Wallet },
  { to: "menu", label: "Menu", icon: UtensilsCrossed },
  { to: "discounts", label: "Discounts", icon: BadgePercent },
  { to: "offers", label: "Offers", icon: Megaphone },
];
/** Shorter labels so seven tabs fit a 360 px phone. */
const TAB_LABEL: Record<string, string> = { dashboard: "Home", payments: "Pay", discounts: "Deals", billing: "Bill" };

/** The bill to the platform is for hotel admins only (cashiers never see it). */
const BILLING = { to: "billing", label: "Chakula bill", icon: Receipt };
const OTHER = [{ to: "settings", label: "Settings", icon: Settings }];
const TITLES: Record<string, string> = { billing: "Chakula bill", orders: "Orders", dashboard: "Dashboard", payments: "Payments", menu: "Menu", discounts: "Discounts & promos", offers: "Offers", settings: "Settings" };

function initials(name: string) {
  return name.split(/\s+/).map((p) => p[0]).slice(0, 2).join("").toUpperCase();
}

function AcceptingToggle() {
  const { data } = useHotelSettings();
  const save = useSave((accepting_orders: boolean) => api.put("/hotel/settings", { accepting_orders }), [keys.settings]);
  if (!data) return null;
  const on = save.isPending ? !!save.variables : data.accepting_orders;
  return (
    <label className={clsx("flex h-11 items-center gap-3 rounded-xl border px-3.5 text-sm font-semibold", on ? "border-ok/30 bg-ok-soft text-ok" : "border-bad/30 bg-bad-soft text-bad")}>
      <span className={clsx("size-2 rounded-full", on ? "animate-pulse bg-ok" : "bg-bad")} />
      <span className="hidden sm:inline">{on ? "Accepting orders" : "Not accepting"}</span>
      <Switch label="Accepting orders" checked={on} onChange={(v) => save.mutate(v)} disabled={save.isPending} />
    </label>
  );
}

/** Orders waiting for the cashier plus open payment problems: shown as a badge. */
function usePaymentsCount() {
  const pending = useQuery({ queryKey: ["hotel", "payments", "pending"], queryFn: () => api.get<{ customer_trans_code: string | null }[]>("/hotel/payments/pending"), refetchInterval: 15_000 });
  const review = useQuery({ queryKey: ["hotel", "payments", "review"], queryFn: () => api.get<unknown[]>("/hotel/review-items"), refetchInterval: 15_000 });
  return (pending.data?.length ?? 0) + (review.data?.length ?? 0);
}

/** Payments the cashier must act on: a code the customer sent, or a problem to resolve. */
function usePaymentsToAct() {
  const pending = useQuery({ queryKey: ["hotel", "payments", "pending"], queryFn: () => api.get<{ customer_trans_code: string | null }[]>("/hotel/payments/pending"), refetchInterval: 15_000 });
  const review = useQuery({ queryKey: ["hotel", "payments", "review"], queryFn: () => api.get<unknown[]>("/hotel/review-items"), refetchInterval: 15_000 });
  const refunds = useQuery({ queryKey: ["hotel", "payments", "refunds"], queryFn: () => api.get<unknown[]>("/hotel/refunds"), refetchInterval: 30_000 });
  return (pending.data ?? []).filter((p) => p.customer_trans_code).length + (review.data?.length ?? 0) + (refunds.data?.length ?? 0);
}

/** Every hotel page: live updates, and alarms that ring until the action is done. */
function HotelAlarms() {
  const qc = useQueryClient();
  useLive("/hotel/events", (e) => {
    if (e.type === "order" || e.type === "reconnected" || e.type === "review" || e.type === "refund") {
      void qc.invalidateQueries({ queryKey: ["hotel", "orders"] });
      void qc.invalidateQueries({ queryKey: ["hotel", "payments"] });
    }
    if (e.type === "hotel") void qc.invalidateQueries({ queryKey: ["hotel", "settings"] });
    if (e.type === "hotel" || e.type === "statement" || e.type === "settlement") void qc.invalidateQueries({ queryKey: ["hotel", "billing"] });
    if (e.type === "forwarder") void qc.invalidateQueries({ queryKey: ["hotel", "forwarder"] });
  }, { staff: true });
  useAlarm("hotel-orders", useNewOrdersCount(), "order", "New order: accept or reject");
  useAlarm("hotel-payments", usePaymentsToAct(), "payment", "Payment to confirm or refund to send");
  return null;
}

/** Hotel admins: a strip on every page while a statement is due, so it is never missed. */
function BillStrip() {
  const q = useQuery({ queryKey: ["hotel", "billing"], queryFn: () => api.get<HotelBilling>("/hotel/billing"), refetchInterval: 5 * 60_000 });
  const { pathname } = useLocation();
  const b = q.data;
  if (!b || !b.due_now || pathname.endsWith("/billing")) return null;
  const urgent = b.overdue || b.paused_for_billing;
  return (
    <Link to="billing" className={clsx("flex items-center gap-3 rounded-2xl px-4 py-3 text-sm font-semibold", urgent ? "bg-bad text-white" : "bg-warn-soft text-warn")}>
      <AlertTriangle className="size-5 shrink-0" />
      <span className="flex-1">
        {b.paused_for_billing ? "Shop paused: " : b.overdue ? "Overdue: " : ""}
        {money(b.due_now)} to pay Chakula{b.due_date && !b.overdue ? ` by ${new Intl.DateTimeFormat("en-KE", { weekday: "long", timeZone: "UTC" }).format(new Date(`${b.due_date}T00:00:00Z`))}` : ""}
      </span>
      <span className="underline">Pay now</span>
    </Link>
  );
}

/** New orders waiting for Accept. */
function useNewOrdersCount() {
  const q = useQuery({ queryKey: ["hotel", "orders", "active"], queryFn: () => api.get<{ status: string }[]>("/hotel/orders"), refetchInterval: 15_000 });
  return (q.data ?? []).filter((o) => o.status === "paid" || o.status === "awaiting_payment").length;
}

function NavItem({ to, label, icon: Icon }: { to: string; label: string; icon: typeof Settings }) {
  const count = usePaymentsCount();
  const fresh = useNewOrdersCount();
  const badge = to === "payments" ? count : to === "orders" ? fresh : 0;
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        clsx(
          "flex h-12 items-center gap-3 rounded-xl px-3.5 text-[0.9375rem] font-medium transition-colors",
          isActive ? "bg-gradient-to-r from-brand to-brand-accent text-white shadow-lg shadow-brand/25" : "text-muted hover:bg-subtle hover:text-ink",
        )
      }
    >
      <Icon className="size-5" /> {label}
      {badge ? <span className="ml-auto flex h-6 min-w-6 items-center justify-center rounded-full bg-bad px-1.5 text-xs font-bold text-white">{badge}</span> : null}
    </NavLink>
  );
}

export function HotelLayout() {
  const me = useMe();
  const { data: settings } = useHotelSettings();
  const { pathname } = useLocation();
  const section = pathname.split("/")[2] ?? "orders";
  const isAdmin = me?.role === "hotel_admin";
  const other = isAdmin ? [BILLING, ...OTHER] : OTHER;
  const tabs = [...MAIN, ...other];

  if (!me) return <Navigate to="/login" replace />;
  if (me.must_change_password) return <Navigate to="/password" replace />;
  if (me.role === "super_admin") return <Navigate to="/admin" replace />;
  if (me.role !== "hotel_admin" && me.role !== "cashier") {
    return (
      <main className="flex min-h-dvh flex-col items-center justify-center gap-4 p-6 text-center">
        <p className="font-semibold">This area is for hotel staff.</p>
        <Button variant="secondary" onClick={() => auth.logout()}>Log out</Button>
      </main>
    );
  }

  return (
    <div className="min-h-dvh bg-page md:p-5">
      <HotelAlarms />
      <div className="sticky top-0 z-40 -mx-0 md:-mx-5 md:-mt-5 md:mb-5"><AlarmBanner /></div>
      <div className="mx-auto flex min-h-dvh max-w-[90rem] gap-5 md:min-h-[calc(100dvh-2.5rem)]">
        {/* Sidebar */}
        <aside className="sticky top-5 hidden h-[calc(100dvh-2.5rem)] w-64 shrink-0 flex-col overflow-y-auto rounded-[1.75rem] bg-surface p-4 shadow-sm md:flex">
          <div className="flex items-center gap-2.5 px-1 pb-5">
            <span className="flex size-10 items-center justify-center rounded-xl bg-brand text-white shadow-md shadow-brand/30"><UtensilsCrossed className="size-5" /></span>
            <span className="text-xl font-extrabold tracking-tight">Chakula</span>
          </div>

          <p className="px-1 pb-1.5 text-xs font-medium text-muted">Store</p>
          <div className="mb-5 flex items-center gap-2.5 rounded-xl border border-line p-2">
            <span className="size-9 shrink-0 overflow-hidden rounded-lg bg-brand-soft">
              {settings?.cover_url ? <img src={settings.cover_url} alt="" className="size-full object-cover" /> : <span className="flex size-full items-center justify-center text-lg">🏪</span>}
            </span>
            <span className="min-w-0">
              <span className="block truncate text-sm font-semibold">{settings?.name ?? "…"}</span>
              <span className={clsx("block text-xs font-medium", settings?.status === "paused" ? "text-bad" : "text-ok")}>{settings?.status === "paused" ? "Paused by platform" : "Active"}</span>
            </span>
          </div>

          <p className="px-1 pb-1.5 text-xs font-medium text-muted">Menu</p>
          <nav className="flex flex-col gap-1">{MAIN.map((n) => <NavItem key={n.to} {...n} />)}</nav>
          <div className="my-4 border-t border-line" />
          <p className="px-1 pb-1.5 text-xs font-medium text-muted">Others</p>
          <nav className="flex flex-col gap-1">{other.map((n) => <NavItem key={n.to} {...n} />)}</nav>

          <div className="mt-auto flex items-center gap-3 rounded-2xl border border-line p-3">
            <span className="relative flex size-10 shrink-0 items-center justify-center rounded-full bg-brand-soft font-bold text-brand">
              {initials(me.name)}
              <span className="absolute right-0 bottom-0 size-2.5 rounded-full border-2 border-white bg-ok" />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-semibold">{me.name}</span>
              <span className="block text-xs text-muted">{me.role === "hotel_admin" ? "Admin" : "Cashier"}</span>
            </span>
            <Link to="/password" aria-label="Change password" title="Change password" className="flex size-9 items-center justify-center rounded-lg text-muted hover:bg-subtle hover:text-ink">
              <KeyRound className="size-4" />
            </Link>
            <button onClick={() => auth.logout()} aria-label="Log out" title="Log out" className="flex size-9 items-center justify-center rounded-lg text-muted hover:bg-subtle hover:text-ink">
              <LogOut className="size-4" />
            </button>
          </div>
        </aside>

        {/* Main */}
        <div className="flex min-w-0 flex-1 flex-col gap-5">
          <header className="sticky top-0 z-30 flex items-center justify-between gap-3 bg-surface px-4 py-3.5 shadow-sm md:static md:rounded-[1.75rem] md:px-6 md:py-4">
            <div className="min-w-0">
              <h1 className="truncate text-xl font-bold md:text-2xl">{TITLES[section] ?? "Hotel"}</h1>
              <p className="truncate text-sm text-muted">{section === "dashboard" ? `Welcome back, ${me.name.split(" ")[0]}` : settings?.name}</p>
            </div>
            <div className="flex items-center gap-2">
              <NotificationBell links={{ "hotel-orders": "/hotel/orders", "hotel-payments": "/hotel/payments" }} />
              <ThemeToggle />
              <AcceptingToggle />
            </div>
          </header>
          <main className="min-w-0 flex-1 px-4 pb-24 md:px-0 md:pb-0">
            {isAdmin && settings && settings.lat == null && section !== "settings" ? (
              <Link to="/hotel/settings" className="mb-5 flex items-center gap-2 rounded-2xl bg-warn-soft px-4 py-3 text-sm font-semibold text-warn">
                <AlertTriangle className="size-4 shrink-0" /> Pin your hotel on the map so customers can order delivery. Tap to set it now.
              </Link>
            ) : null}
            {isAdmin ? <div className="mb-5 empty:hidden"><BillStrip /></div> : null}
            <Outlet />
          </main>
        </div>
      </div>

      {/* Phones: bottom navigation */}
      <nav className="fixed inset-x-0 bottom-0 z-30 grid border-t border-line bg-surface pb-[env(safe-area-inset-bottom)] md:hidden" style={{ gridTemplateColumns: `repeat(${tabs.length}, minmax(0, 1fr))` }}>
        {tabs.map(({ to, label, icon: Icon }) => (
          <NavLink key={to} to={to} className={({ isActive }) => clsx("relative flex h-16 min-w-0 flex-col items-center justify-center gap-1 text-[0.6875rem] font-semibold", isActive ? "text-brand" : "text-muted")}>
            <Icon className="size-5" />
            <span className="max-w-full truncate px-0.5">{TAB_LABEL[to] ?? label}</span>
          </NavLink>
        ))}
      </nav>
    </div>
  );
}

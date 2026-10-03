import clsx from "clsx";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Bike, FlaskConical, LayoutDashboard, LogOut, MapPinned, Percent, ShieldAlert, Users, UtensilsCrossed, Wallet } from "lucide-react";
import { useSyncExternalStore } from "react";
import { NavLink, Navigate, Outlet } from "react-router-dom";

import { ThemeToggle } from "../customer/CustomerLayout";
import { AlarmBanner } from "../components/AlarmBanner";
import { useAlarm } from "../lib/alarm";
import { api, auth } from "../lib/api";
import { useLive } from "../lib/live";

const NAV = [
  { to: "dashboard", label: "Dashboard", icon: LayoutDashboard },
  { to: "review", label: "Needs attention", icon: ShieldAlert },
  { to: "dispatch", label: "Dispatch", icon: Bike },
  { to: "billing", label: "Billing", icon: Wallet },
  { to: "riders", label: "Riders", icon: Users },
  { to: "fees", label: "Fees & bonuses", icon: Percent },
  { to: "delivery", label: "Delivery", icon: MapPinned },
  { to: "tools", label: "Tools", icon: FlaskConical },
];

/** Late hotel payment items + items with no hotel + orders not accepted in time. */
function useAttentionCount() {
  const items = useQuery({ queryKey: ["admin", "reviews", "count"], queryFn: () => api.get<{ open: number }>("/admin/review-items/count"), refetchInterval: 30_000 });
  const alerts = useQuery({ queryKey: ["admin", "alerts"], queryFn: () => api.get<{ unaccepted: unknown[] }>("/admin/alerts"), refetchInterval: 15_000 });
  return (items.data?.open ?? 0) + (alerts.data?.unaccepted.length ?? 0);
}

/** Ring until done (D22): orders not accepted, deliveries without a rider for 5+ minutes, and
 * items only the admin can resolve. Stale hotel items show a badge but don't ring: the hotel
 * resolves those; the admin can only call. */
function AdminAlarms() {
  const qc = useQueryClient();
  useLive("/admin/events", (e) => {
    void qc.invalidateQueries({ queryKey: ["admin", "alerts"] });
    void qc.invalidateQueries({ queryKey: ["admin", "reviews"] });
    void qc.invalidateQueries({ queryKey: ["admin", "dispatch"] });
    if (["settlement", "statement", "payout", "hotel", "reconnected"].includes(e.type)) void qc.invalidateQueries({ queryKey: ["admin", "billing"] });
    if (e.type === "forwarder") void qc.invalidateQueries({ queryKey: ["admin", "forwarder"] });
  }, { staff: true });
  const alerts = useQuery({ queryKey: ["admin", "alerts"], queryFn: () => api.get<{ unaccepted: unknown[] }>("/admin/alerts"), refetchInterval: 15_000 });
  const reviews = useQuery({ queryKey: ["admin", "reviews"], queryFn: () => api.get<{ hotel_name: string | null; type: string }[]>("/admin/review-items"), refetchInterval: 15_000 });
  const board = useQuery({ queryKey: ["admin", "dispatch"], queryFn: () => api.get<{ orders: { status: string; rider_id: string | null; ready_at: string | null; picked_up_at: string | null }[] }>("/admin/dispatch"), refetchInterval: 20_000 });
  const mine = (reviews.data ?? []).filter((r) => !r.hotel_name || ["failed_delivery", "fee_dispute"].includes(r.type)).length;
  const noRider = (board.data?.orders ?? []).filter((o) => o.status === "ready" && !o.rider_id && o.ready_at && Date.now() - new Date(o.ready_at).getTime() >= 5 * 60_000).length;
  useAlarm("admin-unaccepted", alerts.data?.unaccepted.length ?? 0, "duty", "Order not accepted");
  useAlarm("admin-no-rider", noRider, "duty", "Delivery has no rider");
  const tooLong = (board.data?.orders ?? []).filter((o) => ["picked_up", "on_the_way"].includes(o.status) && o.picked_up_at && Date.now() - new Date(o.picked_up_at).getTime() >= 45 * 60_000).length;
  useAlarm("admin-long-delivery", tooLong, "duty", "Delivery taking too long");
  useAlarm("admin-review", mine, "payment", "Needs your decision");
  useAlarm("admin-settlements", usePendingSettlements(), "payment", "Hotel payment to confirm");
  return null;
}

/** Hotel payments to the platform waiting for the admin to check their M-Pesa (M7). */
function usePendingSettlements() {
  const q = useQuery({ queryKey: ["admin", "billing", "pending"], queryFn: () => api.get<{ pending: number }>("/admin/billing/pending/count"), refetchInterval: 30_000 });
  return q.data?.pending ?? 0;
}

/** Rider applications waiting for review. */
function usePendingRiders() {
  const q = useQuery({ queryKey: ["admin", "riders"], queryFn: () => api.get<{ kyc_status: string }[]>("/admin/riders?status=all"), refetchInterval: 60_000 });
  return (q.data ?? []).filter((r) => r.kyc_status === "pending").length;
}

function CountBadge({ n }: { n: number }) {
  return n ? <span className="ml-auto flex h-5 min-w-5 items-center justify-center rounded-full bg-bad px-1.5 text-xs font-bold text-white">{n}</span> : null;
}

/** Super-admin shell (Epic Eats-style sidebar). */
export function AdminLayout() {
  const me = useSyncExternalStore(auth.subscribe, auth.user);
  const attention = useAttentionCount();
  const pendingRiders = usePendingRiders();
  const pendingSettlements = usePendingSettlements();
  if (!me) return <Navigate to="/login" replace />;
  if (me.role !== "super_admin") return <Navigate to="/hotel" replace />;

  return (
    <div className="min-h-dvh bg-page md:p-5">
      <AdminAlarms />
      <div className="sticky top-0 z-40 md:-mx-5 md:-mt-5 md:mb-5"><AlarmBanner /></div>
      <div className="mx-auto flex min-h-dvh max-w-[90rem] overflow-clip bg-surface md:min-h-[calc(100dvh-2.5rem)] md:rounded-[1.75rem] md:shadow-sm">
        <aside className="hidden w-64 shrink-0 flex-col border-r border-line md:flex">
          <div className="flex items-center gap-2.5 px-5 py-5">
            <span className="flex size-10 items-center justify-center rounded-xl border border-line text-brand shadow-sm"><UtensilsCrossed className="size-5" /></span>
            <span>
              <span className="block text-xl font-extrabold tracking-tight text-brand">Chakula</span>
              <span className="block text-xs font-medium text-muted">Super admin</span>
            </span>
          </div>
          <p className="px-5 pt-2 pb-2 text-xs font-semibold tracking-wider text-muted uppercase">Menu</p>
          <nav className="flex flex-col gap-1 px-3">
            {NAV.map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                className={({ isActive }) =>
                  clsx("flex h-11 items-center gap-3 rounded-xl px-3 text-sm font-semibold", isActive ? "bg-brand text-white shadow-md shadow-brand/25" : "text-ink hover:bg-subtle")
                }
              >
                <Icon className="size-5" /> {label}
                {to === "review" ? <CountBadge n={attention} /> : to === "riders" ? <CountBadge n={pendingRiders} /> : to === "billing" ? <CountBadge n={pendingSettlements} /> : null}
              </NavLink>
            ))}
          </nav>
          <div className="mt-auto border-t border-line p-4">
            <p className="truncate text-sm font-semibold">{me.name}</p>
            <button onClick={() => auth.logout()} className="mt-2 flex h-9 w-full items-center gap-2 rounded-lg px-2 text-sm text-muted hover:bg-subtle hover:text-ink">
              <LogOut className="size-4" /> Log out
            </button>
          </div>
        </aside>
        <main className="min-w-0 flex-1">
          {/* Top bar: theme on every screen size; nav + log out on phones (sidebar hidden). */}
          <div className="flex items-center justify-between gap-2 border-b border-line px-4 py-3 sm:px-6">
            <nav className="-mx-1 flex min-w-0 items-center gap-1 overflow-x-auto px-1 md:hidden">
              {NAV.map(({ to, label, icon: Icon }) => (
                <NavLink key={to} to={to} aria-label={label} className={({ isActive }) => clsx("relative flex h-10 shrink-0 items-center gap-2 rounded-xl px-3 text-sm font-semibold", isActive ? "bg-brand text-white" : "text-muted")}>
                  {({ isActive }) => (
                    <>
                      <Icon className="size-4" /> {isActive ? label : null}
                      {(to === "review" && attention) || (to === "billing" && pendingSettlements) ? <span className="absolute -top-0.5 -right-0.5 size-2.5 rounded-full bg-bad ring-2 ring-surface" /> : null}
                    </>
                  )}
                </NavLink>
              ))}
            </nav>
            <span className="hidden text-sm font-medium text-muted md:block">Signed in as {me.name}</span>
            <div className="flex items-center gap-2">
              <ThemeToggle />
              <button onClick={() => auth.logout()} aria-label="Log out" className="flex size-10 items-center justify-center rounded-xl border border-line text-muted hover:bg-subtle md:hidden">
                <LogOut className="size-4" />
              </button>
            </div>
          </div>
          <Outlet />
        </main>
      </div>
    </div>
  );
}

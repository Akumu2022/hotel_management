/** Hotel home in the D.CC dashboard style: sales reports (hotel admin), menu health, today. */
import clsx from "clsx";
import {
  ArrowUpRight,
  BadgePercent,
  Clock,
  ImageOff,
  Megaphone,
  Settings,
  UtensilsCrossed,
} from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { Reports } from "../components/Reports";
import { Skeleton } from "../components/ui";
import { WEEKDAYS, hhmm } from "../lib/format";
import {
  useDiscounts,
  useHotelSettings,
  useIsAdmin,
  useOffers,
  useProducts,
} from "./hooks";

function Stat({
  icon,
  label,
  value,
  total,
  pct,
  tone,
  to,
}: {
  icon: ReactNode;
  label: string;
  value: ReactNode;
  total?: string;
  pct: number;
  tone: "brand" | "ok" | "warn";
  to: string;
}) {
  const bar = { brand: "#dc4b12", ok: "#16a34a", warn: "#f59e0b" }[tone];
  return (
    <Link
      to={to}
      className="group flex flex-col gap-3 rounded-[1.5rem] bg-surface p-5 shadow-sm transition-shadow hover:shadow-md"
    >
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-2 text-sm font-medium text-muted">
          <span
            className="flex size-8 items-center justify-center rounded-lg"
            style={{ background: `${bar}1a`, color: bar }}
          >
            {icon}
          </span>
          {label}
        </span>
        <span className="text-3xl font-bold">{value}</span>
      </div>
      <div className="flex items-center justify-between text-xs text-muted">
        <span>{total}</span>
        <span className="font-semibold text-ink">{pct}%</span>
      </div>
      {/* Striped progress bar, as in the reference dashboard */}
      <div className="h-9 overflow-hidden rounded-xl bg-subtle">
        <div
          className="h-full rounded-xl transition-all duration-700"
          style={{
            width: `${Math.max(pct, 3)}%`,
            background: `repeating-linear-gradient(135deg, ${bar} 0 10px, ${bar}cc 10px 20px)`,
          }}
        />
      </div>
    </Link>
  );
}

function QuickLink({
  to,
  icon,
  title,
  body,
}: {
  to: string;
  icon: ReactNode;
  title: string;
  body: string;
}) {
  return (
    <Link
      to={to}
      className="group flex items-start gap-3 rounded-2xl border border-line p-4 transition-colors hover:border-brand/40 hover:bg-brand-soft/40"
    >
      <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-subtle text-ink group-hover:bg-brand group-hover:text-white">
        {icon}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block font-semibold">{title}</span>
        <span className="block text-sm text-muted">{body}</span>
      </span>
      <ArrowUpRight className="size-4 text-muted group-hover:text-brand" />
    </Link>
  );
}

export function DashboardPage() {
  const products = useProducts();
  const discounts = useDiscounts();
  const offers = useOffers();
  const { data: settings } = useHotelSettings();
  const isAdmin = useIsAdmin();

  if (products.isLoading || !settings) {
    return (
      <div className="grid gap-5 sm:grid-cols-3">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-40 rounded-[1.5rem]" />
        ))}
      </div>
    );
  }

  const list = products.data ?? [];
  const available = list.filter((p) => !p.is_sold_out).length;
  const soldOut = list.length - available;
  const withPhoto = list.filter((p) => p.image_url).length;
  const now = Date.now();
  const liveDeals = (discounts.data ?? []).filter(
    (d) =>
      d.is_active &&
      new Date(d.starts_at).getTime() <= now &&
      (!d.ends_at || new Date(d.ends_at).getTime() > now),
  ).length;
  const liveOffers = (offers.data ?? []).filter(
    (o) =>
      new Date(o.starts_at).getTime() <= now &&
      (!o.ends_at || new Date(o.ends_at).getTime() > now),
  ).length;
  const weekday = (new Date().getDay() + 6) % 7; // Monday = 0
  const today = settings.hours.find((h) => h.weekday === weekday);
  const noPhoto = list.filter((p) => !p.image_url);
  const pct = (a: number, b: number) => (b ? Math.round((a / b) * 100) : 0);

  return (
    <div className="flex flex-col gap-5">
      <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">
        <Stat
          icon={<UtensilsCrossed className="size-4" />}
          label="Available dishes"
          value={available}
          total={`of ${list.length} on the menu`}
          pct={pct(available, list.length)}
          tone="ok"
          to="/hotel/menu"
        />
        <Stat
          icon={<ImageOff className="size-4" />}
          label="Dishes with photos"
          value={withPhoto}
          total={`${list.length - withPhoto} still need one`}
          pct={pct(withPhoto, list.length)}
          tone="brand"
          to="/hotel/menu"
        />
        <Stat
          icon={<BadgePercent className="size-4" />}
          label="Live deals"
          value={liveDeals + liveOffers}
          total={`${liveDeals} discounts · ${liveOffers} banners`}
          pct={Math.min(100, (liveDeals + liveOffers) * 25)}
          tone="warn"
          to="/hotel/discounts"
        />
      </div>

      {isAdmin ? <Reports scope="hotel" /> : null}

      <div className="grid items-start gap-5 lg:grid-cols-2">
        <section className="rounded-[1.5rem] bg-surface p-5 shadow-sm">
          <h2 className="mb-3 flex items-center gap-2 text-lg font-bold">
            <Clock className="size-5 text-brand" /> Today
          </h2>
          <p className="text-sm text-muted">{WEEKDAYS[weekday]}</p>
          <p className="mt-1 text-2xl font-bold">
            {today
              ? `${hhmm(today.opens_at)} – ${hhmm(today.closes_at)}`
              : "Closed today"}
          </p>
          <p className="mt-2 text-sm">
            {settings.accepting_orders ? (
              <span className="font-medium text-ok">Taking orders</span>
            ) : (
              <span className="font-medium text-bad">Orders switched off</span>
            )}
            {soldOut ? (
              <span className="text-muted"> · {soldOut} sold out</span>
            ) : null}
          </p>
        </section>

        <section className="rounded-[1.5rem] bg-surface p-5 shadow-sm">
          <h2 className="mb-3 text-lg font-bold">Quick actions</h2>
          <div className="flex flex-col gap-2">
            <QuickLink
              to="/hotel/menu"
              icon={<UtensilsCrossed className="size-5" />}
              title="Menu"
              body="Add dishes, photos and sold-out"
            />
            <QuickLink
              to="/hotel/offers"
              icon={<Megaphone className="size-5" />}
              title="Offers"
              body="Banners on the customer home screen"
            />
            <QuickLink
              to="/hotel/settings"
              icon={<Settings className="size-5" />}
              title="Settings"
              body="Hours, location, cash pickup"
            />
          </div>
        </section>
      </div>

      {noPhoto.length ? (
        <section className={clsx("rounded-[1.5rem] bg-surface p-5 shadow-sm")}>
          <h2 className="text-lg font-bold">Dishes without a photo</h2>
          <p className="mb-3 text-sm text-muted">
            Photos sell food. Dishes with a good photo get ordered more.
          </p>
          <div className="flex flex-wrap gap-2">
            {noPhoto.map((p) => (
              <Link
                key={p.id}
                to="/hotel/menu"
                className="rounded-full border border-line px-3 py-1.5 text-sm font-medium hover:border-brand hover:text-brand"
              >
                {p.name}
              </Link>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}

/** The rider's own profile: who they are, their bike, how they are doing and what they are owed. */
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowLeft, Bike, Star } from "lucide-react";
import { Link } from "react-router-dom";

import { HelpButton } from "../customer/bits";
import { useConfig } from "../customer/OrderPanel";
import { api } from "../lib/api";
import { money } from "../lib/format";
import type { RiderMe } from "./RiderHome";

type HistoryJob = { id: string; status: string; rider_fee: number; closed_at: string | null };
type Earnings = { owed: number; payouts: { id: string; amount: number; mpesa_code: string; paid_at: string }[] };

const STATUS: Record<RiderMe["kyc_status"], { text: string; tone: string }> = {
  draft: { text: "Application not sent", tone: "bg-subtle text-muted" },
  pending: { text: "Being checked", tone: "bg-warn-soft text-warn" },
  approved: { text: "Approved", tone: "bg-ok-soft text-ok" },
  rejected: { text: "Needs fixing", tone: "bg-bad-soft text-bad" },
  suspended: { text: "Paused", tone: "bg-bad-soft text-bad" },
};

const day = new Intl.DateTimeFormat("en-KE", { day: "numeric", month: "short", year: "numeric", timeZone: "Africa/Nairobi" });
const paidOn = new Intl.DateTimeFormat("en-KE", { weekday: "short", day: "numeric", month: "short", timeZone: "Africa/Nairobi" });
const dayKey = (d: Date) => d.toLocaleDateString("en-CA", { timeZone: "Africa/Nairobi" });

/** 0712 345 678 style from +2547… / 2547… */
function localPhone(p: string | null | undefined) {
  if (!p) return "";
  const d = p.replace(/\D/g, "");
  return d.startsWith("254") ? `0${d.slice(3)}` : p;
}

function Row({ k, v }: { k: string; v: string | null | undefined }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2.5">
      <dt className="text-sm text-muted">{k}</dt>
      <dd className="text-right text-sm font-medium">{v || "Not added"}</dd>
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-2xl bg-surface p-4 shadow-sm">
      <p className="text-xs text-muted">{label}</p>
      <p className={clsx("money mt-0.5 text-xl font-extrabold", tone)}>{value}</p>
    </div>
  );
}

export function ProfileView({ me }: { me: RiderMe }) {
  const config = useConfig();
  const approved = me.kyc_status === "approved";
  const history = useQuery({ queryKey: ["rider", "history"], queryFn: () => api.get<HistoryJob[]>("/rider/jobs/history"), enabled: approved });
  const earnings = useQuery({ queryKey: ["rider", "earnings"], queryFn: () => api.get<Earnings>("/rider/earnings"), enabled: approved });

  const done = (history.data ?? []).filter((j) => j.status === "delivered");
  const today = dayKey(new Date());
  const earnedToday = done.filter((j) => j.closed_at && dayKey(new Date(j.closed_at)) === today).reduce((n, j) => n + j.rider_fee, 0);
  const failed = (history.data ?? []).filter((j) => j.status === "failed").length;
  const status = STATUS[me.kyc_status];
  const idShown = me.national_id ? `${"•".repeat(Math.max(me.national_id.length - 3, 0))}${me.national_id.slice(-3)}` : "";

  return (
    <div className="flex flex-col gap-4">
      <Link to="/rider" className="flex w-fit items-center gap-1.5 text-sm font-semibold text-brand">
        <ArrowLeft className="size-4" /> {approved ? "Back to jobs" : "Back"}
      </Link>

      <section className="flex items-center gap-4 rounded-3xl bg-surface p-5 shadow-sm">
        {me.photo_url ? (
          <img src={me.photo_url} alt="" className="size-20 shrink-0 rounded-full object-cover ring-2 ring-brand/30" />
        ) : (
          <span className="flex size-20 shrink-0 items-center justify-center rounded-full bg-brand-soft text-brand"><Bike className="size-9" /></span>
        )}
        <div className="min-w-0">
          <h1 className="truncate text-xl font-bold">{me.name}</h1>
          <p className="money text-sm text-muted">{localPhone(me.phone)}</p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <span className={clsx("rounded-full px-2.5 py-1 text-xs font-semibold", status.tone)}>{status.text}</span>
            {approved ? (
              <span className={clsx("rounded-full px-2.5 py-1 text-xs font-semibold", me.is_online ? "bg-ok-soft text-ok" : "bg-subtle text-muted")}>
                {me.is_online ? "Online" : "Offline"}
              </span>
            ) : null}
            {me.rating != null ? (
              <span className="flex items-center gap-1 rounded-full bg-warn-soft px-2.5 py-1 text-xs font-semibold text-warn">
                <Star className="size-3.5 fill-current" /> {me.rating.toFixed(1)} ({me.rating_count})
              </span>
            ) : null}
          </div>
        </div>
      </section>

      {me.kyc_note && me.kyc_status !== "approved" ? (
        <p className="rounded-2xl bg-bad-soft p-4 text-sm text-bad">{me.kyc_note}</p>
      ) : null}

      {approved ? (
        <section className="grid grid-cols-2 gap-3">
          <Stat label="Deliveries done" value={history.data ? String(done.length) : "…"} />
          <Stat label="Earned today" value={history.data ? money(earnedToday) : "…"} tone="text-ok" />
          <Stat label="Owed to you" value={earnings.data ? money(earnings.data.owed) : "…"} tone="text-ok" />
          <Stat label="Failed deliveries" value={history.data ? String(failed) : "…"} />
        </section>
      ) : null}

      <section className="rounded-3xl bg-surface p-5 shadow-sm">
        <h2 className="mb-1 text-sm font-bold">My bike</h2>
        <dl className="divide-y divide-line">
          <Row k="Number plate" v={me.bike_plate} />
          <Row k="Bike" v={me.bike_description} />
        </dl>
      </section>

      <section className="rounded-3xl bg-surface p-5 shadow-sm">
        <h2 className="mb-1 text-sm font-bold">My details</h2>
        <dl className="divide-y divide-line">
          <Row k="Phone" v={localPhone(me.phone)} />
          <Row k="ID number" v={idShown} />
          <Row k="Lives in" v={me.residence_area} />
          <Row k="Next of kin" v={me.next_of_kin} />
          <Row k="Next of kin phone" v={localPhone(me.next_of_kin_phone)} />
          <Row k="Riding with Chakula since" v={day.format(new Date(me.created_at))} />
        </dl>
        <p className="mt-3 text-xs text-muted">To change any of these, message the Chakula team on WhatsApp below.</p>
      </section>

      {approved && earnings.data?.payouts.length ? (
        <section className="rounded-3xl bg-surface p-5 shadow-sm">
          <h2 className="mb-1 text-sm font-bold">Payouts sent to you</h2>
          <ul className="divide-y divide-line text-sm">
            {earnings.data.payouts.slice(0, 5).map((p) => (
              <li key={p.id} className="flex items-center justify-between gap-2 py-2.5">
                <span><strong className="money tracking-wide">{p.mpesa_code}</strong> · {paidOn.format(new Date(p.paid_at))}</span>
                <span className="money font-bold">{money(p.amount)}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <HelpButton number={config.data?.support_whatsapp} message={`Hello Chakula, I am rider ${me.name} and I need help with `} />
    </div>
  );
}

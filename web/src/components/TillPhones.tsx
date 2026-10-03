/**
 * Till phone (SMS forwarder app, M8, DECISIONS D26): pairing and live status. Used in the hotel's
 * Settings (its own phone) and the super admin's Till phones page (every hotel).
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { BatteryCharging, BatteryLow, BatteryMedium, Download, KeyRound, MessageSquareText, Smartphone, Unplug } from "lucide-react";
import { useEffect, useState } from "react";

import { ErrorNote } from "./ui";
import { api } from "../lib/api";

export type TillPhone = {
  id: string;
  hotel_id: string | null;
  hotel_name: string | null;
  label: string;
  till_number: string;
  app_version: string | null;
  last_heartbeat_at: string | null;
  last_sms_at: string | null;
  battery: number | null;
  charging: boolean | null;
  pending: number | null;
  sms_permission: boolean | null;
  online: boolean;
  problems: ("offline" | "no_sms_permission" | "messages_waiting")[];
  paired_at: string;
};

export const APK_URL = "/downloads/chakula-till.apk";

const ago = (iso: string | null) => {
  if (!iso) return "never";
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m} min ago`;
  if (m < 48 * 60) return `${Math.round(m / 60)} h ago`;
  return `${Math.round(m / 1440)} days ago`;
};

const PROBLEM: Record<TillPhone["problems"][number], string> = {
  offline: "Not heard from in 40+ minutes: check the phone is on, charged and has data.",
  no_sms_permission: "SMS permission is off: open Chakula Till on the phone and tap Allow SMS.",
  messages_waiting: "Payment messages are waiting on the phone to be sent.",
};

/** One-line health summary, also used for the hotel's warning strip. */
export function phoneHealth(d: TillPhone | undefined): { ok: boolean; text: string } {
  if (!d) return { ok: false, text: "No Till phone connected: payments must be confirmed by hand." };
  if (d.problems.length) return { ok: false, text: PROBLEM[d.problems[0]] };
  return { ok: true, text: "Working: M-Pesa payments confirm by themselves." };
}

export function PhoneCard({ d, onUnpair, unpairing }: { d: TillPhone; onUnpair?: () => void; unpairing?: boolean }) {
  const health = phoneHealth(d);
  const Battery = d.charging ? BatteryCharging : (d.battery ?? 100) < 25 ? BatteryLow : BatteryMedium;
  return (
    <div className={clsx("rounded-2xl border p-4", health.ok ? "border-line" : "border-bad/40 bg-bad-soft/40")}>
      <div className="flex flex-wrap items-start gap-3">
        <span className={clsx("flex size-10 shrink-0 items-center justify-center rounded-xl", health.ok ? "bg-ok-soft text-ok" : "bg-bad-soft text-bad")}>
          <Smartphone className="size-5" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="font-semibold">
            {d.hotel_name ? `${d.hotel_name} · ` : ""}
            {d.label}
          </p>
          <p className={clsx("text-sm font-medium", health.ok ? "text-ok" : "text-bad")}>{health.text}</p>
        </div>
        {onUnpair ? (
          <button onClick={onUnpair} disabled={unpairing} className="flex h-9 items-center gap-1.5 rounded-lg border border-line bg-surface px-3 text-sm font-semibold text-muted hover:text-bad disabled:opacity-50">
            <Unplug className="size-4" /> Unpair
          </button>
        ) : null}
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm sm:grid-cols-4">
        <div>
          <dt className="text-xs text-muted">Last check-in</dt>
          <dd className="font-semibold">{ago(d.last_heartbeat_at)}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Last payment SMS</dt>
          <dd className="font-semibold">{ago(d.last_sms_at)}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Battery</dt>
          <dd className="flex items-center gap-1 font-semibold">
            <Battery className="size-4" /> {d.battery != null ? `${d.battery}%` : "—"}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Till · app</dt>
          <dd className="font-semibold">
            {d.till_number} · v{d.app_version ?? "?"}
          </dd>
        </div>
      </dl>
    </div>
  );
}

/** Make a one-time code and show the steps to connect a phone. */
export function PairingBox({ create, invalidate }: { create: () => Promise<{ code: string; expires_at: string }>; invalidate: unknown[] }) {
  const qc = useQueryClient();
  const [code, setCode] = useState<{ code: string; expires_at: string } | null>(null);
  const [left, setLeft] = useState(0);
  const make = useMutation({ mutationFn: create, onSuccess: setCode });
  useEffect(() => {
    if (!code) return;
    const t = setInterval(() => {
      const s = Math.max(0, Math.round((new Date(code.expires_at).getTime() - Date.now()) / 1000));
      setLeft(s);
      if (s === 0) setCode(null);
      void qc.invalidateQueries({ queryKey: invalidate }); // shows the phone once it connects
    }, 3000);
    setLeft(Math.round((new Date(code.expires_at).getTime() - Date.now()) / 1000));
    return () => clearInterval(t);
  }, [code, qc, invalidate]);
  const server = window.location.origin;
  const local = /localhost|127\.0\.0\.1/.test(window.location.hostname);

  return (
    <div className="rounded-2xl bg-subtle p-4">
      <ol className="flex flex-col gap-3 text-sm">
        <li className="flex gap-3">
          <Step n={1} />
          <span>
            On the <strong>Till phone</strong> (the one that receives the M-Pesa messages), install the app:{" "}
            <a href={APK_URL} className="inline-flex items-center gap-1 font-semibold text-brand underline">
              <Download className="size-3.5" /> Chakula Till
            </a>
            . Android may ask to allow installing from this source.
          </span>
        </li>
        <li className="flex gap-3">
          <Step n={2} />
          <span>
            Open it and enter the server address <strong className="money select-all">{server}</strong>
            {local ? <span className="block text-xs text-warn">This computer's address won't work from a phone: use its Wi-Fi address instead (e.g. http://192.168.1.20:5173).</span> : null}
          </span>
        </li>
        <li className="flex gap-3">
          <Step n={3} />
          <span className="flex-1">
            Enter this code, then follow the checklist on the phone (Allow SMS, background running).
            {code ? (
              <span className="mt-2 flex flex-wrap items-center gap-3">
                <span className="money rounded-xl border-2 border-dashed border-brand bg-surface px-4 py-2 text-2xl font-extrabold tracking-[0.2em] select-all">{code.code}</span>
                <span className="text-xs text-muted">
                  Works once · {Math.floor(left / 60)}:{String(left % 60).padStart(2, "0")} left
                </span>
              </span>
            ) : (
              <button onClick={() => make.mutate()} disabled={make.isPending} className="mt-2 flex h-11 items-center gap-2 rounded-xl bg-brand px-4 font-semibold text-white shadow-md shadow-brand/20 disabled:opacity-50">
                <KeyRound className="size-4" /> Show pairing code
              </button>
            )}
          </span>
        </li>
      </ol>
      <ErrorNote error={make.error} />
      <p className="mt-3 flex items-start gap-2 text-xs text-muted">
        <MessageSquareText className="mt-0.5 size-3.5 shrink-0" />
        The app only sends messages from M-PESA. Personal messages are never read or sent. Connecting a new phone disconnects the old one.
      </p>
    </div>
  );
}

function Step({ n }: { n: number }) {
  return <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-brand text-xs font-bold text-white">{n}</span>;
}

export function useUnpair(path: (id: string) => string, invalidate: unknown[]) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.del(path(id)),
    onSuccess: () => qc.invalidateQueries({ queryKey: invalidate }),
  });
}

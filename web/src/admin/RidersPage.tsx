/** Super admin: review rider applications. ID photos load through the admin-only
 * endpoint with the login token; they are never cached or linked publicly. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { CheckCircle2, IdCard, Phone, ShieldAlert, ShieldCheck, UserRound } from "lucide-react";
import { useEffect, useState } from "react";

import { ErrorNote, Skeleton } from "../components/ui";
import { api, auth, request } from "../lib/api";
import { ResetPassword, Stars } from "../components/accounts";

type Rider = {
  id: string;
  name: string;
  phone: string;
  national_id: string;
  next_of_kin: string;
  next_of_kin_phone: string | null;
  residence_area: string | null;
  photos: Record<"id_front" | "id_back" | "selfie", boolean>;
  photo_url: string | null;
  kyc_status: "draft" | "pending" | "approved" | "rejected" | "suspended";
  kyc_note: string | null;
  submitted_at: string | null;
  reviewed_at: string | null;
  reviewed_by_name: string | null;
  is_online: boolean;
  rating: number | null;
  rating_count: number;
  created_at: string;
};

const TABS = [
  { id: "pending", label: "To review" },
  { id: "approved", label: "Approved" },
  { id: "rejected", label: "Rejected" },
  { id: "suspended", label: "Suspended" },
  { id: "draft", label: "Not submitted" },
] as const;
const CHECKS = ["The selfie is the same person as the ID photo", "Name and ID number match the ID card", "I called the rider on this phone", "I called the next of kin"];
const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString("en-KE", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "—");
const local = (p: string | null) => (p ? `0${p.slice(3, 6)} ${p.slice(6, 9)} ${p.slice(9)}` : "—");

/** An ID photo fetched with the admin's token (img tags can't send headers). */
function PrivatePhoto({ riderId, kind, label }: { riderId: string; kind: string; label: string }) {
  const [url, setUrl] = useState<string | null>(null);
  const [big, setBig] = useState(false);
  useEffect(() => {
    let revoke: string | null = null;
    let alive = true;
    (async () => {
      await request("GET", "/auth/me"); // refresh an expired token first
      const res = await fetch(`/api/v1/admin/riders/${riderId}/kyc/${kind}`, { headers: { Authorization: `Bearer ${auth.token()}` } });
      if (!res.ok || !alive) return;
      revoke = URL.createObjectURL(await res.blob());
      setUrl(revoke);
    })().catch(() => null);
    return () => {
      alive = false;
      if (revoke) URL.revokeObjectURL(revoke);
    };
  }, [riderId, kind]);
  return (
    <figure className="flex flex-col gap-1.5">
      <button onClick={() => url && setBig(true)} className="aspect-[4/3] overflow-hidden rounded-2xl border border-line bg-subtle">
        {url ? <img src={url} alt={label} className="size-full object-cover" /> : <span className="flex size-full items-center justify-center text-sm text-muted">Loading…</span>}
      </button>
      <figcaption className="text-center text-sm font-semibold">{label}</figcaption>
      {big && url ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4" onClick={() => setBig(false)}>
          <img src={url} alt={label} className="max-h-full max-w-full rounded-xl" />
        </div>
      ) : null}
    </figure>
  );
}

function Detail({ r }: { r: Rider }) {
  const qc = useQueryClient();
  const [ticks, setTicks] = useState<boolean[]>(CHECKS.map(() => false));
  const [note, setNote] = useState("");
  useEffect(() => {
    setTicks(CHECKS.map(() => false));
    setNote("");
  }, [r.id]);
  const review = useMutation({
    mutationFn: (action: string) => api.post(`/admin/riders/${r.id}/review`, { action, note: note.trim() || null }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "riders"] }),
  });

  return (
    <section className="min-w-0 rounded-3xl border border-line bg-surface p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold">{r.name}</h2>
          <p className="text-sm text-muted">Applied {when(r.created_at)}{r.submitted_at ? ` · submitted ${when(r.submitted_at)}` : ""}</p>
        </div>
        <span className={clsx("rounded-full px-3 py-1 text-sm font-semibold", r.kyc_status === "approved" ? "bg-ok-soft text-ok" : r.kyc_status === "pending" ? "bg-warn-soft text-warn" : "bg-bad-soft text-bad")}>
          {r.kyc_status}
        </span>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        {r.photos.id_front ? <PrivatePhoto riderId={r.id} kind="id_front" label="ID front" /> : null}
        {r.photos.id_back ? <PrivatePhoto riderId={r.id} kind="id_back" label="ID back" /> : null}
        {r.photos.selfie ? <PrivatePhoto riderId={r.id} kind="selfie" label="Selfie" /> : null}
      </div>

      <dl className="mt-5 grid gap-3 text-sm sm:grid-cols-2">
        {[
          ["ID number", <span key="id" className="money text-lg font-bold tracking-wider">{r.national_id}</span>],
          ["Lives in", r.residence_area],
          ["Rider phone", <a key="p" href={`tel:+${r.phone}`} className="flex items-center gap-1.5 font-bold text-brand"><Phone className="size-4" /> {local(r.phone)}</a>],
          [`Next of kin: ${r.next_of_kin}`, <a key="k" href={`tel:+${r.next_of_kin_phone}`} className="flex items-center gap-1.5 font-bold text-brand"><Phone className="size-4" /> {local(r.next_of_kin_phone)}</a>],
        ].map(([k, v], i) => (
          <div key={i} className="rounded-2xl bg-subtle px-4 py-3">
            <dt className="text-xs font-semibold text-muted uppercase">{k}</dt>
            <dd className="mt-0.5 font-medium">{v}</dd>
          </div>
        ))}
      </dl>
      {r.kyc_note ? <p className="mt-3 rounded-xl bg-bad-soft px-4 py-2.5 text-sm"><strong>Note:</strong> {r.kyc_note}</p> : null}
      {r.reviewed_by_name ? <p className="mt-2 text-xs text-muted">Last decision by {r.reviewed_by_name}, {when(r.reviewed_at)}</p> : null}

      {r.kyc_status === "pending" ? (
        <div className="mt-5 flex flex-col gap-3 border-t border-line pt-5">
          <p className="font-bold">Before approving</p>
          {CHECKS.map((c, i) => (
            <label key={c} className="flex items-center gap-3 text-sm">
              <input type="checkbox" checked={ticks[i]} onChange={(e) => setTicks(ticks.map((t, j) => (j === i ? e.target.checked : t)))} className="size-5 accent-[var(--color-ok)]" />
              {c}
            </label>
          ))}
          <p className="text-xs text-muted">Best practice: meet the rider once with their original ID before their first job.</p>
          <div className="mt-1 grid gap-2 sm:grid-cols-[1fr_auto]">
            <button onClick={() => review.mutate("approve")} disabled={!ticks.every(Boolean) || review.isPending} className="flex h-12 items-center justify-center gap-2 rounded-xl bg-ok font-bold text-white disabled:opacity-40">
              <ShieldCheck className="size-5" /> Approve rider
            </button>
          </div>
          <div className="flex flex-col gap-2 rounded-2xl border border-line p-3 sm:flex-row">
            <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={300} placeholder="Reason to send back, e.g. ID back photo is blurry" className="h-11 min-w-0 flex-1 rounded-xl border border-line bg-surface px-3 text-sm outline-none focus:border-brand" />
            <button onClick={() => review.mutate("reject")} disabled={!note.trim() || review.isPending} className="h-11 rounded-xl border border-bad/40 px-4 text-sm font-semibold text-bad disabled:opacity-40">Send back</button>
          </div>
        </div>
      ) : null}
      {r.kyc_status === "approved" || r.kyc_status === "suspended" ? (
        <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
          <span className="flex items-center gap-2 text-sm">Customer rating: <Stars rating={r.rating} count={r.rating_count} />{r.rating_count >= 10 && (r.rating ?? 5) < 3.5 ? <span className="rounded-full bg-bad-soft px-2 py-0.5 text-xs font-semibold text-bad">Low rating</span> : null}</span>
          <ResetPassword url={`/admin/users/${r.id}/reset-password`} name={r.name} />
        </div>
      ) : null}
      {r.kyc_status === "pending" ? null : r.kyc_status === "approved" ? (
        <div className="mt-5 flex flex-col gap-2 border-t border-line pt-5 sm:flex-row">
          <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={300} placeholder="Reason for suspending" className="h-11 min-w-0 flex-1 rounded-xl border border-line bg-surface px-3 text-sm outline-none focus:border-brand" />
          <button onClick={() => review.mutate("suspend")} disabled={!note.trim() || review.isPending} className="flex h-11 items-center justify-center gap-2 rounded-xl bg-bad px-4 text-sm font-semibold text-white disabled:opacity-40">
            <ShieldAlert className="size-4" /> Suspend
          </button>
        </div>
      ) : r.kyc_status === "suspended" ? (
        <button onClick={() => review.mutate("reinstate")} disabled={review.isPending} className="mt-5 flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-ok font-semibold text-white">
          <CheckCircle2 className="size-4" /> Reinstate rider
        </button>
      ) : null}
      <ErrorNote error={review.error} />
    </section>
  );
}

export function RidersPage() {
  const [tab, setTab] = useState<(typeof TABS)[number]["id"]>("pending");
  const [selected, setSelected] = useState<string | null>(null);
  const all = useQuery({ queryKey: ["admin", "riders"], queryFn: () => api.get<Rider[]>("/admin/riders?status=all"), refetchInterval: 30_000 });
  const list = (all.data ?? []).filter((r) => r.kyc_status === tab);
  const current = (all.data ?? []).find((r) => r.id === selected) ?? list[0];
  const count = (s: string) => (all.data ?? []).filter((r) => r.kyc_status === s).length;

  return (
    <div className="flex flex-col gap-5 p-4 sm:p-6">
      <div>
        <h1 className="text-2xl font-bold">Riders</h1>
        <p className="text-sm text-muted">Every rider is checked by you before their first job. Only super admins can see ID photos.</p>
      </div>
      <div className="flex gap-1 overflow-x-auto rounded-xl bg-subtle p-1">
        {TABS.map((t) => (
          <button key={t.id} onClick={() => { setTab(t.id); setSelected(null); }} className={clsx("flex h-10 shrink-0 items-center gap-2 rounded-lg px-3 text-sm font-semibold", tab === t.id ? "bg-surface shadow-sm" : "text-muted")}>
            {t.label}
            {count(t.id) ? <span className={clsx("rounded-full px-2 text-xs", t.id === "pending" ? "bg-bad text-white" : "bg-line")}>{count(t.id)}</span> : null}
          </button>
        ))}
      </div>
      {all.isLoading ? (
        <Skeleton className="h-64 rounded-3xl" />
      ) : list.length === 0 ? (
        <p className="rounded-3xl border border-dashed border-line py-12 text-center text-sm text-muted">Nobody here.</p>
      ) : (
        <div className="grid items-start gap-5 lg:grid-cols-[300px_minmax(0,1fr)]">
          <ul className="flex flex-col gap-2">
            {list.map((r) => (
              <li key={r.id}>
                <button onClick={() => setSelected(r.id)} className={clsx("flex w-full items-center gap-3 rounded-2xl border p-3 text-left", current?.id === r.id ? "border-brand bg-brand-soft/60" : "border-line bg-surface hover:bg-subtle")}>
                  {r.photo_url ? <img src={r.photo_url} alt="" className="size-11 rounded-full object-cover" /> : <span className="flex size-11 items-center justify-center rounded-full bg-subtle text-muted"><UserRound className="size-5" /></span>}
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-semibold">{r.name}</span>
                    <span className="flex items-center gap-1 text-xs text-muted"><IdCard className="size-3.5" /> {r.national_id}{r.kyc_status === "approved" ? (r.is_online ? " · online" : " · offline") : ""}</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
          {current ? <Detail r={current} /> : null}
        </div>
      )}
    </div>
  );
}

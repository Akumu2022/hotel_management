/** Rider app shell: KYC steps until the Chakula team approves, then jobs. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Bike, Camera, CheckCircle2, Clock, IdCard, KeyRound, ListChecks, LogOut, ShieldAlert, ShieldCheck, UserRound, Wallet } from "lucide-react";
import { type ReactNode, useRef, useState, useSyncExternalStore } from "react";
import { Link, Navigate } from "react-router-dom";

import { Button, ErrorNote, Skeleton } from "../components/ui";
import { AlarmBanner } from "../components/AlarmBanner";
import { NotificationBell } from "../components/NotificationBell";
import { ThemeToggle } from "../customer/CustomerLayout";
import { api, auth } from "../lib/api";
import { compressImage } from "../lib/format";
import { JobsPage } from "./JobsPage";
import { RiderSteps } from "./JoinPage";
import { WalletLoading, WalletPage, useWallet } from "./WalletPage";

export type RiderMe = {
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
  is_online: boolean;
};

const PHOTOS: { kind: "id_front" | "id_back" | "selfie"; title: string; hint: string; icon: ReactNode; capture: "environment" | "user" }[] = [
  { kind: "id_front", title: "ID front", hint: "The side with your photo. All four corners in view, no glare.", icon: <IdCard className="size-6" />, capture: "environment" },
  { kind: "id_back", title: "ID back", hint: "The back of the same ID.", icon: <IdCard className="size-6" />, capture: "environment" },
  { kind: "selfie", title: "Selfie", hint: "Your face, clear and well lit. Customers will see a small copy.", icon: <UserRound className="size-6" />, capture: "user" },
];

function Shell({ me, children }: { me?: RiderMe; children: ReactNode }) {
  return (
    <div className="min-h-dvh bg-page">
      <header className="sticky top-0 z-30 border-b border-line bg-surface/95 backdrop-blur">
        {me?.kyc_status === "approved" ? <AlarmBanner /> : null}
        <div className="mx-auto flex max-w-2xl items-center justify-between gap-3 px-4 py-3">
          <span className="flex items-center gap-2.5">
            {me?.photo_url ? (
              <img src={me.photo_url} alt="" className="size-10 rounded-full object-cover ring-2 ring-brand/30" />
            ) : (
              <span className="flex size-10 items-center justify-center rounded-xl bg-brand text-white"><Bike className="size-5" /></span>
            )}
            <span>
              <span className="block text-[0.9375rem] font-bold leading-tight">{me ? me.name.split(" ")[0] : "Chakula Riders"}</span>
              <span className="block text-xs text-muted">Chakula rider</span>
            </span>
          </span>
          <div className="flex items-center gap-2">
            <NotificationBell links={{ "rider-assigned": "/rider", "rider-open": "/rider" }} />
            <ThemeToggle />
            <Link to="/password" aria-label="Change password" className="flex size-10 items-center justify-center rounded-xl border border-line text-muted hover:bg-subtle">
              <KeyRound className="size-4" />
            </Link>
            <button onClick={() => auth.logout()} aria-label="Log out" className="flex size-10 items-center justify-center rounded-xl border border-line text-muted hover:bg-subtle">
              <LogOut className="size-4" />
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-2xl px-4 py-5 pb-28">{children}</main>
    </div>
  );
}

function PhotoTile({ p, done, onPick, busy }: { p: (typeof PHOTOS)[number]; done: boolean; onPick: (f: File) => void; busy: boolean }) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <button
      type="button"
      onClick={() => input.current?.click()}
      disabled={busy}
      className={clsx("flex items-center gap-4 rounded-2xl border-2 p-4 text-left transition-colors", done ? "border-ok bg-ok-soft/50" : "border-dashed border-line hover:border-brand")}
    >
      <span className={clsx("flex size-12 shrink-0 items-center justify-center rounded-xl", done ? "bg-ok text-white" : "bg-brand-soft text-brand")}>
        {done ? <CheckCircle2 className="size-6" /> : p.icon}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-[0.9375rem] font-bold">{p.title}</span>
        <span className="block text-sm text-muted">{p.hint}</span>
      </span>
      <span className={clsx("flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-semibold", done ? "text-ok" : "bg-ink text-surface")}>
        {busy ? "Uploading…" : done ? "Retake" : <><Camera className="size-4" /> Take</>}
      </span>
      <input
        ref={input}
        type="file"
        accept="image/*"
        capture={p.capture}
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onPick(f);
          e.target.value = "";
        }}
      />
    </button>
  );
}

function KycScreen({ me }: { me: RiderMe }) {
  const qc = useQueryClient();
  const [consent, setConsent] = useState(false);
  const [uploading, setUploading] = useState<string | null>(null);
  const upload = useMutation({
    mutationFn: async ({ kind, file }: { kind: string; file: File }) => {
      setUploading(kind);
      return api.upload<RiderMe>(`/rider/kyc/${kind}`, await compressImage(file), `${kind}.jpg`);
    },
    onSuccess: (data) => qc.setQueryData(["rider", "me"], data),
    onSettled: () => setUploading(null),
  });
  const submit = useMutation({
    mutationFn: () => api.post<RiderMe>("/rider/submit", { consent }),
    onSuccess: (data) => qc.setQueryData(["rider", "me"], data),
  });
  const allPhotos = Object.values(me.photos).every(Boolean);

  return (
    <>
      <h1 className="text-2xl font-bold">Verify your identity</h1>
      <p className="mb-5 text-[0.9375rem] text-muted">Three quick photos with your phone camera. The Chakula team checks them before your first job.</p>
      <RiderSteps step={2} />
      {me.kyc_status === "rejected" ? (
        <div className="mb-4 flex gap-3 rounded-2xl border-2 border-bad/30 bg-bad-soft p-4">
          <ShieldAlert className="size-6 shrink-0 text-bad" />
          <div>
            <p className="font-bold text-bad">Please fix your application</p>
            <p className="text-sm">{me.kyc_note}</p>
          </div>
        </div>
      ) : null}
      <div className="flex flex-col gap-3">
        {PHOTOS.map((p) => (
          <PhotoTile key={p.kind} p={p} done={me.photos[p.kind]} busy={uploading === p.kind} onPick={(file) => upload.mutate({ kind: p.kind, file })} />
        ))}
      </div>
      <ErrorNote error={upload.error} />

      <section className="mt-5 rounded-2xl bg-surface p-4 shadow-sm">
        <p className="mb-2 text-sm font-bold">Your details</p>
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
          <dt className="text-muted">Name</dt><dd className="font-medium">{me.name}</dd>
          <dt className="text-muted">ID number</dt><dd className="money font-medium">{me.national_id}</dd>
          <dt className="text-muted">Lives in</dt><dd className="font-medium">{me.residence_area}</dd>
          <dt className="text-muted">Next of kin</dt><dd className="font-medium">{me.next_of_kin} · 0{me.next_of_kin_phone?.slice(3)}</dd>
        </dl>
      </section>

      <label className="mt-5 flex items-start gap-3 rounded-2xl border border-line bg-surface p-4 text-sm">
        <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} className="mt-1 size-5 accent-[var(--color-brand)]" />
        <span>
          I agree that Chakula keeps my ID photos and selfie to verify who I am and to keep customers safe. Only the Chakula team can see them. I can ask for them to be deleted when I stop riding.
        </span>
      </label>
      <ErrorNote error={submit.error} />
      <Button size="lg" className="mt-4 w-full" disabled={!allPhotos || !consent} busy={submit.isPending} onClick={() => submit.mutate()}>
        {allPhotos ? "Send for review" : "Add all three photos first"}
      </Button>
    </>
  );
}

function StatusCard({ icon, title, body, tone }: { icon: ReactNode; title: string; body: ReactNode; tone: "brand" | "bad" }) {
  return (
    <div className={clsx("flex flex-col items-center gap-3 rounded-3xl p-8 text-center", tone === "brand" ? "bg-brand-soft" : "bg-bad-soft")}>
      <span className={clsx("flex size-16 items-center justify-center rounded-2xl text-white", tone === "brand" ? "bg-brand" : "bg-bad")}>{icon}</span>
      <h1 className="text-2xl font-bold">{title}</h1>
      <div className="max-w-sm text-[0.9375rem] text-muted">{body}</div>
    </div>
  );
}

/** Approved riders: jobs, plus a Wallet tab once the payments module is switched on. */
function ApprovedHome({ me }: { me: RiderMe }) {
  const [tab, setTab] = useState<"jobs" | "wallet">("jobs");
  const wallet = useWallet();
  const w = wallet.data?.enabled ? wallet.data : null;
  return (
    <>
      {tab === "wallet" && w ? <WalletPage w={w} /> : tab === "wallet" ? <WalletLoading /> : <JobsPage me={me} />}
      {w ? (
        <nav className="fixed inset-x-0 bottom-0 z-30 border-t border-line bg-surface/95 pb-[env(safe-area-inset-bottom)] backdrop-blur">
          <div className="mx-auto grid max-w-2xl grid-cols-2">
            {([["jobs", "Jobs", ListChecks], ["wallet", "Wallet", Wallet]] as const).map(([id, label, Icon]) => (
              <button key={id} onClick={() => setTab(id)} className={clsx("flex flex-col items-center gap-0.5 py-2.5 text-sm font-semibold", tab === id ? "text-brand" : "text-muted")}>
                <Icon className="size-6" />
                {label}
              </button>
            ))}
          </div>
        </nav>
      ) : null}
    </>
  );
}

export function RiderHome() {
  const user = useSyncExternalStore(auth.subscribe, auth.user);
  const me = useQuery({ queryKey: ["rider", "me"], queryFn: () => api.get<RiderMe>("/rider/me"), enabled: user?.role === "rider", refetchInterval: (q) => (q.state.data?.kyc_status === "pending" ? 30_000 : false) });
  if (!user) return <Navigate to="/rider/join" replace />;
  if (user.role !== "rider") return <Navigate to={user.role === "super_admin" ? "/admin" : "/hotel"} replace />;
  if (user.must_change_password) return <Navigate to="/password" replace />;
  if (!me.data) return <Shell><Skeleton className="h-64 rounded-3xl" /></Shell>;

  const d = me.data;
  return (
    <Shell me={d}>
      {d.kyc_status === "draft" || d.kyc_status === "rejected" ? (
        <KycScreen me={d} />
      ) : d.kyc_status === "pending" ? (
        <>
          <RiderSteps step={3} />
          <StatusCard
            icon={<Clock className="size-8" />}
            title="We're checking your details"
            tone="brand"
            body={
              <>
                <p>The Chakula team will call you and your next of kin to confirm, usually within a day. Keep your phone on.</p>
                <p className="mt-2">You'll see delivery jobs here as soon as you're approved.</p>
              </>
            }
          />
        </>
      ) : d.kyc_status === "suspended" ? (
        <StatusCard icon={<ShieldAlert className="size-8" />} title="Your account is paused" tone="bad" body={<><p>{d.kyc_note}</p><p className="mt-2">Contact the Chakula team to talk about it.</p></>} />
      ) : (
        <ApprovedHome me={d} />
      )}
      {d.kyc_status === "approved" ? null : (
        <p className="mt-6 flex items-center justify-center gap-1.5 text-xs text-muted"><ShieldCheck className="size-4 text-ok" /> Your ID is private to the Chakula team.</p>
      )}
    </Shell>
  );
}

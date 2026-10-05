/** Hotel settings: identity (name, Till, phone; editable by the hotel admin, D20), options,
 * location and opening hours. The Till number is the most important fact here, so it's big. */
import { ErrorBoundary, MapFailed } from "../components/ErrorBoundary";
import clsx from "clsx";
import { Banknote, Camera, Check, Clock, Copy, MapPin, Palette, Pencil, Phone, Smartphone, Store, Users } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, type ReactNode, Suspense, lazy, useEffect, useRef, useState } from "react";

import { PairingBox, PhoneCard, type TillPhone, useUnpair } from "../components/TillPhones";
import { Button, ErrorNote, Input, PasswordInput, Sheet, Skeleton, Switch } from "../components/ui";
import { ResetPassword } from "../components/accounts";
import { HotelCover } from "../customer/bits";
import { api } from "../lib/api";
import { WEEKDAYS, compressImage, hhmm } from "../lib/format";
import type { DayHours, Upload } from "../lib/types";
import { keys, useHotelSettings, useIsAdmin, useSave } from "./hooks";

const MapPicker = lazy(() => import("../customer/MapPicker"));
const SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const ACCENTS = ["#dc4b12", "#16a34a", "#2563eb", "#9333ea", "#db2777", "#ca8a04", "#0f766e", "#18181b"];

type Day = { open: boolean; opens_at: string; closes_at: string };

function toDays(hours: DayHours[]): Day[] {
  return WEEKDAYS.map((_, weekday) => {
    const h = hours.find((x) => x.weekday === weekday);
    return h ? { open: true, opens_at: hhmm(h.opens_at), closes_at: hhmm(h.closes_at) } : { open: false, opens_at: "08:00", closes_at: "21:00" };
  });
}

/** "Mon–Fri 06:00–23:30", "Sat 08:00–22:00", "Sun closed": consecutive equal days grouped. */
function summarize(days: Day[]): { label: string; value: string; closed: boolean }[] {
  const key = (d: Day) => (d.open ? `${d.opens_at}–${d.closes_at}` : "closed");
  const out: { label: string; value: string; closed: boolean }[] = [];
  let start = 0;
  for (let i = 1; i <= days.length; i++) {
    if (i === days.length || key(days[i]) !== key(days[start])) {
      out.push({
        label: i - 1 === start ? SHORT[start] : `${SHORT[start]}–${SHORT[i - 1]}`,
        value: days[start].open ? key(days[start]) : "Closed",
        closed: !days[start].open,
      });
      start = i;
    }
  }
  return out;
}

function Panel({ icon, title, sub, children, action }: { icon: ReactNode; title: string; sub?: string; children: ReactNode; action?: ReactNode }) {
  return (
    <section className="min-w-0 rounded-[1.5rem] bg-surface p-5 shadow-sm">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-brand-soft text-brand">{icon}</span>
          <div>
            <h2 className="text-lg font-bold">{title}</h2>
            {sub ? <p className="text-sm text-muted">{sub}</p> : null}
          </div>
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

// --- Identity -----------------------------------------------------------------------------------

function IdentitySheet({ name, phone, till, onClose }: { name: string; phone: string; till: string; onClose: () => void }) {
  const [n, setN] = useState(name);
  const [p, setP] = useState(`0${phone.slice(3)}`);
  const [t, setT] = useState(till);
  const save = useSave(() => api.put("/hotel/settings", { name: n.trim(), phone: p, till_number: t }), [keys.settings]);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate(undefined, { onSuccess: onClose });
  };
  return (
    <Sheet
      open
      title="Edit hotel details"
      onClose={onClose}
      footer={
        <Button className="w-full" type="submit" form="identity" busy={save.isPending}>
          Save details
        </Button>
      }
    >
      <form id="identity" onSubmit={submit} className="flex flex-col gap-4">
        <label className="flex flex-col gap-1.5">
          <span className="text-sm font-semibold">Hotel name</span>
          <Input value={n} onChange={(e) => setN(e.target.value)} required minLength={2} maxLength={120} />
          <span className="text-xs text-muted">Shown to customers in capitals on your cover.</span>
        </label>
        <label className="flex flex-col gap-1.5">
          <span className="text-sm font-semibold">M-Pesa Till number</span>
          <Input value={t} onChange={(e) => setT(e.target.value.replace(/\D/g, ""))} inputMode="numeric" required minLength={5} maxLength={10} className="money text-lg font-bold tracking-widest" />
        </label>
        {t !== till ? (
          <p className="rounded-xl bg-warn-soft px-3 py-2.5 text-sm text-warn">
            <strong>Check this twice.</strong> Customers will pay this Till from now on. The SMS forwarder must run on the phone that receives this Till's messages.
          </p>
        ) : null}
        <label className="flex flex-col gap-1.5">
          <span className="text-sm font-semibold">Hotel phone</span>
          <Input value={p} onChange={(e) => setP(e.target.value)} inputMode="tel" required />
          <span className="text-xs text-muted">Customers and riders call this number.</span>
        </label>
        <p className="text-xs text-muted">Changes are recorded with your name.</p>
        <ErrorNote error={save.error} />
      </form>
    </Sheet>
  );
}

function TillTile({ till }: { till: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="relative overflow-hidden rounded-[1.5rem] bg-gradient-to-br from-[#0b8a3e] to-[#06612b] p-5 text-white shadow-lg shadow-ok/20">
      <span className="absolute -top-6 -right-6 size-28 rounded-full bg-white/10" />
      <p className="flex items-center gap-2 text-sm font-semibold text-white/85">
        <Smartphone className="size-4" /> M-Pesa Till number
      </p>
      <p className="money mt-2 text-4xl font-extrabold tracking-[0.12em] break-all sm:text-5xl">{till}</p>
      <div className="mt-3 flex items-center justify-between gap-2">
        <p className="text-sm text-white/85">Customers pay here: Lipa na M-Pesa → Buy Goods</p>
        <button
          onClick={() => {
            void navigator.clipboard?.writeText(till);
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          }}
          className="flex h-9 shrink-0 items-center gap-1.5 rounded-lg bg-white/15 px-3 text-sm font-semibold hover:bg-white/25"
        >
          {copied ? <Check className="size-4" /> : <Copy className="size-4" />} {copied ? "Copied" : "Copy"}
        </button>
      </div>
    </div>
  );
}

// --- Hours -------------------------------------------------------------------------------------

function HoursSheet({ hours, onClose }: { hours: DayHours[]; onClose: () => void }) {
  const [days, setDays] = useState<Day[]>(() => toDays(hours));
  const save = useSave(
    () =>
      api.put("/hotel/settings", {
        hours: days.flatMap((d, weekday) => (d.open ? [{ weekday, opens_at: d.opens_at, closes_at: d.closes_at }] : [])),
      }),
    [keys.settings],
  );
  const set = (i: number, patch: Partial<Day>) => setDays((ds) => ds.map((d, j) => (j === i ? { ...d, ...patch } : d)));
  return (
    <Sheet
      open
      title="Opening hours"
      onClose={onClose}
      footer={
        <Button className="w-full" busy={save.isPending} onClick={() => save.mutate(undefined, { onSuccess: onClose })}>
          Save hours
        </Button>
      }
    >
      <p className="mb-3 text-sm text-muted">Orders stop 15 minutes before closing. A closing time before the opening time means after midnight.</p>
      <ul className="flex flex-col divide-y divide-line">
        {days.map((d, i) => (
          <li key={i} className="flex items-center gap-3 py-2.5">
            <Switch label={`Open on ${WEEKDAYS[i]}`} checked={d.open} onChange={(open) => set(i, { open })} />
            <span className={clsx("w-11 text-sm font-bold", !d.open && "text-muted")}>{SHORT[i]}</span>
            {d.open ? (
              <div className="flex min-w-0 flex-1 items-center gap-1.5">
                <Input aria-label={`${WEEKDAYS[i]} opens`} type="time" value={d.opens_at} onChange={(e) => set(i, { opens_at: e.target.value })} className="h-10 min-w-0 px-2" />
                <span className="text-muted">–</span>
                <Input aria-label={`${WEEKDAYS[i]} closes`} type="time" value={d.closes_at} onChange={(e) => set(i, { closes_at: e.target.value })} className="h-10 min-w-0 px-2" />
              </div>
            ) : (
              <span className="flex-1 text-sm text-muted">Closed</span>
            )}
          </li>
        ))}
      </ul>
      <button
        onClick={() => setDays((ds) => ds.map((d) => (d.open ? { ...d, opens_at: ds[0].opens_at, closes_at: ds[0].closes_at } : d)))}
        className="mt-3 text-sm font-semibold text-brand hover:underline"
      >
        Copy Monday's times to every open day
      </button>
      <ErrorNote error={save.error} />
    </Sheet>
  );
}

// --- Location ----------------------------------------------------------------------------------

function LocationPanel({ lat, lng, canEdit }: { lat: number | null; lng: number | null; canEdit: boolean }) {
  const [pin, setPin] = useState(lat != null && lng != null ? { lat, lng } : null);
  useEffect(() => setPin(lat != null && lng != null ? { lat, lng } : null), [lat, lng]);
  const save = useSave(
    (p: { lat: number; lng: number }) =>
      api.put("/hotel/settings", {
        lat: +p.lat.toFixed(6),
        lng: +p.lng.toFixed(6),
      }),
    [keys.settings],
  );
  const changed = pin && (pin.lat !== lat || pin.lng !== lng);
  return (
    <Panel icon={<MapPin className="size-5" />} title="Hotel location" sub="Where riders collect orders. Delivery fees are measured from here.">
      {lat == null ? <p className="mb-3 rounded-xl bg-warn-soft px-3 py-2 text-sm font-medium text-warn">Not set yet: customers can't get delivery until you drop your pin.</p> : null}
      <Suspense fallback={<Skeleton className="h-72" />}>
        <ErrorBoundary fallback={(retry) => <MapFailed retry={retry} />}>
          <MapPicker value={pin} onChange={(p) => canEdit && setPin(p)} checkZone={false} height="h-72" />
        </ErrorBoundary>
      </Suspense>
      {canEdit && changed ? (
        <div className="mt-3 flex items-center gap-3">
          <Button busy={save.isPending} onClick={() => save.mutate(pin!)}>
            Save location
          </Button>
          <Button variant="ghost" onClick={() => setPin(lat != null && lng != null ? { lat, lng } : null)}>
            Undo
          </Button>
        </div>
      ) : null}
      {save.isSuccess && !changed ? <p className="mt-2 text-sm font-medium text-ok">Location saved</p> : null}
      <ErrorNote error={save.error} />
    </Panel>
  );
}

// --- Page --------------------------------------------------------------------------------------

const PHONES = ["hotel", "forwarder"];

/** The Till phone app (M8): connect a phone, and see that it's working. */
function TillPhonePanel() {
  const q = useQuery({ queryKey: PHONES, queryFn: () => api.get<{ devices: TillPhone[] }>("/hotel/forwarder"), refetchInterval: 30_000 });
  const unpair = useUnpair((id) => `/hotel/forwarder/${id}`, PHONES);
  const [adding, setAdding] = useState(false);
  const devices = q.data?.devices ?? [];
  return (
    <Panel
      icon={<Smartphone className="size-5" />}
      title="Till phone"
      sub="The phone that receives this Till's M-Pesa messages sends them to Chakula, so orders confirm by themselves."
    >
      {q.isLoading ? <Skeleton className="h-24" /> : null}
      <div className="flex flex-col gap-3">
        {devices.map((d) => (
          <PhoneCard key={d.id} d={d} unpairing={unpair.isPending} onUnpair={() => window.confirm("Disconnect this phone? Payments will need confirming by hand until a phone is connected again.") && unpair.mutate(d.id)} />
        ))}
        {devices.length === 0 || adding ? (
          <PairingBox create={() => api.post<{ code: string; expires_at: string }>("/hotel/forwarder/pairing")} invalidate={PHONES} />
        ) : (
          <button onClick={() => setAdding(true)} className="self-start text-sm font-semibold text-brand underline">
            Replace with another phone
          </button>
        )}
      </div>
      <ErrorNote error={unpair.error} />
    </Panel>
  );
}

type Staff = { id: string; role: string; name: string; phone: string; is_active: boolean };
const STAFF = ["hotel", "staff"];

/** D28: the hotel admin adds cashiers, turns them off, and resets their passwords. */
function StaffPanel() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: STAFF, queryFn: () => api.get<Staff[]>("/hotel/staff") });
  const [f, setF] = useState({ name: "", phone: "", password: "" });
  const [adding, setAdding] = useState(false);
  const add = useMutation({
    mutationFn: () => api.post("/hotel/staff", f),
    onSuccess: () => {
      setF({ name: "", phone: "", password: "" });
      setAdding(false);
      qc.invalidateQueries({ queryKey: STAFF });
    },
  });
  const toggle = useMutation({
    mutationFn: (u: Staff) => api.patch(`/hotel/staff/${u.id}`, { is_active: !u.is_active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: STAFF }),
  });
  return (
    <Panel icon={<Users className="size-5" />} title="Staff logins" sub="Cashiers confirm payments and run the orders screen. They choose their own password at first login.">
      {q.isLoading ? <Skeleton className="h-16" /> : null}
      <ul className="flex flex-col gap-2">
        {q.data?.map((u) => (
          <li key={u.id} className="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-subtle px-3 py-2 text-sm">
            <span className={clsx(!u.is_active && "text-muted line-through")}>
              <b>{u.name}</b> · {u.role === "hotel_admin" ? "Admin" : "Cashier"} · <span className="money">{u.phone}</span>
            </span>
            {u.role === "cashier" ? (
              <span className="flex flex-wrap items-center gap-2">
                <button onClick={() => toggle.mutate(u)} className="rounded-lg border border-line px-2 py-1 text-xs font-semibold text-muted hover:bg-surface">{u.is_active ? "Turn off" : "Turn on"}</button>
                {u.is_active ? <ResetPassword url={`/hotel/staff/${u.id}/reset-password`} name={u.name} /> : null}
              </span>
            ) : null}
          </li>
        ))}
      </ul>
      {adding ? (
        <form onSubmit={(e) => { e.preventDefault(); add.mutate(); }} className="mt-3 grid gap-2 sm:grid-cols-3">
          <Input aria-label="Name" placeholder="Name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} required minLength={2} />
          <Input aria-label="Phone" type="tel" placeholder="0712 345 678" value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} required />
          <PasswordInput aria-label="First password" placeholder="First password" autoComplete="new-password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} required minLength={8} />
          <Button type="submit" busy={add.isPending} className="sm:col-span-3">Add cashier</Button>
        </form>
      ) : (
        <button onClick={() => setAdding(true)} className="mt-3 text-sm font-semibold text-brand underline">Add a cashier</button>
      )}
      <ErrorNote error={add.error ?? toggle.error} />
    </Panel>
  );
}

export function SettingsPage() {
  const isAdmin = useIsAdmin();
  const { data, isLoading, error } = useHotelSettings();
  const file = useRef<HTMLInputElement>(null);
  const [editing, setEditing] = useState<"identity" | "hours" | null>(null);
  const save = useSave((body: Record<string, unknown>) => api.put("/hotel/settings", body), [keys.settings]);
  const upload = useSave(
    async (f: File) => {
      const u = await api.upload<Upload>("/hotel/uploads/image", await compressImage(f), "cover.jpg");
      return api.put("/hotel/settings", { cover_image_key: u.image_key });
    },
    [keys.settings],
  );

  if (isLoading) return <Skeleton className="h-60" />;
  if (error || !data) return <ErrorNote error={error} />;
  const days = toDays(data.hours);
  const accent = data.accent_color ?? "#dc4b12";

  return (
    <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <div className="flex min-w-0 flex-col gap-5">
        {/* Cover + identity */}
        <section className="overflow-hidden rounded-[1.5rem] bg-surface shadow-sm">
          <HotelCover src={data.cover_url} name={data.name} accent={accent} size="lg" className="h-44 sm:h-auto sm:aspect-[3/1]">
            <p className="mt-1 flex items-center gap-1.5 text-sm font-medium text-white/85">
              <Store className="size-4" /> {data.status === "active" ? "Live on Chakula" : data.status}
            </p>
          </HotelCover>
          <div className="flex flex-wrap items-center justify-end gap-2 border-b border-line px-4 py-3">
            {isAdmin ? (
              <>
                <Button variant="secondary" size="sm" busy={upload.isPending} onClick={() => file.current?.click()}>
                  <Camera className="size-4" /> {data.cover_url ? "Change cover" : "Add cover photo"}
                </Button>
                <Button size="sm" onClick={() => setEditing("identity")}>
                  <Pencil className="size-4" /> Edit details
                </Button>
              </>
            ) : null}
            <input
              ref={file}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) upload.mutate(f);
                e.target.value = "";
              }}
            />
          </div>
          <div className="flex flex-col gap-3 p-4">
            <TillTile till={data.till_number} />
            <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 rounded-[1.25rem] border border-line px-5 py-4">
              <span>
                <span className="flex items-center gap-2 text-sm font-semibold text-muted">
                  <Phone className="size-4" /> Hotel phone
                </span>
                <span className="text-sm text-muted">Customers and riders call this.</span>
              </span>
              <a href={`tel:+${data.phone}`} className="money text-2xl font-extrabold tracking-wide whitespace-nowrap hover:text-brand">
                0{data.phone.slice(3, 6)} {data.phone.slice(6, 9)} {data.phone.slice(9)}
              </a>
            </div>
          </div>
          <ErrorNote error={upload.error} />
        </section>

        {isAdmin ? <TillPhonePanel /> : null}

        {/* Options */}
        <Panel icon={<Banknote className="size-5" />} title="Ordering options">
          <div className="grid gap-3 sm:grid-cols-2">
            <label className={clsx("flex cursor-pointer flex-col gap-3 rounded-2xl border-2 p-4 transition-colors", data.cash_pickup_enabled ? "border-ok bg-ok-soft/60" : "border-line")}>
              <span className="flex items-center justify-between">
                <span className="text-3xl">💵</span>
                <Switch label="Cash pickup" checked={data.cash_pickup_enabled} onChange={(v) => save.mutate({ cash_pickup_enabled: v })} disabled={!isAdmin || save.isPending} />
              </span>
              <span>
                <span className="block text-[0.9375rem] font-bold">Cash at the counter</span>
                <span className="block text-sm text-muted">Pickup customers pay cash when they collect.</span>
              </span>
              <span className={clsx("text-sm font-bold", data.cash_pickup_enabled ? "text-ok" : "text-muted")}>{data.cash_pickup_enabled ? "On" : "Off"}</span>
            </label>
            <div className="flex flex-col gap-3 rounded-2xl border-2 border-line p-4">
              <span className="flex items-center justify-between">
                <Palette className="size-7" style={{ color: accent }} />
                <span className="h-3 w-16 rounded-full" style={{ background: accent }} />
              </span>
              <span>
                <span className="block text-[0.9375rem] font-bold">Brand colour</span>
                <span className="block text-sm text-muted">The strip on your cover in the customer app.</span>
              </span>
              {isAdmin ? (
                <div className="flex flex-wrap gap-1.5">
                  {ACCENTS.map((c) => (
                    <button
                      key={c}
                      aria-label={`Colour ${c}`}
                      onClick={() => save.mutate({ accent_color: c })}
                      className={clsx("size-7 rounded-full ring-offset-2 ring-offset-surface", c === accent.toLowerCase() && "ring-2 ring-ink")}
                      style={{ background: c }}
                    />
                  ))}
                </div>
              ) : null}
            </div>
          </div>
          <ErrorNote error={save.error} />
        </Panel>

        {/* Hours, compact */}
        <Panel
          icon={<Clock className="size-5" />}
          title="Opening hours"
          sub="Orders stop 15 minutes before closing."
          action={
            isAdmin ? (
              <Button variant="secondary" size="sm" onClick={() => setEditing("hours")}>
                <Pencil className="size-4" /> Edit
              </Button>
            ) : null
          }
        >
          <ul className="flex flex-wrap gap-2">
            {summarize(days).map((g) => (
              <li key={g.label} className={clsx("rounded-xl px-3 py-2 text-sm", g.closed ? "bg-subtle text-muted" : "bg-brand-soft")}>
                <span className="font-bold">{g.label}</span> <span className="money">{g.value}</span>
              </li>
            ))}
          </ul>
        </Panel>
      </div>

      <LocationPanel lat={data.lat} lng={data.lng} canEdit={isAdmin} />
      {isAdmin ? <StaffPanel /> : null}

      {editing === "identity" ? <IdentitySheet name={data.name} phone={data.phone} till={data.till_number} onClose={() => setEditing(null)} /> : null}
      {editing === "hours" ? <HoursSheet hours={data.hours} onClose={() => setEditing(null)} /> : null}
    </div>
  );
}

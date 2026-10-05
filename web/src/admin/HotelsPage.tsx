/** Owner's hotel list (D28): only the owner creates hotels, with the hotel admin's login, and can
 * reset any staff password. Locations can be pasted as "lat, lng" (e.g. from Google Maps). */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, Plus, Users } from "lucide-react";
import { type FormEvent, useState } from "react";

import { Badge, Button, ErrorNote, Field, Input, PasswordInput, Sheet, Skeleton } from "../components/ui";
import { ResetPassword, Stars } from "../components/accounts";
import { api } from "../lib/api";

type Hotel = {
  id: string;
  name: string;
  slug: string;
  phone: string;
  till_number: string;
  status: string;
  lat: number | null;
  lng: number | null;
  rating: number | null;
  rating_count: number;
};
type Staff = { id: string; role: string; name: string; phone: string; is_active: boolean };

/** "-1.2833, 36.8167" (Google Maps copy) -> numbers, or null if it isn't a valid pair. */
export function parseLatLng(text: string): { lat: number; lng: number } | null {
  const m = text.trim().match(/^(-?\d{1,2}(?:\.\d+)?)\s*[,\s]\s*(-?\d{1,3}(?:\.\d+)?)$/);
  if (!m) return null;
  const lat = Number(m[1]);
  const lng = Number(m[2]);
  if (Math.abs(lat) > 90 || Math.abs(lng) > 180) return null;
  return { lat: +lat.toFixed(6), lng: +lng.toFixed(6) };
}

const slugify = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 80);

function StaffList({ hotel }: { hotel: Hotel }) {
  const staff = useQuery({ queryKey: ["admin", "users", hotel.id], queryFn: () => api.get<{ items: Staff[] }>(`/admin/users?hotel_id=${hotel.id}&limit=100`) });
  if (staff.isLoading) return <Skeleton className="h-10" />;
  return (
    <ul className="flex flex-col gap-2">
      {staff.data?.items.map((u) => (
        <li key={u.id} className="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-subtle px-3 py-2 text-sm">
          <span>
            <b>{u.name}</b> · {u.role === "hotel_admin" ? "Admin" : "Cashier"} · <span className="money">{u.phone}</span>
            {!u.is_active ? <Badge tone="bad">Disabled</Badge> : null}
          </span>
          <ResetPassword url={`/admin/users/${u.id}/reset-password`} name={u.name} />
        </li>
      ))}
      {staff.data?.items.length === 0 ? <li className="text-sm text-muted">No logins yet.</li> : null}
    </ul>
  );
}

function LocationEdit({ hotel }: { hotel: Hotel }) {
  const qc = useQueryClient();
  const [where, setWhere] = useState(hotel.lat != null ? `${hotel.lat}, ${hotel.lng}` : "");
  const point = parseLatLng(where);
  const save = useMutation({
    mutationFn: () => api.patch(`/admin/hotels/${hotel.id}`, point!),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "hotels"] }),
  });
  return (
    <div className="flex flex-wrap items-end gap-2">
      <Field label="Exact location (lat, lng)" error={where && !point ? "Use the form -1.28333, 36.81667" : undefined}>
        {(id) => <Input id={id} value={where} onChange={(e) => setWhere(e.target.value)} placeholder="-1.28333, 36.81667" className="w-64" />}
      </Field>
      <Button variant="secondary" onClick={() => save.mutate()} disabled={!point} busy={save.isPending}>Save location</Button>
      {save.isSuccess ? <span className="text-sm text-ok">Saved</span> : null}
      <ErrorNote error={save.error} />
    </div>
  );
}

function NewHotel({ onDone }: { onDone: () => void }) {
  const qc = useQueryClient();
  const [f, setF] = useState({ name: "", slug: "", phone: "", till_number: "", where: "", admin_name: "", admin_phone: "", admin_password: "" });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) =>
    setF((v) => ({ ...v, [k]: e.target.value, ...(k === "name" && (!v.slug || v.slug === slugify(v.name)) ? { slug: slugify(e.target.value) } : {}) }));
  const point = f.where ? parseLatLng(f.where) : null;
  const create = useMutation({
    mutationFn: () =>
      api.post("/admin/hotels", {
        name: f.name,
        slug: f.slug,
        phone: f.phone,
        till_number: f.till_number,
        ...(point ?? {}),
        admin: { name: f.admin_name, phone: f.admin_phone, password: f.admin_password },
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "hotels"] });
      onDone();
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate();
  };
  return (
    <form onSubmit={submit} className="flex flex-col gap-3">
      <Field label="Hotel name">{(id) => <Input id={id} value={f.name} onChange={set("name")} required minLength={2} />}</Field>
      <Field label="Web address" hint={`chakula…/h/${f.slug || "name"}`}>{(id) => <Input id={id} value={f.slug} onChange={set("slug")} required pattern="[a-z0-9-]{2,80}" />}</Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Hotel phone">{(id) => <Input id={id} type="tel" value={f.phone} onChange={set("phone")} required />}</Field>
        <Field label="Till number">{(id) => <Input id={id} inputMode="numeric" value={f.till_number} onChange={set("till_number")} required />}</Field>
      </div>
      <Field
        label="Location (optional)"
        hint="Paste latitude, longitude from Google Maps, e.g. -1.28333, 36.81667"
        error={f.where && !point ? "Use the form -1.28333, 36.81667" : undefined}
      >
        {(id) => <Input id={id} value={f.where} onChange={set("where")} placeholder="-1.28333, 36.81667" />}
      </Field>
      <p className="mt-2 text-sm font-bold">Hotel admin login</p>
      <Field label="Their name">{(id) => <Input id={id} value={f.admin_name} onChange={set("admin_name")} required minLength={2} />}</Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Their phone">{(id) => <Input id={id} type="tel" value={f.admin_phone} onChange={set("admin_phone")} required />}</Field>
        <Field label="First password" hint="They change it at first login">{(id) => <PasswordInput id={id} autoComplete="new-password" value={f.admin_password} onChange={set("admin_password")} required minLength={8} />}</Field>
      </div>
      <ErrorNote error={create.error} />
      <Button type="submit" size="lg" busy={create.isPending} disabled={!!f.where && !point}>Create hotel</Button>
    </form>
  );
}

export function HotelsPage() {
  const hotels = useQuery({ queryKey: ["admin", "hotels"], queryFn: () => api.get<{ items: Hotel[] }>("/admin/hotels?limit=100") });
  const [adding, setAdding] = useState(false);
  const [open, setOpen] = useState<string | null>(null);

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-5 p-4 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-bold"><Building2 className="size-5 text-brand" /> Hotels</h1>
          <p className="text-sm text-muted">Only you can add hotels. Each gets an admin login that can add its own cashiers.</p>
        </div>
        <Button onClick={() => setAdding(true)}><Plus className="size-4" /> Add hotel</Button>
      </div>
      <ErrorNote error={hotels.error} />
      {hotels.isLoading ? <Skeleton className="h-40 rounded-3xl" /> : null}
      <ul className="flex flex-col gap-3">
        {hotels.data?.items.map((h) => (
          <li key={h.id} className="rounded-3xl border border-line bg-surface p-4">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <p className="font-bold">{h.name} {h.status === "paused" ? <Badge tone="warn">Paused</Badge> : null}</p>
                <p className="text-sm text-muted">
                  Till <span className="money">{h.till_number}</span> · <span className="money">{h.phone}</span> ·{" "}
                  {h.lat != null ? <span className="money">{h.lat.toFixed(5)}, {h.lng?.toFixed(5)}</span> : <span className="text-bad">no location</span>}
                </p>
              </div>
              <div className="flex items-center gap-3">
                <Stars rating={h.rating} count={h.rating_count} />
                <button onClick={() => setOpen(open === h.id ? null : h.id)} className="inline-flex items-center gap-1 rounded-lg border border-line px-2.5 py-1.5 text-sm font-semibold hover:bg-subtle">
                  <Users className="size-4" /> Logins & location
                </button>
              </div>
            </div>
            {open === h.id ? (
              <div className="mt-3 flex flex-col gap-3">
                <StaffList hotel={h} />
                <LocationEdit hotel={h} />
              </div>
            ) : null}
          </li>
        ))}
      </ul>
      <Sheet open={adding} onClose={() => setAdding(false)} title="Add hotel">
        <NewHotel onDone={() => setAdding(false)} />
      </Sheet>
    </div>
  );
}

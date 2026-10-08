/** Owner's hotel list: only the owner creates hotels, with the hotel admin's login, and can
 * reset any staff password. Each hotel admin pins their own location on the map. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, Plus, ShieldCheck, Users } from "lucide-react";
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
  till_name: string | null;
  verified: boolean;
  status: string;
  lat: number | null;
  lng: number | null;
  rating: number | null;
  rating_count: number;
};
type Staff = { id: string; role: string; name: string; phone: string; is_active: boolean };

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

/** Record the name M-Pesa shows for the Till, and tick "checked" once you've met the hotel. Changing the Till clears the tick. */
function VerifyPanel({ hotel }: { hotel: Hotel }) {
  const qc = useQueryClient();
  const [name, setName] = useState(hotel.till_name ?? "");
  const [checked, setChecked] = useState(hotel.verified);
  const save = useMutation({
    mutationFn: () => api.patch(`/admin/hotels/${hotel.id}`, { till_name: name.trim() || null, verified: checked }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "hotels"] }),
  });
  return (
    <div className="rounded-2xl border border-line p-4">
      <p className="flex items-center gap-2 text-sm font-bold"><ShieldCheck className="size-4 text-ok" /> Customer trust</p>
      <p className="mt-1 text-xs text-muted">
        Type the business name exactly as M-Pesa shows it when you enter Till {hotel.till_number}. Customers are told to check it before paying. Tick "checked" only after you have met the owner and seen the Till's name yourself.
      </p>
      <div className="mt-3 flex flex-col gap-3">
        <Field label="Name M-Pesa shows for this Till">{(id) => <Input id={id} value={name} onChange={(e) => setName(e.target.value)} maxLength={80} placeholder="e.g. NOOR CAFE LTD" />}</Field>
        <label className="flex items-start gap-2 text-sm">
          <input type="checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)} className="mt-1 size-4 accent-[var(--color-brand)]" />
          <span>I have checked this hotel and its Till. Show "Checked by Chakula" to customers.</span>
        </label>
        <ErrorNote error={save.error} />
        <Button onClick={() => save.mutate()} busy={save.isPending}>Save</Button>
      </div>
    </div>
  );
}

function NewHotel({ onDone }: { onDone: () => void }) {
  const qc = useQueryClient();
  const [f, setF] = useState({ name: "", slug: "", phone: "", till_number: "", till_name: "", admin_name: "", admin_phone: "", admin_password: "" });
  const [verified, setVerified] = useState(false);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) =>
    setF((v) => ({ ...v, [k]: e.target.value, ...(k === "name" && (!v.slug || v.slug === slugify(v.name)) ? { slug: slugify(e.target.value) } : {}) }));
  const create = useMutation({
    mutationFn: () =>
      api.post("/admin/hotels", {
        name: f.name,
        slug: f.slug,
        phone: f.phone,
        till_number: f.till_number,
        till_name: f.till_name.trim() || null,
        verified,
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
      <Field label="Name M-Pesa shows for the Till" hint="Exactly as it appears when you type the Till number">{(id) => <Input id={id} value={f.till_name} onChange={set("till_name")} maxLength={80} placeholder="e.g. NOOR CAFE LTD" />}</Field>
      <label className="flex items-start gap-2 text-sm">
        <input type="checkbox" checked={verified} onChange={(e) => setVerified(e.target.checked)} className="mt-1 size-4 accent-[var(--color-brand)]" />
        <span>I have checked this hotel and its Till (shows "Checked by Chakula" to customers)</span>
      </label>
      <p className="mt-2 text-sm font-bold">Hotel admin login</p>
      <Field label="Their name">{(id) => <Input id={id} value={f.admin_name} onChange={set("admin_name")} required minLength={2} />}</Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Their phone">{(id) => <Input id={id} type="tel" value={f.admin_phone} onChange={set("admin_phone")} required />}</Field>
        <Field label="First password" hint="They change it at first login">{(id) => <PasswordInput id={id} autoComplete="new-password" value={f.admin_password} onChange={set("admin_password")} required minLength={8} />}</Field>
      </div>
      <ErrorNote error={create.error} />
      <Button type="submit" size="lg" busy={create.isPending}>Create hotel</Button>
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
                <p className="font-bold">{h.name} {h.status === "paused" ? <Badge tone="warn">Paused</Badge> : null} {h.verified ? <Badge tone="ok">Checked</Badge> : <Badge tone="warn">Not checked</Badge>}</p>
                <p className="text-sm text-muted">
                  Till <span className="money">{h.till_number}</span>{h.till_name ? <> ({h.till_name})</> : <span className="text-warn"> (name not recorded)</span>} · <span className="money">{h.phone}</span> ·{" "}
                  {h.lat != null ? <span className="text-ok">location pinned</span> : <span className="text-warn">location not pinned yet</span>}
                </p>
              </div>
              <div className="flex items-center gap-3">
                <Stars rating={h.rating} count={h.rating_count} />
                <button onClick={() => setOpen(open === h.id ? null : h.id)} className="inline-flex items-center gap-1 rounded-lg border border-line px-2.5 py-1.5 text-sm font-semibold hover:bg-subtle">
                  <Users className="size-4" /> Manage
                </button>
              </div>
            </div>
            {open === h.id ? (
              <div className="mt-3 flex flex-col gap-3">
                <VerifyPanel key={`${h.till_number}-${h.till_name}-${h.verified}`} hotel={h} />
                <StaffList hotel={h} />
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

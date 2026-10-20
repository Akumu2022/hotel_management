import { Plus } from "lucide-react";
import { type FormEvent, useState } from "react";

import { Badge, Button, Card, EmptyState, ErrorNote, Field, Input, MoneyInput, Select, Sheet, Skeleton, Switch } from "../components/ui";
import { api } from "../lib/api";
import { isoToLocal, localToIso, money, when } from "../lib/format";
import type { Discount, Product } from "../lib/types";
import { keys, useDiscounts, useHotelSettings, useIsAdmin, useProducts, useSave, useW } from "./hooks";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const toMin = (hhmm: string) => Number(hhmm.slice(0, 2)) * 60 + Number(hhmm.slice(3, 5));
const toHhmm = (m: number) => `${String(Math.floor(m / 60) % 24).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;

/** "Happy hour · Mon–Fri 15:00–17:00" or "" when it runs all day, every day. */
function happyHour(d: Discount): string {
  const days = d.days_mask && d.days_mask !== 127 ? DAYS.filter((_, i) => d.days_mask! & (1 << i)).join(", ") : "";
  const hours = d.daily_from != null && d.daily_to != null ? `${toHhmm(d.daily_from)}–${d.daily_to === 1440 ? "24:00" : toHhmm(d.daily_to)}` : "";
  return days || hours ? ["Happy hour", days, hours].filter(Boolean).join(" · ") : "";
}

function describe(d: Discount, products: Product[]): string {
  const amount = d.kind === "percent" ? `${d.percent}% off` : `${money(d.value)} off`;
  const target =
    d.scope === "item" ? (products.find((p) => p.id === d.product_id)?.name ?? "a dish") + (d.kind === "fixed" ? " (each)" : "") : "the order";
  const min = d.min_spend ? ` over ${money(d.min_spend)}` : "";
  return `${amount} ${target}${min}`;
}

function status(d: Discount): { label: string; tone: "ok" | "warn" | "neutral" } {
  const now = Date.now();
  if (!d.is_active) return { label: "Off", tone: "neutral" };
  if (new Date(d.starts_at).getTime() > now) return { label: "Scheduled", tone: "warn" };
  if (d.ends_at && new Date(d.ends_at).getTime() <= now) return { label: "Ended", tone: "neutral" };
  if (d.max_uses && d.uses >= d.max_uses) return { label: "Used up", tone: "neutral" };
  return { label: "Live", tone: "ok" };
}

/** A short, easy-to-type code like "SAVE10K7P" (no 0/O/1/I to mix up). */
function suggestCode(percent: string): string {
  const letters = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  const tail = Array.from({ length: 3 }, () => letters[Math.floor(Math.random() * letters.length)]).join("");
  const n = Number(percent);
  return `SAVE${n > 0 && n < 100 ? Math.round(n) : ""}${tail}`;
}

function ShareCode({ d }: { d: Discount }) {
  const settings = useHotelSettings().data;
  const [done, setDone] = useState(false);
  if (!d.promo_code || !settings?.slug) return null;
  const link = `${window.location.origin}/h/${settings.slug}?promo=${d.promo_code}`;
  const off = d.kind === "percent" ? `${d.percent}% off` : `${money(d.value)} off`;
  const text = `Get ${off} at ${settings.name}! Use code ${d.promo_code}, or tap: ${link}`;
  async function share() {
    try {
      if (navigator.share) await navigator.share({ text });
      else await navigator.clipboard.writeText(text);
      setDone(true);
      setTimeout(() => setDone(false), 1500);
    } catch {
      /* share sheet closed */
    }
  }
  return (
    <Button variant="ghost" size="sm" onClick={share}>
      {done ? "Copied" : "Share"}
    </Button>
  );
}

/** Public: a coupon card on the menu page anyone can claim. Private: the hotel shares the code itself. */
function ShowToggle({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex items-start gap-2 rounded-xl border border-line p-3 text-sm">
      <input type="checkbox" className="mt-1" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span>
        <span className="block font-medium">Show to everyone as a coupon card</span>
        <span className="text-muted">Customers see the code on your menu page and tap Claim. Leave off to share the code yourself with the Share button.</span>
      </span>
    </label>
  );
}

function NewDiscountSheet({ products, copyOf, onClose }: { products: Product[]; copyOf?: Discount; onClose: () => void }) {
  const w = useW();
  const [scope, setScope] = useState<"order" | "item">(copyOf?.scope ?? "order");
  const [productId, setProductId] = useState(copyOf?.product_id ?? products[0]?.id ?? "");
  const [kind, setKind] = useState<"percent" | "fixed">(copyOf?.kind ?? "percent");
  const [percent, setPercent] = useState(String(copyOf?.percent ?? 10));
  const [amount, setAmount] = useState<number | "">(copyOf?.kind === "fixed" ? copyOf.value : "");
  const [minSpend, setMinSpend] = useState<number | "">(copyOf?.min_spend || "");
  const [isPromo, setIsPromo] = useState(false);
  const [code, setCode] = useState("");
  const [maxUses, setMaxUses] = useState("");
  const [isPublic, setIsPublic] = useState(true);
  const [starts, setStarts] = useState(isoToLocal(new Date().toISOString()));
  const [ends, setEnds] = useState("");
  const [happy, setHappy] = useState(copyOf?.daily_from != null || (copyOf?.days_mask != null && copyOf.days_mask !== 127));
  const [days, setDays] = useState(copyOf?.days_mask ?? 31); // Mon-Fri
  const [from, setFrom] = useState(copyOf?.daily_from != null ? toHhmm(copyOf.daily_from) : "15:00");
  const [to, setTo] = useState(copyOf?.daily_to != null ? toHhmm(copyOf.daily_to) : "17:00");

  const save = useSave(
    () =>
      api.post("/hotel/discounts", {
        scope,
        product_id: scope === "item" ? productId : null,
        kind,
        percent: kind === "percent" ? Number(percent) : null,
        amount: kind === "fixed" ? amount || 0 : null,
        min_spend: minSpend || 0,
        promo_code: isPromo ? code : null,
        max_uses: isPromo && maxUses ? Number(maxUses) : null,
        is_public: isPromo && isPublic,
        starts_at: localToIso(starts),
        ends_at: ends ? localToIso(ends) : null,
        days_mask: happy ? days : null,
        daily_from: happy ? toMin(from) : null,
        daily_to: happy ? toMin(to) || 1440 : null,
      }),
    [keys.discounts],
  );

  function submit(e: FormEvent) {
    e.preventDefault();
    save.mutate(undefined, { onSuccess: onClose });
  }

  return (
    <Sheet
      open
      title={copyOf ? "Copy of discount" : "New discount"}
      onClose={onClose}
      footer={
        <Button className="w-full" type="submit" form="discount-form" busy={save.isPending}>
          Create discount
        </Button>
      }
    >
      <form id="discount-form" onSubmit={submit} className="flex flex-col gap-4">
        <p className="rounded-lg bg-warn-soft px-3 py-2 text-sm text-warn">
          Your hotel funds its own discounts. The amount can't be changed later; switch it off and create a new one instead.
        </p>
        <Field label="Applies to">
          {(id) => (
            <Select id={id} value={scope} onChange={(e) => setScope(e.target.value as "order" | "item")}>
              <option value="order">The whole order</option>
              <option value="item">{w("One dish")}</option>
            </Select>
          )}
        </Field>
        {scope === "item" ? (
          <Field label={w("Dish")}>
            {(id) => (
              <Select id={id} value={productId} onChange={(e) => setProductId(e.target.value)}>
                {products.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} ({money(p.price)})
                  </option>
                ))}
              </Select>
            )}
          </Field>
        ) : null}
        <div className="grid grid-cols-2 gap-3">
          <Field label="Type">
            {(id) => (
              <Select id={id} value={kind} onChange={(e) => setKind(e.target.value as "percent" | "fixed")}>
                <option value="percent">Percent off</option>
                <option value="fixed">Shillings off</option>
              </Select>
            )}
          </Field>
          {kind === "percent" ? (
            <Field label="Percent" hint="Rounded down to the shilling">
              {(id) => <Input id={id} inputMode="decimal" value={percent} onChange={(e) => setPercent(e.target.value)} required />}
            </Field>
          ) : (
            <Field label={scope === "item" ? "Off each" : "Off the order"}>
              {(id) => <MoneyInput id={id} value={amount} onChange={setAmount} required />}
            </Field>
          )}
        </div>
        <Field label="Minimum spend" hint="Optional">
          {(id) => <MoneyInput id={id} value={minSpend} onChange={setMinSpend} placeholder="0" />}
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Starts">{(id) => <Input id={id} type="datetime-local" value={starts} onChange={(e) => setStarts(e.target.value)} required />}</Field>
          <Field label="Ends" hint="Optional">{(id) => <Input id={id} type="datetime-local" value={ends} onChange={(e) => setEnds(e.target.value)} />}</Field>
        </div>
        <label className="flex items-center gap-2 text-sm font-medium">
          <input type="checkbox" checked={happy} onChange={(e) => setHappy(e.target.checked)} />
          Happy hour: only on some days and times
        </label>
        {happy ? (
          <div className="flex flex-col gap-3 rounded-xl border border-line p-3">
            <div className="flex flex-wrap gap-1.5" role="group" aria-label="Days">
              {DAYS.map((name, i) => {
                const on = (days & (1 << i)) !== 0;
                return (
                  <button
                    key={name}
                    type="button"
                    aria-pressed={on}
                    onClick={() => setDays(on && days !== 1 << i ? days & ~(1 << i) : days | (1 << i))}
                    className={on ? "h-9 rounded-lg bg-brand px-3 text-sm font-semibold text-white" : "h-9 rounded-lg border border-line px-3 text-sm font-semibold text-muted"}
                  >
                    {name}
                  </button>
                );
              })}
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field label="From">{(id) => <Input id={id} type="time" value={from} onChange={(e) => setFrom(e.target.value)} required />}</Field>
              <Field label="Until">{(id) => <Input id={id} type="time" value={to} onChange={(e) => setTo(e.target.value)} required />}</Field>
            </div>
            <p className="text-xs text-muted">Kenya time. Fill quiet hours: customers see the deal only while it's on.</p>
            {toMin(to) !== 0 && toMin(to) <= toMin(from) ? <p className="text-sm font-medium text-bad">The end time must be after the start (same day).</p> : null}
          </div>
        ) : null}
        <label className="flex items-center gap-2 text-sm font-medium">
          <input type="checkbox" checked={isPromo} onChange={(e) => setIsPromo(e.target.checked)} />
          Only with a promo code
        </label>
        {isPromo ? (
          <div className="grid grid-cols-2 gap-3">
            <Field label="Promo code" hint="Letters and digits; one use per phone">
              {(id) => (
                <div className="flex gap-2">
                  <Input id={id} value={code} onChange={(e) => setCode(e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ""))} required minLength={3} maxLength={20} />
                  <Button type="button" variant="ghost" size="sm" onClick={() => setCode(suggestCode(kind === "percent" ? percent : ""))}>Suggest</Button>
                </div>
              )}
            </Field>
            <Field label="Total uses" hint="Optional limit">
              {(id) => <Input id={id} inputMode="numeric" value={maxUses} onChange={(e) => setMaxUses(e.target.value.replace(/\D/g, ""))} />}
            </Field>
          </div>
        ) : null}
        {isPromo ? <ShowToggle checked={isPublic} onChange={setIsPublic} /> : null}
        <ErrorNote error={save.error} />
      </form>
    </Sheet>
  );
}

function EditDiscountSheet({ d, products, onClose }: { d: Discount; products: Product[]; onClose: () => void }) {
  const [starts, setStarts] = useState(isoToLocal(d.starts_at));
  const [ends, setEnds] = useState(isoToLocal(d.ends_at));
  const [maxUses, setMaxUses] = useState(d.max_uses ? String(d.max_uses) : "");
  const [isPublic, setIsPublic] = useState(!!d.is_public);
  const save = useSave(
    () =>
      api.patch(`/hotel/discounts/${d.id}`, {
        starts_at: localToIso(starts),
        ends_at: ends ? localToIso(ends) : null,
        ...(d.promo_code ? { max_uses: maxUses ? Number(maxUses) : null, is_public: isPublic } : {}),
      }),
    [keys.discounts],
  );
  const remove = useSave(() => api.del(`/hotel/discounts/${d.id}`), [keys.discounts]);

  function submit(e: FormEvent) {
    e.preventDefault();
    save.mutate(undefined, { onSuccess: onClose });
  }

  return (
    <Sheet
      open
      title="Edit discount"
      onClose={onClose}
      footer={
        <div className="flex gap-2">
          <Button
            variant="danger"
            busy={remove.isPending}
            onClick={() => window.confirm("Delete this discount? This can't be undone.") && remove.mutate(undefined, { onSuccess: onClose })}
          >
            Delete
          </Button>
          <Button className="flex-1" type="submit" form="discount-edit-form" busy={save.isPending}>
            Save
          </Button>
        </div>
      }
    >
      <form id="discount-edit-form" onSubmit={submit} className="flex flex-col gap-4">
        <p className="font-medium">{describe(d, products)}</p>
        <p className="rounded-lg bg-warn-soft px-3 py-2 text-sm text-warn">
          The amount and what it applies to can't change, because past orders refer to them. To change them, use Copy to make a new discount and switch this one off. Delete removes it for good; past orders keep what they were charged.
        </p>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Starts">{(id) => <Input id={id} type="datetime-local" value={starts} onChange={(e) => setStarts(e.target.value)} required />}</Field>
          <Field label="Ends" hint="Optional">{(id) => <Input id={id} type="datetime-local" value={ends} onChange={(e) => setEnds(e.target.value)} />}</Field>
        </div>
        {d.promo_code ? (
          <Field label="Total uses" hint={`Code ${d.promo_code}, used ${d.uses}. Empty means no limit`}>
            {(id) => <Input id={id} inputMode="numeric" value={maxUses} onChange={(e) => setMaxUses(e.target.value.replace(/\D/g, ""))} />}
          </Field>
        ) : null}
        {d.promo_code ? <ShowToggle checked={isPublic} onChange={setIsPublic} /> : null}
        <ErrorNote error={save.error ?? remove.error} />
      </form>
    </Sheet>
  );
}

function DiscountRow({ d, products, canEdit, onEdit, onCopy }: { d: Discount; products: Product[]; canEdit: boolean; onEdit: () => void; onCopy: () => void }) {
  const w = useW();
  const toggle = useSave((is_active: boolean) => api.patch(`/hotel/discounts/${d.id}`, { is_active }), [keys.discounts]);
  const s = status(d);
  return (
    <li className="flex items-center gap-3 p-3">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <p className="font-medium">{w(describe(d, products))}</p>
          <Badge tone={s.tone}>{s.label}</Badge>
          {d.promo_code ? <Badge tone="brand">Code {d.promo_code}</Badge> : null}
          {d.promo_code ? <Badge tone="neutral">{d.is_public ? "On menu page" : "Private"}</Badge> : null}
        </div>
        {happyHour(d) ? <p className="text-sm font-medium text-brand">{happyHour(d)}</p> : null}
        <p className="text-sm text-muted">
          {when(d.starts_at)} → {when(d.ends_at)}
          {d.promo_code ? ` · used ${d.uses}${d.max_uses ? ` of ${d.max_uses}` : ""}` : ""}
        </p>
      </div>
      {canEdit ? (
        <div className="flex items-center gap-2">
          <ShareCode d={d} />
          <Button variant="ghost" size="sm" onClick={onCopy}>Copy</Button>
          <Button variant="ghost" size="sm" onClick={onEdit}>Edit</Button>
          <Switch label="Discount on" checked={d.is_active} onChange={(v) => toggle.mutate(v)} disabled={toggle.isPending} />
        </div>
      ) : null}
    </li>
  );
}

export function DiscountsPage() {
  const w = useW();
  const isAdmin = useIsAdmin();
  const discounts = useDiscounts();
  const products = useProducts();
  const [creating, setCreating] = useState(false);
  const [copying, setCopying] = useState<Discount | null>(null);
  const [editing, setEditing] = useState<Discount | null>(null);

  if (discounts.isLoading || products.isLoading) return <Skeleton className="h-40" />;
  if (discounts.error) return <ErrorNote error={discounts.error} />;
  const list = discounts.data!;
  const items = products.data ?? [];

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <p className="text-sm text-muted">{w("Customers get the single best deal on each dish and on the order.")}</p>
        {isAdmin ? (
          <Button onClick={() => setCreating(true)}>
            <Plus className="size-4" /> Discount
          </Button>
        ) : null}
      </div>
      {list.length === 0 ? (
        <EmptyState
          title="No discounts yet"
          body={w("Customers get the single best discount on each dish and on the order. Promo codes compete with automatic discounts.")}
          action={isAdmin ? <Button onClick={() => setCreating(true)}>Create a discount</Button> : null}
        />
      ) : (
        <Card>
          <ul className="divide-y divide-line">
            {list.map((d) => (
              <DiscountRow key={d.id} d={d} products={items} canEdit={isAdmin} onEdit={() => setEditing(d)} onCopy={() => setCopying(d)} />
            ))}
          </ul>
        </Card>
      )}
      {creating || copying ? <NewDiscountSheet products={items} copyOf={copying ?? undefined} onClose={() => { setCreating(false); setCopying(null); }} /> : null}
      {editing ? <EditDiscountSheet d={editing} products={items} onClose={() => setEditing(null)} /> : null}
    </div>
  );
}

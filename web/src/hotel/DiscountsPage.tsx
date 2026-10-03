import { Plus } from "lucide-react";
import { type FormEvent, useState } from "react";

import { Badge, Button, Card, EmptyState, ErrorNote, Field, Input, MoneyInput, Select, Sheet, Skeleton, Switch } from "../components/ui";
import { api } from "../lib/api";
import { isoToLocal, localToIso, money, when } from "../lib/format";
import type { Discount, Product } from "../lib/types";
import { keys, useDiscounts, useIsAdmin, useProducts, useSave } from "./hooks";

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

function NewDiscountSheet({ products, onClose }: { products: Product[]; onClose: () => void }) {
  const [scope, setScope] = useState<"order" | "item">("order");
  const [productId, setProductId] = useState(products[0]?.id ?? "");
  const [kind, setKind] = useState<"percent" | "fixed">("percent");
  const [percent, setPercent] = useState("10");
  const [amount, setAmount] = useState<number | "">("");
  const [minSpend, setMinSpend] = useState<number | "">("");
  const [isPromo, setIsPromo] = useState(false);
  const [code, setCode] = useState("");
  const [maxUses, setMaxUses] = useState("");
  const [starts, setStarts] = useState(isoToLocal(new Date().toISOString()));
  const [ends, setEnds] = useState("");
  const [happy, setHappy] = useState(false);
  const [days, setDays] = useState(31); // Mon-Fri
  const [from, setFrom] = useState("15:00");
  const [to, setTo] = useState("17:00");

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
      title="New discount"
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
              <option value="item">One dish</option>
            </Select>
          )}
        </Field>
        {scope === "item" ? (
          <Field label="Dish">
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
                <Input id={id} value={code} onChange={(e) => setCode(e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ""))} required minLength={3} maxLength={20} />
              )}
            </Field>
            <Field label="Total uses" hint="Optional limit">
              {(id) => <Input id={id} inputMode="numeric" value={maxUses} onChange={(e) => setMaxUses(e.target.value.replace(/\D/g, ""))} />}
            </Field>
          </div>
        ) : null}
        <ErrorNote error={save.error} />
      </form>
    </Sheet>
  );
}

function DiscountRow({ d, products, canEdit }: { d: Discount; products: Product[]; canEdit: boolean }) {
  const toggle = useSave((is_active: boolean) => api.patch(`/hotel/discounts/${d.id}`, { is_active }), [keys.discounts]);
  const s = status(d);
  return (
    <li className="flex items-center gap-3 p-3">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <p className="font-medium">{describe(d, products)}</p>
          <Badge tone={s.tone}>{s.label}</Badge>
          {d.promo_code ? <Badge tone="brand">Code {d.promo_code}</Badge> : null}
        </div>
        {happyHour(d) ? <p className="text-sm font-medium text-brand">{happyHour(d)}</p> : null}
        <p className="text-sm text-muted">
          {when(d.starts_at)} → {when(d.ends_at)}
          {d.promo_code ? ` · used ${d.uses}${d.max_uses ? ` of ${d.max_uses}` : ""}` : ""}
        </p>
      </div>
      {canEdit ? <Switch label="Discount on" checked={d.is_active} onChange={(v) => toggle.mutate(v)} disabled={toggle.isPending} /> : null}
    </li>
  );
}

export function DiscountsPage() {
  const isAdmin = useIsAdmin();
  const discounts = useDiscounts();
  const products = useProducts();
  const [creating, setCreating] = useState(false);

  if (discounts.isLoading || products.isLoading) return <Skeleton className="h-40" />;
  if (discounts.error) return <ErrorNote error={discounts.error} />;
  const list = discounts.data!;
  const items = products.data ?? [];

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <p className="text-sm text-muted">Customers get the single best deal on each dish and on the order.</p>
        {isAdmin ? (
          <Button onClick={() => setCreating(true)}>
            <Plus className="size-4" /> Discount
          </Button>
        ) : null}
      </div>
      {list.length === 0 ? (
        <EmptyState
          title="No discounts yet"
          body="Customers get the single best discount on each dish and on the order. Promo codes compete with automatic discounts."
          action={isAdmin ? <Button onClick={() => setCreating(true)}>Create a discount</Button> : null}
        />
      ) : (
        <Card>
          <ul className="divide-y divide-line">
            {list.map((d) => (
              <DiscountRow key={d.id} d={d} products={items} canEdit={isAdmin} />
            ))}
          </ul>
        </Card>
      )}
      {creating ? <NewDiscountSheet products={items} onClose={() => setCreating(false)} /> : null}
    </div>
  );
}

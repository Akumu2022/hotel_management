import clsx from "clsx";
import { Plus, Trash2 } from "lucide-react";
import { type FormEvent, useState } from "react";

import { Badge, Button, Card, EmptyState, ErrorNote, Field, Input, MoneyInput, Select, Sheet, Skeleton, Switch } from "../components/ui";
import { api } from "../lib/api";
import { money } from "../lib/format";
import type { ExtraGroup, ExtraItem } from "../lib/types";
import { keys, useExtras, useProducts, useSave } from "./hooks";

const IDEAS = ["Size", "Toppings", "Sides", "Sauces", "Drinks", "Cooking"];

/** "Must choose 1", "Optional, up to 3": what the customer is asked, in words. */
export function ruleText(min: number, max: number | null): string {
  const pick = max === 1 ? "pick one" : max ? `up to ${max}` : "any number";
  return min > 0 ? `Required, ${pick}` : `Optional, ${pick}`;
}

function ItemRow({ group, item }: { group: ExtraGroup; item: ExtraItem }) {
  const save = useSave(
    (is_sold_out: boolean) => api.patch(`/hotel/extras/${group.id}/items/${item.id}`, { is_sold_out }),
    [keys.extras],
    false,
  );
  const finished = save.isPending ? !!save.variables : item.is_sold_out;
  return (
    <li className="flex items-center justify-between gap-3 px-3 py-2 text-sm">
      <span className={clsx("min-w-0", finished && "text-muted line-through")}>
        {item.name} <span className="money text-muted">{item.price_delta ? `+${money(item.price_delta)}` : "free"}</span>
      </span>
      <label className="flex shrink-0 items-center gap-2">
        <span className={clsx("text-xs font-semibold", finished ? "text-bad" : "text-ok")}>{finished ? "Finished" : "Available"}</span>
        <Switch label={`${item.name} available`} checked={!finished} onChange={(available) => save.mutate(!available)} disabled={save.isPending} />
      </label>
    </li>
  );
}

type Draft = { id?: string; name: string; price: number | "" };

function GroupSheet({ group, onClose }: { group: ExtraGroup | null; onClose: () => void }) {
  const { data: products } = useProducts(false);
  const [name, setName] = useState(group?.name ?? "");
  const [required, setRequired] = useState((group?.min_picks ?? 0) > 0);
  const [limit, setLimit] = useState<"one" | "upto" | "any">(group ? (group.max_picks === 1 ? "one" : group.max_picks ? "upto" : "any") : "any");
  const [upto, setUpto] = useState(String(group?.max_picks && group.max_picks > 1 ? group.max_picks : 3));
  const [items, setItems] = useState<Draft[]>(group?.items.map((i) => ({ id: i.id, name: i.name, price: i.price_delta })) ?? [{ name: "", price: "" }]);
  const [dishes, setDishes] = useState<Set<string>>(new Set(group?.product_ids ?? []));

  const max = limit === "one" ? 1 : limit === "upto" ? Math.max(2, Math.min(20, Number(upto) || 3)) : null;
  const min = required ? 1 : 0;

  const save = useSave(async () => {
    const clean = items.filter((i) => i.name.trim());
    const rules = { name: name.trim(), min_picks: min, max_picks: max };
    if (!group) {
      return api.post<ExtraGroup>("/hotel/extras", {
        ...rules,
        items: clean.map((i, n) => ({ name: i.name.trim(), price_delta: i.price === "" ? 0 : i.price, sort_order: n })),
        product_ids: [...dishes],
      });
    }
    await api.patch(`/hotel/extras/${group.id}`, { ...rules, product_ids: [...dishes] });
    const keep = new Set(clean.map((i) => i.id).filter(Boolean));
    for (const old of group.items) if (!keep.has(old.id)) await api.del(`/hotel/extras/${group.id}/items/${old.id}`);
    for (const [n, i] of clean.entries()) {
      const body = { name: i.name.trim(), price_delta: i.price === "" ? 0 : i.price, sort_order: n };
      if (i.id) await api.patch(`/hotel/extras/${group.id}/items/${i.id}`, body);
      else await api.post(`/hotel/extras/${group.id}/items`, body);
    }
    return group;
  }, [keys.extras, keys.products]);

  const remove = useSave(() => api.del(`/hotel/extras/${group!.id}`), [keys.extras, keys.products]);

  function submit(e: FormEvent) {
    e.preventDefault();
    save.mutate(undefined, { onSuccess: onClose });
  }
  const set = (n: number, patch: Partial<Draft>) => setItems((list) => list.map((x, i) => (i === n ? { ...x, ...patch } : x)));
  const list = products ?? [];
  const allOn = list.length > 0 && list.every((p) => dishes.has(p.id));
  const toggle = (id: string) =>
    setDishes((s) => {
      const next = new Set(s);
      if (!next.delete(id)) next.add(id);
      return next;
    });

  return (
    <Sheet
      open
      title={group ? `Edit ${group.name}` : "New group of extras"}
      onClose={onClose}
      footer={
        <div className="flex gap-2">
          {group ? (
            <Button
              variant="danger"
              busy={remove.isPending}
              onClick={() => {
                if (window.confirm(`Delete "${group.name}"? Dishes will stop offering it. Past orders are not changed.`)) remove.mutate(undefined, { onSuccess: onClose });
              }}
            >
              Delete
            </Button>
          ) : null}
          <Button className="flex-1" type="submit" form="extras-form" busy={save.isPending} disabled={!name.trim() || !items.some((i) => i.name.trim())}>
            {group ? "Save" : "Create group"}
          </Button>
        </div>
      }
    >
      <form id="extras-form" onSubmit={submit} className="flex flex-col gap-5">
        <Field label="Group name" hint="What the customer sees, e.g. Toppings or Choose your size">
          {(id) => <Input id={id} value={name} onChange={(e) => setName(e.target.value)} maxLength={80} required />}
        </Field>
        {group ? null : (
          <div className="-mt-3 flex flex-wrap gap-1.5">
            {IDEAS.map((s) => (
              <button key={s} type="button" onClick={() => setName(s)} className="rounded-full border border-line bg-surface px-3 py-1 text-xs font-semibold hover:border-brand">
                {s}
              </button>
            ))}
          </div>
        )}

        <section className="flex flex-col gap-3 rounded-xl bg-subtle p-3">
          <p className="text-sm font-semibold">What must the customer do?</p>
          <Select aria-label="Must they choose" value={required ? "yes" : "no"} onChange={(e) => setRequired(e.target.value === "yes")}>
            <option value="no">Optional: they can skip it (e.g. toppings)</option>
            <option value="yes">Required: they must choose (e.g. size)</option>
          </Select>
          <Select aria-label="How many" value={limit} onChange={(e) => setLimit(e.target.value as typeof limit)}>
            <option value="one">Pick one only</option>
            <option value="upto">Pick up to a number</option>
            <option value="any">Pick any number</option>
          </Select>
          {limit === "upto" ? (
            <Field label="Most they can pick">
              {(id) => <Input id={id} inputMode="numeric" value={upto} onChange={(e) => setUpto(e.target.value.replace(/\D/g, ""))} />}
            </Field>
          ) : null}
          <p className="text-xs text-muted">Customers will see: <b>{ruleText(min, max)}</b></p>
        </section>

        <section className="flex flex-col gap-2">
          <p className="text-sm font-semibold">Extras in this group</p>
          {items.map((it, n) => (
            <div key={it.id ?? n} className="grid grid-cols-[1fr_7rem_auto] items-center gap-2">
              <Input aria-label="Extra name" placeholder="e.g. Extra cheese" value={it.name} maxLength={80} onChange={(e) => set(n, { name: e.target.value })} />
              <MoneyInput aria-label="Extra price" placeholder="0" value={it.price} onChange={(v) => set(n, { price: v })} />
              <Button type="button" variant="ghost" size="sm" aria-label="Remove extra" onClick={() => setItems((l) => l.filter((_, i) => i !== n))}>
                <Trash2 className="size-4" />
              </Button>
            </div>
          ))}
          <Button type="button" variant="secondary" size="sm" className="w-fit" onClick={() => setItems((l) => [...l, { name: "", price: "" }])}>
            <Plus className="size-4" /> Add another extra
          </Button>
          <p className="text-xs text-muted">Leave the price empty for a free extra.</p>
        </section>

        <section className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <p className="text-sm font-semibold">Offer on these dishes</p>
            <button type="button" className="text-sm font-semibold text-brand" onClick={() => setDishes(allOn ? new Set() : new Set(list.map((p) => p.id)))}>
              {allOn ? "Clear all" : "Select all"}
            </button>
          </div>
          <ul className="max-h-64 divide-y divide-line overflow-y-auto rounded-lg border border-line">
            {list.map((p) => (
              <li key={p.id}>
                <label className="flex cursor-pointer items-center gap-3 px-3 py-2 text-sm">
                  <input type="checkbox" checked={dishes.has(p.id)} onChange={() => toggle(p.id)} />
                  <span className="flex-1">{p.name}</span>
                  <span className="money text-muted">{money(p.price)}</span>
                </label>
              </li>
            ))}
            {list.length === 0 ? <li className="px-3 py-4 text-sm text-muted">Add dishes first, then come back.</li> : null}
          </ul>
        </section>
        <ErrorNote error={save.error ?? remove.error} />
      </form>
    </Sheet>
  );
}

/** The hotel's menu-level extras: build a group once, attach it to many dishes. */
export function ExtrasPanel({ isAdmin }: { isAdmin: boolean }) {
  const extras = useExtras();
  const { data: products } = useProducts(false);
  const [editing, setEditing] = useState<ExtraGroup | "new" | null>(null);
  const names = new Map((products ?? []).map((p) => [p.id, p.name]));

  if (extras.isLoading) return <Skeleton className="h-40" />;
  if (extras.error) return <ErrorNote error={extras.error} />;
  const groups = extras.data ?? [];

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted">Build a group once (Size, Toppings, Sides) and offer it on as many dishes as you like. Change a price here and every dish updates.</p>
        {isAdmin && groups.length ? (
          <Button onClick={() => setEditing("new")}>
            <Plus className="size-4" /> Group of extras
          </Button>
        ) : null}
      </div>
      {groups.length === 0 ? (
        <EmptyState
          title="No extras yet"
          body="Extras are things a customer adds to a dish: cheese on a pizza, a size, a side. Create a group, add the extras with their prices, then pick the dishes that offer it."
          action={isAdmin ? <Button onClick={() => setEditing("new")}>Create your first group</Button> : null}
        />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {groups.map((g) => (
            <Card key={g.id}>
              <div className="flex items-start justify-between gap-2 border-b border-line px-3 py-2.5">
                <div className="min-w-0">
                  <p className="font-semibold">{g.name}</p>
                  <div className="mt-1 flex flex-wrap gap-1.5">
                    <Badge tone={g.min_picks > 0 ? "brand" : "neutral"}>{ruleText(g.min_picks, g.max_picks)}</Badge>
                    <Badge>
                      {g.product_ids.length} dish{g.product_ids.length === 1 ? "" : "es"}
                    </Badge>
                  </div>
                  {g.product_ids.length ? (
                    <p className="mt-1 line-clamp-2 text-xs text-muted">{g.product_ids.map((id) => names.get(id)).filter(Boolean).join(", ")}</p>
                  ) : (
                    <p className="mt-1 text-xs text-warn">Not on any dish yet. Edit and tick the dishes.</p>
                  )}
                </div>
                {isAdmin ? (
                  <Button variant="ghost" size="sm" onClick={() => setEditing(g)}>
                    Edit
                  </Button>
                ) : null}
              </div>
              <ul className="divide-y divide-line">
                {g.items.map((i) => (
                  <ItemRow key={i.id} group={g} item={i} />
                ))}
                {g.items.length === 0 ? <li className="px-3 py-3 text-sm text-muted">No extras in this group.</li> : null}
              </ul>
            </Card>
          ))}
        </div>
      )}
      {editing ? <GroupSheet group={editing === "new" ? null : editing} onClose={() => setEditing(null)} /> : null}
    </div>
  );
}

/**
 * Quick "finished" list for staff in the middle of service: mark an item finished for today
 * (it comes back by itself at the next opening) or until someone switches it back, and put
 * it back on sale. Opens from the orders screen; the Menu page has the same switch per item.
 */
import clsx from "clsx";
import { Search } from "lucide-react";
import { useMemo, useState } from "react";

import { Badge, ErrorNote, Sheet, Skeleton } from "../components/ui";
import { api } from "../lib/api";
import { money } from "../lib/format";
import type { Product } from "../lib/types";
import { keys, useProducts, useSave, useW } from "./hooks";

/** "Back Tue 07:00": when an item marked finished for today returns by itself. */
export const backAt = (iso: string) =>
  `Back ${new Date(iso).toLocaleString("en-KE", { weekday: "short", hour: "2-digit", minute: "2-digit", hour12: false })}`;

function Row({ product }: { product: Product }) {
  const save = useSave(
    (body: { is_sold_out: boolean; back_tomorrow?: boolean }) => api.patch(`/hotel/products/${product.id}`, body),
    [keys.products],
  );
  const btn = "h-10 rounded-xl border border-line px-3 text-sm font-semibold hover:bg-subtle disabled:opacity-60";
  return (
    <li className="flex flex-col gap-2 py-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0">
        <p className="truncate font-semibold">{product.name}</p>
        <p className="money text-sm text-muted">{money(product.price)}</p>
      </div>
      {product.is_sold_out ? (
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="bad">{product.sold_out_until ? backAt(product.sold_out_until) : "Finished"}</Badge>
          <button disabled={save.isPending} onClick={() => save.mutate({ is_sold_out: false })} className={clsx(btn, "bg-ok text-white hover:bg-ok")}>
            Back on sale
          </button>
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          <button disabled={save.isPending} onClick={() => save.mutate({ is_sold_out: true, back_tomorrow: true })} className={btn}>
            Finished for today
          </button>
          <button disabled={save.isPending} onClick={() => save.mutate({ is_sold_out: true })} className={btn}>
            Finished until I switch it back
          </button>
        </div>
      )}
      <ErrorNote error={save.error} />
    </li>
  );
}

export function StockSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const w = useW();
  const products = useProducts();
  const [q, setQ] = useState("");
  const list = useMemo(() => {
    const term = q.trim().toLowerCase();
    return (products.data ?? [])
      .filter((p) => !term || p.name.toLowerCase().includes(term))
      .sort((a, b) => Number(b.is_sold_out) - Number(a.is_sold_out) || a.name.localeCompare(b.name));
  }, [products.data, q]);
  const finished = (products.data ?? []).filter((p) => p.is_sold_out).length;
  return (
    <Sheet open={open} onClose={onClose} title={w("Mark dishes finished")}>
      <p className="mb-3 text-sm text-muted">
        {finished ? `${finished} finished right now. ` : ""}
        Customers cannot order a finished item. "Finished for today" puts it back on sale by itself at the next opening.
      </p>
      <label className="relative mb-2 block">
        <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted" />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search" aria-label="Search items" className="h-11 w-full rounded-xl border border-line bg-surface pr-3 pl-9 text-sm outline-none focus:border-brand" />
      </label>
      {products.isLoading ? (
        <Skeleton className="h-40" />
      ) : list.length ? (
        <ul className="divide-y divide-line">{list.map((p) => <Row key={p.id} product={p} />)}</ul>
      ) : (
        <p className="py-8 text-center text-sm text-muted">Nothing found.</p>
      )}
    </Sheet>
  );
}

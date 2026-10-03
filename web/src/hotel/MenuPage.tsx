import clsx from "clsx";
import { CheckCircle2, Circle, Pencil, Plus } from "lucide-react";
import { useMemo, useState } from "react";

import { Badge, Button, Card, EmptyState, ErrorNote, Skeleton, Switch } from "../components/ui";
import { api } from "../lib/api";
import { money } from "../lib/format";
import type { Category, Product } from "../lib/types";
import { CategorySheet } from "./CategorySheet";
import { FoodImage } from "../customer/FoodImage";
import { ProductSheet } from "./ProductSheet";
import { keys, useCategories, useHotelSettings, useIsAdmin, useProducts, useSave } from "./hooks";

/** Onboarding checklist (Bonfol "Setup store 6/7"), hidden once complete. */
function SetupChecklist({ categories, products }: { categories: Category[]; products: Product[] }) {
  const { data: settings } = useHotelSettings();
  const steps = [
    { done: !!settings?.hours.length, label: "Set opening hours (Settings)" },
    { done: categories.length > 0, label: "Add menu categories" },
    { done: products.length >= 5, label: "Add at least 5 dishes" },
    { done: products.length > 0 && products.every((p) => p.image_url), label: "Add a photo to every dish" },
    { done: !!settings?.cover_url, label: "Add a cover photo (Settings)" },
  ];
  const done = steps.filter((s) => s.done).length;
  if (done === steps.length) return null;
  return (
    <Card className="mb-4 p-4">
      <div className="mb-2 flex items-center justify-between">
        <p className="font-semibold">Set up your menu</p>
        <p className="text-sm text-muted">
          {done} / {steps.length} done
        </p>
      </div>
      <div className="mb-3 h-2 overflow-hidden rounded-full bg-page">
        <div className="h-full bg-brand" style={{ width: `${(done / steps.length) * 100}%` }} />
      </div>
      <ul className="grid gap-1.5 sm:grid-cols-2">
        {steps.map((s) => (
          <li key={s.label} className={clsx("flex items-center gap-2 text-sm", s.done && "text-muted line-through")}>
            {s.done ? <CheckCircle2 className="size-4 text-ok" /> : <Circle className="size-4 text-muted" />}
            {s.label}
          </li>
        ))}
      </ul>
    </Card>
  );
}

function SoldOutSwitch({ product }: { product: Product }) {
  const save = useSave(
    (is_sold_out: boolean) => api.patch(`/hotel/products/${product.id}`, { is_sold_out }),
    [keys.products],
  );
  const soldOut = save.isPending ? !!save.variables : product.is_sold_out;
  return (
    <label className="flex w-full items-center justify-between gap-2">
      <Switch
        label={`${product.name} available`}
        checked={!soldOut}
        onChange={(available) => save.mutate(!available)}
        disabled={save.isPending}
      />
      <span className={clsx("order-first text-xs font-semibold", soldOut ? "text-bad" : "text-ok")}>
        {soldOut ? "Sold out" : "Available"}
      </span>
    </label>
  );
}

function ProductTile({ product, onEdit }: { product: Product; onEdit?: () => void }) {
  const options = product.options.filter((o) => !o.is_archived).length;
  return (
    <article className={clsx("flex min-w-0 flex-col rounded-2xl border border-line bg-surface p-2 transition-shadow hover:shadow-md", product.is_archived && "opacity-60")}>
      <button type="button" onClick={onEdit} disabled={!onEdit} className="relative block aspect-[4/3] w-full overflow-hidden rounded-xl">
        <FoodImage src={product.thumb_url} name={product.name} dim={product.is_sold_out} emojiSize="text-5xl" />
        <span className="absolute top-2 left-2 flex flex-wrap gap-1">
          {product.is_archived ? <Badge tone="warn">Archived</Badge> : null}
          {!product.image_url ? <Badge tone="warn">No photo</Badge> : null}
          {options ? <Badge>{options} option{options > 1 ? "s" : ""}</Badge> : null}
        </span>
        {onEdit ? (
          <span className="absolute top-2 right-2 flex size-8 items-center justify-center rounded-lg bg-surface/95 text-ink shadow-sm">
            <Pencil className="size-4" />
          </span>
        ) : null}
      </button>
      <div className="flex flex-1 flex-col gap-2 px-1.5 pt-2.5 pb-1">
        <div className="min-w-0">
          <h3 className="line-clamp-2 text-sm leading-snug font-semibold">{product.name}</h3>
          <p className="money mt-0.5 text-[1.0625rem] font-bold">{money(product.price)}</p>
        </div>
        {!product.is_archived ? (
          <div className="mt-auto flex items-center justify-between rounded-xl bg-subtle px-3 py-2">
            <SoldOutSwitch product={product} />
          </div>
        ) : null}
      </div>
    </article>
  );
}

export function MenuPage() {
  const isAdmin = useIsAdmin();
  const [showArchived, setShowArchived] = useState(false);
  const categories = useCategories();
  const products = useProducts(showArchived);
  const [activeCat, setActiveCat] = useState<string | "all">("all");
  const [editing, setEditing] = useState<Product | "new" | null>(null);
  const [editingCat, setEditingCat] = useState<Category | "new" | null>(null);

  const grouped = useMemo(() => {
    const cats = categories.data ?? [];
    const list = products.data ?? [];
    return cats
      .filter((c) => activeCat === "all" || c.id === activeCat)
      .map((c) => ({ category: c, products: list.filter((p) => p.category_id === c.id) }));
  }, [categories.data, products.data, activeCat]);

  if (categories.isLoading || products.isLoading) {
    return (
      <div className="flex flex-col gap-3">
        <Skeleton className="h-10 w-48" />
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-20" />
        ))}
      </div>
    );
  }
  if (categories.error || products.error) return <ErrorNote error={categories.error ?? products.error} />;

  const cats = categories.data!;
  const activeProducts = (products.data ?? []).filter((p) => !p.is_archived);

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted">Tap a dish to edit it. Flip the switch when something runs out.</p>
        {isAdmin ? (
          <div className="flex gap-2">
            <Button variant="secondary" onClick={() => setEditingCat("new")}>
              <Plus className="size-4" /> Category
            </Button>
            <Button onClick={() => setEditing("new")} disabled={!cats.length}>
              <Plus className="size-4" /> Dish
            </Button>
          </div>
        ) : null}
      </div>

      {isAdmin ? <SetupChecklist categories={cats} products={activeProducts} /> : null}

      {cats.length === 0 ? (
        <EmptyState
          title="No categories yet"
          body="Start with categories such as Breakfast, Mains or Drinks, then add dishes to them."
          action={isAdmin ? <Button onClick={() => setEditingCat("new")}>Add a category</Button> : null}
        />
      ) : (
        <>
          <div className="sticky top-[3.5625rem] z-20 -mx-4 mb-3 flex gap-2 overflow-x-auto bg-page px-4 py-2">
            {[{ id: "all", name: "All" } as const, ...cats].map((c) => (
              <button
                key={c.id}
                onClick={() => setActiveCat(c.id)}
                className={clsx(
                  "h-9 shrink-0 rounded-full border px-4 text-sm font-medium",
                  activeCat === c.id ? "border-brand bg-brand text-white" : "border-line bg-surface",
                )}
              >
                {c.name}
              </button>
            ))}
          </div>
          <label className="mb-3 flex items-center gap-2 text-sm text-muted">
            <input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} />
            Show archived dishes
          </label>

          <div className="flex flex-col gap-4">
            {grouped.map(({ category, products: items }) => (
              <Card key={category.id}>
                <div className="flex items-center justify-between border-b border-line px-3 py-2">
                  <div>
                    <p className="font-semibold">{category.name}</p>
                    {category.available_from ? (
                      <p className="text-xs text-muted">
                        Shown {category.available_from.slice(0, 5)}–{category.available_to?.slice(0, 5)}
                      </p>
                    ) : null}
                  </div>
                  {isAdmin ? (
                    <Button variant="ghost" size="sm" onClick={() => setEditingCat(category)}>
                      Edit
                    </Button>
                  ) : null}
                </div>
                {items.length ? (
                  <div className="grid grid-cols-2 gap-3 p-3 sm:grid-cols-3 xl:grid-cols-4">
                    {items.map((p) => (
                      <ProductTile key={p.id} product={p} onEdit={isAdmin ? () => setEditing(p) : undefined} />
                    ))}
                  </div>
                ) : (
                  <p className="p-4 text-sm text-muted">No dishes in this category.</p>
                )}
              </Card>
            ))}
          </div>
        </>
      )}

      {editing ? (
        <ProductSheet
          product={editing === "new" ? null : editing}
          categories={cats}
          defaultCategory={activeCat !== "all" ? activeCat : cats[0]?.id}
          onClose={() => setEditing(null)}
        />
      ) : null}
      {editingCat ? (
        <CategorySheet category={editingCat === "new" ? null : editingCat} onClose={() => setEditingCat(null)} />
      ) : null}
    </div>
  );
}

import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowLeft, Bike, ChevronDown, Clock, Minus, Phone, Plus, Search, Store, Timer, X } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { ErrorNote, Skeleton } from "../components/ui";
import { api } from "../lib/api";
import { hhmm, money } from "../lib/format";
import { tr, useT } from "../lib/i18n";
import { ConfirmDialog, HotelCover, JourneySteps, VerifiedBadge, categoryEmoji, etaText, toast } from "./bits";
import { TopBar } from "./CustomerLayout";
import { FoodImage } from "./FoodImage";
import { cart, useCart, useOrderMode } from "./store";
import type { Menu, MenuCategory, MenuProduct, PublicHotel } from "./types";

type Sort = "popular" | "low" | "high";

function nowInNairobi(): string {
  return new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: "Africa/Nairobi", hour12: false }).format(new Date());
}

function categoryOpen(c: MenuCategory, now: string): boolean {
  if (!c.available_from || !c.available_to) return true;
  const from = hhmm(c.available_from);
  const to = hhmm(c.available_to);
  return from < to ? now >= from && now < to : now >= from || now < to;
}

const timeFmt = new Intl.DateTimeFormat("en-KE", { hour: "2-digit", minute: "2-digit", timeZone: "Africa/Nairobi" });

export function StatusChip({ hotel }: { hotel: PublicHotel }) {
  const t = useT();
  const map = {
    open: { text: t("Open now"), cls: "bg-ok-soft text-ok" },
    closing_soon: { text: t("Closes {time}", { time: hotel.closes_at ? timeFmt.format(new Date(hotel.closes_at)) : "" }), cls: "bg-warn-soft text-warn" },
    closed: { text: hotel.opens_at ? t("Opens {time}", { time: timeFmt.format(new Date(hotel.opens_at)) }) : t("Closed"), cls: "bg-subtle text-muted" },
    paused: { text: t("Not taking orders"), cls: "bg-subtle text-muted" },
    not_accepting: { text: t("Not taking orders"), cls: "bg-subtle text-muted" },
  }[hotel.state];
  return (
    <span className={clsx("inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold whitespace-nowrap", map.cls)}>
      <span className="size-1.5 rounded-full bg-current" />
      {map.text}
    </span>
  );
}

type Item = MenuProduct & { categoryOpen: boolean; window: string | null };

function ProductCard({
  item,
  hotel,
  canOrder,
  onOptions,
  onConflict,
}: {
  item: Item;
  hotel: PublicHotel;
  canOrder: boolean;
  onOptions: () => void;
  onConflict: (retry: () => void) => void;
}) {
  const t = useT();
  const c = useCart();
  const key = cart.lineKey(item.id, []);
  const line = c.lines.find((l) => l.key === key);
  const inCart = c.lines.filter((l) => l.product_id === item.id).reduce((n, l) => n + l.quantity, 0);
  const unavailable = item.is_sold_out || !item.categoryOpen;
  const price = item.discount_price ?? item.price;
  const pct = item.discount_price !== null ? Math.round((1 - item.discount_price / item.price) * 100) : 0;

  function addPlain() {
    const add = () =>
      cart.add(hotel, { product_id: item.id, option_ids: [], name: item.name, options_label: "", unit_price: price, thumb_url: item.thumb_url });
    if (add()) toast(tr("Added {name}", { name: item.name }));
    else onConflict(() => (cart.clear(), add(), toast(tr("Added {name}", { name: item.name }))));
  }

  return (
    <article className={clsx("group flex min-w-0 flex-col rounded-2xl border border-line bg-surface p-2 transition-shadow hover:shadow-md", unavailable && "opacity-70")}>
      <button
        type="button"
        onClick={item.options.length && !unavailable && canOrder ? onOptions : undefined}
        className="relative block aspect-[4/3] w-full overflow-hidden rounded-xl"
        tabIndex={-1}
      >
        <FoodImage src={item.image_url ?? item.thumb_url} name={item.name} dim={unavailable} className="transition-transform duration-300 group-hover:scale-[1.03]" />
        <span className="absolute top-2.5 left-2.5 flex gap-1.5">
          {item.is_sold_out ? (
            <span className="rounded-md bg-surface px-2 py-1 text-xs font-semibold text-bad shadow-sm">{t("Sold out")}</span>
          ) : !item.categoryOpen ? (
            <span className="rounded-md bg-surface px-2 py-1 text-xs font-semibold text-ink shadow-sm">{item.window}</span>
          ) : pct > 0 ? (
            <span className="rounded-md bg-brand px-2 py-1 text-xs font-semibold text-white shadow-sm">−{pct}%</span>
          ) : null}
          {inCart && item.options.length ? (
            <span className="rounded-md bg-surface px-2 py-1 text-xs font-semibold text-brand shadow-sm">{t("{n} in order", { n: inCart })}</span>
          ) : null}
        </span>
      </button>
      {/* Phones: name, price, then a full-width button. Wider: button beside the price. */}
      <div className="flex flex-1 flex-col gap-2.5 px-1 pt-2.5 pb-0.5 sm:flex-row sm:items-end sm:justify-between sm:px-1.5 sm:pt-3">
        <div className="min-w-0">
          <h3 className="line-clamp-2 text-[0.875rem] leading-snug font-medium">{item.name}</h3>
          <p className="money mt-1 flex flex-wrap items-baseline gap-x-1.5 text-[1rem] font-semibold whitespace-nowrap sm:text-[1.0625rem]">
            {money(price)}
            {pct > 0 ? <s className="text-xs font-normal text-muted">{money(item.price)}</s> : null}
          </p>
        </div>
        {unavailable || !canOrder ? null : line && !item.options.length ? (
          <div className="flex h-10 shrink-0 items-center justify-between rounded-lg border border-brand bg-brand-soft">
            <button className="flex h-full w-9 items-center justify-center text-brand" aria-label={`Remove one ${item.name}`} onClick={() => cart.setQuantity(key, line.quantity - 1)}>
              <Minus className="size-4" />
            </button>
            <span className="money w-5 text-center text-sm font-bold text-brand">{line.quantity}</span>
            <button
              className="flex h-full w-9 items-center justify-center text-brand disabled:opacity-40"
              aria-label={`Add one ${item.name}`}
              disabled={line.quantity >= 20}
              onClick={() => cart.setQuantity(key, line.quantity + 1)}
            >
              <Plus className="size-4" />
            </button>
          </div>
        ) : (
          <button
            onClick={item.options.length ? onOptions : addPlain}
            className="h-10 w-full shrink-0 rounded-lg border border-line bg-surface px-4 text-sm font-medium transition-colors hover:border-brand hover:text-brand sm:w-auto"
          >
            {t("Add")}
          </button>
        )}
      </div>
    </article>
  );
}

function OptionsSheet({ hotel, product, onClose, onConflict }: { hotel: PublicHotel; product: MenuProduct; onClose: () => void; onConflict: (retry: () => void) => void }) {
  const t = useT();
  const [chosen, setChosen] = useState<string[]>([]);
  const [qty, setQty] = useState(1);
  const groups = useMemo(() => {
    const map = new Map<string, MenuProduct["options"]>();
    product.options.forEach((o) => map.set(o.group_name, [...(map.get(o.group_name) ?? []), o]));
    return [...map.entries()];
  }, [product]);
  const base = product.discount_price ?? product.price;
  const unit = base + product.options.filter((o) => chosen.includes(o.id)).reduce((n, o) => n + o.price_delta, 0);
  const add = () =>
    cart.add(
      hotel,
      {
        product_id: product.id,
        option_ids: chosen,
        name: product.name,
        options_label: product.options.filter((o) => chosen.includes(o.id)).map((o) => o.name).join(", "),
        unit_price: unit,
        thumb_url: product.thumb_url,
      },
      qty,
    );

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 sm:items-center sm:p-6" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-label={product.name} onClick={(e) => e.stopPropagation()} className="flex max-h-[92dvh] w-full max-w-md flex-col overflow-hidden rounded-t-3xl bg-surface sm:rounded-3xl">
        <div className="relative aspect-[16/10] shrink-0">
          <FoodImage src={product.image_url} name={product.name} emojiSize="text-7xl" />
          <button onClick={onClose} aria-label="Close" className="absolute top-3 right-3 flex size-10 items-center justify-center rounded-full bg-surface shadow">
            <X className="size-5" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-5">
          <h2 className="text-xl font-semibold">{product.name}</h2>
          {product.description ? <p className="mt-1 text-sm text-muted">{product.description}</p> : null}
          <p className="money mt-2 text-lg font-semibold">{money(base)}</p>
          {groups.map(([group, opts]) => (
            <fieldset key={group} className="mt-5">
              <legend className="mb-2.5 text-sm font-semibold">{group} <span className="font-normal text-muted">· {t("optional")}</span></legend>
              <div className="flex flex-col gap-2">
                {opts.map((o) => {
                  const on = chosen.includes(o.id);
                  return (
                    <label key={o.id} className={clsx("flex h-12 cursor-pointer items-center justify-between rounded-xl border px-4 text-sm", on ? "border-brand bg-brand-soft" : "border-line")}>
                      <span className="flex items-center gap-3">
                        <input type="checkbox" checked={on} onChange={() => setChosen((c) => (on ? c.filter((x) => x !== o.id) : [...c, o.id]))} className="size-4 accent-[#dc4b12]" />
                        {o.name}
                      </span>
                      <span className="money text-muted">{o.price_delta ? `+${money(o.price_delta)}` : t("Free")}</span>
                    </label>
                  );
                })}
              </div>
            </fieldset>
          ))}
        </div>
        <div className="flex items-center gap-3 border-t border-line p-4 pb-[max(1rem,env(safe-area-inset-bottom))]">
          <div className="flex h-12 items-center rounded-xl border border-line">
            <button className="flex h-full w-11 items-center justify-center" aria-label="Fewer" onClick={() => setQty((q) => Math.max(1, q - 1))}><Minus className="size-4" /></button>
            <span className="money w-6 text-center font-semibold">{qty}</span>
            <button className="flex h-full w-11 items-center justify-center" aria-label="More" onClick={() => setQty((q) => Math.min(20, q + 1))}><Plus className="size-4" /></button>
          </div>
          <button
            className="h-12 flex-1 rounded-xl bg-brand font-semibold text-white hover:bg-brand-hover"
            onClick={() => {
              if (add()) {
                toast(tr("Added {name}", { name: `${qty}× ${product.name}` }));
                onClose();
              } else onConflict(() => (cart.clear(), add(), toast(tr("Added {name}", { name: `${qty}× ${product.name}` })), onClose()));
            }}
          >
            {t("Add to order")} · <span className="money">{money(unit * qty)}</span>
          </button>
        </div>
      </div>
    </div>
  );
}

type Group = { id: string; name: string; items: Item[] };

export function HotelPage() {
  const { slug = "" } = useParams();
  const menu = useQuery({ queryKey: ["menu", slug], queryFn: () => api.get<Menu>(`/hotels/${slug}/menu`) });
  const [category, setCategory] = useState("all");
  const [params] = useSearchParams();
  const [search, setSearch] = useState(params.get("q") ?? "");
  const [sort, setSort] = useState<Sort>("popular");
  const [optionsFor, setOptionsFor] = useState<MenuProduct | null>(null);
  const [conflict, setConflict] = useState<null | (() => void)>(null);
  const c = useCart();
  const t = useT();
  const mode = useOrderMode();

  const groups: Group[] = useMemo(() => {
    if (!menu.data) return [];
    const now = nowInNairobi();
    const term = search.trim().toLowerCase();
    const eff = (p: Item) => p.discount_price ?? p.price;
    const out = menu.data.categories
      .filter((cat) => category === "all" || cat.id === category)
      .map((cat) => {
        let items: Item[] = cat.products.map((p) => ({
          ...p,
          categoryOpen: categoryOpen(cat, now),
          window: cat.available_from ? `${hhmm(cat.available_from)}–${hhmm(cat.available_to)}` : null,
        }));
        if (term) items = items.filter((p) => p.name.toLowerCase().includes(term) || p.description.toLowerCase().includes(term));
        return { id: cat.id, name: cat.name, items };
      })
      .filter((g) => g.items.length);
    if (sort === "popular") return out;
    // Sorting by price reads better as one list.
    const all = out.flatMap((g) => g.items).sort((a, b) => (sort === "low" ? eff(a) - eff(b) : eff(b) - eff(a)));
    return [{ id: "sorted", name: sort === "low" ? tr("Lowest price first") : tr("Highest price first"), items: all }];
  }, [menu.data, category, search, sort]);

  if (menu.error) return (<><TopBar /><div className="p-6"><ErrorNote error={menu.error} /></div></>);

  const hotel = menu.data?.hotel;
  const showHeadings = category === "all" || sort !== "popular";

  return (
    <>
      <TopBar />
      <div className="flex-1 px-4 pt-4 pb-28 sm:px-6 lg:pb-8">
        <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-6">
          <Link to="/" className="flex h-10 w-fit shrink-0 items-center gap-2 rounded-xl border border-line bg-surface px-3.5 text-sm font-semibold hover:bg-subtle">
            <ArrowLeft className="size-4" /> {t("All hotels")}
          </Link>
          <JourneySteps step={0} className="sm:max-w-xl" />
        </div>
        {/* Hero cover with the hotel name */}
        {hotel ? (
          <HotelCover src={hotel.cover_url} name={hotel.name} accent={hotel.accent_color} size="lg" className="h-48 rounded-3xl sm:h-60">
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <StatusChip hotel={hotel} />
              {hotel.verified ? <VerifiedBadge /> : null}
              <span className="flex items-center gap-1.5 rounded-full bg-surface px-2.5 py-1 text-xs font-semibold text-ink">
                <Timer className="size-3.5" /> {t("{min} min", { min: etaText(hotel.prep_minutes, mode) })}
              </span>
              <span className="flex items-center gap-1.5 rounded-full bg-white/15 px-2.5 py-1 text-xs font-medium text-white backdrop-blur"><Bike className="size-3.5" /> {t("Delivery")}</span>
              <span className="flex items-center gap-1.5 rounded-full bg-white/15 px-2.5 py-1 text-xs font-medium text-white backdrop-blur"><Store className="size-3.5" /> {t("Pickup")}</span>
              <a href={`tel:+${hotel.phone}`} className="flex items-center gap-1.5 rounded-full bg-surface px-3 py-1 text-xs font-semibold text-ink"><Phone className="size-3.5" /> {t("Call")}</a>
            </div>
          </HotelCover>
        ) : (
          <Skeleton className="h-48 rounded-3xl sm:h-60" />
        )}

        {hotel && !hotel.is_open ? (
          <div className="mt-4 flex items-center gap-2 rounded-2xl bg-warn-soft px-4 py-3 text-sm font-medium text-warn">
            <Clock className="size-4" /> {t("{name} isn't taking orders right now. You can still look at the menu.", { name: hotel.name })}
          </div>
        ) : null}

        {/* Toolbar */}
        <div className="sticky top-0 z-30 -mx-4 mt-4 flex flex-col gap-3 bg-surface/95 px-4 py-3 backdrop-blur sm:-mx-6 sm:px-6 md:flex-row md:items-center md:justify-between">
          <div className="no-scrollbar flex gap-1 overflow-x-auto rounded-2xl bg-subtle p-1">
            {[{ id: "all", name: t("All Menu") }, ...(menu.data?.categories ?? [])].map((cat) => (
              <button
                key={cat.id}
                onClick={() => setCategory(cat.id)}
                className={clsx(
                  "flex h-10 shrink-0 items-center gap-1.5 rounded-xl px-3.5 text-[0.8125rem] font-semibold whitespace-nowrap transition-all",
                  category === cat.id ? "bg-surface text-ink shadow-sm" : "text-muted hover:text-ink",
                )}
              >
                <span className="text-base">{cat.id === "all" ? "🍽️" : categoryEmoji(cat.name)}</span>
                {cat.name}
              </button>
            ))}
          </div>
          <div className="flex gap-2">
            <label className="relative flex-1 md:w-56 md:flex-none">
              <Search className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-muted" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={t("Search dishes")}
                aria-label="Search the menu"
                className="h-11 w-full rounded-xl border border-line bg-surface pr-3 pl-10 text-sm outline-none focus:border-brand"
              />
            </label>
            <label className="relative">
              <select
                value={sort}
                onChange={(e) => setSort(e.target.value as Sort)}
                aria-label="Sort"
                className="h-11 appearance-none rounded-xl border border-line bg-surface pr-9 pl-3.5 text-sm font-medium outline-none focus:border-brand"
              >
                <option value="popular">{t("By category")}</option>
                <option value="low">{t("Price: low to high")}</option>
                <option value="high">{t("Price: high to low")}</option>
              </select>
              <ChevronDown className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-muted" />
            </label>
          </div>
        </div>

        {/* Grid */}
        <div className="mt-2">
          {menu.isLoading ? (
            <div className="grid grid-cols-2 gap-3 sm:gap-4 md:grid-cols-3 xl:grid-cols-4">
              {Array.from({ length: 8 }, (_, i) => (
                <div key={i} className="rounded-2xl border border-line p-2">
                  <Skeleton className="aspect-[4/3] rounded-xl" />
                  <Skeleton className="mt-3 h-4 w-2/3" />
                  <Skeleton className="mt-2 h-5 w-1/3" />
                </div>
              ))}
            </div>
          ) : groups.length === 0 ? (
            <div className="flex flex-col items-center gap-2 py-16 text-center">
              <span className="text-5xl">🔎</span>
              <p className="font-semibold">{search ? t("No dishes match “{q}”", { q: search }) : t("No dishes here yet")}</p>
              {search ? <button onClick={() => setSearch("")} className="text-sm font-semibold text-brand">{t("Clear search")}</button> : null}
            </div>
          ) : (
            groups.map((g) => (
              <section key={g.id} className="mb-6">
                {showHeadings ? (
                  <h2 className="mb-3 flex items-center gap-2 text-lg font-bold">
                    <span>{g.id === "sorted" ? "↕️" : categoryEmoji(g.name)}</span> {g.name}
                    <span className="text-sm font-medium text-muted">· {g.items.length}</span>
                  </h2>
                ) : null}
                <div className="grid grid-cols-2 gap-3 sm:gap-4 md:grid-cols-3 xl:grid-cols-4">
                  {g.items.map((item) => (
                    <ProductCard
                      key={item.id}
                      item={item}
                      hotel={hotel!}
                      canOrder={hotel!.is_open}
                      onOptions={() => setOptionsFor(item)}
                      onConflict={(retry) => setConflict(() => retry)}
                    />
                  ))}
                </div>
              </section>
            ))
          )}
        </div>
      </div>

      {optionsFor && hotel ? (
        <OptionsSheet hotel={hotel} product={optionsFor} onClose={() => setOptionsFor(null)} onConflict={(retry) => setConflict(() => retry)} />
      ) : null}

      <ConfirmDialog
        open={!!conflict}
        emoji="🛒"
        title={t("Start a new order?")}
        body={t("Your order has dishes from {hotel}. You can order from one hotel at a time, so we'll clear it first.", { hotel: c.hotel_name ?? "" })}
        confirm={t("Start new order")}
        cancel={t("Keep my order")}
        onConfirm={() => conflict?.()}
        onClose={() => setConflict(null)}
      />
    </>
  );
}

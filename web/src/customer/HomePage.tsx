import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowRight, Bike, Clock, Flame, Search, Star, Store, Timer, UtensilsCrossed, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { ErrorNote, Skeleton } from "../components/ui";
import { api } from "../lib/api";
import { useT } from "../lib/i18n";
import { TopBar } from "./CustomerLayout";
import { HotelCover, VerifiedBadge, etaText } from "./bits";
import { useOrderMode } from "./store";
import { InstallBanner } from "./InstallBanner";
import { StatusChip } from "./HotelPage";
import { useRecentOrders } from "./store";
import { money } from "../lib/format";
import type { PublicHotel, PublicOffer, SearchHit } from "./types";

function HotelCard({ hotel }: { hotel: PublicHotel }) {
  const t = useT();
  const mode = useOrderMode();
  return (
    <Link
      to={`/h/${hotel.slug}`}
      className={clsx(
        "group block overflow-hidden rounded-2xl bg-surface shadow-sm ring-1 ring-line transition-all hover:-translate-y-0.5 hover:shadow-xl",
        !hotel.is_open && "opacity-90",
      )}
    >
      <HotelCover src={hotel.cover_url} name={hotel.name} accent={hotel.accent_color} dim={!hotel.is_open} className="aspect-[16/11]">
        <p className="mt-1.5 flex items-center gap-3 text-xs font-medium text-white/85">
          <span className="flex items-center gap-1"><Bike className="size-3.5" /> {t("Delivery")}</span>
          <span className="flex items-center gap-1"><Store className="size-3.5" /> {t("Pickup")}</span>
          <span className="flex items-center gap-1"><UtensilsCrossed className="size-3.5" /> {t("Eat in")}</span>
        </p>
      </HotelCover>
      <div className="flex items-center justify-between gap-2 px-4 py-3">
        <span className="flex min-w-0 flex-wrap items-center gap-1.5 whitespace-nowrap">
          <StatusChip hotel={hotel} />
          {hotel.verified ? <VerifiedBadge /> : null}
          {hotel.rating_count ? (
            <span className="flex items-center gap-1 rounded-full bg-subtle px-2.5 py-1 text-xs font-semibold text-ink" title={t("{n} ratings", { n: hotel.rating_count })}>
              <Star className="size-3.5 fill-warn text-warn" /> {hotel.rating?.toFixed(1)}
            </span>
          ) : null}
          <span className="flex items-center gap-1 rounded-full bg-subtle px-2.5 py-1 text-xs font-semibold text-ink" title={mode === "delivery" ? t("Delivery") : t("Pickup")}>
            <Timer className="size-3.5" /> {t("{min} min", { min: etaText(hotel.prep_minutes, mode) })}
          </span>
        </span>
        <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-brand text-white shadow-md shadow-brand/25 transition-transform group-hover:translate-x-0.5" aria-label={t("View menu")}>
          <ArrowRight className="size-5" />
        </span>
      </div>
    </Link>
  );
}

/** "PIZZA WEDNESDAY\nBuy one Get One Free!" -> big headline + highlighted sub-line. */
function splitTitle(title: string): [string, string] {
  const [head, ...rest] = title.split("\n");
  return [head.trim(), rest.join(" ").trim()];
}

function OfferBanner({ offer: o, cta }: { offer: PublicOffer; cta: string }) {
  const [head, sub] = splitTitle(o.title);
  const left = o.ends_at ? Math.max(0, new Date(o.ends_at).getTime() - Date.now()) : null;
  const ending = left != null && left < 24 * 3600_000 ? (left < 3600_000 ? `${Math.max(1, Math.round(left / 60_000))} min left` : `${Math.round(left / 3600_000)} h left`) : null;
  return (
    <Link
      to={`/h/${o.hotel_slug}`}
      className="group relative flex h-48 w-[90%] shrink-0 snap-center overflow-hidden rounded-3xl bg-gradient-to-br from-brand to-[#7a1d00] text-white shadow-lg shadow-brand/20 sm:w-[32rem]"
    >
      {o.image_url ? (
        // The photo fills all the space the text doesn't use, fading into the colour behind the words.
        <img
          src={o.image_url}
          alt=""
          className="absolute inset-y-0 right-0 h-full w-[68%] object-cover transition-transform duration-500 group-hover:scale-105"
          style={{ maskImage: "linear-gradient(to right, transparent, #000 38%)", WebkitMaskImage: "linear-gradient(to right, transparent, #000 38%)" }}
        />
      ) : (
        <span className="absolute top-3 right-4 text-8xl select-none">🔥</span>
      )}
      <span className="pointer-events-none absolute inset-0 bg-gradient-to-r from-black/50 via-black/10 to-transparent" />
      <span className="relative flex w-[57%] flex-col justify-between p-4">
        <span className="flex flex-wrap items-center gap-1.5">
          <span className="truncate rounded-full bg-white/95 px-2.5 py-1 text-xs font-bold text-ink">{o.hotel_name}</span>
          {ending ? <span className="rounded-full bg-black/45 px-2 py-1 text-xs font-semibold backdrop-blur">⏱ {ending}</span> : null}
        </span>
        <span className="block">
          <span className="block text-2xl leading-[1.05] font-extrabold tracking-tight uppercase drop-shadow-[0_2px_6px_rgba(0,0,0,0.45)] sm:text-3xl">{head}</span>
          {sub ? <span className="mt-2 inline-block rounded-lg bg-amber-300 px-2.5 py-1 text-sm font-extrabold text-ink">{sub}</span> : null}
        </span>
        <span className="flex items-center gap-1 text-sm font-bold">
          {cta} <ArrowRight className="size-4 transition-transform group-hover:translate-x-1" />
        </span>
      </span>
    </Link>
  );
}

function DishSearch({ q }: { q: string }) {
  const t = useT();
  const [term, setTerm] = useState(q);
  useEffect(() => {
    const id = setTimeout(() => setTerm(q.trim()), 250);
    return () => clearTimeout(id);
  }, [q]);
  const hits = useQuery({
    queryKey: ["search", term],
    queryFn: () => api.get<SearchHit[]>(`/search?q=${encodeURIComponent(term)}`),
    enabled: term.length > 0,
    placeholderData: (prev) => prev,
  });
  if (!term) return null;
  if (hits.isLoading) return <Skeleton className="h-24 rounded-2xl" />;
  if (hits.error) return <ErrorNote error={hits.error} />;
  if (!hits.data?.length)
    return <p className="rounded-2xl border border-dashed border-line bg-surface px-4 py-8 text-center text-sm text-muted">{t("No dish matches “{q}”", { q: term })}</p>;
  return (
    <ul className="divide-y divide-line overflow-hidden rounded-2xl bg-surface ring-1 ring-line">
      {hits.data.map((h) => (
        <li key={h.product_id}>
          <Link to={`/h/${h.hotel_slug}?q=${encodeURIComponent(term)}`} className="flex items-center gap-3 p-3 hover:bg-subtle">
            {h.thumb_url ? (
              <img src={h.thumb_url} alt="" className="size-14 shrink-0 rounded-xl object-cover" />
            ) : (
              <span className="flex size-14 shrink-0 items-center justify-center rounded-xl bg-subtle text-2xl">🍽️</span>
            )}
            <span className="min-w-0 flex-1">
              <span className="block truncate font-semibold">{h.name}</span>
              <span className="block truncate text-xs text-muted">{h.hotel_name} · {h.category}</span>
            </span>
            <span className="shrink-0 text-right text-sm font-bold">
              {h.is_sold_out ? <span className="text-xs font-semibold text-muted">{t("Sold out")}</span> : money(h.price)}
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

export function HomePage() {
  const t = useT();
  const hotels = useQuery({ queryKey: ["hotels"], queryFn: () => api.get<PublicHotel[]>("/hotels"), refetchInterval: 60_000 });
  const offers = useQuery({ queryKey: ["offers"], queryFn: () => api.get<PublicOffer[]>("/offers") });
  const recent = useRecentOrders();
  const [searching, setSearching] = useState(false);
  const [q, setQ] = useState("");
  const showSearch = searching || q.length > 0;

  return (
    <>
      <TopBar />
      <div className="flex-1 px-4 py-5 pb-28 sm:px-6 lg:pb-6">
        <section className="relative overflow-hidden rounded-2xl bg-brand px-6 py-7 text-white sm:px-8">
          <div className="relative z-10 max-w-md">
            <p className="text-sm font-medium text-white/80">{t("Karibu!")}</p>
            <h1 className="mt-1 text-2xl leading-tight font-bold sm:text-3xl">{t("Hot food from local hotels, delivered or ready for pickup.")}</h1>
            <p className="mt-2 flex items-center gap-1.5 text-sm text-white/85"><Clock className="size-4" /> {t("Pay by M-Pesa straight to the hotel")}</p>
          </div>
          <span className="pointer-events-none absolute -bottom-6 hidden text-[8.75rem] opacity-90 select-none sm:right-6 sm:block">🍲</span>
        </section>

        <div className="mt-4">
          <InstallBanner />
        </div>

        {recent.length ? (
          <Link to={`/o/${recent[0].token}`} className="mt-4 flex items-center justify-between rounded-2xl border border-line bg-surface p-4 hover:bg-subtle">
            <span>
              <span className="block text-xs font-medium tracking-wide text-muted uppercase">{t("Your last order")}</span>
              <span className="font-semibold">{recent[0].hotel_name} · #{recent[0].code}</span>
            </span>
            <span className="flex items-center gap-1 text-sm font-semibold text-brand">{t("Track")} <ArrowRight className="size-4" /></span>
          </Link>
        ) : null}

        {offers.data?.length ? (
          <section className="mt-6">
            <h2 className="mb-3 flex items-center gap-2 text-lg font-semibold">
              <Flame className="size-5 text-brand" /> {t("Today's deals")}
            </h2>
            <div className="no-scrollbar -mx-4 flex snap-x snap-mandatory gap-3 overflow-x-auto px-4 pb-1 sm:-mx-6 sm:px-6">
              {offers.data.map((o) => (
                <OfferBanner key={o.id} offer={o} cta={t("Order now")} />
              ))}
            </div>
          </section>
        ) : null}

        <section className="mt-6">
          <div className="mb-3 flex items-center justify-between gap-3">
            <h2 className="text-lg font-semibold">{t("Hotels near you")}</h2>
            <button
              type="button"
              onClick={() => { setSearching((v) => !v); setQ(""); }}
              aria-label={t("Search")}
              className="flex h-10 items-center gap-2 rounded-full bg-brand pr-5 pl-4 text-sm font-bold text-white shadow-md shadow-brand/25 transition-transform hover:scale-105"
            >
              {showSearch ? <X className="size-5" /> : <Search className="size-5" />}
              {showSearch ? t("Close") : t("Search")}
            </button>
          </div>
          {showSearch ? (
            <div className="mb-4 space-y-3">
              <div className="relative">
                <Search className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-muted" />
                <input
                  autoFocus
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  placeholder={t("Search food, e.g. pizza")}
                  aria-label={t("Search")}
                  className="h-11 w-full rounded-full border border-line bg-surface pr-4 pl-10 text-sm outline-none focus:border-brand"
                />
              </div>
              <DishSearch q={q} />
            </div>
          ) : null}
          {showSearch && q.trim() ? null : hotels.isLoading ? (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {[0, 1, 2].map((i) => (
                <Skeleton key={i} className="aspect-[16/12] rounded-2xl" />
              ))}
            </div>
          ) : hotels.error ? (
            <ErrorNote error={hotels.error} />
          ) : (
            hotels.data!.length === 0 ? (
              <div className="flex flex-col items-center gap-2 rounded-2xl border border-dashed border-line bg-surface px-6 py-12 text-center">
                <span className="text-5xl">🍽️</span>
                <p className="text-lg font-semibold">{t("No hotels are open right now")}</p>
                <p className="max-w-xs text-sm text-muted">{t("New hotels are joining soon. Check back in a little while.")}</p>
              </div>
            ) : (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {hotels.data!.map((h) => (
                <HotelCard key={h.slug} hotel={h} />
              ))}
            </div>
            )
          )}
        </section>
        <p className="mt-8 text-center text-xs text-muted">
          <Link to="/login" className="underline">{t("Staff login")}</Link>
        </p>
      </div>
    </>
  );
}

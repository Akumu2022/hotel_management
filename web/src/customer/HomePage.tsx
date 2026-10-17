import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowRight, Bike, Flame, LocateFixed, MapPin, Search, Star, Store, Timer, UtensilsCrossed, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { ErrorNote, Skeleton } from "../components/ui";
import { api } from "../lib/api";
import { useT } from "../lib/i18n";
import { AgeGate, useAgeConfirmed } from "./age";
import { setSection, useSection } from "./section";
import { TopBar } from "./CustomerLayout";
import { HotelCover, VerifiedBadge, etaText } from "./bits";
import { TOWNS, areaQuery, locate, setArea, townArea, useArea, type Area } from "./area";
import { useOrderMode } from "./store";
import { InstallBanner } from "./InstallBanner";
import { StatusChip } from "./HotelPage";
import { OfferCarousel } from "./OfferCarousel";
import { useConfig } from "./OrderPanel";
import { useRecentOrders } from "./store";
import { money } from "../lib/format";
import type { PublicHotel, PublicOffer, SearchHit } from "./types";

const FEATHER = "linear-gradient(to right, transparent 0%, transparent 18%, black 60%)";

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
          {hotel.kind === "liquor" ? null : <span className="flex items-center gap-1"><UtensilsCrossed className="size-3.5" /> {t("Eat in")}</span>}
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
          {hotel.distance_km != null ? (
            <span className="flex items-center gap-1 rounded-full bg-subtle px-2.5 py-1 text-xs font-semibold text-ink">
              <MapPin className="size-3.5" /> {t("{km} km", { km: hotel.distance_km })}
            </span>
          ) : null}
          {hotel.pickup_only ? (
            <span className="rounded-full bg-subtle px-2.5 py-1 text-xs font-semibold text-muted">{t("Pickup only")}</span>
          ) : null}
        </span>
        <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-brand text-white shadow-md shadow-brand/25 transition-transform group-hover:translate-x-0.5" aria-label={t("View menu")}>
          <ArrowRight className="size-5" />
        </span>
      </div>
    </Link>
  );
}

/** Ask for the phone's location, or pick a town. Shown first time, and from "change". */
function LocationPicker({ onDone, current }: { onDone: () => void; current: Area | null }) {
  const t = useT();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  async function useMyLocation() {
    setBusy(true);
    setProblem("");
    const res = await locate();
    setBusy(false);
    if (res === "ok") onDone();
    else
      setProblem(
        res === "denied"
          ? t("Location is blocked for this site. Allow it in your browser settings, or choose your town below.")
          : t("We couldn't get your location. Choose your town below."),
      );
  }
  return (
    <div className="rounded-2xl border border-line bg-surface p-4">
      <p className="font-semibold">{t("Where are you?")}</p>
      <p className="mt-0.5 text-sm text-muted">{t("We use it only to show hotels close to you.")}</p>
      <button
        type="button"
        onClick={useMyLocation}
        disabled={busy}
        className="mt-3 flex h-11 w-full items-center justify-center gap-2 rounded-full bg-brand text-sm font-bold text-white shadow-md shadow-brand/25 disabled:opacity-60"
      >
        <LocateFixed className="size-5" /> {busy ? t("Finding you…") : t("Use my location")}
      </button>
      {problem ? <p className="mt-2 text-sm text-bad">{problem}</p> : null}
      <p className="mt-4 mb-2 text-xs font-medium tracking-wide text-muted uppercase">{t("Or choose your town")}</p>
      <div className="flex flex-wrap gap-2">
        {TOWNS.map((town) => (
          <button
            key={town.name}
            type="button"
            onClick={() => { setArea(townArea(town.name)); onDone(); }}
            className={clsx(
              "rounded-full border px-3.5 py-1.5 text-sm font-medium hover:bg-subtle",
              current?.source === "town" && current.label === town.name ? "border-brand text-brand" : "border-line",
            )}
          >
            {town.name}
          </button>
        ))}
      </div>
    </div>
  );
}

function DishSearch({ q, area, kind }: { q: string; area: Area; kind: "hotel" | "liquor" }) {
  const t = useT();
  const [term, setTerm] = useState(q);
  useEffect(() => {
    const id = setTimeout(() => setTerm(q.trim()), 250);
    return () => clearTimeout(id);
  }, [q]);
  const hits = useQuery({
    queryKey: ["search", term, area.lat, area.lng, kind],
    queryFn: () => api.get<SearchHit[]>(`/search?q=${encodeURIComponent(term)}&${areaQuery(area)}&kind=${kind}`),
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
  const area = useArea();
  const [changing, setChanging] = useState(false);
  // Food hotels, or liquor stores (18+ only: the customer confirms once before the stores are shown).
  const kind = useSection();
  useEffect(() => { setQ(""); setSearching(false); }, [kind]);
  const aged = useAgeConfirmed();
  const locked = kind === "liquor" && !aged;
  // Nothing is fetched until we know where the customer is.
  const hotels = useQuery({
    queryKey: ["hotels", area?.lat, area?.lng, ...(kind === "liquor" ? ["liquor"] : [])],
    queryFn: () => api.get<PublicHotel[]>(`/hotels?${areaQuery(area)}${kind === "liquor" ? "&kind=liquor" : ""}`),
    enabled: !!area && !locked,
    refetchInterval: 60_000,
  });
  const offers = useQuery({
    queryKey: ["offers", area?.lat, area?.lng],
    queryFn: () => api.get<PublicOffer[]>(`/offers?${areaQuery(area)}`),
    enabled: !!area,
  });
  const recent = useRecentOrders();
  const banner = useConfig().data?.banner;
  const [searching, setSearching] = useState(false);
  const [q, setQ] = useState("");
  const showSearch = searching || q.length > 0;

  return (
    <>
      <TopBar />
      <div className="flex-1 px-4 py-5 pb-28 sm:px-6 lg:pb-6">
        <section
          className="relative flex min-h-44 items-center overflow-hidden rounded-2xl bg-brand px-6 py-7 text-white sm:min-h-56 sm:px-8"
          style={{ background: banner?.bg_color || undefined, color: banner?.text_color || undefined }}
        >
          {banner?.image_url ? (
            // Banner colour holds the left half, then melts away so the photo takes over on the right.
            <img
              src={banner.image_url}
              alt=""
              className="pointer-events-none absolute inset-y-0 right-0 h-full w-[62%] object-cover"
              style={{ WebkitMaskImage: FEATHER, maskImage: FEATHER }}
            />
          ) : (
            <span className="pointer-events-none absolute right-6 text-6xl select-none sm:text-[8rem]">{banner?.emoji || "🍲"}</span>
          )}
          <div className="relative z-10 w-[56%] max-w-md min-w-0 sm:w-1/2">
            <p className="text-lg font-semibold opacity-90 sm:text-xl">{banner?.greeting || t("Karibu!")}</p>
            <h1 className="mt-1 text-2xl leading-tight font-bold sm:text-3xl">{banner?.title || t("Hot food from local hotels, delivered or ready for pickup.")}</h1>
            <p className="mt-2 text-sm opacity-90">{banner?.note || t("Pay by M-Pesa straight to the hotel")}</p>
          </div>
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

        {area && kind === "hotel" && offers.data?.length ? (
          <section className="mt-6">
            <h2 className="mb-3 flex items-center gap-2 text-lg font-semibold">
              <Flame className="size-5 text-brand" /> {t("Today's deals")}
            </h2>
            <OfferCarousel offers={offers.data} cta={t("Order now")} />
          </section>
        ) : null}


        <div role="tablist" className="mt-6 grid grid-cols-2 gap-1 rounded-xl bg-subtle p-1">
          {([["hotel", t("Chakula")], ["liquor", t("Drinks")]] as const).map(([k, label]) => (
            <button
              key={k}
              role="tab"
              aria-selected={kind === k}
              onClick={() => setSection(k)}
              className={clsx("h-10 rounded-lg text-sm font-semibold", kind === k ? "bg-surface shadow-sm" : "text-muted")}
            >
              {label}
            </button>
          ))}
        </div>

        <section className="mt-4">
          <div className="mb-3 flex items-center justify-between gap-3">
            <h2 className="min-w-0 text-lg font-semibold">
              {kind === "liquor" ? t("Drinks near you") : t("Hotels near you")}
              {area ? (
                <button
                  type="button"
                  onClick={() => setChanging((v) => !v)}
                  className="mt-0.5 flex items-center gap-1 text-xs font-medium text-muted underline-offset-2 hover:underline"
                >
                  <MapPin className="size-3.5" /> {area.label === "your location" ? t("Your location") : area.label} · {t("change")}
                </button>
              ) : null}
            </h2>
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
              {area ? <DishSearch q={q} area={area} kind={kind} /> : null}
            </div>
          ) : null}
          {!area || changing ? (
            <div className="mb-4"><LocationPicker current={area} onDone={() => setChanging(false)} /></div>
          ) : null}
          {locked ? (
            <AgeGate onNo={() => setSection("hotel")} />
          ) : !area || (showSearch && q.trim()) ? null : hotels.isLoading ? (
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
                <p className="text-lg font-semibold">{kind === "liquor" ? t("No drinks stores near {place} yet", { place: area.label }) : t("No hotels near {place} yet", { place: area.label })}</p>
                <p className="max-w-xs text-sm text-muted">{t("We're growing. Try another town, or check back soon.")}</p>
                <button type="button" onClick={() => setChanging(true)} className="mt-1 text-sm font-semibold text-brand">{t("Change location")}</button>
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

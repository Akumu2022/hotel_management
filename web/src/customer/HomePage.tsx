import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowRight, Bike, Clock, Star, Store, Timer, UtensilsCrossed } from "lucide-react";
import { Link } from "react-router-dom";

import { ErrorNote, Skeleton } from "../components/ui";
import { api } from "../lib/api";
import { useT } from "../lib/i18n";
import { TopBar } from "./CustomerLayout";
import { HotelCover, etaText } from "./bits";
import { useOrderMode } from "./store";
import { InstallBanner } from "./InstallBanner";
import { StatusChip } from "./HotelPage";
import { useRecentOrders } from "./store";
import type { PublicHotel, PublicOffer } from "./types";

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

export function HomePage() {
  const t = useT();
  const hotels = useQuery({ queryKey: ["hotels"], queryFn: () => api.get<PublicHotel[]>("/hotels"), refetchInterval: 60_000 });
  const offers = useQuery({ queryKey: ["offers"], queryFn: () => api.get<PublicOffer[]>("/offers") });
  const recent = useRecentOrders();

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
            <h2 className="mb-3 text-lg font-semibold">{t("Today's deals")}</h2>
            <div className="no-scrollbar -mx-4 flex snap-x gap-3 overflow-x-auto px-4 sm:-mx-6 sm:px-6">
              {offers.data.map((o) => (
                <Link key={o.id} to={`/h/${o.hotel_slug}`} className="relative flex h-32 w-72 shrink-0 snap-start items-end overflow-hidden rounded-2xl bg-ink p-4 text-white">
                  {o.image_url ? (
                    <img src={o.image_url} alt="" className="absolute inset-0 size-full object-cover opacity-60" />
                  ) : (
                    <span className="absolute -top-2 right-2 text-8xl opacity-90">🔥</span>
                  )}
                  <span className="relative">
                    <span className="mb-1 inline-block rounded-md bg-brand px-2 py-0.5 text-xs font-semibold">{o.hotel_name}</span>
                    <span className="block text-lg leading-tight font-semibold">{o.title}</span>
                  </span>
                </Link>
              ))}
            </div>
          </section>
        ) : null}

        <section className="mt-6">
          <h2 className="mb-3 text-lg font-semibold">{t("Hotels near you")}</h2>
          {hotels.isLoading ? (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {[0, 1, 2].map((i) => (
                <Skeleton key={i} className="aspect-[16/12] rounded-2xl" />
              ))}
            </div>
          ) : hotels.error ? (
            <ErrorNote error={hotels.error} />
          ) : (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {hotels.data!.map((h) => (
                <HotelCard key={h.slug} hotel={h} />
              ))}
            </div>
          )}
        </section>
        <p className="mt-8 text-center text-xs text-muted">
          <Link to="/login" className="underline">{t("Staff login")}</Link>
        </p>
      </div>
    </>
  );
}

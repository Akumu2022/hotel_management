import clsx from "clsx";
import { ArrowRight, ChevronLeft, ChevronRight } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import type { PublicOffer } from "./types";

/** "PIZZA WEDNESDAY\nBuy one Get One Free!" -> big headline + highlighted sub-line. */
function splitTitle(title: string): [string, string] {
  const [head, ...rest] = title.split("\n");
  return [head.trim(), rest.join(" ").trim()];
}

export function OfferBanner({ offer: o, cta, wide = false }: { offer: PublicOffer; cta: string; wide?: boolean }) {
  const [head, sub] = splitTitle(o.title);
  const left = o.ends_at ? Math.max(0, new Date(o.ends_at).getTime() - Date.now()) : null;
  const ending = left != null && left < 24 * 3600_000 ? (left < 3600_000 ? `${Math.max(1, Math.round(left / 60_000))} min left` : `${Math.round(left / 3600_000)} h left`) : null;
  return (
    <Link
      to={`/h/${o.hotel_slug}`}
      data-slide
      className={clsx(
        "group relative flex h-48 shrink-0 snap-center overflow-hidden rounded-3xl bg-gradient-to-br from-brand to-[#7a1d00] text-white shadow-lg shadow-brand/20",
        wide ? "w-full" : "w-[90%] sm:w-[32rem]",
      )}
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

/**
 * Deals from one or many hotels in a row you can swipe, drag, or step with the arrows. Dots show
 * where you are, and with more than one deal it slides on by itself until you touch it.
 */
export function OfferCarousel({ offers, cta, wide = false }: { offers: PublicOffer[]; cta: string; wide?: boolean }) {
  const track = useRef<HTMLDivElement>(null);
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);
  const count = offers.length;

  const slides = useCallback(() => Array.from(track.current?.querySelectorAll<HTMLElement>("[data-slide]") ?? []), []);

  const go = useCallback(
    (to: number) => {
      const el = slides()[((to % count) + count) % count];
      const box = track.current;
      if (el && box) box.scrollTo({ left: el.offsetLeft - box.offsetLeft - (box.clientWidth - el.clientWidth) / 2, behavior: "smooth" });
    },
    [count, slides],
  );

  // Which slide is nearest the middle, for the dots.
  const onScroll = () => {
    const box = track.current;
    if (!box) return;
    const mid = box.scrollLeft + box.clientWidth / 2;
    let best = 0;
    let bestDist = Infinity;
    slides().forEach((el, i) => {
      const d = Math.abs(el.offsetLeft - box.offsetLeft + el.clientWidth / 2 - mid);
      if (d < bestDist) [best, bestDist] = [i, d];
    });
    setIndex(best);
  };

  useEffect(() => {
    if (count < 2 || paused || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const id = setInterval(() => go(index + 1), 5000);
    return () => clearInterval(id);
  }, [count, paused, index, go]);

  if (!count) return null;
  return (
    <div className="relative" onPointerEnter={() => setPaused(true)} onPointerLeave={() => setPaused(false)} onTouchStart={() => setPaused(true)} onFocus={() => setPaused(true)}>
      <div ref={track} onScroll={onScroll} className="no-scrollbar -mx-4 flex snap-x snap-mandatory gap-3 overflow-x-auto scroll-smooth px-4 pb-1 sm:-mx-6 sm:px-6">
        {offers.map((o) => (
          <OfferBanner key={o.id} offer={o} cta={cta} wide={wide} />
        ))}
      </div>
      {count > 1 ? (
        <>
          <button
            type="button"
            aria-label="Previous deal"
            onClick={() => go(index - 1)}
            className="absolute top-1/2 left-1 hidden size-9 -translate-y-1/2 items-center justify-center rounded-full bg-surface/90 text-ink shadow-md backdrop-blur hover:bg-surface md:flex"
          >
            <ChevronLeft className="size-5" />
          </button>
          <button
            type="button"
            aria-label="Next deal"
            onClick={() => go(index + 1)}
            className="absolute top-1/2 right-1 hidden size-9 -translate-y-1/2 items-center justify-center rounded-full bg-surface/90 text-ink shadow-md backdrop-blur hover:bg-surface md:flex"
          >
            <ChevronRight className="size-5" />
          </button>
          <div className="mt-3 flex justify-center gap-1.5">
            {offers.map((o, i) => (
              <button
                key={o.id}
                type="button"
                aria-label={`Deal ${i + 1}`}
                onClick={() => go(i)}
                className={clsx("h-1.5 rounded-full transition-all", i === index ? "w-6 bg-brand" : "w-1.5 bg-line hover:bg-muted/50")}
              />
            ))}
          </div>
        </>
      ) : null}
    </div>
  );
}

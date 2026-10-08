/**
 * One-screen checkout, written as four plain numbered steps. The phone sends
 * item IDs and choices only; every amount comes from POST /quotes. "Place order" carries an
 * Idempotency-Key created when checkout opens, so repeated taps make one order.
 */
import { ErrorBoundary, MapFailed } from "../components/ErrorBoundary";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowLeft, Check, MapPin, Minus, Plus, X } from "lucide-react";
import { type FormEvent, type ReactNode, Suspense, lazy, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { Skeleton } from "../components/ui";
import { ApiError, api, request } from "../lib/api";
import { money } from "../lib/format";
import { pointInZone } from "../lib/geo";
import { useT } from "../lib/i18n";
import { BonusLine, BonusNudges, ConfirmDialog, HelpButton, JourneySteps, ModePicker } from "./bits";
import { TopBar } from "./CustomerLayout";
import { FoodImage } from "./FoodImage";
import { useConfig } from "./OrderPanel";
import { type PlaceLabel, cart, orderMode, places, profile, rememberOrder, useCart, useOrderMode, usePlaces, useProfile } from "./store";
import type { Menu, OrderPlaced, Quote, RiderFeeMode } from "./types";

const MapPicker = lazy(() => import("./MapPicker"));

const PLACE_EMOJI: Record<PlaceLabel, string> = {
  Home: "🏠",
  Work: "💼",
  Other: "📍",
};

const PROMO_ERRORS: Record<string, string> = {
  promo_unknown: "We don't recognise that code",
  promo_disabled: "That code is no longer active",
  promo_not_started: "That code isn't active yet",
  promo_ended: "That code has ended",
  promo_min_spend: "Spend a little more to use that code",
  promo_already_used: "You've already used that code",
  promo_limit_reached: "That code has been fully used",
  promo_not_better: "You already have a better deal",
};

/** 32 hex chars. getRandomValues works on plain http too (randomUUID needs HTTPS). */
function newKey() {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, "0")).join("");
}

const inputCls = "h-12 w-full rounded-xl border border-line bg-surface px-4 text-[0.9375rem] outline-none placeholder:text-stone-400 focus:border-brand focus:ring-4 focus:ring-brand/10";

function Step({ n, title, hint, done, children }: { n: number; title: string; hint?: string; done?: boolean; children: ReactNode }) {
  return (
    <section className="rounded-3xl border border-line bg-surface p-5 sm:p-6">
      <header className="mb-4 flex items-start gap-3">
        <span
          className={clsx(
            "flex size-8 shrink-0 items-center justify-center rounded-full text-sm font-bold text-white shadow-md transition-colors",
            done ? "bg-ok shadow-ok/30" : "bg-brand shadow-brand/30",
          )}
        >
          {done ? <Check className="size-4" strokeWidth={3} /> : n}
        </span>
        <div>
          <h2 className="text-[1.0625rem] leading-8 font-bold">{title}</h2>
          {hint ? <p className="-mt-0.5 text-sm text-muted">{hint}</p> : null}
        </div>
      </header>
      <div className="flex flex-col gap-4">{children}</div>
    </section>
  );
}

function PayOption({ active, disabled, onClick, emoji, title, body }: { active: boolean; disabled?: boolean; onClick: () => void; emoji: string; title: string; body: string }) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={active}
      disabled={disabled}
      onClick={onClick}
      className={clsx(
        "flex w-full items-center gap-3.5 rounded-2xl border-2 p-4 text-left transition-all",
        active ? "border-brand bg-brand-soft" : "border-line bg-surface hover:border-stone-300",
        disabled && "cursor-not-allowed opacity-45",
      )}
    >
      <span className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-surface text-2xl shadow-sm ring-1 ring-line">{emoji}</span>
      <span className="min-w-0 flex-1">
        <span className="block text-[0.9375rem] font-semibold">{title}</span>
        <span className="block text-[0.8125rem] text-muted">{body}</span>
      </span>
      <span className={clsx("flex size-5 shrink-0 items-center justify-center rounded-full border-2", active ? "border-brand bg-brand" : "border-stone-300")}>
        {active ? <span className="size-2 rounded-full bg-surface" /> : null}
      </span>
    </button>
  );
}

export function CheckoutPage() {
  const t = useT();
  const navigate = useNavigate();
  const c = useCart();
  const saved = useProfile();
  const type = useOrderMode();
  const config = useConfig({ fresh: true });
  const menu = useQuery({
    queryKey: ["menu", c.hotel_slug],
    queryFn: () => api.get<Menu>(`/hotels/${c.hotel_slug}/menu`),
    enabled: !!c.hotel_slug,
  });
  const hotelInfo = menu.data?.hotel;

  const [feeMode, setFeeMode] = useState<"included" | "cash">("cash");
  const [payment, setPayment] = useState<"mpesa" | "cash">("mpesa");
  const [name, setName] = useState(saved.name);
  const [phone, setPhone] = useState(saved.phone);
  const [landmark, setLandmark] = useState(saved.landmark);
  const [pin, setPin] = useState(saved.lat !== null && saved.lng !== null ? { lat: saved.lat, lng: saved.lng } : null);
  const [promoInput, setPromoInput] = useState("");
  const [promo, setPromo] = useState("");
  const [idemKey, setIdemKey] = useState(newKey);
  const [placing, setPlacing] = useState(false);
  const [placeError, setPlaceError] = useState<string | null>(null);
  const [changedTo, setChangedTo] = useState<Quote | null>(null);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const saved_places = usePlaces();
  const [saveAs, setSaveAs] = useState<PlaceLabel | null>(null);
  const [mapKey, setMapKey] = useState(0); // bump to re-centre the map on a saved place

  const zoneMode = config.data?.delivery_mode === "area";
  // With no drawn area, a hotel delivers once it has a map location.
  const deliveryAvailable = !!config.data && (zoneMode || hotelInfo?.lat != null);
  useEffect(() => {
    if (config.data && hotelInfo && !deliveryAvailable && type === "delivery") orderMode.set("pickup");
  }, [config.data, hotelInfo, deliveryAvailable, type]);

  // A remembered pin from an earlier session may be outside today's area: drop it rather
  // than show an error the customer didn't cause.
  useEffect(() => {
    const z = config.data?.delivery_zone ?? [];
    if (pin && config.data?.delivery_mode === "area" && z.length >= 3 && !pointInZone(pin.lat, pin.lng, z)) {
      setPin(null);
      setLandmark(""); // the directions belonged to that old spot
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config.data]);

  // Moving the pin clears an old "outside the area" message.
  useEffect(() => setPlaceError(null), [pin]);
  useEffect(() => {
    if (type !== "pickup") setPayment("mpesa"); // delivery and eat in are paid first
  }, [type]);
  // Eat in: minutes from now until the customer sits down.
  const [arriveIn, setArriveIn] = useState<number | null>(null);

  const riderFeeMode: RiderFeeMode = type === "delivery" ? feeMode : "none";
  const phoneDigits = phone.replace(/\D/g, "");
  const quoteBody = useMemo(
    () => ({
      hotel_slug: c.hotel_slug,
      lines: c.lines.map((l) => ({
        product_id: l.product_id,
        quantity: l.quantity,
        option_ids: l.option_ids,
      })),
      type,
      rider_fee_mode: riderFeeMode,
      promo_code: promo || null,
      phone: phoneDigits.length >= 9 ? phone : null,
      lat: type === "delivery" && pin ? pin.lat : null,
      lng: type === "delivery" && pin ? pin.lng : null,
    }),
    [c, type, riderFeeMode, promo, phone, phoneDigits.length, pin],
  );
  const quote = useQuery({
    queryKey: ["quote", quoteBody],
    queryFn: () => api.post<Quote>("/quotes", quoteBody),
    enabled: !!c.hotel_slug && c.lines.length > 0,
    placeholderData: (prev) => prev,
    retry: false,
  });
  const q = quote.data;
  useEffect(() => setIdemKey(newKey()), [quoteBody]);

  if (!c.lines.length) {
    return (
      <>
        <TopBar />
        <div className="flex flex-1 flex-col items-center justify-center gap-3 p-10 text-center">
          <span className="text-7xl">🛒</span>
          <p className="text-xl font-bold">{t("Your order is empty")}</p>
          <p className="text-sm text-muted">Pick a hotel and add something tasty.</p>
          <Link to="/" className="mt-2 rounded-xl bg-brand px-6 py-3 font-semibold text-white shadow-lg shadow-brand/25">
            {t("Browse hotels")}
          </Link>
        </div>
      </>
    );
  }

  async function place(expectedTotal: number) {
    setPlacing(true);
    setPlaceError(null);
    profile.set({
      name,
      phone,
      landmark,
      lat: pin?.lat ?? null,
      lng: pin?.lng ?? null,
    });
    try {
      const placed = await request<OrderPlaced>(
        "POST",
        "/orders",
        {
          ...quoteBody,
          name,
          phone,
          payment_method: payment,
          landmark: type === "delivery" ? landmark : null,
          arrive_at: type === "eat_in" && arriveIn ? new Date(Date.now() + arriveIn * 60_000).toISOString() : null,
          expected_total: expectedTotal,
        },
        { auth: false, headers: { "Idempotency-Key": idemKey } },
      );
      if (type === "delivery" && saveAs && pin) places.save({ label: saveAs, lat: pin.lat, lng: pin.lng, landmark });
      rememberOrder({
        token: placed.tracking_token,
        code: placed.code,
        hotel_name: c.hotel_name ?? "",
        at: new Date().toISOString(),
      });
      cart.clear();
      navigate(`/o/${placed.tracking_token}`, { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.code === "price_changed" && err.extra?.quote) setChangedTo(err.extra.quote as Quote);
      else setPlaceError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setPlacing(false);
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    if (type === "delivery" && !pin) return setPlaceError("Tap the map to show the rider where to bring your food");
    if (type === "delivery" && pinOutside) return setPlaceError("Your pin is outside our delivery area. Move it inside the dashed line, or choose pickup.");
    if (type === "delivery" && q?.too_far) return setPlaceError(`That's too far from ${c.hotel_name} for our riders. Choose pickup or a closer spot.`);
    if (type === "eat_in" && !arriveIn) return setPlaceError("Choose when you'll arrive");
    if (q) place(q.till_amount);
  }

  const cashCapExceeded = payment === "cash" && q?.cash_cap != null && q.till_amount > q.cash_cap;
  const riderFee = (type === "delivery" ? q?.rider_fee : 0) || config.data?.rider_fee || 0;
  const feeIsFrom = type !== "delivery" || !q || q.rider_fee_estimated;
  const zone = zoneMode ? (config.data?.delivery_zone ?? []) : [];
  const pinOutside = !!pin && zone.length >= 3 && !pointInZone(pin.lat, pin.lng, zone);
  const done = {
    how: true,
    details: name.trim().length >= 2 && phoneDigits.length >= 9,
    where: type === "pickup" || (type === "eat_in" && !!arriveIn) || (type === "delivery" && !!pin && !pinOutside && !q?.too_far && landmark.trim().length >= 3),
    pay: !cashCapExceeded,
  };
  const doneCount = Object.values(done).filter(Boolean).length;

  return (
    <>
      <TopBar />
      <form onSubmit={submit} className="flex flex-1 flex-col lg:flex-row">
        {/* Left: steps */}
        <div className="flex-1 bg-subtle/60 px-4 py-5 sm:px-6">
          <div className="mx-auto flex max-w-2xl flex-col gap-4">
            <div className="flex items-center gap-3">
              <Link to={c.hotel_slug ? `/h/${c.hotel_slug}` : "/"} className="flex h-11 items-center gap-2 rounded-xl border border-line bg-surface px-3.5 text-sm font-semibold hover:bg-subtle">
                <ArrowLeft className="size-4" /> {t("Back to menu")}
              </Link>
              <div className="min-w-0">
                <h1 className="text-2xl leading-tight font-bold">{t("Checkout")}</h1>
                <p className="truncate text-sm text-muted">{t("Ordering from {hotel}", { hotel: c.hotel_name ?? "" })}</p>
              </div>
            </div>
            <div className="rounded-3xl border border-line bg-surface p-4 sm:p-5">
              <JourneySteps step={1} />
            </div>

            {/* Checkout progress, sticky so it stays visible while scrolling on phones */}
            <div className="sticky top-0 z-20 -mx-4 bg-subtle/95 px-4 py-2 backdrop-blur sm:mx-0 sm:rounded-2xl sm:px-4">
              <div className="flex items-center justify-between text-sm">
                <span className="font-semibold">{doneCount === 4 ? t("All set. Ready to place your order") : t("{done} of 4 steps done", { done: doneCount })}</span>
                <span className="text-muted">{Math.round((doneCount / 4) * 100)}%</span>
              </div>
              <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-surface">
                <div className={clsx("h-full rounded-full transition-all duration-500", doneCount === 4 ? "bg-ok" : "bg-brand")} style={{ width: `${(doneCount / 4) * 100}%` }} />
              </div>
            </div>
            <Step n={1} title={t("How do you want your food?")} done={done.how}>
              <ModePicker riderFee={riderFee} feeIsFrom={feeIsFrom} hotelName={c.hotel_name} deliveryAvailable={deliveryAvailable} />
            </Step>

            <Step n={2} title={t("Your details")} hint={t("So the hotel and rider can reach you")} done={done.details}>
              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <label htmlFor="name" className="mb-1.5 block text-sm font-medium">
                    {t("Your name")}
                  </label>
                  <input id="name" className={inputCls} value={name} onChange={(e) => setName(e.target.value)} required minLength={2} autoComplete="name" placeholder="e.g. Achieng" />
                </div>
                <div>
                  <label htmlFor="phone" className="mb-1.5 block text-sm font-medium">
                    {t("Phone number")}
                  </label>
                  <input id="phone" className={inputCls} type="tel" inputMode="tel" value={phone} onChange={(e) => setPhone(e.target.value)} required placeholder="0712 345 678" autoComplete="tel" />
                </div>
              </div>
            </Step>

            {type === "delivery" ? (
              <Step n={3} title={t("Where should we bring it?")} hint={t("Tap the map on your location, then describe the spot")} done={done.where}>
                {saved_places.length ? (
                  <div>
                    <p className="mb-2 text-sm font-medium">{t("Saved places")}</p>
                    <div className="flex flex-wrap gap-2">
                      {saved_places.map((pl) => {
                        const active = pin && Math.abs(pin.lat - pl.lat) < 1e-5 && Math.abs(pin.lng - pl.lng) < 1e-5;
                        return (
                          <span
                            key={pl.label}
                            className={clsx("flex h-11 items-center rounded-xl border-2 pl-3 text-sm font-semibold", active ? "border-brand bg-brand-soft" : "border-line bg-surface")}
                          >
                            <button
                              type="button"
                              onClick={() => {
                                setPin({ lat: pl.lat, lng: pl.lng });
                                setLandmark(pl.landmark);
                                setMapKey((k) => k + 1);
                              }}
                              className="flex items-center gap-1.5"
                            >
                              <span>{PLACE_EMOJI[pl.label]}</span> {t(pl.label)}
                            </button>
                            <button
                              type="button"
                              onClick={() => places.remove(pl.label)}
                              aria-label={t("Remove {place}", {
                                place: t(pl.label),
                              })}
                              className="ml-1 flex size-9 items-center justify-center rounded-lg text-muted hover:text-bad"
                            >
                              <X className="size-3.5" />
                            </button>
                          </span>
                        );
                      })}
                    </div>
                  </div>
                ) : null}
                <ErrorBoundary fallback={(retry) => <MapFailed retry={retry} />}>
                  <Suspense fallback={<Skeleton className="h-64 rounded-xl" />}>
                    <MapPicker
                      key={mapKey}
                      zone={zone}
                      value={pin}
                      onChange={setPin}
                      hotel={
                        hotelInfo?.lat != null && hotelInfo.lng != null
                          ? {
                              lat: hotelInfo.lat,
                              lng: hotelInfo.lng,
                              name: hotelInfo.name,
                            }
                          : null
                      }
                      rangeKm={zoneMode ? undefined : config.data?.max_delivery_km}
                    />
                  </Suspense>
                </ErrorBoundary>
                {pin && !pinOutside && q ? (
                  q.too_far ? (
                    <p className="rounded-xl bg-bad-soft px-3.5 py-2.5 text-sm font-medium text-bad">
                      That's {q.distance_km} km from {c.hotel_name}. Our riders go up to {q.max_delivery_km} km. Choose pickup or a closer spot.
                    </p>
                  ) : (
                    <div className="flex items-center gap-3 rounded-xl bg-subtle px-3.5 py-3 text-sm">
                      <MapPin className="size-4 shrink-0 text-brand" />
                      <span>
                        {q.distance_km != null ? (
                          <>
                            <strong>{q.distance_km} km</strong> · {c.hotel_name} ·{" "}
                          </>
                        ) : null}
                        {t("Delivery")} <strong className="money">{money(q.rider_fee)}</strong>
                      </span>
                    </div>
                  )
                ) : null}
                <div>
                  <label htmlFor="landmark" className="mb-1.5 block text-sm font-medium">
                    {t("Directions for the rider")}
                  </label>
                  <textarea
                    id="landmark"
                    className={clsx(inputCls, "h-20 resize-none py-3")}
                    value={landmark}
                    onChange={(e) => setLandmark(e.target.value)}
                    required
                    minLength={3}
                    maxLength={300}
                    placeholder="e.g. Blue gate opposite the chemist, 2nd floor"
                  />
                </div>
                {pin && !pinOutside ? (
                  <div>
                    <p className="mb-2 text-sm font-medium">{t("Save this place as")}</p>
                    <div className="flex flex-wrap gap-2">
                      {(["Home", "Work", "Other"] as const).map((l) => (
                        <button
                          key={l}
                          type="button"
                          aria-pressed={saveAs === l}
                          onClick={() => setSaveAs(saveAs === l ? null : l)}
                          className={clsx(
                            "flex h-10 items-center gap-1.5 rounded-xl border-2 px-3.5 text-sm font-semibold",
                            saveAs === l ? "border-brand bg-brand-soft text-brand" : "border-line bg-surface",
                          )}
                        >
                          {PLACE_EMOJI[l]} {t(l)}
                        </button>
                      ))}
                    </div>
                  </div>
                ) : null}
              </Step>
            ) : type === "eat_in" ? (
              <Step n={3} title={t("When will you arrive?")} hint={t("Pay now; the hotel has your food ready when you sit down")} done={done.where}>
                <div className="flex flex-wrap gap-2" role="radiogroup" aria-label={t("When will you arrive?")}>
                  {[20, 30, 45, 60, 90, 120].map((m) => (
                    <button
                      key={m}
                      type="button"
                      role="radio"
                      aria-checked={arriveIn === m}
                      onClick={() => setArriveIn(m)}
                      className={clsx("flex h-11 items-center rounded-xl border-2 px-4 text-sm font-semibold", arriveIn === m ? "border-brand bg-brand-soft text-brand" : "border-line bg-surface")}
                    >
                      {m < 60 ? t("In {m} min", { m }) : t("In {h} h", { h: m / 60 })}
                    </button>
                  ))}
                </div>
                <div className="flex items-center gap-3 rounded-2xl bg-subtle p-4">
                  <span className="text-3xl">🍽️</span>
                  <div>
                    <p className="font-semibold">{c.hotel_name}</p>
                    <p className="text-sm text-muted">
                      {arriveIn
                        ? t("Arriving about {time}. Show your order number when you come in.", {
                            time: new Date(Date.now() + arriveIn * 60_000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }),
                          })
                        : t("Show your order number when you come in")}
                    </p>
                  </div>
                </div>
              </Step>
            ) : (
              <Step n={3} title={t("Where to collect")} hint={t("We'll tell you when it's ready")} done={done.where}>
                <div className="flex items-center gap-3 rounded-2xl bg-subtle p-4">
                  <span className="text-3xl">🏪</span>
                  <div>
                    <p className="font-semibold">{c.hotel_name}</p>
                    <p className="text-sm text-muted">{t("Show your order number at the counter")}</p>
                  </div>
                </div>
              </Step>
            )}

            <Step n={4} title={t("How will you pay?")} done={done.pay}>
              {type === "eat_in" ? (
                <PayOption active onClick={() => setPayment("mpesa")} emoji="📱" title={t("M-Pesa now")} body={t("Eat-in orders are paid first, so the food is ready when you arrive")} />
              ) : type === "delivery" ? (
                <>
                  {/* D35: hotels never handle rider money. The customer pays the rider directly. */}
                  <PayOption
                    active
                    disabled={q ? !q.option_b_allowed : false}
                    onClick={() => setFeeMode("cash")}
                    emoji="📱"
                    title={t("Food by M-Pesa now. You pay the rider {fee} yourself", { fee: money(riderFee) })}
                    body={q && !q.option_b_allowed ? t("Delivery is not available for this number. Choose pickup or contact support.") : t("The hotel never handles the delivery fee. Pay the rider directly when the food arrives.")}
                  />
                </>
              ) : (
                <>
                  {/* Every order is paid first (D34): nothing is cooked for someone who may not come. */}
                  <PayOption active emoji="📱" title={t("Pay with M-Pesa first")} body={t("Straight to the hotel's Till. The hotel starts cooking once your payment arrives.")} onClick={() => setPayment("mpesa")} />
                </>
              )}
            </Step>
          </div>
        </div>

        {/* Right: order summary */}
        <aside className="bg-surface lg:sticky lg:top-5 lg:h-[calc(100dvh-2.5rem)] lg:w-[25rem] lg:shrink-0 lg:self-start lg:border-l lg:border-line">
          <div className="flex h-full flex-col">
            <div className="flex items-center justify-between px-5 pt-5 pb-3">
              <h2 className="text-lg font-bold">{t("Your order")}</h2>
              <span className="rounded-full bg-subtle px-2.5 py-1 text-xs font-semibold text-muted">{cart.count(c)} items</span>
            </div>
            <ul className="flex flex-col gap-3 px-5 lg:flex-1 lg:overflow-y-auto">
              {c.lines.map((l) => {
                const ql = q?.lines.find((x) => x.product_id === l.product_id && x.quantity === l.quantity && x.options.join(", ") === l.options_label);
                return (
                  <li key={l.key} className="flex gap-3 rounded-2xl border border-line p-2.5">
                    <div className="size-16 shrink-0 overflow-hidden rounded-xl">
                      <FoodImage src={l.thumb_url} name={l.name} emojiSize="text-3xl" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-start justify-between gap-1">
                        <p className="truncate text-sm font-semibold">{l.name}</p>
                        <button
                          type="button"
                          onClick={() => cart.setQuantity(l.key, 0)}
                          aria-label={`Remove ${l.name}`}
                          className="-mt-1 -mr-1 flex size-7 shrink-0 items-center justify-center rounded-full text-muted hover:bg-bad-soft hover:text-bad"
                        >
                          <X className="size-4" />
                        </button>
                      </div>
                      {l.options_label ? <p className="truncate text-xs text-muted">{l.options_label}</p> : null}
                      <div className="mt-1.5 flex items-center justify-between">
                        <span className="money text-sm font-semibold">{money(ql?.line_total ?? l.unit_price * l.quantity)}</span>
                        <div className="flex h-8 items-center rounded-lg border border-line">
                          <button type="button" className="flex h-full w-8 items-center justify-center text-muted" aria-label="One less" onClick={() => cart.setQuantity(l.key, l.quantity - 1)}>
                            <Minus className="size-3.5" />
                          </button>
                          <span className="money w-5 text-center text-sm font-semibold">{l.quantity}</span>
                          <button type="button" className="flex h-full w-8 items-center justify-center text-muted" aria-label="One more" onClick={() => cart.setQuantity(l.key, l.quantity + 1)}>
                            <Plus className="size-3.5" />
                          </button>
                        </div>
                      </div>
                    </div>
                  </li>
                );
              })}
            </ul>

            <div className="flex flex-col gap-3 p-5 pb-32 lg:pb-5">
              <div className="flex gap-2">
                <input
                  aria-label="Promo code"
                  className={clsx(inputCls, "h-11 uppercase placeholder:normal-case")}
                  placeholder={t("Promo code (optional)")}
                  value={promoInput}
                  onChange={(e) => setPromoInput(e.target.value.toUpperCase())}
                />
                <button
                  type="button"
                  onClick={() => setPromo(promoInput.trim())}
                  disabled={!promoInput.trim()}
                  className="h-11 shrink-0 rounded-xl bg-ink px-5 text-sm font-semibold text-white disabled:opacity-30"
                >
                  {t("Apply")}
                </button>
              </div>
              {promo && q?.promo_error ? <p className="-mt-1 text-sm text-bad">{PROMO_ERRORS[q.promo_error] ?? "That code can't be used"}</p> : null}
              {promo && q?.promo_applied ? <p className="-mt-1 text-sm font-medium text-ok">🎉 Promo {promo} applied</p> : null}

              <BonusNudges q={q} delivery={type === "delivery"} payAllByMpesa={q?.rider_fee_cash === 0} />
              <div className="rounded-2xl bg-subtle p-4 text-sm">
                {q ? (
                  <div className="flex flex-col gap-2">
                    <div className="flex justify-between">
                      <span className="text-muted">{t("Food")}</span>
                      <span className="money font-medium">{money(q.items_total)}</span>
                    </div>
                    {q.order_discount ? (
                      <div className="flex justify-between">
                        <span className="text-muted">{t("Discount")}</span>
                        <span className="money font-medium text-ok">−{money(q.order_discount)}</span>
                      </div>
                    ) : null}
                    <div className="flex justify-between">
                      <span className="text-muted">{t("Service fee")}</span>
                      <span className="money font-medium">{money(q.service_fee - q.eat_in_fee)}</span>
                    </div>
                    {q.eat_in_fee ? (
                      <div className="flex justify-between">
                        <span className="text-muted">{t("Eat-in booking")}</span>
                        <span className="money font-medium">{money(q.eat_in_fee)}</span>
                      </div>
                    ) : null}
                    {q.rider_fee_in_till ? (
                      <div className="flex justify-between">
                        <span className="text-muted">{t("Delivery")}</span>
                        <span className="money font-medium">{money(q.rider_fee_in_till)}</span>
                      </div>
                    ) : null}
                    <BonusLine q={q} />
                    <div className="mt-1 flex items-center justify-between border-t border-dashed border-stone-300 pt-3">
                      <span className="font-semibold">{payment === "cash" ? t("Pay at the counter") : t("Pay by M-Pesa")}</span>
                      <span className="money text-xl font-extrabold">{money(q.till_amount)}</span>
                    </div>
                    {q.rider_fee_cash ? (
                      <div className="flex justify-between text-muted">
                        <span>{t("+ cash to the rider")}</span>
                        <span className="money">{money(q.rider_fee_cash)}</span>
                      </div>
                    ) : null}
                  </div>
                ) : (
                  <Skeleton className="h-28" />
                )}
              </div>

              {placeError ? <p className="rounded-xl bg-bad-soft px-4 py-3 text-sm text-bad">{placeError}</p> : null}

              {/* Actions: cancel next to place, as on any till receipt */}
              <div className="fixed inset-x-0 bottom-0 z-40 flex gap-2 border-t border-line bg-surface p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] lg:static lg:border-0 lg:p-0">
                <button
                  type="button"
                  onClick={() => setConfirmCancel(true)}
                  className="h-13 shrink-0 rounded-xl border-2 border-line px-4 py-3 text-[0.9375rem] font-semibold text-muted transition-colors hover:border-bad/40 hover:bg-bad-soft hover:text-bad"
                >
                  {t("Cancel order")}
                </button>
                <button
                  type="submit"
                  disabled={!q || quote.isFetching || placing || cashCapExceeded}
                  className="flex h-13 flex-1 items-center justify-center gap-2 rounded-xl bg-brand py-3 text-[0.9375rem] font-semibold text-white shadow-lg shadow-brand/25 hover:bg-brand-hover disabled:cursor-not-allowed disabled:bg-line disabled:text-muted disabled:shadow-none"
                >
                  {placing ? <span className="size-4 animate-spin rounded-full border-2 border-white border-t-transparent" /> : null}
                  {t("Place order")}
                  {q ? <span className="money">· {money(q.till_amount)}</span> : null}
                </button>
              </div>
              <p className="text-center text-xs text-muted">{t("By ordering you agree to the terms and privacy policy.")}</p>
              <HelpButton number={config.data?.support_whatsapp} message={`Hello Chakula, I need help ordering from ${c.hotel_name}.`} />
            </div>
          </div>
        </aside>
      </form>

      <ConfirmDialog
        open={confirmCancel}
        emoji="🗑️"
        title={t("Cancel this order?")}
        body={<>Everything in your order from {c.hotel_name} will be removed. Nothing has been paid.</>}
        confirm={t("Yes, cancel order")}
        cancel={t("Keep ordering")}
        danger
        onConfirm={() => {
          cart.clear();
          navigate("/", { replace: true });
        }}
        onClose={() => setConfirmCancel(false)}
      />

      <ConfirmDialog
        open={!!changedTo}
        emoji="🏷️"
        title="Price updated"
        body={
          <>
            The hotel changed a price since you added it. Your new total is <strong className="money text-ink">{changedTo ? money(changedTo.till_amount) : ""}</strong>
            {q ? (
              <>
                {" "}
                (was <span className="money">{money(q.till_amount)}</span>)
              </>
            ) : null}
            .
          </>
        }
        confirm={`Place order · ${changedTo ? money(changedTo.till_amount) : ""}`}
        cancel="Go back"
        onConfirm={() => {
          const total = changedTo!.till_amount;
          quote.refetch();
          place(total);
        }}
        onClose={() => setChangedTo(null)}
      />
    </>
  );
}

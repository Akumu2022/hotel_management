/** The "Order" panel from the reference POS design, with a plain delivery/pickup choice. */
import { useQuery } from "@tanstack/react-query";
import { Minus, Plus, Trash2, X } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../lib/api";
import { money } from "../lib/format";
import { useT } from "../lib/i18n";
import { BonusLine, BonusNudges, ConfirmDialog, ModePicker } from "./bits";
import { FoodImage } from "./FoodImage";
import { cart, useCart, useOrderMode } from "./store";
import type { PublicConfig, Quote } from "./types";

export function useConfig(opts: { fresh?: boolean } = {}) {
  return useQuery({
    queryKey: ["config"],
    queryFn: () => api.get<PublicConfig>("/config"),
    staleTime: opts.fresh ? 0 : 60_000,
    refetchOnMount: opts.fresh ? "always" : true,
  });
}

export function useCartQuote() {
  const c = useCart();
  const mode = useOrderMode();
  const body = {
    hotel_slug: c.hotel_slug,
    lines: c.lines.map((l) => ({ product_id: l.product_id, quantity: l.quantity, option_ids: l.option_ids })),
    type: mode,
    rider_fee_mode: mode === "delivery" ? "cash" : "none",
  };
  return useQuery({
    queryKey: ["quote", body],
    queryFn: () => api.post<Quote>("/quotes", body),
    enabled: !!c.hotel_slug && c.lines.length > 0,
    placeholderData: (prev) => prev,
    retry: false,
  });
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return <div className="border-y border-line bg-subtle px-5 py-2 text-xs font-semibold tracking-wider text-ink uppercase">{children}</div>;
}

function Stepper({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  return (
    <div className="inline-flex h-8 items-center rounded-lg border border-line bg-surface">
      <button className="flex h-full w-8 items-center justify-center text-muted hover:text-ink" aria-label="One less" onClick={() => onChange(value - 1)}>
        {value === 1 ? <Trash2 className="size-3.5" /> : <Minus className="size-3.5" />}
      </button>
      <span className="money w-5 text-center text-sm font-semibold">{value}</span>
      <button className="flex h-full w-8 items-center justify-center text-muted hover:text-ink disabled:opacity-30" aria-label="One more" disabled={value >= 20} onClick={() => onChange(value + 1)}>
        <Plus className="size-3.5" />
      </button>
    </div>
  );
}

export function OrderPanel({ onProceed }: { onProceed?: () => void }) {
  const t = useT();
  const c = useCart();
  const mode = useOrderMode();
  const navigate = useNavigate();
  const quote = useCartQuote();
  const config = useConfig();
  const [confirmClear, setConfirmClear] = useState(false);
  const q = quote.data;
  const empty = c.lines.length === 0;

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-start justify-between gap-3 px-5 pt-5 pb-3">
        <div>
          <h2 className="text-lg font-semibold">{t("Your order")}</h2>
          <p className="text-sm text-muted">{c.hotel_name ?? t("Nothing added yet")}</p>
        </div>
        {!empty ? (
          <button onClick={() => setConfirmClear(true)} className="mr-10 flex h-9 items-center gap-1.5 rounded-lg px-2.5 text-sm font-medium text-bad hover:bg-bad-soft lg:mr-0">
            <Trash2 className="size-4" /> {t("Clear order")}
          </button>
        ) : null}
      </div>

      <SectionLabel>{t("How do you want your food?")}</SectionLabel>
      <div className="px-5 py-4">
        <ModePicker compact riderFee={config.data?.rider_fee} hotelName={c.hotel_name} deliveryAvailable={config.data?.delivery_available ?? true} />
      </div>

      <SectionLabel>{t("Order details")}</SectionLabel>
      <div className="flex-1 overflow-y-auto px-5 py-4">
        {empty ? (
          <div className="flex h-full min-h-40 flex-col items-center justify-center gap-2 text-center">
            <span className="text-5xl">🍽️</span>
            <p className="font-semibold">{t("Your order is empty")}</p>
            <p className="max-w-56 text-sm text-muted">{t("Tap “Add” on any dish to start your order.")}</p>
          </div>
        ) : (
          <ol className="flex flex-col gap-4">
            {c.lines.map((l, i) => {
              const ql = q?.lines.find((x) => x.product_id === l.product_id && x.quantity === l.quantity && x.options.join(", ") === l.options_label);
              return (
                <li key={l.key} className="group/item flex gap-3">
                  <span className="mt-5 flex size-6 shrink-0 items-center justify-center rounded-full bg-subtle text-xs font-bold text-muted">{i + 1}</span>
                  <div className="size-16 shrink-0 overflow-hidden rounded-xl">
                    <FoodImage src={l.thumb_url} name={l.name} emojiSize="text-3xl" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-start justify-between gap-2">
                      <p className="text-sm font-medium">{l.quantity}x {l.name}</p>
                      <button
                        onClick={() => cart.setQuantity(l.key, 0)}
                        aria-label={`Remove ${l.name}`}
                        title="Remove"
                        className="-mt-1 -mr-1 flex size-7 shrink-0 items-center justify-center rounded-full text-muted hover:bg-bad-soft hover:text-bad"
                      >
                        <X className="size-4" />
                      </button>
                    </div>
                    {l.options_label ? (
                      <div className="mt-1 flex flex-wrap gap-1">
                        {l.options_label.split(", ").map((o) => (
                          <span key={o} className="rounded-md bg-subtle px-2 py-0.5 text-xs text-muted">{o}</span>
                        ))}
                      </div>
                    ) : null}
                    <div className="mt-2 flex items-center justify-between">
                      <Stepper value={l.quantity} onChange={(v) => cart.setQuantity(l.key, v)} />
                      <p className="money text-[0.9375rem] font-semibold">{money(ql?.line_total ?? l.unit_price * l.quantity)}</p>
                    </div>
                  </div>
                </li>
              );
            })}
          </ol>
        )}
      </div>

      <SectionLabel>{t("Payment details")}</SectionLabel>
      <div className="flex flex-col gap-2.5 px-5 py-4 text-sm">
        <div className="flex justify-between"><span className="text-muted">{t("Food")}</span><span className="money font-medium">{money(q?.items_total ?? 0)}</span></div>
        {q?.order_discount ? <div className="flex justify-between"><span className="text-muted">{t("Discount")}</span><span className="money font-medium text-ok">−{money(q.order_discount)}</span></div> : null}
        <div className="flex justify-between"><span className="text-muted">{t("Service fee")}</span><span className="money font-medium">{money(empty ? 0 : (q?.service_fee ?? 0) - (q?.eat_in_fee ?? 0))}</span></div>
        {!empty && q?.eat_in_fee ? <div className="flex justify-between"><span className="text-muted">{t("Eat-in booking")}</span><span className="money font-medium">{money(q.eat_in_fee)}</span></div> : null}
        {mode === "delivery" ? <div className="flex justify-between"><span className="text-muted">{t("Delivery")}</span><span className="money font-medium">{money(empty ? 0 : (q?.rider_fee ?? 0))}</span></div> : null}
        {!empty ? <BonusLine q={q} /> : null}
        {!empty ? <BonusNudges q={q} delivery={mode === "delivery"} payAllByMpesa /> : null}
      </div>
      <div className="flex items-center justify-between border-t border-line px-5 py-4">
        <span className="text-sm font-semibold uppercase">{t("Total")}</span>
        <span className="money text-xl font-bold">{money(empty ? 0 : (q?.till_amount ?? 0))}</span>
      </div>
      <div className="px-5 pb-5">
        <button
          disabled={empty || !q}
          onClick={() => {
            onProceed?.();
            navigate("/checkout");
          }}
          className="h-12 w-full rounded-xl bg-brand text-[0.9375rem] font-semibold text-white shadow-lg shadow-brand/25 transition-colors hover:bg-brand-hover disabled:cursor-not-allowed disabled:bg-line disabled:text-muted disabled:shadow-none"
        >
          {t("Continue to checkout")}
        </button>
      </div>

      <ConfirmDialog
        open={confirmClear}
        emoji="🗑️"
        title={t("Clear your order?")}
        body={t("All {n} items from {hotel} will be removed.", { n: cart.count(c), hotel: c.hotel_name ?? "" })}
        confirm={t("Yes, clear it")}
        cancel={t("Keep it")}
        danger
        onConfirm={() => cart.clear()}
        onClose={() => setConfirmClear(false)}
      />
    </div>
  );
}

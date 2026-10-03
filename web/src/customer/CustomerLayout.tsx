/**
 * App shell from the reference designs: a white rounded frame on a grey page, main content on
 * the left and the Order panel on the right (desktop). On phones the panel opens full screen
 * from a sticky bottom bar.
 */
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { ChevronsUpDown, Moon, ReceiptText, Sun, UtensilsCrossed, WifiOff, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, Outlet, useLocation, useNavigate, useParams } from "react-router-dom";

import { api } from "../lib/api";
import { money } from "../lib/format";
import { setLang, useLang, useT } from "../lib/i18n";
import { setTheme, useTheme } from "../lib/theme";
import { HelpButton, Toaster } from "./bits";
import { FoodImage } from "./FoodImage";
import { OrderPanel, useCartQuote, useConfig } from "./OrderPanel";
import { cart, useCart, useRecentOrders } from "./store";
import type { PublicHotel } from "./types";

function useOnline() {
  const [online, setOnline] = useState(navigator.onLine);
  useEffect(() => {
    const up = () => setOnline(true);
    const down = () => setOnline(false);
    window.addEventListener("online", up);
    window.addEventListener("offline", down);
    return () => {
      window.removeEventListener("online", up);
      window.removeEventListener("offline", down);
    };
  }, []);
  return online;
}

export function Logo() {
  return (
    <Link to="/" className="flex items-center gap-2.5">
      <span className="flex size-10 items-center justify-center rounded-xl border border-line bg-surface text-brand shadow-sm">
        <UtensilsCrossed className="size-5" />
      </span>
      <span className="hidden text-[1.375rem] font-extrabold tracking-tight text-brand min-[440px]:inline">Chakula</span>
    </Link>
  );
}

function HotelSwitcher() {
  const { slug } = useParams();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const hotels = useQuery({ queryKey: ["hotels"], queryFn: () => api.get<PublicHotel[]>("/hotels") });
  const current = hotels.data?.find((h) => h.slug === slug);

  useEffect(() => {
    const close = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex h-11 items-center gap-2.5 rounded-xl border border-line bg-surface pr-3 pl-1.5 text-sm font-medium hover:bg-subtle"
      >
        <span className="size-8 overflow-hidden rounded-lg">
          <FoodImage src={current?.cover_url} name={current?.name ?? "hotel"} emojiSize="text-base" />
        </span>
        <span className="max-w-40 truncate">{current?.name ?? "Choose a hotel"}</span>
        <ChevronsUpDown className="size-4 text-muted" />
      </button>
      {open ? (
        <div className="absolute top-12 left-0 z-50 w-72 overflow-hidden rounded-xl border border-line bg-surface p-1.5 shadow-xl">
          {hotels.data?.map((h) => (
            <button
              key={h.slug}
              onClick={() => {
                setOpen(false);
                navigate(`/h/${h.slug}`);
              }}
              className={clsx("flex w-full items-center gap-3 rounded-lg p-2 text-left hover:bg-subtle", h.slug === slug && "bg-brand-soft")}
            >
              <span className="size-9 shrink-0 overflow-hidden rounded-lg">
                <FoodImage src={h.cover_url} name={h.name} emojiSize="text-lg" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium">{h.name}</span>
                <span className={clsx("block text-xs", h.is_open ? "text-ok" : "text-muted")}>{h.is_open ? "Open now" : "Closed"}</span>
              </span>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function LangToggle() {
  const lang = useLang();
  return (
    <div className="flex h-10 items-center rounded-xl bg-subtle p-1 text-xs font-bold" role="group" aria-label="Language">
      {(["en", "sw"] as const).map((l) => (
        <button
          key={l}
          onClick={() => setLang(l)}
          aria-pressed={lang === l}
          className={clsx("h-8 rounded-lg px-2.5 uppercase", lang === l ? "bg-surface text-ink shadow-sm" : "text-muted")}
        >
          {l}
        </button>
      ))}
    </div>
  );
}

export function ThemeToggle() {
  const theme = useTheme();
  const dark = theme === "dark";
  return (
    <button
      onClick={() => setTheme(dark ? "light" : "dark")}
      aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
      title={dark ? "Light mode" : "Dark mode"}
      className="flex size-10 items-center justify-center rounded-xl border border-line text-muted hover:bg-subtle hover:text-ink"
    >
      {dark ? <Sun className="size-4" /> : <Moon className="size-4" />}
    </button>
  );
}

export function TopBar() {
  const t = useT();
  const recent = useRecentOrders();
  const { slug } = useParams();
  const config = useConfig();
  return (
    <header className="flex items-center justify-between gap-3 border-b border-line px-4 py-4 sm:px-6">
      <div className="flex min-w-0 items-center gap-3 sm:gap-5">
        <Logo />
        <div className="hidden sm:block">{slug ? <HotelSwitcher /> : null}</div>
      </div>
      <div className="flex items-center gap-2">
        <ThemeToggle />
        <LangToggle />
        <HelpButton variant="compact" number={config.data?.support_whatsapp} message="Hello Chakula, I need help with " />
        {recent.length ? (
          <Link
            to="/orders"
            className="relative flex h-10 items-center gap-2 rounded-xl border border-line px-3 text-sm font-semibold hover:bg-subtle"
          >
            <ReceiptText className="size-4" />
            <span className="hidden sm:inline">{t("My orders")}</span>
          </Link>
        ) : null}
      </div>
    </header>
  );
}

function MobileCartBar({ onOpen }: { onOpen: () => void }) {
  const t = useT();
  const c = useCart();
  const quote = useCartQuote();
  const count = cart.count(c);
  if (!count) return null;
  return (
    <div className="fixed inset-x-0 bottom-0 z-40 animate-[slide-up_.3s_ease-out] p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] lg:hidden">
      <button onClick={onOpen} className="flex h-14 w-full items-center justify-between rounded-2xl bg-brand px-5 text-white shadow-xl shadow-brand/30">
        <span className="flex items-center gap-2.5 font-semibold">
          <span key={count} className="flex size-7 animate-[bump_.35s_ease-out] items-center justify-center rounded-full bg-white text-sm font-bold text-brand">{count}</span>
          {t("View your order")}
        </span>
        <span className="money font-bold">{money(quote.data?.till_amount ?? cart.estimate(c))}</span>
      </button>
    </div>
  );
}

export function CustomerLayout() {
  const t = useT();
  const online = useOnline();
  const { pathname } = useLocation();
  const [sheet, setSheet] = useState(false);
  const withPanel = !pathname.startsWith("/checkout") && !pathname.startsWith("/o/") && !pathname.startsWith("/orders");

  useEffect(() => setSheet(false), [pathname]);

  return (
    <div className="min-h-dvh md:p-5">
      <Toaster />
      {!online ? (
        <div className="fixed inset-x-0 top-0 z-50 flex items-center justify-center gap-2 bg-ink px-4 py-2 text-sm text-white">
          <WifiOff className="size-4" /> {t("You're offline. Your order is saved.")}
        </div>
      ) : null}
      <div className="mx-auto flex min-h-dvh max-w-[90rem] overflow-clip bg-surface md:min-h-[calc(100dvh-2.5rem)] md:rounded-[1.75rem] md:shadow-sm">
        <div className="flex min-w-0 flex-1 flex-col">
          <Outlet />
        </div>
        {withPanel ? (
          <aside className="sticky top-5 hidden h-[calc(100dvh-2.5rem)] w-[23.75rem] shrink-0 self-start border-l border-line lg:block">
            <OrderPanel />
          </aside>
        ) : null}
      </div>

      {withPanel ? <MobileCartBar onOpen={() => setSheet(true)} /> : null}
      {sheet ? (
        <div className="fixed inset-0 z-50 flex flex-col bg-surface lg:hidden" role="dialog" aria-modal="true" aria-label="Your order">
          <button onClick={() => setSheet(false)} aria-label="Close" className="absolute top-4 right-4 z-10 flex size-10 items-center justify-center rounded-full bg-subtle">
            <X className="size-5" />
          </button>
          <OrderPanel onProceed={() => setSheet(false)} />
        </div>
      ) : null}
    </div>
  );
}


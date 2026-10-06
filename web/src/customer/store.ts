/**
 * Things the phone remembers: the cart, the customer's name/phone/last
 * location, and recent orders. All in localStorage, wrapped so private mode still works.
 * The cart holds one hotel only. Prices here are for display; the server
 * recalculates everything.
 */
import { useSyncExternalStore } from "react";

function read<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function write(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* storage unavailable: keep in memory only */
  }
}

function createStore<T>(key: string, fallback: T) {
  let state = read(key, fallback);
  const listeners = new Set<() => void>();
  return {
    get: () => state,
    set(next: T) {
      state = next;
      write(key, next);
      listeners.forEach((fn) => fn());
    },
    subscribe(fn: () => void) {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
  };
}

// --- Cart -------------------------------------------------------------------------------------

export type CartLine = {
  key: string; // product + sorted options
  product_id: string;
  option_ids: string[];
  quantity: number;
  name: string;
  options_label: string;
  unit_price: number; // display only
  thumb_url?: string | null;
};

export type Cart = { hotel_slug: string | null; hotel_name: string | null; lines: CartLine[] };

const EMPTY: Cart = { hotel_slug: null, hotel_name: null, lines: [] };
const cartStore = createStore<Cart>("cart-v1", EMPTY);

export const useCart = () => useSyncExternalStore(cartStore.subscribe, cartStore.get);

export const cart = {
  get: cartStore.get,
  lineKey: (productId: string, optionIds: string[]) => [productId, ...[...optionIds].sort()].join(":"),
  /** Returns false if the cart holds another hotel's items (caller asks to clear first). */
  add(hotel: { slug: string; name: string }, line: Omit<CartLine, "key" | "quantity">, qty = 1): boolean {
    const c = cartStore.get();
    if (c.hotel_slug && c.hotel_slug !== hotel.slug && c.lines.length) return false;
    const key = cart.lineKey(line.product_id, line.option_ids);
    const existing = c.lines.find((l) => l.key === key);
    const lines = existing
      ? c.lines.map((l) => (l.key === key ? { ...l, quantity: Math.min(20, l.quantity + qty) } : l))
      : [...c.lines, { ...line, key, quantity: qty }];
    cartStore.set({ hotel_slug: hotel.slug, hotel_name: hotel.name, lines });
    return true;
  },
  setQuantity(key: string, quantity: number) {
    const c = cartStore.get();
    const lines =
      quantity <= 0
        ? c.lines.filter((l) => l.key !== key)
        : c.lines.map((l) => (l.key === key ? { ...l, quantity: Math.min(20, quantity) } : l));
    cartStore.set(lines.length ? { ...c, lines } : EMPTY);
  },
  clear: () => cartStore.set(EMPTY),
  count: (c: Cart) => c.lines.reduce((n, l) => n + l.quantity, 0),
  estimate: (c: Cart) => c.lines.reduce((n, l) => n + l.unit_price * l.quantity, 0),
};

// --- Profile and recent orders ----------------------------------------------------------------

export type Profile = {
  name: string;
  phone: string;
  landmark: string;
  lat: number | null;
  lng: number | null;
};

const profileStore = createStore<Profile>("profile-v1", {
  name: "",
  phone: "",
  landmark: "",
  lat: null,
  lng: null,
});
export const profile = profileStore;
export const useProfile = () => useSyncExternalStore(profileStore.subscribe, profileStore.get);

export type RecentOrder = { token: string; code: string; hotel_name: string; at: string };
const recentStore = createStore<RecentOrder[]>("recent-orders-v1", []);
export const useRecentOrders = () => useSyncExternalStore(recentStore.subscribe, recentStore.get);
export function rememberOrder(o: RecentOrder) {
  recentStore.set([o, ...recentStore.get().filter((r) => r.token !== o.token)].slice(0, 200));
}

// --- Delivery or pickup (chosen in the order panel, used at checkout) -------------------------

export type Mode = "delivery" | "pickup" | "eat_in";
const modeStore = createStore<Mode>("order-mode-v1", "delivery");
export const orderMode = modeStore;
export const useOrderMode = () => useSyncExternalStore(modeStore.subscribe, modeStore.get);

/** Refill the cart from a past order. Prices shown are the old ones until the server re-quotes. */
export function orderAgain(t: {
  hotel_slug: string;
  hotel_name: string;
  type: Mode;
  items: { product_id: string; option_ids: string[]; name: string; options: string[]; quantity: number; line_total: number; thumb_url: string | null }[];
}) {
  cart.clear();
  for (const i of t.items) {
    cart.add(
      { slug: t.hotel_slug, name: t.hotel_name },
      {
        product_id: i.product_id,
        option_ids: i.option_ids,
        name: i.name,
        options_label: i.options.join(", "),
        unit_price: Math.round(i.line_total / i.quantity),
        thumb_url: i.thumb_url,
      },
      i.quantity,
    );
  }
  orderMode.set(t.type);
}

// --- Saved places (on this phone only) ----------------------------------------------------------

export type PlaceLabel = "Home" | "Work" | "Other";
export type Place = { label: PlaceLabel; lat: number; lng: number; landmark: string };

const placesStore = createStore<Place[]>("places-v1", []);
export const usePlaces = () => useSyncExternalStore(placesStore.subscribe, placesStore.get);
export const places = {
  save(p: Place) {
    placesStore.set([p, ...placesStore.get().filter((x) => x.label !== p.label)]);
  },
  remove(label: PlaceLabel) {
    placesStore.set(placesStore.get().filter((x) => x.label !== label));
  },
};

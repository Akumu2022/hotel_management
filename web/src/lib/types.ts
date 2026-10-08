// Mirrors backend/app/schemas/catalogue.py. Money is always whole KES (int).

export type Category = {
  id: string;
  name: string;
  sort_order: number;
  available_from: string | null;
  available_to: string | null;
};

export type ProductOption = {
  id: string;
  group_name: string;
  name: string;
  price_delta: number;
  sort_order: number;
  is_archived: boolean;
};

export type Product = {
  id: string;
  category_id: string;
  name: string;
  description: string;
  price: number;
  prep_minutes: number;
  is_sold_out: boolean;
  is_archived: boolean;
  image_url: string | null;
  thumb_url: string | null;
  options: ProductOption[];
};

export type Upload = { image_key: string; thumb_key: string; image_url: string; thumb_url: string };

export type Discount = {
  id: string;
  scope: "item" | "order";
  product_id: string | null;
  kind: "percent" | "fixed";
  value: number;
  percent: number | null;
  min_spend: number;
  promo_code: string | null;
  starts_at: string;
  ends_at: string | null;
  max_uses: number | null;
  uses: number;
  is_active: boolean;
  days_mask?: number | null; // happy hour: Mon = 1 ... Sun = 64
  daily_from?: number | null; // minutes from midnight, Kenya time
  daily_to?: number | null;
};

export type Offer = {
  id: string;
  title: string;
  image_url: string | null;
  product_id: string | null;
  discount_id: string | null;
  starts_at: string;
  ends_at: string | null;
  sort_order: number;
};

export type DayHours = { weekday: number; opens_at: string; closes_at: string };

export type HotelSettings = {
  name: string;
  phone: string;
  till_number: string;
  till_name: string | null;
  verified: boolean;
  cash_pickup_enabled: boolean;
  accepting_orders: boolean;
  status: "active" | "paused";
  accent_color: string | null;
  cover_url: string | null;
  hours: DayHours[];
  lat: number | null;
  lng: number | null;
};

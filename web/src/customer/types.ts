// Mirrors backend/app/schemas (catalogue + orders). Money is whole KES.

export type PublicHotel = {
  slug: string;
  name: string;
  phone: string;
  accent_color: string | null;
  cover_url: string | null;
  is_open: boolean;
  state: "open" | "closing_soon" | "closed" | "paused" | "not_accepting";
  closes_at: string | null;
  opens_at: string | null;
  cash_pickup_enabled: boolean;
  lat: number | null;
  lng: number | null;
  prep_minutes: number;
};

export type MenuOption = { id: string; group_name: string; name: string; price_delta: number };

export type MenuProduct = {
  id: string;
  name: string;
  description: string;
  price: number;
  prep_minutes: number;
  is_sold_out: boolean;
  image_url: string | null;
  thumb_url: string | null;
  options: MenuOption[];
  discount_price: number | null;
};

export type MenuCategory = {
  id: string;
  name: string;
  available_from: string | null;
  available_to: string | null;
  products: MenuProduct[];
};

export type Menu = { hotel: PublicHotel; categories: MenuCategory[] };

export type PublicOffer = {
  id: string;
  hotel_slug: string;
  hotel_name: string;
  title: string;
  image_url: string | null;
  product_id: string | null;
  ends_at: string | null;
};

export type OrderType = "delivery" | "pickup";
export type RiderFeeMode = "included" | "cash" | "none";

export type Quote = {
  lines: {
    product_id: string;
    name: string;
    unit_price: number;
    options: string[];
    options_price: number;
    quantity: number;
    line_discount: number;
    line_total: number;
  }[];
  items_total: number;
  order_discount: number;
  food_net: number;
  service_fee: number;
  rider_fee: number;
  rider_fee_in_till: number;
  rider_fee_cash: number;
  till_amount: number;
  promo_applied: boolean;
  promo_error: string | null;
  option_b_allowed: boolean;
  cash_allowed: boolean;
  cash_cap: number | null;
  distance_km: number | null;
  rider_fee_estimated: boolean;
  too_far: boolean;
  max_delivery_km: number | null;
  // Platform bonuses (DECISIONS D19)
  platform_bonus: number;
  bonus_kind: "stamp" | "free_delivery" | null;
  free_delivery_min_food: number | null;
  stamp_every: number;
  stamps_have: number;
  stamp_reward: number;
};

export type OrderPlaced = {
  code: string;
  tracking_token: string;
  status: string;
  till_number: string;
  till_amount: number;
  payment_method: "mpesa" | "cash";
  expires_at: string | null;
};

export type Track = {
  code: string;
  status: string;
  type: OrderType;
  payment_method: "mpesa" | "cash";
  rider_fee_mode: RiderFeeMode;
  hotel_name: string;
  hotel_slug: string;
  hotel_phone: string;
  till_number: string;
  items: {
    product_id: string;
    option_ids: string[];
    name: string;
    options: string[];
    quantity: number;
    line_total: number;
    thumb_url: string | null;
  }[];
  items_total: number;
  order_discount: number;
  food_net: number;
  service_fee: number;
  rider_fee: number;
  till_amount: number;
  rider_fee_cash: number;
  platform_bonus: number;
  bonus_kind: "stamp" | "free_delivery" | null;
  delivery_code: string | null;
  customer_trans_code: string | null;
  distance_km: number | null;
  landmark: string | null;
  expires_at: string | null;
  prep_minutes: number | null;
  reason: string | null;
  can_cancel: boolean;
  created_at: string;
  events: { status: string; at: string }[];
  rider_name: string | null;
  rider_phone: string | null;
  rider_photo_url: string | null;
  fee_question: boolean;
};

export type PublicConfig = {
  delivery_zone: [number, number][];
  delivery_available: boolean;
  rider_fee: number;
  rider_fee_bands: { max_km: number; fee: number }[];
  support_whatsapp: string | null;
  max_delivery_km: number;
  delivery_mode: "area" | "distance";
};

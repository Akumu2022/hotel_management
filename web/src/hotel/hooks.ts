import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSyncExternalStore } from "react";

import { toast } from "../components/toast";
import { api, auth } from "../lib/api";
import type { Category, Discount, HotelSettings, Offer, Product } from "../lib/types";

export function useMe() {
  return useSyncExternalStore(auth.subscribe, auth.user);
}

export function useIsAdmin() {
  return useMe()?.role === "hotel_admin";
}

export const keys = {
  categories: ["hotel", "categories"] as const,
  products: ["hotel", "products"] as const,
  discounts: ["hotel", "discounts"] as const,
  offers: ["hotel", "offers"] as const,
  settings: ["hotel", "settings"] as const,
};

export const useCategories = () =>
  useQuery({ queryKey: keys.categories, queryFn: () => api.get<Category[]>("/hotel/categories") });

export const useProducts = (includeArchived = false) =>
  useQuery({
    queryKey: [...keys.products, includeArchived],
    queryFn: () => api.get<Product[]>(`/hotel/products?include_archived=${includeArchived}`),
  });

export const useDiscounts = () =>
  useQuery({ queryKey: keys.discounts, queryFn: () => api.get<Discount[]>("/hotel/discounts") });

export const useOffers = () =>
  useQuery({ queryKey: keys.offers, queryFn: () => api.get<Offer[]>("/hotel/offers") });

/** A liquor store's screens say drinks, not dishes or food. */
export function toDrinks(s: string): string {
  return s
    .replace("Kitchen too busy", "Too busy")
    .replace("Kitchen problem (gas, power…)", "Store problem (power, stock…)")
    .replace("In the kitchen", "Preparing")
    .replace("Nothing cooking.", "Nothing being prepared.")
    .replace("start cooking", "start preparing")
    .replace(", pickup, eat in and delivery,", ", pickup and delivery,")
    .replace(/\bDishes\b/g, "Drinks")
    .replace(/\bdishes\b/g, "drinks")
    .replace(/\bDish\b/g, "Drink")
    .replace(/\bdish\b/g, "drink")
    .replace(/\bFood\b/g, "Drinks")
    .replace(/\bfood\b/g, "drinks")
    .replace(/\bhotel\b/g, "store")
    .replace(/\bHotel\b/g, "Store");
}

/** True when the signed-in store is a liquor store: no prep time, deals, kitchen or meal categories. */
export function useIsLiquor(): boolean {
  return useHotelSettings().data?.kind === "liquor";
}

export function useW(): (s: string) => string {
  const liquor = useHotelSettings().data?.kind === "liquor";
  return (s) => (liquor ? toDrinks(s) : s);
}

export const useHotelSettings = () =>
  useQuery({ queryKey: keys.settings, queryFn: () => api.get<HotelSettings>("/hotel/settings") });

/** A mutation that refreshes the given lists when it succeeds. */
export function useSave<TArgs, TResult = unknown>(
  fn: (args: TArgs) => Promise<TResult>,
  invalidate: readonly (readonly string[])[],
  saved: string | false = "Saved",
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: async () => {
      await Promise.all(invalidate.map((k) => qc.invalidateQueries({ queryKey: k })));
      if (saved) toast(saved);
    },
  });
}

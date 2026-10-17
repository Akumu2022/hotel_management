import clsx from "clsx";

import { isDrinks } from "../lib/i18n";

/** Keyword -> emoji for dishes without a photo yet. A warm tile beats an empty grey box. */
const EMOJI: [RegExp, string][] = [
  [/beer|lager|tusker|guinness|pilsner|\bale\b|stout|cider|balozi|white cap|castle/i, "🍺"],
  [/wine|merlot|chardonnay|sauvignon|rose|prosecco/i, "🍷"],
  [/whisk|brandy|cognac|\brum\b|jameson|johnnie|jack daniel|hennessy/i, "🥃"],
  [/vodka|\bgin\b|gilbey|tequila|cocktail|liqueur|baileys|smirnoff|konyagi/i, "🍸"],
  [/champagne|sparkling|[0-9]+ ?(ml|litre|ltr)\b|bottle|crate/i, "🍾"],
  [/chai|tea|coffee/i, "☕"],
  [/mandazi|doughnut|donut/i, "🍩"],
  [/egg/i, "🍳"],
  [/sausage|smokie|hot ?dog/i, "🌭"],
  [/fish|tilapia/i, "🐟"],
  [/pilau|biryani|rice/i, "🍛"],
  [/stew|soup|curry/i, "🍲"],
  [/chapati|bread|toast/i, "🫓"],
  [/nyama|goat|beef|meat|mutura/i, "🍖"],
  [/chicken|wings/i, "🍗"],
  [/chips|fries/i, "🍟"],
  [/kachumbari|salad|sukuma|greens/i, "🥗"],
  [/githeri|beans/i, "🫘"],
  [/mukimo|potato/i, "🥔"],
  [/mango/i, "🥭"],
  [/passion|juice/i, "🧃"],
  [/soda|cola/i, "🥤"],
  [/water/i, "💧"],
  [/burger/i, "🍔"],
  [/pizza/i, "🍕"],
  [/ugali/i, "🍚"],
];

const TINTS = ["#fff1ea", "#fef3c7", "#ecfccb", "#e0f2fe", "#fce7f3", "#ede9fe"];

export function emojiFor(name: string): string {
  return EMOJI.find(([re]) => re.test(name))?.[1] ?? (isDrinks() ? "🍺" : "🍽️");
}

function tintFor(name: string): string {
  let h = 0;
  for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return TINTS[h % TINTS.length];
}

export function FoodImage({
  src,
  name,
  className,
  emojiSize = "text-6xl",
  dim,
}: {
  src: string | null | undefined;
  name: string;
  className?: string;
  emojiSize?: string;
  dim?: boolean;
}) {
  if (src) {
    return (
      <img
        src={src}
        alt=""
        loading="lazy"
        className={clsx("size-full object-cover", dim && "opacity-50 grayscale", className)}
      />
    );
  }
  return (
    <div
      className={clsx("flex size-full items-center justify-center", dim && "opacity-50 grayscale", className)}
      style={{ background: `radial-gradient(circle at 30% 25%, #ffffff 0%, ${tintFor(name)} 70%)` }}
      aria-hidden
    >
      <span className={clsx(emojiSize, "drop-shadow-sm select-none")}>{emojiFor(name)}</span>
    </div>
  );
}

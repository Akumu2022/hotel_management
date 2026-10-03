import clsx from "clsx";

/** Keyword -> emoji for dishes without a photo yet. A warm tile beats an empty grey box. */
const EMOJI: [RegExp, string][] = [
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
  return EMOJI.find(([re]) => re.test(name))?.[1] ?? "🍽️";
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

/** A coloured tile with the customer's initial, derived from the order code, so a rider and the
 * hotel can spot the same order at a glance when many are waiting at the counter. */
function hue(code: string) {
  let h = 0;
  for (const ch of code) h = (h * 31 + ch.charCodeAt(0)) % 360;
  return h;
}

export function OrderTag({ code, name, className = "" }: { code: string; name?: string | null; className?: string }) {
  const initial = (name ?? "").trim().charAt(0).toUpperCase() || "#";
  return (
    <span
      aria-hidden
      style={{ backgroundColor: `hsl(${hue(code)} 62% 38%)` }}
      className={`flex size-11 shrink-0 items-center justify-center rounded-xl text-xl font-extrabold text-white ${className}`}
    >
      {initial}
    </span>
  );
}

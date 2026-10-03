# UI/UX Direction

Reference designs (screenshots of 2026-10-02 in `Pictures\Screenshots`): **Bonfol** POS and
dashboard, **D.CC** order queue and dashboard, **Epic Eats** admin. They are restaurant POS
designs for desktop, dine-in and walk-in sales. Our product is different: customers order
**on mid-range Android phones over patchy networks**, pay an **M-Pesa Till**, and get
**delivery or pickup**. We keep their visual language and change the structure to fit.

---

## 1. Visual system (taken from the references, tightened)

| Token | Value | Notes |
|---|---|---|
| Primary | `#C2410C` (fill), `#EA580C` (accents, charts) | Bonfol orange. Their `#F04E1A` with white text is about 3.6:1, which fails WCAG AA for normal text. The darker fill passes (5.2:1). |
| Surface | `#FFFFFF` cards on `#F5F5F4` page | Same as the references |
| Text | `#1C1917` / muted `#57534E` | Muted text must stay ≥ 4.5:1. The references' light-grey labels are too faint in sunlight. |
| Status | green = done, amber = in progress, red = problem, blue = info | Always **colour + text label**, never colour alone |
| Radius | 12 px cards, 10 px buttons, full pills for chips | |
| Font | System UI stack (no web-font download) | Saves about 100 KB on first load. `font-variant-numeric: tabular-nums` for all money |
| Money | `KES 650`, whole shillings, no decimals | The references use `$8.00`. Decimals imply cents we never charge. |
| Hotel accent | Per-hotel colour (spec §5) on the cover and header strip only | Buttons always use the primary colour, so contrast and recognition stay consistent |
| Photos | 4:3 fixed ratio, WebP thumbnail, lazy-loaded, blurred placeholder | Prevents layout jumps |
| Tap targets | ≥ 48 px high on customer and rider screens | The references' "Add" buttons (~32 px) are too small for thumbs |

**Remove everywhere:** decorative hatched/striped bars (D.CC), the duplicate donut "Total"
(Bonfol: it repeats the revenue figure), user avatars for customers, and fake trend
percentages with no defined baseline.

---

## 2. Customer app (mobile-first PWA)

Based on **Bonfol POS** (grid, category chips, cart panel) and the **D.CC** cart (stepper,
promo code), re-laid out for a phone.

### Keep
- Category chips under the hotel header. Make them **sticky and horizontally scrollable**, with time-based menus hiding unavailable categories.
- Photo-first product cards with name, price and a "Popular" badge.
- Search and a "Popular" sort.
- Option chips on cart lines ("Kerupuk +$1.00" → "Extra meat +KES 80").
- Promo-code field with an Apply button (D.CC).

### Remove
- **Dine In / Takeaway / Table location.** Replace with **Delivery | Pickup**.
- **Tax line.** Prices are tax-inclusive; the spec has no tax.
- The store-switcher dropdown in the header. Hotels are chosen on Home, and the cart holds **one hotel only** (D4).
- The permanent right-hand cart panel. On a phone it becomes a **sticky bottom bar** ("3 items · KES 1,240 · View cart") that opens the cart full screen.
- The "Input manually" button and bell/profile icons. The customer has no account.

### Improve
- **Add → stepper.** Tapping Add turns the button into `– 1 +` in place (D.CC's stepper, without the separate "Add to cart" step). Items with options open a bottom sheet first.
- **Sold out:** greyed photo plus a "Sold out" label in place of the button. Keep the item visible; don't hide it.
- **Server-calculated totals only.** The cart shows the latest `/quotes` result with a skeleton while it loads. If the total changes at checkout, show "Price updated: KES 770 → KES 790" and ask the customer to confirm.

### Add (missing from every reference)
1. **Home:** the 5 hotels as large cards with cover photo, Open / Closes in 20 min / Closed, and active offers. Closed hotels go last and can't be ordered from.
2. **Checkout (one screen, spec §5):** name and phone (pre-filled for returning customers) → Delivery/Pickup → map pin and landmark (pin outside the zone shows an inline error) → rider fee **A "Include in M-Pesa payment"** vs **B "Pay rider KES 100 cash"** as two cards that show the resulting total → M-Pesa or Cash at counter (pickup only) → promo → summary: *Food, Discount, Service fee, Rider fee, **Pay to Till***. Button text: **"Place order · KES 770"**, not "Proceed".
3. **Pay screen:** the Till number large with a Copy button, the exact amount, 3 numbered steps, an **expiry countdown** (D5), and a code field that checks the M-Pesa code format before submitting. After submitting, show "Checking payment…" (never "Paid" until the server confirms).
4. **Tracking page:** a vertical status timeline, the **4-digit delivery code in large type**, hotel phone (tap to call), rider name and phone once on the way, and a WhatsApp support link. Late-payment and review states use plain-language messages (D5).
5. **System states:** "You're offline — your cart is saved", "Ordering paused", "Kitchen closes in 15 min", and empty, error and skeleton states for every list.

---

## 3. Hotel dashboard (tablet or phone at the counter)

Based on **D.CC order queues** (status cards) and **Bonfol** KPI strip, popular-menu table and setup checklist.

### Keep
- **Order queue cards** (D.CC): code, customer, time, item count, status chip. Make this **the home screen**, not one panel among many.
- The KPI strip (Bonfol), redefined: *Waiting to accept · In kitchen · Ready for rider · Sales today (KES)*.
- The "Popular menu" table (Item · Orders · Sales) for reports.
- **"Setup store 6/7 steps"** (Bonfol): great for onboarding. Steps: hours, Till number, categories, menu with photos, staff, cash pickup choice, test order.
- One flat revenue bar chart (Bonfol) on Reports only.

### Remove
- The POS product grid / "Input manually". Hotels don't place orders in this app.
- Tables, Available Tables, Procurement, Inventory, Stock, Recipes, Production, Subscription, and the multi-store cards (one login = one hotel).
- The "Open Sales" button and the date/shop pickers on the live screen.

### Improve and add
- **Board by status:** New (paid) → Accepted → Preparing → Ready → Out / Collected. Tap a card to open it. Big buttons for the single next action.
- **New paid order:** full-width alert banner with repeating sound and a **countdown to auto-reject** (D6: escalates at 5 min, auto-rejects at 10). Accept shows prep-time chips (10 / 15 / 20 / 30 min). Reject requires a reason picker.
- Header: an **"Accepting orders" toggle** that is always visible, plus a **"Payment phone offline"** warning when the forwarder is silent.
- **Payments tab:** review queue with a badge count, manual confirm (code + amount), "Cash received", and rider fee handover.
- **Menu editor:** list rows with a one-tap **Sold out** switch; edit in a side sheet; photo upload compressed on the device.
- **Money tab:** this week's amount owed, due date, statement history, and a pause warning before it happens ("KES 4,200 of 5,000 limit").

---

## 4. Super admin (desktop)

Based on the **Epic Eats** layout: grouped sidebar, KPI row, tables.

### Sidebar
- **Daily operations:** Live board, **Dispatch** (ready orders without a rider), **Review queue** (badge), Orders
- **Partners:** Hotels, Riders, Customers (flags and blocklist)
- **Money:** Statements, Settlements, Rider payouts
- **System:** Forwarder devices, Settings, Audit log

### Remove from Epic Eats
Top countries, restaurant logos and brand lists, table bookings, profit/earnings dual charts,
and "Restaurants support" ticketing.

### Add
- KPI row: *Orders today · Awaiting acceptance · Unassigned ready orders · Open reviews · Hotels overdue*. Each card links to its filtered list.
- **Duty alerts banner** for anything time-critical: unaccepted orders past 5 min (D6), escalated late payments (D5), offline payment phones.
- **Settings page** as a plain form in sections (Fees, Timers, Limits, Delivery zone map). Show an "Unconfirmed defaults: review and save" banner until saved (D1), and the change history underneath.

---

## 5. Rider area (phone, outdoors, one hand)

None of the references cover it. Design it minimal:
- An **Online / Offline** toggle the full width of the screen.
- One current-job card: pickup → drop-off, landmark, call customer, open in Maps.
- One big next-action button: *Picked up → On the way → Enter delivery code*.
- Delivery code entry on a **numeric keypad with 4 large boxes**.
- Fee buttons: "Fee received", and "Fee not paid" (only after delivery, D8).
- Statement: this week's deliveries, fees received, pending payout.

---

## 6. Build notes
- React + Tailwind + shadcn/ui, with the tokens above in `tailwind.config` and CSS variables.
- Four route areas in one PWA: `/` customer, `/hotel`, `/rider`, `/admin`. Admin and hotel code is lazy-loaded so the customer bundle stays small (target < 150 KB JS gzip for the customer area).
- Test on a real mid-range Android over throttled "Slow 4G" before each milestone sign-off.

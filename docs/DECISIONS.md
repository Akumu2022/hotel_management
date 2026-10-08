# Spec Addendum — Decisions for Build

Source spec: *Hotel Food Ordering App — Developer Specification* (Oct 1, 2026).
This addendum overrides the spec wherever they differ. Agreed 2026-10-02.

Planning volume: **~100 orders/day across 5 hotels** (≈20 per hotel; peak ≈15–20/hour platform-wide).

---

## D1. Business settings are admin-entered, never hard-coded

- All section-2 values are form fields in the super-admin panel (**Settings**), stored in the `settings` table and validated by a typed schema in code (e.g. commission must be 0–50 %, money must be a whole shilling ≥ 0).
- Admins type percentages as normal numbers (`10` or `12.5`); they are stored as basis points (`1000`, `1250`). Money is entered and stored in whole KES.
- **Per-hotel overrides** for commission rate and service fee, because each partner agreement may differ. A blank hotel value falls back to the global default.
- Seed values = the spec's proposed defaults, marked **unconfirmed**. The admin dashboard shows a banner until an admin has reviewed and saved them once.
- Every change is audit-logged (who, old → new, when) and applies **to new orders only** (orders snapshot the values).

| Setting | Seed value |
|---|---|
| Commission | 10 % of food after discounts |
| Service fee | KES 20 |
| Rider fee (single zone) | KES 100 |
| Rounding | Round down to whole shilling (fixed rule, not a setting) |
| Unpaid order expiry | 20 min |
| Late-payment grace (see D5) | 24 h |
| Hotel acceptance timeout (see D6) | 10 min (alert duty person at 5 min) |
| First-time cash pickup cap | KES 1,000 |
| Hotel unpaid-balance limit | KES 5,000 or 3 days overdue |
| Rider "fee not paid" compensation cap | 2 per rider per week |
| Order cut-off before closing | 15 min |
| Rider payout default | Instant |
| Delivery zone | Polygon drawn on the map by the admin |

## D2. PostgreSQL everywhere

- PostgreSQL 16 in development (Docker Compose), CI and production. **SQLite is dropped**, along with the "SQLite in development: rules" in spec section 3.
- PostgreSQL features may be used directly: row locks, partial unique indexes, `CHECK`, `INSERT … ON CONFLICT`, and later `LISTEN/NOTIFY`.
- The backend runs on **Python 3.13**, not the host's 3.14, for library wheel compatibility. Tests run against a real PostgreSQL server.
- **Amended 2026-10-02 (owner): no Docker during development.** Local development uses a Python 3.13 virtualenv and a portable PostgreSQL 16 started by `backend/scripts/dev-db.ps1`. The Docker files stay in the repo for deployment (M9) and are revisited then. CI keeps using a PostgreSQL 16 service.

## D3. Fixes to contradictions in the spec

1. **Discounts, promos and offers are in Phase 1 (M2).** They are removed from Phase 2.
2. **The matching engine is built in M4, not M9.** It is tested by inserting SMS records directly, so every matching case in section 14 (including SMS-before-code) is testable in M4. M9 (now M8, see D10) only adds the Android app and signed ingest. Because a real SMS sample exists, the **parser is also built in M4**.
3. **Refund ledger entries are keyed per refund.** `ledger_entries` gets a `refund_id` column, with unique `(refund_id, entry_type)`. This allows several partial refunds per order.
4. **Commission on refunds is reversed pro rata, cumulatively.** Each refund records how much of it is food, service fee and rider fee. After each refund:
   `commission_reversed_total = floor(rate × total_food_refunded)`, and this refund's reversal = that total − earlier reversals.
   It can therefore never exceed the original commission. The service fee is reversed only on a **full** refund.

## D4. Ordering scope

- **One hotel per cart.** Adding an item from another hotel asks the customer to clear the cart.
- **Scheduled orders are removed from launch.** The `scheduled_for` column is left out of the first migration.
- Orders are accepted only while the hotel is open, not paused, and "Accepting orders" is on, up to the closing cut-off.

## D5. Late payment (money arrives after expiry)

- **Entering a code pauses expiry.** When a customer enters a transaction code, the order moves to *Checking payment* and is not expired while matching or review is pending.
- **Payments are always stored.** A payment matching an **expired** order within the grace period (24 h) creates a `late_payment` review item. The tracking page shows "Payment received after the order expired — the hotel is reviewing."
- **The cashier chooses Reinstate or Refund.** Reinstate checks the items are still available, then moves the order to **Paid** and the normal flow runs. Refund creates a full refund record.
- **Escalation.** If unresolved after 15 minutes it goes to the duty person. If still unresolved at hotel closing, it defaults to Refund.
- **Countdown.** The tracking page shows the expiry countdown, to prevent late payments in the first place.

## D6. Hotel does not accept a paid order

- **0 min:** loud repeating alert plus Web Push.
- **5 min:** duty person alerted (admin dashboard alert plus push).
- **10 min:** automatic reject (reason `not_accepted_in_time`). The full refund record comes from the hotel's Till, since the money is already there.
- **Repeat misses:** two auto-rejects in a row switch the hotel's **Accepting orders** off. Staff turn it back on with one tap. Misses are shown in hotel reports.

## D7. Failed delivery

The super admin classifies every failed delivery:

| Cause | Customer | Rider fee | Other |
|---|---|---|---|
| **Customer fault** (unreachable for 10 min after arrival, refused, wrong pin) | No refund | Rider keeps or is paid the fee (option B: platform compensation, as in D8) | Number loses option B; 2nd case → blocklist |
| **Rider fault** (lost, spilled, accident) | Full refund from the hotel's Till | Rider earns no fee for the job | Platform credits the hotel the refunded amount on its weekly statement (ledger: Platform owes Hotel). Rider gets a strike; 2 strikes in 30 days → suspended |
| **Hotel fault** (wrong or missing order) | Refund (full or item) from the hotel | Rider keeps the fee | — |

## D8. Rider "fee not paid" (option B) — anti-abuse

- **Only after a verified delivery code.** "Fee not paid" can only be tapped after the order is **Delivered**, so the rider must have met the customer.
- **The customer is asked.** The tracking page asks: "Did you pay the rider KES 100?"
  - **Yes:** dispute review item; no compensation until an admin resolves it.
  - **No, or no answer within 24 h:** compensation is approved.
- **Compensation is paid in the weekly rider payout,** never instantly. This leaves time for review.
- **Cap per rider:** more than 2 compensations a week goes to manual review.
- **Customer number:** the customer's number loses option B on the first confirmed case and is blocklisted on the second.

## D9. Phone identity and SMS

- **Unverified numbers are an accepted pilot limitation.** Phone numbers are not verified (no OTP), so per-phone rules can be bypassed.
- **Partial check once the forwarder runs:** the masked payer digits in the Till SMS are compared with the checkout phone. A mismatch does not block payment (people pay from other phones). It only stops the order counting toward "trusted / not first-time" status.
- **SMS provider: Africa's Talking,** behind a `SmsSender` interface. In development it logs to the console.
- **The "rider on the way" SMS includes the 4-digit delivery code,** so a person receiving an order placed by someone else can complete delivery.

## D10. Revised milestones

At 100 orders/day, manual payment confirmation means about 20 code entries per cashier per day. The forwarder is the biggest operational saving, so it moves **before** the pilot.

| # | Milestone | Change from spec |
|---|---|---|
| M1 | Foundation | PostgreSQL only; settings schema and admin-editable settings (D1) |
| M2 | Hotel catalogue | Includes discounts, promos, offers |
| M3 | Ordering | One hotel per cart; no scheduled orders |
| M4 | Payments | Plus matching engine and SMS parser (from samples), late-payment flow |
| M5 | Hotel operations | Plus acceptance timeout and auto-reject (D6) |
| M6 | Riders | Plus D7/D8 rules |
| M7 | Statements | Refund-keyed ledger (D3) |
| M8 | **Forwarder** (was M9) | BroadcastReceiver + WorkManager + periodic inbox rescan instead of a permanent foreground service; tested early on the real Till phones (Android 13+ "restricted settings" step documented) |
| M9 | **Pilot** (was M8) | — |
| Later | Flutter rider app, Daraja | unchanged |

## D11. Infrastructure

- **Oracle Cloud:** upgrade the account to Pay-As-You-Go (still free within Always Free limits). This avoids idle-instance reclamation. The fallback is still a ~USD 5 VPS.
- **Repository layout (monorepo):**
  ```
  backend/      FastAPI app, Alembic, tests
  web/          React + Vite PWA (customer, hotel, rider, admin areas)
  forwarder/    Kotlin Android app (M8)
  docs/         spec addendum, SMS samples (anonymized)
  docker-compose.yml
  ```

## D12. Rules chosen during M1 (gaps in the spec)

- **One discount per level.** Each line gets the single best item discount; the order gets the single best order discount. A promo code competes with automatic discounts at its level; if it is not better, the quote says `promo_not_better`. Fixed item discounts are per unit.
- **Overpayment refunds** are a separate refund part (`excess_amount`) that reverses no commission or fee.
- **Refund approval is idempotent** via a client-supplied refund ID. The ledger entry for the money leaving the hotel is written when the M-Pesa code is recorded.
- **Ledger semantics.** Each entry is either an *obligation* (who owes whom) or a *payment* (money moved). Balances = obligations − payments in each direction. `ledger_entries`, `order_events` and `audit_log` are append-only through a database trigger.
- **Refresh-token reuse** (presenting a rotated token) revokes all of that user's sessions. Deactivating a user or changing their password does the same.

## D12b. Rules chosen during M2

- **Cashiers** can read the catalogue but only flip *Sold out* and *Accepting orders*. Everything else in the catalogue and settings is for the hotel admin. A hotel's name, Till and phone are set by the super admin only.
- **Discount terms are fixed once created** (scope, product, percent or amount, minimum spend, code), because orders refer to them. Only the dates, use limit and on/off switch can change.
- **Promo codes** are 3–20 letters or digits, stored in capitals, and unique per hotel. A total use limit only applies to promo codes.
- **Categories** can be deleted only when empty; products are archived, never deleted.
- **Sold-out dishes stay visible**, greyed out. Archived dishes and empty categories are hidden from customers.
- **Photos** are re-encoded to WebP (1200 px plus a 400 px thumbnail) with EXIF/GPS stripped. A hotel can only attach photos it uploaded itself.
- **Opening hours**: a closing time at or before the opening time means the hotel closes after midnight. Customers see "closing soon" in the 30 minutes before the order cut-off.

## D12c. Rules chosen during M3

- **Cash pickup orders never expire.** They start in *Awaiting payment* with no expiry, and the hotel accepts them directly (after a confirmation call for first-time numbers). Cash is recorded at collection. Only M-Pesa orders expire after the set time.
- **No delivery until the zone is drawn.** Until the admin saves a delivery zone, checkout offers pickup only.
- **Price changes:** the phone sends the total it showed (`expected_total`). If the server's total differs, the order is refused with the new quote, the customer confirms, and the same Idempotency-Key is reused (the failed attempt left nothing behind).
- **An unusable promo code** the customer typed refuses the order with the promo reason, rather than silently charging full price.
- **Order codes** are 6 characters from an alphabet without look-alikes (no 0/O, 1/I, 5/S…). Tracking tokens are 32 random URL-safe characters.
- **Rate limits** (per IP per minute): 10 order placements, 60 quotes, 120 tracking reads, 10 cancels. They are in-memory, which is correct for the single API process at launch.
- **Unknown request fields are rejected** (e.g. a `price` sent by a phone), not ignored.

## D14. Rider fee by distance; admin-drawn delivery area (owner, 2026-10-02)

- **The rider fee depends on distance**, not a flat fee. The super admin sets bands (default: up to 2 km KES 100, up to 5 km KES 150, up to 10 km KES 200), measured in a straight line from the **hotel's map location** to the customer's pin. Beyond the last band, delivery is refused ("too far, choose pickup").
- The server computes the fee; the phone never sends it. Before a pin is dropped, quotes show the nearest band as "from KES X". A hotel without a location is charged the nearest band.
- **The delivery area is drawn by the super admin** on a map (*Delivery & fees*): a circle (centre plus radius slider) or a tapped outline. Pins outside it are flagged on the map immediately and refused by the server. With no area saved, checkout offers pickup only.
- Hotel locations can be set by the super admin (*Delivery & fees → Hotel locations*) or by the hotel admin (*Settings → Hotel location*).
- This replaces the flat `rider_fee` setting (migration 0002 converts it).

## D29. Secrets stay on the server; owner can clear "Needs attention" (owner, 2026-10-06)

- **Login sessions:** the refresh token is an httpOnly, SameSite=Strict cookie limited to `/api/v1/auth`; it is never in a response body or in browser storage, so page scripts and DevTools' storage panel can't read it. The 15-minute access token is kept in memory only. The browser keeps just the non-secret profile (name, role) to draw screens. Old stored sessions are moved to the cookie automatically on the next visit. Refreshes are serialised across tabs (Web Locks) so two tabs can't trip the token-reuse protection.
- **Login is rate limited** (10 attempts per minute per IP; password changes too).
- **Production refuses weak secrets:** with `APP_ENV=production` the API won't start unless `JWT_SECRET` and `FORWARDER_KEY` are 32+ random characters and `COOKIE_SECURE=true`. Secrets live only in the server's environment, never in the web app.
- **Needs attention:** a hotel's payment item is the hotel's alone for its first 15 minutes; once escalated to the owner's queue, the owner can settle it with the same actions (recorded as resolved by the owner), so the queue can always be emptied.
- **Notification bell** (owner, hotel and rider top bars): lists exactly what is ringing (the same list that plays the sound) with a Go link to where it's fixed, plus items that wait without sound (owner: hotel payment items to settle, rider applications). It never silences an alarm.
- **Dismissing "no SMS" closes the order** as expired, "Payment not received". Before, the order stayed in checking-payment and the every-minute job reopened the item, so it could never be cleared. Money arriving later is a late payment (D5).
- **Dispatch: Cancel & refund** a delivery that has no rider (same rules as Find order), so the "Delivery has no rider" alarm can always be ended.
- **Production web image** (`web/Dockerfile.prod` + `web/nginx.conf`): static build served by nginx (~8 MB memory vs ~180 MB for the dev server), long caching for hashed files, no caching for the service worker.

## D28. Eat-in orders, ratings, password reset, owner creates hotels (owner, 2026-10-05)

- **SMS matching uses the full number.** Real Till SMS show the payer's full number (`254792468015`). When it is full and equals exactly one waiting order's checkout number with the same amount, that order is paid whatever the name. Masked numbers keep the D25 rules (last 3 digits + name). While the Till phone is online, the hotel's waiting card says the payment confirms automatically; manual entry is a fallback behind a link.
- **Eat in** is a third order type beside delivery and pickup: order ahead, pay first, come and eat. No map, no rider, no delivery fee. The customer picks an arrival time. The order flow is unchanged: the hotel prepares only after payment is confirmed, and cancels/refunds follow the existing rules. Every screen marks it **EAT IN** so the hotel can tell it apart.
- **Eat-in markup** (`eat_in_fee`, KES, owner-entered under Settings, may be 0) is added to the customer's total and paid to the hotel's Till with the food. The hotel keeps none of it: it goes on the hotel's weekly statement as owed to the platform, like the service fee.
- **Ratings:** after a completed order the customer may rate the hotel (all orders) and the rider (delivery orders), 1–5 stars with an optional comment, once per order. Averages show on the admin pages; the customer hotel list puts higher-rated hotels first (open hotels before closed ones still).
- **Passwords:** every password box has a show/hide eye. The super admin can reset any staff or rider password, a hotel admin their own staff; the person gets a temporary password and must change it at next login. Everyone can change their own password. Self-service reset by SMS is "later".
- **Hotels are created only by the owner** (super admin), from an admin screen that also creates the hotel admin's login. There is no hotel self-sign-up.
- **Coordinates:** hotel locations can also be typed/pasted as `lat, lng` (e.g. from Google Maps). Rider GPS fixes worse than 100 m accuracy are not used for the live position.

## D34. Everything is paid first; protecting customers from copycats (owner, 2026-10-08)

- **No more "cash when I collect".** Every order (delivery, pickup, eat in) is paid by M-Pesa to the hotel's Till **before the hotel starts**. This removes the "ordered and never came" loss. The server refuses any new cash order (`cash_not_accepted`, 422); the quote says `cash_allowed: false`; the checkout (web and app) and the hotel's settings no longer offer it. Cash orders already in the system finish as before. The delivery option where the rider fee is paid in cash to the rider (option B) is a separate thing and is unchanged.
- **The platform never holds customers' money.** Customers pay the hotel's own Till directly (D1). A hotel is only told to start once its own Till's SMS (read by the Chakula Till app, D26) shows the payment, so nobody, including Chakula, can "disappear with" customer payments.
- **Telling the real platform from a copycat** (a lookalike app or site showing its own Till):
  - **Till name check.** The owner records the business name M-Pesa shows for each hotel's Till. The customer's payment card says "M-Pesa will show: ZZ TEST KITCHEN LTD" and "if it shows a different name, don't pay: call the hotel". A copycat's Till will not carry the real hotel's name.
  - **"Checked by Chakula" badge** on a hotel only after the owner has met the hotel and ticked "I have checked this hotel and its Till" (a real check, not automatic). **Only the super admin can set it.** If a hotel changes its Till number (or the admin changes the number or name), the badge and the recorded name are removed until it is checked again, so a hijacked hotel login can't quietly send customers to another Till.
  - **Safety card** on the home screen and the payment card ("How we keep your money safe") says: pay only the hotel's Till; check the name; only use the official app or website; never pay someone who messages you privately.
  - The 4-digit PIN (D33) proves food was handed over, so a hotel cannot claim a handover that did not happen.
- **Still to do outside the code:** one official, memorable web address with HTTPS; the app on the Play Store under your own developer account; hotel contracts; a way for customers to report a fake. These are what stop customers being fooled by a lookalike, and no feature inside the app can do that on its own.

## D33. Pickup PIN, rider bike details and the rider app (owner, 2026-10-08)

- **Pickup and eat-in PIN.** Every order gets a 4-digit PIN (the same `delivery_code` that delivery orders already had). For pickup and eat in, **the customer reads their PIN out to the hotel** and the hotel types it in before the order can be marked collected. The customer sees the PIN on their tracking page (web and app) once the order is paid. It proves the person at the counter is the one who ordered, so nobody else can collect the food.
  - The hotel's screens and API **never show the PIN**; they only ask for it.
  - Five wrong PINs lock the handover (423). The hotel is told to call the customer. A correct PIN is still refused after the lock.
  - Cash pickup needs the PIN too (the cash is recorded at handover).
  - Orders placed before this existed have no PIN and are handed over as before. Repeating a finished handover is harmless.
- **Rider bike details.** To apply, a rider gives the **number plate** (saved as capital letters and digits, 5–10 characters with both) and a **short description** of the bike. A **logbook photo is optional**. The logbook is a private file like the ID photos; only the super admin can open it. The admin's review page shows the plate, description and logbook. Riders who joined earlier have no bike details; they can add them while their application is open, and a draft can't be submitted without them.
- **Call and WhatsApp buttons** use the hotel's own phone (set by the hotel admin in Settings) and the rider's or customer's phone from the order. They are hidden when there is no usable Kenyan number. Chakula's own WhatsApp help line stays the admin's `support_whatsapp` setting.
- **Rider app (Android).** Built with the customer app from one Flutter project, as a separate install ("Chakula Rider", `com.hotelapp.hotel_app.rider`, dark icon), so the customer app stays small and only the rider app asks for background-location permissions.
  - Sign up (details and bike, photos, review), sign in, "pending / fix and resend / paused" screens, jobs (go online, take, picked up, on my way, delivered with the customer's code, cash fee, can't deliver, release), history and earnings, profile, change password, English / Kiswahili, dark mode.
  - While online it shares its location every ~30 s (~10 s on the road) using an Android foreground service, so it keeps working when the screen is locked, which a web page cannot do. The web rider page still works.
  - Build: `flutter build apk --flavor rider -t lib/rider/main.dart`. The customer app is `flutter build apk --flavor customer`.
  - The login's refresh token is kept in the phone's app storage. Move it to the Android Keystore before launch.

---

## D31. Launch hardening and stuck deliveries (owner request, 2026-10-06)

- **Stuck deliveries have a way out.** Dispatch shows **Close delivery…** on any delivery whose food has left the hotel. The super admin picks *Customer got the food* or *It could not be delivered*, and writes what happened (shown to the customer, rider and hotel, and audit-logged).
  - *Delivered* follows the rider's own rules without the code (the customer's completed-order count, and the rider fee as usual). For cash-fee deliveries the admin says whether the customer paid the rider; if not, Chakula pays the rider (D8).
  - *Could not be delivered* files the usual failed-delivery decision under Needs attention, where the admin picks whose fault it was, and refunds, rider pay and strikes follow D7. A double tap changes nothing.
  - Not available before pickup (use Swap rider or Cancel & refund there).
- **The alarm can be silenced, not hidden.** The bell offers *Silence for 10 min / 30 min / 1 h*. Sound, vibration and the system notification stop; the bell, badge and tab title stay. It rings again when something new arrives or time is up. This relaxes D22's "no silence button".
- **The payment simulator is development-only.** `POST /admin/test-payment` (any code, any amount) is refused when `APP_ENV=production`, unless `PAYMENT_SIMULATOR=true` is set (and `check-production` then fails). Pasting a real SMS (`/admin/test-sms`) stays, for messages the Till phone missed, and every use is audit-logged with the text. The Tools page hides what the server disables.
- **Web Push** (replaces "deferred to M9" in D6). Staff and riders can turn on alerts per device; nothing about what rings or when changes. Hotel: new order, payment to confirm. Rider: delivery waiting (online riders), job assigned. Super admin: decisions needed. Same tag replaces an earlier notification. The page's own alarm is used when it is open and visible. Off until VAPID keys are set.
- **Rider location (D27 limit).** A web page can only share location while it's open. Now: the screen stays awake while the rider carries an order, a fresh position is sent the moment the app returns to the front, a notice asks the rider to keep Chakula open, and one tells them if it was away for a minute or more. The customer sees "location paused" after 5 minutes. The lasting fix is a native rider app with a foreground location service (the Till app's Kotlin base can be reused); until it exists, dispatch has the map and the Close delivery action.
- **Shared rate limits** with `REDIS_URL` (see README); in-memory otherwise, and in-memory if Redis is down.
- **Routing server** is configurable (`OSRM_URL`); README explains how to run your own.
- **Launch check:** `python -m app.cli check-production` lists what must be fixed before going live. `seed-demo` refuses to run in production and no longer uses a password written in the code (`DEMO_PASSWORD` or a random one, printed once).
- **Tests:** the real-SMS sample moved to `backend/tests/data/` so tests run from the `backend` folder alone.
- **Hotel hours restored** after testing: 06:00 to 23:30 every day, order cutoff 15 minutes.

## D30. Customer live rider map (owner request, 2026-10-06)

- **When:** on the customer's tracking page, once the rider has collected the food (picked up / on the way). Not before, not after delivery, and never another order's rider. Pickup and eat-in orders have no map.
- **What the customer sees:** a map with the hotel, their pin, and the rider gliding along. A dotted orange line flows from the rider to the door along the road (the straight line is shown until the road route arrives, or if routing is unavailable) and shortens as the rider gets closer. Under the title: distance, "about N min" (20 km/h motorbike estimate) and "Live / Updated Ns ago". Over 5 minutes without a position it says the rider's location is paused. Fully translated for Kiswahili.
- **How:** each rider position is pushed to that order's live channel (`rider_location`) and also returned in `GET /track/{token}` as `live`. `GET /track/{token}/route` returns the road line (OSRM, cached 60 s on a ~110 m grid, failures cached 30 s, 15 s timeout, 30 requests/min per client).
- **Rider app:** while carrying an order it sends a position every 10 s or 40 m (was 30 s / 100 m). Idle riders are unchanged.
- **Privacy:** only the rider's first name, phone and photo (already shown) and the position, and only while the food is on the road. The customer's own pin is theirs already.
- **Limits:** the public OSRM demo server can take 10 s or more, so the first road line may arrive late; self-host OSRM at scale. Like D27, positions only flow while the rider's Chakula screen is open.

## D27. Rider live location (owner, 2026-10-03)

- While a rider is **online**, the rider screen sends the phone's GPS position every 30 s, or sooner after moving 100 m. Going offline stops it. Riders see "Sharing your location with dispatch". Only approved, online riders can send a position.
- **Dispatch map** (super admin) shows riders (green = free, orange = on a job, grey = not seen for 5+ minutes), hotels (🏪) and customer drop-off pins. A dashed line runs from each rider to where they're heading next, with the distance.
- During a job each fix is also kept (at most one per 20 s) as the job's **trail**, `GET /admin/dispatch/{order}/trail`, for disputes. Trails are deleted after 30 days.
- Limitation: a web page can only share location while it's open. Riders must keep the Chakula screen open while on a job; a closed browser stops updates. The Flutter rider app ("Later") would lift this.

## D26. SMS forwarder: the Till phone app (M8, 2026-10-03)

- **App:** `forwarder/`, "Chakula Till", Kotlin, Android 8+. Tested on Android 16. Built with `./gradlew assembleDebug`; hotels download it from `/downloads/chakula-till.apk` (copied from the build, not committed).
- **Pairing:** the hotel admin (Settings → Till phone) or super admin (Tools → Till phones) shows a one-time 8-letter code, valid 15 minutes. The app sends it with the server address and receives its device ID and signing secret. The secret is stored encrypted by the phone's Android Keystore. Server side it is never stored: it is HMAC(`FORWARDER_KEY`, a per-phone salt). **One phone per Till**: pairing a new phone unpairs the old one.
- **Every request is signed** (HMAC-SHA256 over timestamp, nonce and body hash). Requests more than 5 minutes off, a reused nonce, a changed body or an unpaired phone are refused.
- **Only messages from MPESA** are read and sent. The app filters on the phone, and the server drops anything else unread.
- **Delivery without a permanent notification:**
  - An SMS broadcast queues the message and uploads it as soon as there is internet.
  - A 15-minute WorkManager check-in rescans the inbox for the last 3 days, uploads anything not yet acknowledged, and reports health (battery, queue size, SMS permission).
  - The server stores each raw message once and ignores repeats, so resending is always safe. One message that fails to process goes to review and never blocks the rest.
- **Health:** a phone not heard from in 40 minutes, with SMS permission off, or with messages stuck is shown as a problem on the hotel's Settings and Payments pages and on the admin's Tools page.
- **Android 13+:** an app installed from a file must be allowed "restricted settings" before it can get SMS permission. The app shows the steps (App info → ⋮ → Allow restricted settings) and asks to be excluded from battery optimisation.
- **Tested end to end in the Android emulator:** pairing; an SMS without a code confirming the right order by itself; the phone offline (message queued, sent when back online); a wrong payer name going to review; an app update keeping its pairing.

## D25. Rider free again; payer name check (owner, 2026-10-03)

- **Dispatch shows when a rider is free.** Each rider shows *Free · ready for a job*, *On N jobs* or *Offline*, plus their last delivery ("Delivered #XWUMVX 3 min ago"). A *Just finished* list covers the last 12 hours, and when a delivery completes while Dispatch is open a green notice says the rider is free for the next job.
- **Payer name vs checkout name.** The Till SMS name is compared word by word, in any order, with the name typed at checkout. It tolerates one-letter slips (Mohamed/Mohammed) and short forms (Kam/Kamau). Words of 1–2 letters never count. Score: 2 names, 1 name, or none.
  - **With the customer's code**, the code decides: the order is paid whatever the name (people pay for each other). The hotel's order card shows "Paid by …" with the match.
  - **Without a code**, an order is chosen automatically only if exactly one waiting order fits the amount, the phone digits and **at least one name**; two names beat one. If the amount fits but no name matches, nothing is confirmed and the hotel gets a review item naming the likely order, to check and use *Match to order*.

## D24. Cancel after accepting; weekly billing to the platform (M7, owner 2026-10-03)

**Cancel & refund after accepting.** The hotel admin (own hotel) or the super admin can cancel an order the hotel accepted but can't finish (e.g. ran out mid-cook), with a reason. Everything received is refunded through the normal refund flow, commission and service fee are reversed, and a rider who took the job loses it. Once the food is with a rider, it's a failed delivery instead.

**Hotels pay the platform directly** by M-Pesa Send Money to **0742554713** (setting `platform_mpesa_number`, editable under *Delivery*).

- **Statements:** one per hotel per week (Monday–Sunday, Kenya time), made automatically on Monday by the every-minute job. A statement shows commission, service fees, rider fees held for weekly riders, credits (refund reversals, platform bonuses, failed-delivery credits), the balance brought forward and any payments during the week. *Amount due* is the running balance at the end of the week; paying ahead carries forward. Commission is summed from the stored per-order amounts, never recalculated. No statement is made for a week with no activity and nothing owed.
- **Due date:** Monday + `hotel_overdue_days` (default 3, i.e. Thursday). A statement is **paid** once confirmed payments made after its week cover its amount. Paying the latest statement clears the earlier ones.
- **Paying:** the hotel admin enters the M-Pesa code and amount (*Chakula bill* page; cashiers don't see it). It counts only when the super admin confirms it against their own M-Pesa message. The admin can correct the amount, or mark it *not received* with a reason, and the hotel can fix that claim and send it again. Pending claims ring the super admin until handled. Codes are unique across hotels and repeated taps are harmless.
- **Auto pause:** a hotel is paused while a statement is overdue, or while what it owes on issued statements exceeds `hotel_unpaid_limit` (this week's sales don't count until they're on a statement, so busy hotels aren't paused mid-week). It resumes by itself the moment a confirmation clears it. A pause the admin set for another reason is never lifted by billing.
- **Rider payouts:** the Billing page lists what the platform owes each rider (weekly-paid fees, compensation). The admin sends the money by M-Pesa and records the code. Several payouts per week are allowed, but never more than is owed. Riders see what they're owed and their payouts on their home screen.

## D23. End-to-end journeys and the gaps they found (2026-10-03)

**Alarms stop by themselves.** Each alarm follows a live count of what is waiting, never a "silence" button. When anyone, on any device, does the action, the server pushes the change to every open screen (Server-Sent Events) and the alarm stops.

Measured in Chrome:

| Action | Other device stopped after |
|---|---|
| Hotel accepts a new order | 0.3 s |
| Refund marked sent | 0.7 s |
| Rider takes an open job | 0.1 s |

`backend/tests/test_e2e.py` runs 16 journeys across all roles through the HTTP API and asserts each alarm starts and stops:

- pickup paid by SMS; delivery with two riders; admin assignment and swap;
- option B unpaid fee; customer cancel; hotel reject;
- unaccepted order → duty alarm → auto-reject → hotel paused;
- under- and overpaid; expiry and late payment; first-time cash cap;
- failed deliveries → strikes → suspension; rider can't go offline with a job; no-rider and long-delivery alarms;
- double taps; access control.

**Gaps found and fixed:**
1. **Refunds to send rang nobody.** They now join the hotel payment alarm until marked sent. Approving or sending a refund broadcasts at once.
2. **Resolving a review item didn't broadcast**, so other devices rang for up to 15 s. It now broadcasts at once.
3. **An assigned job's "seen" state lived only on the rider's phone.** It's now stored on the server (`orders.rider_seen_at`): taking a job, tapping "Got it" or acting on it counts as seen, and Dispatch shows "Not seen yet: ringing".
4. **Riders could go offline while holding a job.** Refused until they finish or drop it.
5. **Suspending a rider stranded their jobs.** Jobs not yet collected go back to the open pool and ring other riders.
6. **No alarm for a stuck delivery.** The admin is now rung when a delivery has been on the road 45+ minutes, until it's delivered or failed.
7. **A customer asked "did you pay the rider?" got no sound.** The question now rings on the tracking page until answered.
8. **An unmatched payment could only be dismissed.** This happened when a customer paid without sending their code and the amount matched no single order. New **Match to order** action: the cashier types the order number and the normal checks run (exact, under, over, or late if the order had expired). It's refused for unknown or already-paid orders.

**Still open (not built yet):**
- ~~Weekly statements and rider payouts (M7).~~ Done, see D24.
- ~~The SMS forwarder app (M8).~~ Done, see D26.
- Web Push for closed browsers, and deployment (M9).
- ~~No way to cancel an order after the hotel has accepted it.~~ Done, see D24.
- Customers get no SMS updates (only the open tracking page).
- ~~No rider live location.~~ Done, see D27.
- Phone numbers aren't verified (D9).

## D22. Alarms ring until the action is done (owner, 2026-10-02)

- **One shared alarm** (`web/src/lib/alarm.ts`) on every staff screen, not just one page.
  - A **looping** WebAudio sound keeps playing in background tabs, where timers are slowed.
  - It stops only when nothing is waiting. With several reasons at once, the most urgent tone plays.
- **Sound unlock:** browsers block sound until the user touches the page, so the **first touch or key press anywhere** unlocks it. A banner shows until then, red if something is already waiting.
- **While ringing:** the tab title flashes "🔔 (n) …", phones vibrate, and a hidden tab shows a **system notification that stays up** until the action is done. Permission is asked on the first touch.
- **What rings, and what stops it:**

| Who | Rings for | Stops when |
|---|---|---|
| Hotel | New order | Accepted or rejected |
| Hotel | Payment code to confirm, or a payment problem | Confirmed or resolved |
| Rider (online, approved) | A job assigned to them | They tap **Got it** (jobs they take themselves count as seen) |
| Rider | Open jobs while they have none | They take one, or another rider does |
| Super admin | Order not accepted after 5 min | Accepted or auto-cancelled |
| Super admin | Ready delivery with no rider for 5+ min | A rider is assigned |
| Super admin | Failed delivery, fee dispute, item with no hotel | Resolved |

  Stale hotel payment items only show a badge for the admin, because the hotel resolves them; the admin can only call.
- **Limit until Web Push (M9):** nothing rings when the browser itself is closed or the phone kills the tab. Keep the order screen open on the hotel's device.

## D21. Riders: KYC, dispatch, delivery (M6, owner 2026-10-02)

- **Riders sign up themselves.** They give their full name (two or more names), ID number (6–9 digits), M-Pesa phone, residential area, next of kin (name and phone, which must differ from the rider's own), a password, and three phone-camera photos: **ID front, ID back and a selfie**. They also tick a consent box.
  - **One submission** (`POST /riders/apply`): a 3-step page (details → photos → check & send) sends everything together at the end. The account is created only if all of it is valid, so there are no half-finished sign-ups. Each problem is shown in words under its field before sending, and server refusals (e.g. ID number already registered) send the rider back to the right step and field.
  - Status flow: pending → approved / rejected (fix and resubmit) → suspended / reinstated.
- **Only the super admin confirms riders.** The review screen shows the photos side by side, plus call buttons for the rider and the next of kin.
  - Approve stays disabled until four checks are ticked: the selfie matches the ID, the name and ID number match, the rider was called, and the next of kin was called.
  - Meeting the rider once with their original ID is recommended.
  - Every decision is audit-logged.
- **Hotels never manage riders**, so there are no new hotel users or dashboards. The hotel's order card shows the rider's first name, photo and a call button, and a **Handed to rider** button.
- **ID photos are private** (Kenya Data Protection Act):
  - stored outside the public media folder (`private_media/`);
  - readable only through an admin-only endpoint, never cached (`Cache-Control: no-store`);
  - EXIF and GPS are stripped.
  
  Customers and hotels see only a small photo made from the selfie, the rider's first name and phone, from pickup onward. A national ID number can't be registered twice.
- **Dispatch: riders claim and the admin assigns.**
  - Approved, online riders see open jobs from Accepted onward (pickup area, distance, fee, item count; no customer details) and tap **Take this job**.
  - A conditional update means exactly one rider wins (tested with 5 at once). A rider can hold at most 2 active jobs.
  - The admin's Dispatch board assigns or swaps riders until pickup, and highlights ready orders with no rider for 5+ minutes.
  - The rider sees the customer's name, phone, pin, landmark and a Google Maps directions link only after taking the job.
- **Steps:** Ready → Picked up (hotel "Handed to rider" or rider "I have the food") → On the way → Delivered.
  - **Delivered** needs the customer's 4-digit code. Riders never receive the code from the server. Wrong tries count; after 5, the job locks and goes to the admin.
  - A delivered order counts toward the customer's completed orders (stamp card).
- **Rider fee**, as in the spec's table:
  - **A + instant:** the hotel and the rider both confirm the handover; the ledger entry is written once both have. A rider "not received" becomes an admin fee dispute.
  - **A + weekly:** recorded at delivery (hotel owes platform, platform owes rider).
  - **B:** the rider confirms the cash at delivery, or reports "not paid" (D8). The customer is asked on the tracking page. "No", or no answer within 24 h (background job), means the platform compensates the rider, up to 2 per week before manual review. The customer then loses option B, and a second case blocklists them.
- **Failed delivery (D7):** the rider reports a reason and the admin classifies it on Needs attention:
  - **Customer fault:** no refund; the rider is paid; the customer loses option B.
  - **Hotel fault:** full refund; the rider is paid.
  - **Rider fault:** full refund, a `failed_delivery_credit` (the platform makes the hotel whole), and a strike. Two strikes in 30 days auto-suspends the rider.
  
  Failed deliveries and fee disputes are the admin's; hotels don't see them.

## D20. Order history, hotel-owned identity, demo hotels (owner, 2026-10-02)

- **Customer order history:**
  - The phone keeps up to 200 orders' tracking tokens, since there are no accounts.
  - `POST /track/history` returns all of them in one call: status, items, amount paid (ledger), refunds and bonus.
  - Filters: status, hotel, period and search, plus totals (orders, completed, total paid, rewards saved).
  - Only tokens unlock orders, so nobody can list another person's orders by typing their phone number.
  - The server keeps every order by phone regardless, which is what future bonuses will use.
- **Hotel admins edit their own name, Till and phone.** This replaces "contact support".
  - Every change is audit-logged with old and new values.
  - A Till number taken by another hotel is refused.
  - A Till change is refused while M-Pesa customers are still paying the old Till.
  - Cashiers can't change these.
- **Hotel staff navigation:** Dashboard is first in the hotel menu. Hotel admins land on it; cashiers land on Orders, where the alarm rings. Phone tab labels are shortened (Home, Pay, Deals) so seven tabs fit 360 px.
- **Readability:** no text under 12 px except the phone tab bar (11 px). Audited at 1366×768 and 360×780: no sideways scrolling on any customer, hotel or admin screen.
- **Demo hotels:** Noor Cafe, Jadelica, Sawan, The Hood, Siri-Tamu and Tuutis, all with Bungoma CBD locations. Names are stored in normal case; covers show them in capitals.

## D19. Commission tiers, bonuses, dashboards, hotel-owned payment review (owner, 2026-10-02)

- **Commission is a flat fee by food total**, not 10%: up to KES 500 → 20; 501–1,000 → 30; 1,001–2,000 → 40; 2,001–3,000 → 50; 3,001–4,000 → 60; 4,001–5,000 → 70.
  - Above 5,000: +10 for every started 1,000 (5,001–6,000 → 80).
  - It applies to the **food total only**; rider fees are excluded so option A and B orders pay the same. It is never more than the food itself.
  - The hotel pays it. The customer still pays the KES 20 service fee.
  - Tiers are admin-editable (Fees & bonuses). A hotel with its own percent deal keeps it.
  - Orders snapshot the fee. Partial refunds reverse it pro rata (fee × food refunded ÷ food); refunding everything reverses it all.
- **Platform-funded bonuses**, one per order (the bigger one):
  - **Stamp card:** every 5th completed order, the next order gets KES 100 off, capped at the food. Rewards are counted from orders, so a cancelled, rejected or expired reward order gives the stamp back.
  - **Free delivery** when food reaches KES 1,500, only when the rider fee goes through the Till (option A), so the rider is paid as usual.
  - **Daily budget:** KES 2,000 for all hotels; a bonus is offered only if it fits. Decisions are serialised with an advisory lock when placing.
  - **Money flow:** the customer pays `till_amount = food + service + rider_in_till − platform_bonus`. The ledger records `bonus_credit` (platform owes the hotel), so the hotel's sale stays whole. A full refund writes `bonus_credit_reversal`.
  - **Hotel visibility:** the hotel board shows "+KES X from Chakula".
- **Happy hour:** hotel discounts can be limited to weekdays and a daily time window (Kenya time); hotels fund these.
- **Referral bonus:** deferred until phone numbers are verified by SMS code. Unverified numbers make it easy to farm. No first-order discount for the same reason.
- **Dashboards:**
  - Built from the ledger, so they agree with statements. Kenya days; at most 366 days per query.
  - **Hotel admin:** money received, orders, average order, platform fees, best sellers, busiest hours, payment methods, payments history with CSV.
  - **Super admin:** the same across hotels, plus commission, service fees, bonuses paid, platform earnings and a per-hotel table, filterable by hotel.
  - Cashiers don't see reports.
- **Payment review belongs to each hotel.** The super admin's "Needs attention" shows only:
  - orders not accepted in time;
  - hotel items open 15+ minutes, read-only with **Call hotel**;
  - items with no hotel (unreadable SMS, unknown Till), which the admin resolves.
  
  The admin resolve API refuses hotel items (403 `hotel_item`). The payment simulator moved to **Tools**.

## D18. Hotel operations (M5)

- **Order board:** columns New / In the kitchen / Ready / Done today. It's the hotel staff home screen, updated live over Server-Sent Events. Events are sent only after the change is committed, and a rolled-back change sends nothing. A paid order reached an open board in **0.67 s** in testing (target: under 3 s).
- **Status steps** are allowed only from the previous status (409 otherwise), and repeat taps are no-ops:
  - **Pickup:** Paid → Accepted (with prep minutes, shown to the customer) → Preparing → Ready → Collected.
  - **Delivery:** stops at Ready until riders arrive (M6).
  - **Cash pickup** is accepted straight from Awaiting payment, and cash is recorded at collection.
  - Collected orders count toward the customer's completed orders, which affects the first-time cash cap.
- **Reject** needs a reason (sold out, too busy, closing, can't deliver, other, plus an optional note), and the customer sees it. A paid order gets a refund record for **exactly what was received and not already refunded**.
- **D6 timings:**
  - **New order:** a loud repeating alarm on the board. Browsers need one tap to allow sound, so the board shows a "Tap to turn on the alarm" bar.
  - **5 minutes:** a duty alert on the admin's Payment review screen, with "Call hotel".
  - **10 minutes:** auto-reject with a refund.
  - **Two auto-rejects in a row** switch "Accepting orders" off.
  
  The auto-reject job handles each order separately, so one failure cannot block the others.
- **Web Push** is built (see D31). It needs VAPID keys and HTTPS; without it, alerts reach the board only while it is open: the alarm keeps ringing in a background tab once switched on, but not when the browser is closed.
- **Live-update URLs carry the 15-minute access token** (EventSource cannot send headers). Uvicorn's own access log is therefore off (`--no-access-log`); the app's JSON request log records paths without query strings.
- **Development note:** on Windows, "localhost" tries IPv6 first and added about 2 s to every request; the Vite proxy now targets `127.0.0.1`.

## D17. Payments (M4)

- **The SMS app stays M8** (owner, 2026-10-02). Until then, cashiers confirm by reading the Till phone's SMS (code and amount). An admin "Paste SMS" tool runs a pasted message through the exact parser and matching the M8 app will use.
- **The parser is built from real Till SMS** (`backend/tests/data/till_payments.txt`, with names and numbers anonymised). Spaces between parts are optional (phone apps hide some), and the date is read as day/month/year in EAT. Any non-whole-shilling amount, unreadable date or unknown wording is **flagged for a human, never guessed**. Reversals are only acted on when the message contains a known transaction code.
- **The same checks apply to every confirmation source** (manual, SMS, Daraja later): the payment went to this hotel's Till, the amount is exact, it was paid after the order was created (2 minutes' tolerance), and the code is unique. One code can never confirm two orders; a database unique constraint and a row lock enforce this.
- **Underpaid:** the order is held in review. The cashier either **refunds what was paid** (it is returned in full with no commission or fee, and the order is cancelled) or **accepts the shortfall** (the hotel absorbs it). One order is never split across several M-Pesa payments.
- **Overpaid:** the order is confirmed, and "refund the extra" is queued for the hotel admin.
- **Who can approve refunds:** the hotel admin. Cashiers confirm payments, record cash and mark refunds as sent.
- **No SMS needed to match:** a payment without an entered code auto-matches only when exactly one pending order at that hotel has the same amount and the same last 3 phone digits. Otherwise it goes to review.
- **Background jobs** (every minute, in the API process):
  - expire unpaid M-Pesa orders (never those where a code was entered, D5);
  - alert when a code was entered but no payment was seen after 5 minutes;
  - refund late payments still unresolved when the hotel closes (D5).

## D16. Road distance, per-km pricing, one distance for everyone (owner, 2026-10-02)

- **Distance is calculated automatically by road** (OSRM routing on OpenStreetMap data), from the hotel's location to the customer's pin. If routing is unavailable, the fallback is straight line × 1.3 so ordering never stops. The admin can switch to straight-line measuring. The public OSRM server is fine for the pilot; self-host it or use a paid provider at scale.
- **Two pricing methods**, chosen by the admin:
  - **Per km:** base + per-km × distance, never below the minimum, rounded up to KES 10, up to a furthest distance.
  - **Bands** (D14).
  
  One server function (`PlatformSettings.rider_fee_at`) computes every fee. The admin page previews it, and a **distance calculator** shows the exact distance and fee for any spot.
- **The distance and rider fee are stored on the order when it is placed** (`orders.distance_km`, `orders.rider_fee`). The customer, the hotel and the rider all read these stored values, so they always match, including the cash amount to hand the rider in option B. Later price changes never alter an existing order.
- **Delivery area is optional.** With a drawn area, pins must be inside it. With no area, any hotel with a map location delivers up to the furthest distance from itself (the simplest way to cover a big region). A hotel with no location and no area is pickup-only.
- **Stale pins:** a pin remembered from an earlier visit that falls outside today's area is dropped (with its directions) instead of producing an error. Checkout always reloads the latest area.

## D15. UX features (owner, 2026-10-02)

- **Pilot area: Bungoma CBD.** The demo delivery area is a 4 km circle around the town centre; the admin redraws it as needed.
- **Installable app (PWA)** with a hand-written service worker. Pages are network-first with an offline shell. Hotels, menus, offers and config are served from cache and refreshed in the background. Built assets and photos are cache-first. **Orders, payments, tracking and staff APIs are never cached.** It runs on production builds only.
- **WhatsApp help:** a `support_whatsapp` setting (admin-entered, normalised to 2547…; empty hides the button). Messages are pre-filled with the order code where there is one.
- **Kiswahili:** the customer screens have an EN/SW switch. English strings are the keys and a missing translation falls back to English. Hotel-entered text (dish and category names) is shown as typed. **The translations need review by a native speaker before launch.**
- **Time estimates:** each hotel's typical prep time is the median of its live dishes' prep minutes (15 if none). Cards show "prep+5 to prep+20 min" for delivery and "prep−5 to prep+5" for pickup, rounded to 5 minutes.
- **Saved places** (Home / Work / Other) live on the phone only, like the rest of the customer profile. Nothing is stored on the server beyond the order itself.
- **Order again** refills the basket from a past order; the server re-prices everything at checkout.
- **Dark mode** follows the phone's setting until the user picks one; brand orange is unchanged.

## D13. UI direction

The visual style follows the owner's reference designs (Bonfol, D.CC, Epic Eats). The screen structure is adapted for mobile delivery and pickup ordering. See [UI.md](UI.md) for what is kept, removed and added.

## Open inputs needed from the owner

- [x] ~~Real M-Pesa Till SMS sample(s)~~: received 2 Oct 2026 (backend/tests/data). More samples (especially a reversal) are welcome; each becomes a test.
- [x] ~~Delivery zone boundary~~: the admin now draws it (D14). Still needed: each hotel's real location and the real delivery area.
- [ ] Hotel list: names, Till numbers, phones, hours (needed by M2; placeholders are fine until then).

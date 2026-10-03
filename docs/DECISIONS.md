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
- The SMS forwarder app (M8); payments currently arrive through the admin's paste-SMS tool or cashier confirmation.
- Web Push for closed browsers, and deployment (M9).
- ~~No way to cancel an order after the hotel has accepted it.~~ Done, see D24.
- Customers get no SMS updates (only the open tracking page).
- No rider live location.
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
- **Web Push is deferred to deployment (M9).** The library could not be downloaded on the development connection. Until then, alerts reach the board while it is open: the alarm keeps ringing in a background tab once switched on, but not when the browser is closed.
- **Live-update URLs carry the 15-minute access token** (EventSource cannot send headers). Uvicorn's own access log is therefore off (`--no-access-log`); the app's JSON request log records paths without query strings.
- **Development note:** on Windows, "localhost" tries IPv6 first and added about 2 s to every request; the Vite proxy now targets `127.0.0.1`.

## D17. Payments (M4)

- **The SMS app stays M8** (owner, 2026-10-02). Until then, cashiers confirm by reading the Till phone's SMS (code and amount). An admin "Paste SMS" tool runs a pasted message through the exact parser and matching the M8 app will use.
- **The parser is built from real Till SMS** (`docs/sms_samples/till_payments.txt`, with names and numbers anonymised). Spaces between parts are optional (phone apps hide some), and the date is read as day/month/year in EAT. Any non-whole-shilling amount, unreadable date or unknown wording is **flagged for a human, never guessed**. Reversals are only acted on when the message contains a known transaction code.
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

- [x] ~~Real M-Pesa Till SMS sample(s)~~: received 2 Oct 2026 (docs/sms_samples). More samples (especially a reversal) are welcome; each becomes a test.
- [x] ~~Delivery zone boundary~~: the admin now draws it (D14). Still needed: each hotel's real location and the real delivery area.
- [ ] Hotel list: names, Till numbers, phones, hours (needed by M2; placeholders are fine until then).

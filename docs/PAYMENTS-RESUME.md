# READ THIS BEFORE SWITCHING TO THE `payments-module` BRANCH

**Launch decision (owner, 2026-10-11): we launch from `main` with MANUAL payments (till code
matching). The payments module is paused until after launch and lives only on `payments-module`.**

## The trap
The running Docker database (`hotel_management_pgdata`) is now on `main`'s migrations (head `0023`).
The payments migrations (`0016`-`0022` and the merge revision `0024`) were stepped **back** on
2026-10-11 with `alembic downgrade 0015`. That dropped the payments sandbox tables (schema
`payments`, STK attempts, payouts). Hotels, menus, offers, orders and users were not touched.
A full backup from just before is `backups/hotel-before-main-switch.sql` (not in git).

If you check out `payments-module` against this database **without re-applying its migrations
first**, the API will not start or the payments tables will be missing.

## To resume payments later (in this order)
1. `git checkout payments-module` and `git merge main` (keep it current).
2. `docker compose up -d --build api`; the API upgrades the database to `0024` on start
   (or run `docker compose exec api alembic upgrade head`).
3. Payments stay OFF until `PAYMENTS_ENABLED=true`. Details: `docs/PAYMENTS-STATUS.md`
   (on `payments-module`).

## Going back to `main` afterwards
`docker compose exec api alembic downgrade 0015` on the `payments-module` code **first**, then
`git checkout main` and rebuild the api. Do not switch branches with the database on `0024`
and code on `main`: the API crashes with "Can't locate revision identified by '0024'".

## Never
Do not merge `payments-module` into `main` unless the owner asks. Non-payments work goes on
`main`, then `git merge main` into `payments-module`.

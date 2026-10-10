# Putting Chakula live on orderfood.co.ke

This guide takes you from a blank rented server to a live site, one step at a time. You only
need to do steps 1 to 8 once. After that, putting a new version live is one command (step 11).

**What you end up with:** one small server running the database, the API and the website behind
Caddy, which handles HTTPS and the certificate by itself. Only ports 80 and 443 are open to the
internet. The database, API and website containers cannot be reached from outside.

## 1. What to rent

- **A small server (VPS) running Ubuntu 22.04 or 24.04**, in a data centre close to Kenya.
- **2 vCPU, 4 GB memory, 40 GB disk** is enough for the pilot. (Building the website needs about
  1.5 GB at the moment it builds; step 3 adds swap so a 2 GB server also works.)
- Roughly US$6–12 a month on DigitalOcean, Hetzner, Vultr or similar. Oracle's free tier also
  works but has been known to reclaim idle servers: upgrade it to pay-as-you-go if you use it.
- When asked, choose to log in with an **SSH key**, not a password.
- Turn on the provider's **automatic server backups** (snapshots) too. They are on top of the
  daily backups in step 9, not instead of them.
- Write down the server's **public IP address**. Below it is written as `SERVER_IP`.

## 2. Point the domain at the server

At whoever you registered **orderfood.co.ke** with, open the DNS settings and add two records:

| Type | Name | Value     |
|------|------|-----------|
| A    | `@`  | SERVER_IP |
| A    | `www`| SERVER_IP |

Do this first: DNS can take from a few minutes to a few hours. Check it from your PC:
`nslookup orderfood.co.ke` must print `SERVER_IP`. The certificate in step 6 cannot be issued
until this works.

## 3. Prepare the server (once)

Log in (`ssh root@SERVER_IP`), then:

```bash
apt-get update && apt-get install -y git
git clone https://github.com/Akumu2022/hotel_management.git /opt/chakula
cd /opt/chakula
bash deploy/bootstrap-server.sh
```

If the repository is private, GitHub will ask you to sign in: create a personal access token
(GitHub, Settings, Developer settings) and use it as the password, or set up a deploy key.

`bootstrap-server.sh` installs Docker, opens only SSH and the web ports in the firewall, blocks
repeated wrong SSH logins, adds swap and turns on automatic security updates.

## 4. Write the settings file

```bash
cd /opt/chakula
cp deploy/env.production.example .env
chmod 600 .env
nano .env
```

Fill in every value marked `CHANGE`. Make each secret with `openssl rand -hex 32` (run it once
per secret, never reuse one). Use `openssl rand -hex 24` for the database password.

- `ACME_EMAIL`: your real email. Let's Encrypt warns this address if a certificate is in trouble.
- `JWT_SECRET` and `FORWARDER_KEY`: two different long secrets. If either is lost or changed
  later, every login and every paired Till phone stops working, so keep a copy somewhere safe
  that is **not** this server (a password manager).
- Leave `VAPID_*` empty for now; step 7 makes them.

The server refuses to start in production with weak or default secrets, so a mistake here shows
up straight away rather than silently.

## 5. First start

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

The first build takes 5 to 10 minutes. Then:

```bash
docker compose -f docker-compose.prod.yml ps
```

`db`, `api`, `web` and `caddy` should all be running, and `api` should say `healthy`.
If the API does not become healthy: `docker compose -f docker-compose.prod.yml logs api`.

## 6. Check the HTTPS address

Open **https://orderfood.co.ke** in a browser. You should see the Chakula home page with a
padlock. The first visit may take a few seconds while the certificate is issued.

If you get a certificate error instead, it is almost always DNS (step 2 not finished) or a
closed firewall port. Look at `docker compose -f docker-compose.prod.yml logs caddy`.

Also check **https://orderfood.co.ke/health**: it must answer `{"status":"ok"}`.

## 7. Create the first admin and finish the settings

```bash
cd /opt/chakula
C="docker compose -f docker-compose.prod.yml exec"

# Your super admin login (you type the password; 8 characters or more)
$C api python -m app.cli create-superadmin --name "Your Name" --phone 07XXXXXXXX

# Web Push keys for alarms when a browser is closed: copy the three lines it prints into .env
$C api python -m app.cli vapid-keys
nano .env                                 # paste the three VAPID lines
docker compose -f docker-compose.prod.yml up -d    # restart so the API reads them

# The launch check: fix every [FAIL] before real customers use the site
$C api python -m app.cli check-production
```

Expect `[WARN]` about the free public routing server until you run your own (see the README,
"Road routing"). That is fine for the pilot. Every `[FAIL]` must be fixed first.

This is a **brand new, empty database**. Do not copy the development database here: it holds
the "ZZ" test hotel, test riders and test logins, which must never exist on the live site.

Then sign in at https://orderfood.co.ke/login as the super admin and, in this order:

1. **Settings**: confirm commission, fees, timeouts and caps (they show as unconfirmed until
   you save them once).
2. **Delivery**: draw the delivery area and set the rider fee bands or per-km price.
3. **Hotels**: add each real hotel with its real Till number, the **name M-Pesa shows for that
   Till** (`Till name`), phone, hours and map location. Create its hotel admin login.
4. Only after you have visited a hotel in person, tick **Verified** for it. That is what shows
   the green "Checked by Chakula" badge to customers.

## 8. Pair each hotel's Till phone

On the phone that receives the Till's M-Pesa messages, install the **Chakula Till** app. The
hotel admin signs in at https://orderfood.co.ke, opens Settings, Till phone, **Pair a phone**,
and types the 8-letter code into the app. The server address in the app must be
`https://orderfood.co.ke`. Send one small real payment to the Till to prove it works end to end
before the hotel opens.

## 9. Backups (do this before the first real customer)

```bash
cd /opt/chakula
bash deploy/backup.sh                 # try it once by hand: it must say "Backup done"
crontab -e
```

Add this line to run it every night at 02:30:

```
30 2 * * * cd /opt/chakula && bash deploy/backup.sh >> /var/log/chakula-backup.log 2>&1
```

Backups go to `/var/backups/chakula` and the last 14 days are kept. A backup that stays on the
same server does not survive that server dying, so also copy them elsewhere: install `rclone`,
set up a destination (Google Drive, S3, another server), and put its name in `BACKUP_REMOTE` in
`.env`. Every few weeks, **test a restore** on a spare machine. A backup you have never
restored is a hope, not a backup.

**Restoring the database** (this replaces everything currently in it; use your `POSTGRES_USER`
and `POSTGRES_DB` from `.env` if you changed them from `hotel`):

```bash
cd /opt/chakula
C="docker compose -f docker-compose.prod.yml"
$C stop api web                                   # nobody is using the database now
$C exec -T db psql -U hotel -d postgres -c "DROP DATABASE hotel;" -c "CREATE DATABASE hotel;"
gunzip -c /var/backups/chakula/db_YYYY-MM-DD_HHMMSS.sql.gz | $C exec -T db psql -U hotel -d hotel
$C up -d                                          # starts api and web again
```

Photos: stop `api`, then
`docker run --rm -v chakula_media:/data -v /var/backups/chakula:/in alpine tar xzf /in/media_YYYY-MM-DD_HHMMSS.tar.gz -C /data`
(and the same with `private_media`), then start `api` again.

## 10. Watch that it stays up

Create a free account at an uptime monitor (UptimeRobot or similar) and add an HTTPS check on
**https://orderfood.co.ke/health** every 5 minutes, with an email or SMS alert to you.

Useful commands on the server (from `/opt/chakula`):

```bash
docker compose -f docker-compose.prod.yml ps                # what is running
docker compose -f docker-compose.prod.yml logs -f api       # live API log (Ctrl+C to stop)
docker compose -f docker-compose.prod.yml restart api       # restart just the API
df -h /                                                     # how full the disk is
```

## 11. Putting a new version live

On your PC: commit and push your changes. Then on the server:

```bash
cd /opt/chakula
bash deploy/update.sh
```

It takes a backup, pulls the new code, rebuilds, restarts, and runs the launch check. Do updates
at a quiet hour: the site is unavailable for under a minute while the API restarts. Customers
with an order open will see it reconnect by itself.

**Rolling back** if the new version is broken: find the last good commit (`git log --oneline`),
then `git checkout <that commit>` and `docker compose -f docker-compose.prod.yml up -d --build`.
Database changes are applied automatically when the API starts and are not undone by going back
to old code; if a release changed the database and must be undone, restore the backup taken at
the start of `update.sh` (step 9).

## 12. The phone apps for orderfood.co.ke

On your PC (Windows), build each app pointing at the live site. These addresses use HTTPS and
have no port, so they keep working whatever the server's IP is:

```powershell
cd mobile
flutter build apk --release --flavor customer --dart-define=API_BASE=https://orderfood.co.ke/api/v1
flutter build apk --release --flavor rider -t lib/rider/main.dart --dart-define=API_BASE=https://orderfood.co.ke/api/v1
cd ..\forwarder
.\build-apk.ps1 -Server https://orderfood.co.ke -Out C:\path\to\Chakula-Till-SMS.apk
```

For the Play Store you need your own Google Play developer account, and signed release builds
(an app-bundle, `flutter build appbundle`, with your own keystore, kept safe and backed up:
losing it means you can never update the app). Until then, hand the APK files to hotels and
riders directly.

## 13. The day before opening

- `check-production` shows no `[FAIL]`.
- A real customer order has been placed, paid with real M-Pesa and collected, end to end, at one
  hotel, with the real Till phone.
- Each hotel's "Till name" is exactly what M-Pesa shows when you pay that Till.
- A backup has run and you have seen the file.
- The uptime monitor is on and alerts reach you.
- Riders you intend to use have been approved in the admin area (their ID photos and bike plate
  checked).
- Your support phone number and WhatsApp are set in Settings.

## Things to know

- **One API process only.** Live updates and order timers live inside the single API container.
  Do not scale it up or add workers; if you ever outgrow one process, the live-update broker has
  to move to PostgreSQL first (noted in `backend/app/services/events.py`).
- **Secrets stay on the server.** `.env` is never committed. The `JWT_SECRET` and `FORWARDER_KEY`
  are never in the apps or the website.
- **Disk space.** Menu photos, ID photos and database backups grow. Check `df -h /` monthly.
- **Server time.** Keep the server on automatic time (Ubuntu does this): order timers and
  M-Pesa message matching depend on the clock.

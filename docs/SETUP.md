# Setup

The system has three parts: the **Supabase** project (auth + private Realtime channel), the **Pi listener** (joins calls), and the **web app** (`web/`, deployed on Vercel) used by the family to place calls.

## 1. Supabase project (manual, one-time)

1. Create a free account/project at https://supabase.com (an agent can't create third-party accounts for you).
2. **Project Settings → API**: copy the **Project URL** and the **publishable** key (`sb_publishable_…`). Both are used by the Pi, the web app and the test script.

## 2. Database + security (run once)

1. **SQL Editor** → paste and run [`supabase/setup.sql`](../supabase/setup.sql). This creates the `family_members` allowlist and the Realtime Authorization policies that make `visio-tv-calls` a private channel.
2. **Authentication → Users → Add user → Create new user** (repeat for each person, and once for the Pi):
   - each family member: their email + a password you choose for them
   - the Pi device account, e.g. `pi-device@example.com`
   - tick **Auto Confirm User** every time (no emails are ever sent — Supabase's built-in mailer only delivers to project team members anyway).
3. **Table Editor → `family_members`** → insert one row per email above (**lowercase**, including the Pi's). An account that isn't in this table can log in but can do nothing: RLS blocks the channel.
4. **Project Settings → Realtime → turn OFF "Allow public access"**. This is what actually closes the old hole where anyone with the publishable key could ring the TV.
   ⚠️ Do this only once the updated Pi listener (step 3) is deployed, since it breaks the old unauthenticated path.

## 3. Pi listener

```
cp pi/.env.example pi/.env
```

Fill in `SUPABASE_URL`, `SUPABASE_ANON_KEY` (publishable key), and the device account's `SUPABASE_DEVICE_EMAIL` / `SUPABASE_DEVICE_PASSWORD`. Then deploy:

```
scp -r pi julienne@visio-tv.<your-tailnet>.ts.net:/home/julienne/visio-tv
ssh julienne@visio-tv.<your-tailnet>.ts.net "chmod +x /home/julienne/visio-tv/install.sh && /home/julienne/visio-tv/install.sh"
ssh julienne@visio-tv.<your-tailnet>.ts.net "systemctl --user restart visio-tv-listener.service"
```

The installer is idempotent — safe to re-run after any change. One first-time-only manual step (needs a password-capable sudo shell) installs the Firefox camera policy; `install.sh` prints the exact command if it can't do it itself.

Verify:

```
ssh julienne@visio-tv.<your-tailnet>.ts.net "journalctl -n 20 --no-pager _SYSTEMD_USER_UNIT=visio-tv-listener.service"
```

You want to see `Device login OK` followed by `Subscribed to channel=visio-tv-calls (private)`.

## 4. Test trigger (optional, CLI)

```
cp test/.env.example test/.env   # fill in URL, key, and the device credentials
cd test && npm install
npm run start    # rings the TV
npm run end      # hangs up
```

Removing the credentials from `test/.env` turns this into the security check: subscribing must then fail.

## 5. Web app

```
cp web/.env.example web/.env.local   # fill in URL + publishable key
cd web && npm install && npm run dev
```

Open http://localhost:3000, log in with a family account, and check the badge reads **En ligne** when the Pi is up.

## 6. Deploy to Vercel (manual)

1. Create a GitHub repo and push this project.
2. Vercel → **Add New → Project** → import the repo → set **Root Directory = `web`**.
3. Add the two environment variables (`NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`) → Deploy.

No Supabase redirect-URL configuration is needed, since login is email + password rather than magic links.

Day-to-day operation and troubleshooting: [RUNBOOK.md](RUNBOOK.md).

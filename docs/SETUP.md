# Setup

## 1. Create the Supabase project (manual, one-time)

1. Go to https://supabase.com and create a free account/project (you do this yourself — an agent can't create third-party accounts on your behalf).
2. In the new project, go to **Project Settings → API** and copy:
   - **Project URL** (`https://<project-ref>.supabase.co`)
   - **anon public** key
3. No database table or RLS policy is needed — this project only uses a Realtime **Broadcast** channel (`visio-tv-calls`), which is pure pub/sub and doesn't touch Postgres.

## 2. Configure the Pi side

On your Windows machine:

```
cp pi/.env.example pi/.env
```

Edit `pi/.env` and fill in the real `SUPABASE_URL` and `SUPABASE_ANON_KEY` from step 1.

## 3. Configure the test trigger

```
cp test/.env.example test/.env
```

Fill in the same `SUPABASE_URL` / `SUPABASE_ANON_KEY`. Then, with Node.js installed locally:

```
cd test
npm install
```

## 4. Deploy to the Pi

From `C:\dev\visio-tv`:

```
scp -r pi julienne@visio-tv.<your-tailnet>.ts.net:/home/julienne/visio-tv
ssh julienne@visio-tv.<your-tailnet>.ts.net "chmod +x /home/julienne/visio-tv/install.sh && /home/julienne/visio-tv/install.sh"
```

The installer is idempotent — safe to re-run after pushing updated files.

Then reboot the Pi so labwc's autostart picks up the new service:

```
ssh julienne@visio-tv.<your-tailnet>.ts.net "sudo reboot"
```

## 5. Verify

```
ssh julienne@visio-tv.<your-tailnet>.ts.net "systemctl --user status visio-tv-listener.service"
```

Then follow the testing steps in [RUNBOOK.md](RUNBOOK.md).

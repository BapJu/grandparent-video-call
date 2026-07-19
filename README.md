# visio-tv

Auto-answering video call kiosk for a Raspberry Pi wired to a TV + webcam at a family member's home. A remote trigger (Supabase Realtime broadcast) makes the Pi join a Jitsi Meet room fullscreen, camera/mic already live — no interaction needed on their end.

- [docs/SETUP.md](docs/SETUP.md) — first-time setup (Supabase project, deploy to the Pi)
- [docs/RUNBOOK.md](docs/RUNBOOK.md) — testing, logs, common failure modes

## Layout

- `pi/` — code and config deployed to the Raspberry Pi (listener service, systemd unit, labwc autostart, Chromium policy, installer)
- `test/` — manual Node script to send `start_call`/`end_call` broadcast events until the real family web client exists

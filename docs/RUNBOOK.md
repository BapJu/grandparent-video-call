# Runbook

## Logs

This Pi's journald keeps a single shared `system.journal` (no per-UID split journals), so plain `journalctl --user` reports "No journal files were found" even though the unit's logs are there. Use the `_SYSTEMD_USER_UNIT` field matcher on plain `journalctl` instead:

```
ssh julienne@visio-tv.<your-tailnet>.ts.net "journalctl -f _SYSTEMD_USER_UNIT=visio-tv-listener.service"
ssh julienne@visio-tv.<your-tailnet>.ts.net "journalctl --since today _SYSTEMD_USER_UNIT=visio-tv-listener.service"
```

## End-to-end test (no Vercel client needed yet)

From `C:\dev\visio-tv\test` (after `npm install` and filling in `.env`):

```
npm run start   # sends start_call with a fresh random room, prints the room URL
npm run end     # sends end_call
```

Steps:
1. Open the journalctl log (above) in one terminal.
2. Run `npm run start` → confirm the log shows the event received and chromium launching; confirm the Pi's screen shows the Jitsi room fullscreen, camera/mic already live.
3. Join the printed `https://meet.jit.si/<room>` URL from your own phone/laptop → confirm two-way audio/video.
4. Run `npm run end` → confirm chromium closes within a few seconds on the Pi.
5. `ssh ... "sudo reboot"` → after it comes back, re-run step 2 to confirm the listener auto-started via labwc + systemd `Restart=always`/linger.
6. To test reconnect resilience, briefly disable the Pi's network (or block outbound to `*.supabase.co`) and confirm the listener reconnects once restored (see reconnect backoff log lines).
7. To test the auto-teardown safety net, temporarily set `MAX_CALL_DURATION_SECONDS=30` in `pi/.env`, redeploy, start a call, and confirm chromium closes on its own after 30s without an `end_call`. Revert afterwards.
8. Check actual data usage of a short test call (e.g. via the 4G modem's own usage counter, or `vnstat`/`ifstat` on the Pi if installed) — if usage is too high for the data plan, add a resolution cap to the Jitsi URL hash in `pi/listener/kiosk.py`, e.g. `&config.resolution=360&config.constraints.video.height.ideal=360`.

## Browser: Firefox, not Chromium

The kiosk uses **Firefox** (`--kiosk --profile ~/.config/visio-tv-ff`). Chromium is unusable on this Pi: its camera capture hangs forever on the missing xdg-desktop-portal Camera backend (full story in [CAMERA-ISSUE.md](CAMERA-ISSUE.md)). The critical pref is `media.webrtc.camera.allow-pipewire=false` in [pi/firefox/user.js](../pi/firefox/user.js); camera/mic are allowlisted for meet.jit.si via `/etc/firefox/policies/policies.json` (installed from `pi/policies/firefox-policies.json`, needs sudo once).

## Why the /kiosk wrapper is disabled (KIOSK_URL empty)

The web app has a `/kiosk` page that embeds Jitsi via the IFrame API, which lets the Pi unmute *itself* on join (Jitsi never lets a moderator unmute a remote participant) and accept `set_media` commands from the app. It works — verified: the Pi joined with mic and camera already live, and remote mute worked.

**But meet.jit.si disconnects embedded calls after 5 minutes**: *"Embedding meet.jit.si is only meant for demo purposes, so this call will disconnect in 5 minutes."* That makes it unusable here, so `KIOSK_URL` is left empty and the Pi loads meet.jit.si directly (unlimited call length, but it joins muted).

The wrapper code is kept because it becomes usable as-is with either:
- **JaaS** (8x8 Jitsi as a Service) — free up to 25 monthly active users, no embedding limit, and its JWTs also remove the moderator-login requirement. Needs a JaaS account plus a JWT-issuing API route.
- **A self-hosted Jitsi** — no limits at all.

To re-enable, set `KIOSK_URL=https://tv-visio.vercel.app/kiosk` in the Pi's `.env` and restart the service.

## Known quirk: the Pi joins muted (manual unmute for now)

meet.jit.si forces participants who arrive before the moderator to join with camera/mic off, regardless of URL `startWith*Muted=false` params. Until this is automated in the listener, unmute remotely over SSH once the call is live (Jitsi shortcuts: `v` = camera, `m` = mic — they are **toggles**, so only send them when the state is known):

```
ssh julienne@visio-tv.<your-tailnet>.ts.net "export XDG_RUNTIME_DIR=/run/user/1000; export WAYLAND_DISPLAY=wayland-0; wtype v; sleep 2; wtype m"
```

Verify the camera actually opened: `fuser -v /dev/video0` (should show firefox).

## Seeing what's really on the Pi's screen

Raspberry Pi Connect's screen-share viewer can show a black screen when the actual display is fine. Capture the compositor output directly instead:

```
ssh julienne@visio-tv.<your-tailnet>.ts.net "XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-0 grim /tmp/screen.png"
scp julienne@visio-tv.<your-tailnet>.ts.net:/tmp/screen.png .
```

## Important: meet.jit.si requires you to be the moderator

meet.jit.si now blocks anonymous rooms from actually going live until someone authenticates as moderator — an anonymous participant (including the Pi) just sits on "the conference hasn't started, no moderator has arrived yet" with no video/audio flowing. This is enforced server-side and can't be bypassed with URL parameters.

**Workflow**: every time you place a call, join the same `https://meet.jit.si/<room>` URL yourself (from your phone/laptop) and sign in with a free account (Jitsi/Google/GitHub) when prompted, so you become moderator. The moment you do, the meeting goes live for everyone already waiting — including the Pi, which needs no changes on its end. Your browser should remember the login after the first time, so this is a one-tap "sign in" rather than typing credentials on every call.

If this ever becomes too much friction, the alternative is self-hosting Jitsi (removes the moderator requirement entirely, at the cost of running/maintaining your own server) — revisit if needed.

## Common failure modes

- **Firefox doesn't appear on screen**: the systemd user unit likely didn't inherit `WAYLAND_DISPLAY`. Check `systemctl --user show-environment` on the Pi (over SSH, in a session where `loginctl enable-linger` is active) and confirm `WAYLAND_DISPLAY`/`XDG_RUNTIME_DIR` are set. If not, double check `~/.config/labwc/autostart` ran the `import-environment` line before `start`.
- **Camera not working / NotAllowedError**: confirm `~/.config/visio-tv-ff/user.js` still contains `media.webrtc.camera.allow-pipewire=false` (a Firefox update or profile reset could lose it — install.sh re-copies it), and that `/etc/firefox/policies/policies.json` exists.
- **Screen stays blank/asleep when a call starts**: `sudo raspi-config nonint do_blanking 1` targets the classic screen-blanking path; if the Wayland/labwc session still blanks the HDMI output, this needs a labwc/Wayland-specific idle-inhibit fix — check for a running idle daemon (e.g. `swayidle`) and disable/reconfigure it, or investigate `wlopm` to force outputs on. Flag if this happens — it wasn't fully verifiable without physical access to the display during initial build.
- **Orphaned firefox process after a crash**: the listener runs `kill_stray_kiosk()` on startup (matches on the kiosk profile path in the process list), so a restart (`Restart=always`) should self-heal this.
- **Subscription never reaches `SUBSCRIBED`**: check `SUPABASE_URL`/`SUPABASE_ANON_KEY` in `pi/.env`, and that the channel name matches between the Pi listener and whatever sends the broadcast (`SUPABASE_CHANNEL`, default `visio-tv-calls`).

## Updating the deployed code

```
scp -r pi julienne@visio-tv.<your-tailnet>.ts.net:/home/julienne/visio-tv
ssh julienne@visio-tv.<your-tailnet>.ts.net "/home/julienne/visio-tv/install.sh && systemctl --user restart visio-tv-listener.service"
```

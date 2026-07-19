# Investigation: camera not working (black call on the Pi)

> **RESOLVED (2026-07-19).** Root cause: Raspberry Pi OS's browser builds route camera
> capture through the xdg-desktop-portal Camera interface (for Pi camera modules), and
> this labwc setup has **no Camera portal backend** — Chromium hangs forever on video
> device enumeration, Firefox fails fast with NotAllowedError. Fix: switch the kiosk to
> **Firefox** with `media.webrtc.camera.allow-pipewire=false` (direct V4L2), set via
> `pi/firefox/user.js`. Verified end-to-end: two-way audio + Pi camera video on meet.jit.si.
> Remaining quirk: meet.jit.si forces participants who join before the moderator to join
> muted — see RUNBOOK for the unmute procedure until it's automated.

## TL;DR

Two separate blockers were found. Neither is a "black screen" — the Pi's display works fine.

1. **The Pi's screen was never actually black.** What looked black was the **Raspberry Pi Connect screen-share viewer** in the browser (no physical HDMI monitor is attached). A direct compositor capture (`grim`) shows a normal desktop, and shows Jitsi rendering correctly during a call. Verify the real screen with:
   `ssh ... "XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-0 grim /tmp/x.png"` then scp it back.

2. **Chromium 150 on this Pi cannot access the camera** — this is the real bug. The Pi joins the Jitsi room but shows only an avatar + muted mic, so the call looks black/empty.

## Root cause of the camera failure (Chromium)

- Audio capture works (`getUserMedia({audio:true})` succeeds).
- Video capture **hangs forever**. Chromium's verbose media log shows:
  ```
  MDM::EnumerateSystemDevices({type=VIDEO_INPUT})
  VideoCaptureManager::EnumerateDevices
  ServiceVideoCaptureProvider::GetDeviceInfosAsync   <-- never returns
  ```
  Every later request logs `[Joining ongoing scan]` and waits on that stuck scan.
- It is **not** an OS/device problem: all 19 `/dev/video*` nodes open + QUERYCAP instantly from Python; the user is in the `video` group; `libcamera`/`udev` respond fine; the UGREEN USB camera is detected (`/dev/video0`, MJPG+YUYV).
- The Chromium `VideoCaptureService` process is alive but never opens any `/dev/video*` — the hang is inside Chromium's capture-service IPC, likely choking while enumerating the many Pi ISP M2M nodes (pispbe ×16, rpi-hevc-dec) that sit alongside the real USB camera. This matches known "RPi camera stack + USB camera together break browser capture" reports on Trixie.

## Firefox comparison (promising)

Firefox 152 (already installed) **enumerates the camera instantly** where Chromium hangs:
`DEVICES(2): audioinput | videoinput`, `secureContext=true`. It returns a clean `NotAllowedError` (a permission gate) instead of hanging.

Getting Firefox to actually grant the camera in an unattended kiosk still needs work — setting `permissions.default.camera=1` + `media.navigator.permission.disabled=true` and writing `moz_perms` rows was not sufficient in testing (still `NotAllowedError`, address bar showed a blocked-camera icon). Next things to try: overwrite (not duplicate) any existing block rows in `permissions.sqlite`, check `permissions.default.*` really wins under Wayland, or use a `policies.json` (`/etc/firefox/policies/`) with `Permissions.Camera.Allow`/`BlockNewRequests:false`.

## Secondary blocker (separate, already known)

meet.jit.si requires the **caller to sign in as moderator** before the room goes live; the Pi otherwise sits on "the conference has not yet started". See [RUNBOOK.md](RUNBOOK.md). Self-hosting Jitsi removes both the moderator gate and gives control over device handling.

## Useful diagnostic notes

- Launching Chromium over SSH hangs at `about:blank` unless you export a D-Bus session and use `--password-store=basic` (otherwise it blocks on the secret-service keyring). The service-launched kiosk (inside the labwc session) does not have this problem.
- Chromium's remote debugging (`--remote-debugging-port=9222`, loopback only) + a small CDP script was the tool that localized the hang. Scripts left in the session scratchpad: `gum_step.py` (per-step camera probe), `cdp_inspect.py` (page state + screenshot).

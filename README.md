# Grandparent Video Call

**One-tap video calls for someone who can't use a phone or computer.**

A Raspberry Pi wired to a TV and a USB webcam sits in a grandparent's living
room. A family member taps **Call** in a small web app, and the TV lights up and
**answers the call by itself** — camera and microphone already live, nothing to
click, swipe, or log into on the grandparent's end. Between calls the same screen
runs as a **digital photo frame** showing pictures the family uploads.

Built so an elderly relative who can't operate any device can still see family
face-to-face, and so the whole thing survives a power cut or internet drop with
no one on site.

## Features

- **Zero-interaction answering** — the Pi joins the call fullscreen on its own, unmuted. Nothing for the grandparent to do.
- **Remote trigger from anywhere** — family opens a private web app ("Call" / "Hang up") on their phone; the Pi reacts in real time.
- **No host login** — the Pi is the meeting moderator (signed JWT), so the room starts itself; callers just join.
- **Remote controls during the call** — adjust the grandparent's speaker volume, mute/unmute their mic or camera, and silence the incoming ringtone, all from the caller's screen.
- **Multi-caller** — several relatives can join; the call only ends once everyone has left (or after a max duration).
- **Digital photo frame** — between calls the TV shows a slideshow of family photos (uploaded from the web app, iPhone HEIC converted automatically), on a daily schedule.
- **Resilient & unattended** — auto-login, auto-start, and auto-restart so it recovers from power or network outages on its own.
- **Private by design** — the Pi's camera and mic stay off until a call; only allow-listed family accounts can trigger a call or upload photos.

## How it works

```
Family phone  ──(private Supabase Realtime channel)──▶  Raspberry Pi
 (Next.js web app on Vercel)                             (Python listener + Firefox kiosk)
        │                                                       │
        └──────────── both join the same ────────────┐         │
                       JaaS (8x8 Jitsi) room  ◀───────┴─────────┘
```

- **Raspberry Pi 5** running a small Python **listener** service. It subscribes to a private [Supabase](https://supabase.com) Realtime channel, launches a **Firefox kiosk** on the TV pointed at the web app's `/kiosk` page, and performs the OS-level actions (ringtone, speaker volume, screen power, photo slideshow).
- **Web app** (Next.js, deployed on **Vercel**): a "Call Grandma" button for family, a photo uploader, and the Pi's own `/kiosk` page that embeds the video call via the **Jitsi IFrame API**.
- **Video** through **[JaaS](https://jaas.8x8.vc) (8x8 Jitsi as a Service)** — free for small usage, no 5-minute embed limit, and the Pi joins as a moderator via a server-signed JWT so nobody has to log in as host.
- **Supabase** provides Realtime (the trigger channel, presence for the Pi's online status), Auth (family accounts), and Storage (the photo bucket) — all locked down with Row-Level Security and a `family_members` allow-list.

> **Note on video quality:** the Raspberry Pi 5 has no hardware video encoder, so outgoing video is encoded in software — 720p @ 24fps is the practical ceiling.

## Hardware

- Raspberry Pi 5 (Raspberry Pi OS / Debian, Wayland + labwc)
- A TV or monitor (HDMI, or VGA via adapter) with speakers
- A USB webcam with a microphone
- Internet: Ethernet, Wi-Fi, or a 4G USB dongle (for a home with no fixed line)

## Getting started

1. **[docs/SETUP.md](docs/SETUP.md)** — create the Supabase project, set up JaaS, deploy the web app to Vercel, and install the listener on the Pi.
2. **[docs/RUNBOOK.md](docs/RUNBOOK.md)** — testing, logs, and common failure modes.

You'll need free accounts on Supabase, Vercel, and JaaS (8x8). Copy each
`*.env.example` to its real `.env` / `.env.local` and fill in your own values —
no secrets are committed to this repo.

## Repository layout

- `pi/` — everything deployed to the Raspberry Pi: the `listener/` Python service, the systemd unit, the labwc autostart snippet, the Firefox kiosk profile/policy, and the installer.
- `web/` — the Next.js web app (family call UI, photo uploader, the Pi's kiosk page, and the server route that signs JaaS JWTs).
- `supabase/` — SQL to set up the database (family allow-list, Realtime authorization, the photo storage bucket and its policies).
- `test/` — small Node scripts to exercise the Realtime channel (trigger a call, check presence/media) without the full UI.
- `docs/` — setup and runbook.

## License

Personal project, shared in case it's useful to others building something
similar. Use it as a starting point for your own family's setup.

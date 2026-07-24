"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import type { RealtimeChannel } from "@supabase/supabase-js";
import { createClient } from "@/lib/supabase/client";
import SignOutButton from "./SignOutButton";
import EmbeddedCall from "./EmbeddedCall";

const CHANNEL = "visio-tv-calls";
const APP_ID = process.env.NEXT_PUBLIC_JAAS_APP_ID;

type PiStatus = "connecting" | "offline" | "idle" | "in_call";

type PiPresence = {
  device?: string;
  status?: "idle" | "in_call";
  room?: string | null;
  since?: string;
};

export default function CallPanel({ userEmail }: { userEmail: string }) {
  const [piStatus, setPiStatus] = useState<PiStatus>("connecting");
  const [room, setRoom] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // Whether the caller's own embedded call view is open.
  const [showCall, setShowCall] = useState(false);
  // Real mic/camera state reported by the Pi's kiosk page during a call.
  const [media, setMedia] = useState<{
    audioMuted: boolean;
    videoMuted: boolean;
  } | null>(null);
  const channelRef = useRef<RealtimeChannel | null>(null);

  useEffect(() => {
    const supabase = createClient();
    let cancelled = false;

    (async () => {
      // Make sure realtime carries the user's JWT before joining the private channel.
      await supabase.realtime.setAuth();
      if (cancelled) return;

      const channel = supabase.channel(CHANNEL, {
        config: { private: true, presence: { key: userEmail } },
      });
      channelRef.current = channel;

      const syncPi = () => {
        const state = channel.presenceState<PiPresence>();
        // Presence can briefly hold more than one entry for the Pi (a track()
        // adds an entry rather than replacing it), so always take the newest.
        const pi = Object.values(state)
          .flat()
          .filter((m) => m.device === "pi")
          .sort((a, b) => (a.since ?? "").localeCompare(b.since ?? ""))
          .at(-1);

        if (!pi) {
          setPiStatus("offline");
          setRoom(null);
          return;
        }
        setPiStatus(pi.status === "in_call" ? "in_call" : "idle");
        setRoom(pi.status === "in_call" ? pi.room ?? null : null);
      };

      channel
        .on("presence", { event: "sync" }, syncPi)
        .on("presence", { event: "join" }, syncPi)
        .on("presence", { event: "leave" }, syncPi)
        .on("broadcast", { event: "media_state" }, ({ payload }) => {
          const p = payload as { audio_muted?: boolean; video_muted?: boolean };
          if (typeof p.audio_muted === "boolean" && typeof p.video_muted === "boolean")
            setMedia({ audioMuted: p.audio_muted, videoMuted: p.video_muted });
        })
        .subscribe((status, err) => {
          if (cancelled) return;
          if (status === "SUBSCRIBED") {
            setError(null);
            syncPi();
          } else if (status === "CHANNEL_ERROR" || status === "TIMED_OUT") {
            setPiStatus("offline");
            setError(
              "Connexion au canal impossible. Vérifie que ton compte fait bien partie de la famille."
            );
            if (err) console.error(err);
          }
        });
    })();

    return () => {
      cancelled = true;
      if (channelRef.current) supabase.removeChannel(channelRef.current);
      channelRef.current = null;
    };
  }, [userEmail]);

  const send = useCallback(
    async (event: "start_call" | "end_call", payload: object) => {
      const channel = channelRef.current;
      if (!channel) return;
      setBusy(true);
      try {
        await channel.send({ type: "broadcast", event, payload });
      } finally {
        setTimeout(() => setBusy(false), 1200);
      }
    },
    []
  );

  // Leave the embedded call view when the room ends.
  useEffect(() => {
    if (!room) setShowCall(false);
  }, [room]);

  const startCall = useCallback(async () => {
    const newRoom = `visio-tv-${crypto.randomUUID()}`;
    // Optimistic: presence from the Pi confirms it a moment later.
    setRoom(newRoom);
    setMedia(null);
    await send("start_call", { room: newRoom });
  }, [send]);

  const endCall = useCallback(async () => {
    setRoom(null);
    setMedia(null);
    await send("end_call", {});
  }, [send]);

  // Ask the Pi (its kiosk page) to mute/unmute itself — Jitsi forbids a
  // moderator from doing it to a remote participant, so the Pi acts on itself.
  const setPiMedia = useCallback(async (want: { audio?: boolean; video?: boolean }) => {
    await channelRef.current?.send({ type: "broadcast", event: "set_media", payload: want });
  }, []);

  const badge = {
    connecting: { text: "Connexion…", cls: "bg-slate-700 text-slate-300" },
    offline: { text: "Hors ligne", cls: "bg-red-950 text-red-300" },
    idle: { text: "En ligne", cls: "bg-emerald-950 text-emerald-300" },
    in_call: { text: "Appel en cours", cls: "bg-sky-950 text-sky-300" },
  }[piStatus];

  const callActive = room !== null;

  return (
    <main className="flex min-h-dvh flex-col items-center justify-between p-6">
      <header className="flex w-full max-w-sm items-center justify-between pt-2">
        <h1 className="text-xl font-bold">Visio TV</h1>
        <span className={`rounded-full px-3 py-1 text-sm ${badge.cls}`}>
          {badge.text}
        </span>
      </header>

      <div className="flex w-full max-w-sm flex-col items-center gap-4">
        <p className="text-center text-slate-400">La télé de Mamie</p>

        {error && (
          <p className="w-full rounded-lg bg-red-950 px-4 py-3 text-center text-red-300">
            {error}
          </p>
        )}

        {!callActive ? (
          <button
            onClick={startCall}
            disabled={piStatus !== "idle" || busy}
            className="w-full rounded-2xl bg-emerald-600 px-6 py-8 text-2xl font-bold transition hover:bg-emerald-500 disabled:cursor-not-allowed disabled:bg-slate-800 disabled:text-slate-500"
          >
            📞 Appeler Mamie
          </button>
        ) : (
          <div className="flex w-full flex-col gap-3">
            <button
              onClick={() => setShowCall(true)}
              disabled={!APP_ID}
              className="w-full rounded-2xl bg-sky-600 px-6 py-8 text-center text-2xl font-bold transition hover:bg-sky-500 disabled:opacity-50"
            >
              🎥 Rejoindre l’appel
            </button>

            <div className="flex gap-3">
              <button
                onClick={() => setPiMedia({ audio: !(media?.audioMuted ?? false) })}
                disabled={!media}
                className="flex-1 rounded-xl border border-slate-700 px-4 py-3 text-base transition hover:bg-slate-900 disabled:opacity-40"
              >
                {media?.audioMuted ? "🔇 Micro coupé" : "🎤 Micro actif"}
              </button>
              <button
                onClick={() => setPiMedia({ video: !(media?.videoMuted ?? false) })}
                disabled={!media}
                className="flex-1 rounded-xl border border-slate-700 px-4 py-3 text-base transition hover:bg-slate-900 disabled:opacity-40"
              >
                {media?.videoMuted ? "🚫 Caméra coupée" : "📷 Caméra active"}
              </button>
            </div>

            <button
              onClick={endCall}
              disabled={busy}
              className="w-full rounded-2xl bg-red-700 px-6 py-4 text-lg font-semibold transition hover:bg-red-600 disabled:opacity-50"
            >
              Raccrocher
            </button>
          </div>
        )}

        {piStatus === "offline" && !error && (
          <p className="text-center text-sm text-slate-500">
            La télé de Mamie est éteinte ou déconnectée.
          </p>
        )}
      </div>

      <Link
        href="/photos"
        className="w-full max-w-sm rounded-xl border border-slate-700 px-4 py-3 text-center text-slate-300 transition hover:bg-slate-900"
      >
        🖼️ Photos de Mamie
      </Link>

      <footer className="flex w-full max-w-sm items-center justify-between pb-2 text-sm text-slate-500">
        <span>{userEmail}</span>
        <SignOutButton />
      </footer>

      {showCall && room && (
        <EmbeddedCall
          room={room}
          displayName={userEmail.split("@")[0]}
          onClose={() => setShowCall(false)}
        />
      )}
    </main>
  );
}

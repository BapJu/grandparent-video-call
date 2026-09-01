"use client";

/**
 * Kiosk page loaded by the Raspberry Pi's Firefox kiosk (not by humans).
 *
 * It embeds the JaaS meeting through the Jitsi IFrame API with a moderator
 * JWT, so the Pi *starts* the room on its own — nobody has to sign in as
 * moderator anymore. Being the local participant, it can also unmute itself
 * cleanly (API commands, not simulated keystrokes).
 *
 * The Pi's OS-level actions (ringtone, speaker volume, hang-up, slideshow)
 * live in the Python listener, so this page pushes the events it sees over the
 * private Supabase channel and lets the listener act on them:
 *   participant joined  -> "ring"
 *   chat message        -> "stop_ring" (+ "volume" for +/-/plus/moins)
 *   left alone          -> "call_empty"
 *   conference closed   -> "call_ended"
 * and it obeys "set_media" from the family app (remote mic/camera control).
 *
 * Params arrive in the URL hash (never sent to the server):
 *   #room=<room>&token=<supabase-access-token>[&moderator=1]
 */

import { useEffect, useRef, useState } from "react";
import { createClient, type RealtimeChannel } from "@supabase/supabase-js";
import type { JitsiEmbedApi } from "@/lib/jitsi";

const JAAS_DOMAIN = "8x8.vc";
const APP_ID = process.env.NEXT_PUBLIC_JAAS_APP_ID!;
const CHANNEL = "visio-tv-calls";

function readHashParams() {
  if (typeof window === "undefined") return { room: null, token: null };
  const p = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  return { room: p.get("room"), token: p.get("token") };
}

// Detect a volume command in a chat message. "+++" stacks (capped); ordinary
// chat like "bonjour" returns 0 and is left alone.
function volumeSteps(text: string): number {
  const t = text.trim().toLowerCase();
  if (t === "plus" || t === "+") return 1;
  if (t === "moins" || t === "-") return -1;
  if (t && /^\++$/.test(t)) return Math.min(t.length, 5);
  if (t && /^-+$/.test(t)) return -Math.min(t.length, 5);
  return 0;
}

export default function KioskPage() {
  const containerRef = useRef<HTMLDivElement>(null);
  const apiRef = useRef<JitsiEmbedApi | null>(null);
  const scriptRef = useRef<HTMLScriptElement | null>(null);
  const cleanupChannelRef = useRef<(() => void) | null>(null);
  const [status, setStatus] = useState("Chargement…");

  useEffect(() => {
    const { room, token } = readHashParams();
    if (!room) return setStatus("Aucune salle indiquée (#room=…)");
    if (!APP_ID) return setStatus("JaaS non configuré");

    let disposed = false;

    (async () => {
      // 1) Moderator JWT for this room.
      let jwt: string;
      try {
        const resp = await fetch("/api/jaas-token", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({ room, moderator: true, name: "Mamie" }),
        });
        if (!resp.ok) throw new Error(`token ${resp.status}`);
        jwt = (await resp.json()).token;
      } catch (e) {
        console.error(e);
        return setStatus("Impossible d'obtenir le jeton JaaS");
      }
      if (disposed) return;

      // 2) Load the per-tenant IFrame API script, then start the meeting.
      const script = document.createElement("script");
      scriptRef.current = script;
      script.src = `https://${JAAS_DOMAIN}/${APP_ID}/external_api.js`;
      script.async = true;
      script.onerror = () => setStatus("Impossible de charger JaaS");
      script.onload = () => startMeeting(room!, token, jwt);
      document.body.appendChild(script);
    })();

    function startMeeting(room: string, token: string | null, jwt: string) {
      if (disposed || !containerRef.current) return;

      const api = new window.JitsiMeetExternalAPI(JAAS_DOMAIN, {
        roomName: `${APP_ID}/${room}`,
        jwt,
        parentNode: containerRef.current,
        width: "100%",
        height: "100%",
        configOverwrite: {
          prejoinPageEnabled: false,
          prejoinConfig: { enabled: false },
          startWithAudioMuted: false,
          startWithVideoMuted: false,
          disableDeepLinking: true,
          disableInviteFunctions: true,
          p2p: { enabled: false },

          // --- Optimisations Réseau 4G & Élimination du "Connection Poor" ---
          // 1. Désactive le simulcast : n'encode et n'envoie qu'UN SEUL flux vidéo au lieu de 3
          disableSimulcast: true,

          // 2. Suspend les couches de transmission inutiles
          enableLayerSuspension: true,

          // 3. Forcer le codec H264 plus économe en calcul/bande passante
          videoQuality: {
            preferredCodec: "H264",
          },

          // 4. Plafond de débit montant (1200 kbps max pour stabiliser la 4G)
          startBitrate: 1000,

          // 5. Résolution 720p @ 20-24fps
          resolution: 720,
          constraints: {
            video: {
              height: { ideal: 720, max: 720, min: 360 },
              width: { ideal: 1280, max: 1280, min: 640 },
              frameRate: { ideal: 20, max: 24 },
            },
          },
        },
        interfaceConfigOverwrite: {
          MOBILE_APP_PROMO: false,
          SHOW_JITSI_WATERMARK: false,
        },
      });
      apiRef.current = api;
      setStatus("");

      // Link back to the listener over the private channel.
      const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
      const anon = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
      let channel: RealtimeChannel | null = null;
      if (url && anon && token) {
        const supabase = createClient(url, anon);
        supabase.realtime.setAuth(token);
        channel = supabase.channel(CHANNEL, { config: { private: true } });
        channel
          .on("broadcast", { event: "set_media" }, async ({ payload }) => {
            // want.* is the DESIRED muted state: toggle only when we're not
            // already there.
            const want = payload as { audio?: boolean; video?: boolean };
            if (typeof want.audio === "boolean" && (await api.isAudioMuted()) !== want.audio)
              api.executeCommand("toggleAudio");
            if (typeof want.video === "boolean" && (await api.isVideoMuted()) !== want.video)
              api.executeCommand("toggleVideo");
          })
          .subscribe();
        cleanupChannelRef.current = () => supabase.removeChannel(channel!);
      }

      const notify = (event: string, payload: object = {}) =>
        channel?.send({ type: "broadcast", event, payload });

      const publishMediaState = async () => {
        try {
          notify("media_state", {
            audio_muted: await api.isAudioMuted(),
            video_muted: await api.isVideoMuted(),
          });
        } catch {
          /* best effort */
        }
      };

      // Self-unmute cleanly via the API (no simulated keystrokes).
      const ensureUnmuted = async () => {
        try {
          if (await api.isAudioMuted()) api.executeCommand("toggleAudio");
          if (await api.isVideoMuted()) api.executeCommand("toggleVideo");
        } catch {
          /* ignore */
        }
      };

      let rang = false;

      api.addListener("videoConferenceJoined", () => {
        ensureUnmuted();
        publishMediaState();
      });
      api.addListener("audioMuteStatusChanged", publishMediaState);
      api.addListener("videoMuteStatusChanged", publishMediaState);

      api.addListener("participantJoined", () => {
        notify("call_busy"); // cancel any pending "left alone" hang-up
        publishMediaState(); // so the caller's control buttons know the state
        if (!rang) {
          rang = true;
          notify("ring"); // caller is really here now
        }
      });

      api.addListener("incomingMessage", (e: { message?: string }) => {
        notify("stop_ring");
        const steps = volumeSteps(e?.message ?? "");
        if (steps) notify("volume", { steps });
      });

      api.addListener("participantLeft", () => {
        if (api.getNumberOfParticipants() <= 1) notify("call_empty");
      });
      api.addListener("readyToClose", () => notify("call_ended"));
    }

    return () => {
      disposed = true;
      cleanupChannelRef.current?.();
      apiRef.current?.dispose();
      scriptRef.current?.remove();
    };
  }, []);

  return (
    <div className="fixed inset-0 bg-black">
      <div ref={containerRef} className="h-full w-full" />
      {status && (
        <p className="absolute inset-0 flex items-center justify-center text-2xl text-slate-400">
          {status}
        </p>
      )}
    </div>
  );
}

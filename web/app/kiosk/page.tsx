"use client";

/**
 * Kiosk page loaded by the Raspberry Pi's Firefox kiosk (not by humans).
 *
 * Why this exists: Jitsi never lets a moderator unmute a remote participant
 * (by design, for privacy). But the IFrame API *can* control the local
 * participant — so by embedding Jitsi here, the Pi can unmute itself on join
 * and honour mic/camera commands sent from the family app.
 *
 * Params arrive in the URL hash (never sent to the server):
 *   #room=<jitsi-room>&token=<supabase-access-token>
 */

import { useEffect, useRef, useState } from "react";
import { createClient } from "@supabase/supabase-js";

const JITSI_DOMAIN = "meet.jit.si";
const CHANNEL = "visio-tv-calls";

type JitsiApi = {
  addListener: (event: string, handler: (payload: never) => void) => void;
  executeCommand: (command: string, ...args: unknown[]) => void;
  isAudioMuted: () => Promise<boolean>;
  isVideoMuted: () => Promise<boolean>;
  dispose: () => void;
};

declare global {
  interface Window {
    JitsiMeetExternalAPI: new (domain: string, options: object) => JitsiApi;
  }
}

function readHashParams() {
  if (typeof window === "undefined") return { room: null, token: null };
  const p = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  return { room: p.get("room"), token: p.get("token") };
}

export default function KioskPage() {
  const containerRef = useRef<HTMLDivElement>(null);
  const apiRef = useRef<JitsiApi | null>(null);
  const [status, setStatus] = useState("Chargement…");

  useEffect(() => {
    const { room, token } = readHashParams();
    if (!room) {
      setStatus("Aucune salle indiquée (#room=…)");
      return;
    }

    let disposed = false;
    let cleanupRealtime: (() => void) | undefined;

    const script = document.createElement("script");
    script.src = `https://${JITSI_DOMAIN}/external_api.js`;
    script.async = true;

    script.onload = () => {
      if (disposed || !containerRef.current) return;

      const api = new window.JitsiMeetExternalAPI(JITSI_DOMAIN, {
        roomName: room,
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
        },
        interfaceConfigOverwrite: {
          SHOW_JITSI_WATERMARK: false,
          SHOW_WATERMARK_FOR_GUESTS: false,
          MOBILE_APP_PROMO: false,
        },
        userInfo: { displayName: "Mamie" },
      });
      apiRef.current = api;
      setStatus("");

      // --- self-unmute -------------------------------------------------
      // meet.jit.si forces participants who arrive before the moderator to
      // join muted, ignoring startWith*Muted. Fix it from the inside once
      // the conference is actually joined.
      const ensureUnmuted = async () => {
        try {
          if (await api.isAudioMuted()) api.executeCommand("toggleAudio");
          if (await api.isVideoMuted()) api.executeCommand("toggleVideo");
        } catch {
          /* API not ready yet — the retries below cover it */
        }
      };

      api.addListener("videoConferenceJoined", () => {
        // The conference can report "joined" while still waiting for a
        // moderator, so retry for a while instead of unmuting just once.
        ensureUnmuted();
        let tries = 0;
        const timer = setInterval(() => {
          if (disposed || ++tries > 20) return clearInterval(timer);
          ensureUnmuted();
        }, 3000);
      });

      // --- remote control from the family app ---------------------------
      const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
      const anon = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
      if (token && url && anon) {
        const supabase = createClient(url, anon);
        supabase.realtime.setAuth(token);
        const channel = supabase.channel(CHANNEL, { config: { private: true } });

        const publishMediaState = async () => {
          try {
            await channel.send({
              type: "broadcast",
              event: "media_state",
              payload: {
                audio_muted: await api.isAudioMuted(),
                video_muted: await api.isVideoMuted(),
              },
            });
          } catch {
            /* best effort */
          }
        };

        channel
          .on("broadcast", { event: "set_media" }, async ({ payload }) => {
            const want = payload as { audio?: boolean; video?: boolean };
            if (typeof want.audio === "boolean") {
              const muted = await api.isAudioMuted();
              if (muted === want.audio) api.executeCommand("toggleAudio");
            }
            if (typeof want.video === "boolean") {
              const muted = await api.isVideoMuted();
              if (muted === want.video) api.executeCommand("toggleVideo");
            }
          })
          .subscribe();

        api.addListener("audioMuteStatusChanged", publishMediaState);
        api.addListener("videoMuteStatusChanged", publishMediaState);
        api.addListener("videoConferenceJoined", publishMediaState);

        cleanupRealtime = () => {
          supabase.removeChannel(channel);
        };
      }
    };

    script.onerror = () => setStatus("Impossible de charger Jitsi");
    document.body.appendChild(script);

    return () => {
      disposed = true;
      cleanupRealtime?.();
      apiRef.current?.dispose();
      script.remove();
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

"use client";

/**
 * Full-screen embedded JaaS call for the family caller, so they stay inside
 * tv-visio instead of being sent off to 8x8.vc. Mirrors what the Pi's /kiosk
 * page does, but with the normal Jitsi UI (the caller drives it themselves).
 */

import { useEffect, useRef } from "react";
import { createClient } from "@/lib/supabase/client";
import type { JitsiEmbedApi } from "@/lib/jitsi";

const JAAS_DOMAIN = "8x8.vc";
const APP_ID = process.env.NEXT_PUBLIC_JAAS_APP_ID!;

export default function EmbeddedCall({
  room,
  displayName,
  onClose,
  media,
  ringing,
  onSetMedia,
  onVolume,
  onStopRing,
}: {
  room: string;
  displayName: string;
  onClose: () => void;
  media: { audioMuted: boolean; videoMuted: boolean } | null;
  ringing: boolean;
  onSetMedia: (want: { audio?: boolean; video?: boolean }) => void;
  onVolume: (steps: number) => void;
  onStopRing: () => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const apiRef = useRef<JitsiEmbedApi | null>(null);
  const scriptRef = useRef<HTMLScriptElement | null>(null);

  useEffect(() => {
    let disposed = false;

    (async () => {
      // Signed JaaS token for this room (server holds the private key).
      let jwt: string;
      try {
        const supabase = createClient();
        const {
          data: { session },
        } = await supabase.auth.getSession();
        const resp = await fetch("/api/jaas-token", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${session?.access_token}`,
          },
          body: JSON.stringify({ room, moderator: true, name: displayName }),
        });
        if (!resp.ok) throw new Error(`token ${resp.status}`);
        jwt = (await resp.json()).token;
      } catch (e) {
        console.error(e);
        onClose();
        return;
      }
      if (disposed) return;

      const script = document.createElement("script");
      scriptRef.current = script;
      script.src = `https://${JAAS_DOMAIN}/${APP_ID}/external_api.js`;
      script.async = true;
      script.onerror = () => onClose();
      script.onload = () => {
        if (disposed || !containerRef.current) return;
        const api = new window.JitsiMeetExternalAPI(JAAS_DOMAIN, {
          roomName: `${APP_ID}/${room}`,
          jwt,
          parentNode: containerRef.current,
          width: "100%",
          height: "100%",
          userInfo: { displayName },
          configOverwrite: {
            prejoinPageEnabled: false,
            prejoinConfig: { enabled: false },
            disableDeepLinking: true,
            p2p: { enabled: false },
          },
          interfaceConfigOverwrite: { MOBILE_APP_PROMO: false },
        });
        apiRef.current = api;
        api.addListener("readyToClose", onClose);
      };
      document.body.appendChild(script);
    })();

    return () => {
      disposed = true;
      apiRef.current?.dispose();
      scriptRef.current?.remove();
    };
  }, [room, displayName, onClose]);

  return (
    <div className="fixed inset-0 z-50 bg-black">
      <div ref={containerRef} className="h-full w-full" />

      {/* Controls for Mamie's end, laid over the top of the call. Jitsi's own
          toolbar (hang up, your mic/cam) is at the bottom. */}
      <div className="pointer-events-none absolute inset-x-0 top-0 flex justify-center p-2">
        <div className="pointer-events-auto flex max-w-[96vw] items-center gap-0.5 rounded-full bg-black/70 px-1 py-1 text-white backdrop-blur">
          <button
            onClick={() => onVolume(-1)}
            aria-label="Baisser le volume de Mamie"
            className="rounded-full px-2.5 py-1.5 text-base transition hover:bg-white/15"
          >
            🔉
          </button>
          <button
            onClick={() => onVolume(1)}
            aria-label="Monter le volume de Mamie"
            className="rounded-full px-2.5 py-1.5 text-base transition hover:bg-white/15"
          >
            🔊
          </button>
          <span className="mx-0.5 h-5 w-px bg-white/20" />
          <button
            onClick={() => onSetMedia({ audio: !(media?.audioMuted ?? false) })}
            disabled={!media}
            aria-label="Micro de Mamie"
            className="rounded-full px-2.5 py-1.5 text-base transition hover:bg-white/15 disabled:opacity-40"
          >
            {media?.audioMuted ? "🔇" : "🎤"}
          </button>
          <button
            onClick={() => onSetMedia({ video: !(media?.videoMuted ?? false) })}
            disabled={!media}
            aria-label="Caméra de Mamie"
            className="rounded-full px-2.5 py-1.5 text-base transition hover:bg-white/15 disabled:opacity-40"
          >
            {media?.videoMuted ? "🚫" : "📷"}
          </button>
        </div>
      </div>

      {/* While the Pi is ringing, a big animated prompt: it won't stop on its
          own, the caller has to tap it. */}
      {ringing && (
        <div className="pointer-events-none absolute inset-x-0 top-16 flex justify-center px-4">
          <button
            onClick={onStopRing}
            className="pointer-events-auto flex items-center gap-3 rounded-full bg-amber-500 px-6 py-4 text-lg font-bold text-black shadow-2xl"
          >
            <span className="animate-ring text-3xl">🔔</span>
            Couper la sonnerie
          </button>
        </div>
      )}
    </div>
  );
}

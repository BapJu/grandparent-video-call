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
}: {
  room: string;
  displayName: string;
  onClose: () => void;
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
    </div>
  );
}

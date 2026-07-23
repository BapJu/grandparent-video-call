import { NextResponse } from "next/server";
import { createClient } from "@supabase/supabase-js";
import { SignJWT, importPKCS8 } from "jose";

/**
 * Signs a JaaS (8x8 Jitsi as a Service) JWT so a family member — or the Pi —
 * can join a meeting as moderator. Every JaaS participant needs a token signed
 * with the tenant's RSA private key, which must never reach the browser, hence
 * this server-side route.
 *
 * Auth: Authorization: Bearer <supabase access token>. The same route serves
 * the web app (its session token) and the Pi (its device-account token); both
 * are checked against the family_members allowlist via RLS.
 */

const APP_ID = process.env.JAAS_APP_ID;
const KID = process.env.JAAS_KID;
const PRIVATE_KEY = process.env.JAAS_PRIVATE_KEY;

const TOKEN_TTL_SECONDS = 3 * 60 * 60; // long enough for any call

export async function POST(request: Request) {
  if (!APP_ID || !KID || !PRIVATE_KEY) {
    return NextResponse.json({ error: "JaaS not configured" }, { status: 500 });
  }

  const auth = request.headers.get("authorization") ?? "";
  const accessToken = auth.startsWith("Bearer ") ? auth.slice(7) : null;
  if (!accessToken) {
    return NextResponse.json({ error: "Missing bearer token" }, { status: 401 });
  }

  // Validate the caller and confirm family membership using their own token
  // (RLS only lets a family member read the allowlist).
  const supabase = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    { global: { headers: { Authorization: `Bearer ${accessToken}` } } }
  );

  const {
    data: { user },
    error: userError,
  } = await supabase.auth.getUser();
  if (userError || !user) {
    return NextResponse.json({ error: "Invalid token" }, { status: 401 });
  }

  const { data: members } = await supabase
    .from("family_members")
    .select("id")
    .limit(1);
  if ((members?.length ?? 0) === 0) {
    return NextResponse.json({ error: "Not a family member" }, { status: 403 });
  }

  let body: { room?: string; moderator?: boolean; name?: string };
  try {
    body = await request.json();
  } catch {
    body = {};
  }
  const room = body.room || "*";
  const moderator = body.moderator !== false; // default true
  const name = body.name || "Visio TV";

  const now = Math.floor(Date.now() / 1000);
  const key = await importPKCS8(PRIVATE_KEY, "RS256");

  const token = await new SignJWT({
    aud: "jitsi",
    iss: "chat",
    sub: APP_ID,
    room,
    context: {
      user: {
        id: user.id,
        name,
        email: user.email,
        moderator,
      },
      features: {
        livestreaming: false,
        recording: false,
        transcription: false,
        "outbound-call": false,
      },
    },
  })
    .setProtectedHeader({ alg: "RS256", kid: KID, typ: "JWT" })
    .setIssuedAt(now)
    .setNotBefore(now - 10)
    .setExpirationTime(now + TOKEN_TTL_SECONDS)
    .sign(key);

  return NextResponse.json({ token });
}

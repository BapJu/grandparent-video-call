// Manual test trigger: sends the same start_call/end_call broadcast events
// that the family web client sends, over the PRIVATE 'visio-tv-calls' channel.
// Doubles as the negative security test: without valid credentials in
// test/.env, subscribing to the private channel must fail.
//
// Usage:
//   node trigger.mjs start   # sends start_call with a fresh random room id
//   node trigger.mjs end     # sends end_call

import "dotenv/config";
import { randomUUID } from "node:crypto";
import { createClient } from "@supabase/supabase-js";

const action = process.argv[2];
if (!["start", "end"].includes(action)) {
  console.error("Usage: node trigger.mjs <start|end>");
  process.exit(1);
}

const url = process.env.SUPABASE_URL;
const anonKey = process.env.SUPABASE_ANON_KEY;
const channelName = process.env.SUPABASE_CHANNEL || "visio-tv-calls";
const email = process.env.SUPABASE_TEST_EMAIL;
const password = process.env.SUPABASE_TEST_PASSWORD;

if (!url || !anonKey) {
  console.error(
    "Missing SUPABASE_URL / SUPABASE_ANON_KEY - copy test/.env.example to test/.env and fill it in."
  );
  process.exit(1);
}

const supabase = createClient(url, anonKey);

if (email && password) {
  const { error } = await supabase.auth.signInWithPassword({ email, password });
  if (error) {
    console.error(`Login failed for ${email}: ${error.message}`);
    process.exit(1);
  }
  await supabase.realtime.setAuth();
  console.log(`Authenticated as ${email}`);
} else {
  console.warn(
    "No SUPABASE_TEST_EMAIL/PASSWORD set - proceeding unauthenticated (expected to FAIL on the private channel; this is the negative test)."
  );
}

const channel = supabase.channel(channelName, { config: { private: true } });

const timeout = setTimeout(() => {
  console.error(
    "Timed out subscribing to the private channel (auth missing/invalid, or email not in family_members?)"
  );
  process.exit(1);
}, 10_000);

channel.subscribe(async (status, err) => {
  if (status === "CHANNEL_ERROR" || status === "TIMED_OUT") {
    clearTimeout(timeout);
    console.error(`Subscribe failed: ${status}${err ? " - " + err.message : ""}`);
    process.exit(1);
  }
  if (status !== "SUBSCRIBED") return;
  clearTimeout(timeout);

  if (action === "start") {
    const room = `visio-tv-${randomUUID()}`;
    await channel.send({ type: "broadcast", event: "start_call", payload: { room } });
    console.log(`Sent start_call for room: ${room}`);
    console.log(`Join it yourself at: https://meet.jit.si/${room}`);
  } else {
    await channel.send({ type: "broadcast", event: "end_call", payload: {} });
    console.log("Sent end_call");
  }

  await supabase.removeChannel(channel);
  process.exit(0);
});

// Manual test trigger: sends the same start_call/end_call broadcast events
// that the future Vercel/Supabase family client will send, so the Pi-side
// listener can be validated end-to-end before that client exists.
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

if (!url || !anonKey) {
  console.error(
    "Missing SUPABASE_URL / SUPABASE_ANON_KEY - copy test/.env.example to test/.env and fill them in."
  );
  process.exit(1);
}

const supabase = createClient(url, anonKey);
const channel = supabase.channel(channelName);

const timeout = setTimeout(() => {
  console.error("Timed out waiting to subscribe to the channel");
  process.exit(1);
}, 10_000);

channel.subscribe(async (status) => {
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

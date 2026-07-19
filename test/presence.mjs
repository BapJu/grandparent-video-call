// Debug helper: dump the presence state of the visio-tv-calls channel.
// Usage: node presence.mjs [seconds]
import "dotenv/config";
import { createClient } from "@supabase/supabase-js";

const seconds = Number(process.argv[2] ?? 12);
const supabase = createClient(
  process.env.SUPABASE_URL,
  process.env.SUPABASE_ANON_KEY
);

const { error } = await supabase.auth.signInWithPassword({
  email: process.env.SUPABASE_TEST_EMAIL,
  password: process.env.SUPABASE_TEST_PASSWORD,
});
if (error) {
  console.error("login failed:", error.message);
  process.exit(1);
}
await supabase.realtime.setAuth();

const channel = supabase.channel(process.env.SUPABASE_CHANNEL || "visio-tv-calls", {
  config: { private: true, presence: { key: "debug-observer" } },
});

const dump = (label) =>
  console.log(`[${label}]`, JSON.stringify(channel.presenceState(), null, 2));

channel
  .on("presence", { event: "sync" }, () => dump("sync"))
  .on("presence", { event: "join" }, ({ key }) => dump(`join ${key}`))
  .on("presence", { event: "leave" }, ({ key }) => dump(`leave ${key}`))
  .subscribe((status, err) => {
    if (status === "SUBSCRIBED") console.log("subscribed, watching presence…");
    else if (err) console.error(status, err.message);
  });

setTimeout(() => process.exit(0), seconds * 1000);

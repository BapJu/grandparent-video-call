// Debug helper: read the Pi kiosk's mic/camera state and optionally change it.
//   node media.mjs                 # just watch media_state broadcasts
//   node media.mjs mute-audio      # ask the Pi to mute its microphone
//   node media.mjs unmute-audio
//   node media.mjs mute-video
//   node media.mjs unmute-video
import "dotenv/config";
import { createClient } from "@supabase/supabase-js";

const action = process.argv[2];
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
  config: { private: true },
});

channel
  .on("broadcast", { event: "media_state" }, ({ payload }) =>
    console.log("media_state:", JSON.stringify(payload))
  )
  .subscribe(async (status) => {
    if (status !== "SUBSCRIBED") return;
    console.log("watching media_state…");
    const want = {
      "mute-audio": { audio: true },
      "unmute-audio": { audio: false },
      "mute-video": { video: true },
      "unmute-video": { video: false },
    }[action];
    if (want) {
      await new Promise((r) => setTimeout(r, 1500));
      await channel.send({ type: "broadcast", event: "set_media", payload: want });
      console.log("sent set_media:", JSON.stringify(want));
    }
  });

setTimeout(() => process.exit(0), 14000);

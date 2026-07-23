#!/usr/bin/env python3
"""Log what a call is actually doing, once every 10s, to a CSV.

Written because a call kept dying after a few minutes with no obvious cause:
guessing was expensive (each test needs a human to join and wait), so this
records the timeline instead — bitrates, connection quality, packet loss,
CPU and network counters — to show exactly what degrades first.

Usage: python3 watch_call.py [seconds] [outfile]
"""

import json
import subprocess
import sys
import time

sys.path.insert(0, "/home/julienne/visio-tv/listener")
import jitsi_probe  # noqa: E402

STATS_SCRIPT = """
const w = window.wrappedJSObject || window;
const out = {};
try {
  const st = w.APP.store.getState();
  out.p2p = !!st['features/base/conference'].p2p;
  const parts = st['features/base/participants'];
  out.remote = parts.remote ? (parts.remote.size ?? Object.keys(parts.remote).length) : 0;
  const q = w.APP.conference._room.connectionQuality.getStats();
  out.quality = q.connectionQuality;
  out.upVideo = q.bitrate && q.bitrate.video ? q.bitrate.video.upload : null;
  out.downVideo = q.bitrate && q.bitrate.video ? q.bitrate.video.download : null;
  out.upAudio = q.bitrate && q.bitrate.audio ? q.bitrate.audio.upload : null;
  out.lossUp = q.packetLoss ? q.packetLoss.upload : null;
  out.lossDown = q.packetLoss ? q.packetLoss.download : null;
} catch (e) { out.err = String(e).slice(0, 60); }
return JSON.stringify(out);
"""


def cpu_of(name: str) -> str:
    try:
        r = subprocess.run(
            ["ps", "-C", name, "-o", "%cpu=", "--sort=-%cpu"],
            capture_output=True, text=True, timeout=5,
        )
        return r.stdout.split("\n")[0].strip() or "0"
    except Exception:
        return "?"


def net_bytes() -> int:
    try:
        with open("/proc/net/dev") as f:
            for line in f:
                if "eth0" in line:
                    p = line.split()
                    return int(p[1]) + int(p[9])
    except OSError:
        pass
    return 0


def main() -> None:
    duration = float(sys.argv[1]) if len(sys.argv) > 1 else 600
    out_path = sys.argv[2] if len(sys.argv) > 2 else "/tmp/call-watch.csv"

    end = time.time() + duration
    prev_net = net_bytes()
    with open(out_path, "w") as f:
        f.write("t,quality,upVideo,downVideo,upAudio,lossUp,lossDown,remote,p2p,cpuFirefox,kbpsNet,err\n")
        f.flush()
        t0 = time.time()
        while time.time() < end:
            time.sleep(10)
            now = net_bytes()
            kbps = (now - prev_net) * 8 / 10 / 1000
            prev_net = now

            raw = jitsi_probe._run(STATS_SCRIPT)
            try:
                s = json.loads(raw.get("value") if isinstance(raw, dict) else raw)
            except Exception:
                s = {"err": "probe failed"}

            f.write(
                f"{int(time.time()-t0)},{s.get('quality','')},{s.get('upVideo','')},"
                f"{s.get('downVideo','')},{s.get('upAudio','')},{s.get('lossUp','')},"
                f"{s.get('lossDown','')},{s.get('remote','')},{s.get('p2p','')},"
                f"{cpu_of('firefox')},{kbps:.0f},{s.get('err','')}\n"
            )
            f.flush()


if __name__ == "__main__":
    main()

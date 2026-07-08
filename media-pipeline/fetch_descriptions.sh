#!/bin/bash
# Backfill video descriptions for year-only channels (resumable: skips cached ids).
cd "$(dirname "$0")"
python3 - << 'EOF'
import json, os, subprocess, sys, time

ids = []
for ch in ("WFAttitudeVideos2", "RuthlessAggressionV12"):
    for e in json.load(open(f"cache/yt_{ch}.json")):
        ids.append(e["id"])

todo = [i for i in ids if not os.path.exists(f"cache/desc/{i}.json")]
print(f"{len(ids)} total, {len(todo)} to fetch", flush=True)

for n, vid in enumerate(todo, 1):
    try:
        out = subprocess.run(
            ["yt-dlp", "-J", "--skip-download", f"https://www.youtube.com/watch?v={vid}"],
            capture_output=True, text=True, timeout=60)
        if out.returncode == 0:
            d = json.loads(out.stdout)
            slim = {"id": vid, "description": d.get("description", ""),
                    "upload_date": d.get("upload_date"), "duration": d.get("duration")}
            json.dump(slim, open(f"cache/desc/{vid}.json", "w"))
        else:
            json.dump({"id": vid, "error": out.stderr[-200:]}, open(f"cache/desc/{vid}.json", "w"))
    except Exception as ex:
        json.dump({"id": vid, "error": str(ex)[:200]}, open(f"cache/desc/{vid}.json", "w"))
    if n % 50 == 0:
        print(f"{n}/{len(todo)} fetched", flush=True)
    time.sleep(0.4)
print("description backfill complete", flush=True)
EOF

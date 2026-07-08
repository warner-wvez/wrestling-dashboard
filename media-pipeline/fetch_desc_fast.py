import json, os, subprocess, sys
from concurrent.futures import ThreadPoolExecutor

os.chdir(os.path.dirname(os.path.abspath(__file__)))
ids = []
for ch in ("WFAttitudeVideos2", "RuthlessAggressionV12"):
    for e in json.load(open(f"cache/yt_{ch}.json")):
        ids.append(e["id"])
todo = [i for i in ids if not os.path.exists(f"cache/desc/{i}.json")]
print(f"{len(ids)} total, {len(todo)} to fetch", flush=True)

done = 0
def fetch(vid):
    global done
    try:
        out = subprocess.run(["yt-dlp", "-J", "--skip-download",
                              f"https://www.youtube.com/watch?v={vid}"],
                             capture_output=True, text=True, timeout=60)
        if out.returncode == 0:
            d = json.loads(out.stdout)
            slim = {"id": vid, "description": d.get("description", ""),
                    "duration": d.get("duration")}
        else:
            slim = {"id": vid, "error": out.stderr[-200:]}
    except Exception as ex:
        slim = {"id": vid, "error": str(ex)[:200]}
    json.dump(slim, open(f"cache/desc/{vid}.json", "w"))
    done += 1
    if done % 100 == 0:
        print(f"{done}/{len(todo)}", flush=True)

with ThreadPoolExecutor(max_workers=5) as ex:
    list(ex.map(fetch, todo))
print("backfill complete", flush=True)

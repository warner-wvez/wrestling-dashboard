import json, os, subprocess, sys
from concurrent.futures import ThreadPoolExecutor

os.chdir(os.path.dirname(os.path.abspath(__file__)))
ids = []
for ch in ("WFAttitudeVideos2", "RuthlessAggressionV12"):
    path = f"cache/yt_{ch}.json"
    if not os.path.exists(path):
        print(f"  channel cache missing, skipping: {path}", flush=True)
        continue
    with open(path) as f:
        for e in json.load(f):
            ids.append(e["id"])
todo = [i for i in ids if not os.path.exists(f"cache/desc/{i}.json")]
print(f"{len(ids)} total, {len(todo)} to fetch", flush=True)

done = 0
done_lock = __import__("threading").Lock()
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
            slim = None                          # transient failure: see below
            err = out.stderr[-200:]
    except Exception as ex:
        slim = None
        err = str(ex)[:200]
    # Only cache SUCCESSES. A failed fetch (429/timeout/network blip) must NOT
    # leave a file behind: `todo` skips anything with a file, so a cached error
    # would drop that video's description forever. No file => retried next run.
    # Write atomically (tmp + replace) so an interrupted write can't leave a
    # half-file that later crashes media_map.py's json.load.
    if slim is not None:
        final = f"cache/desc/{vid}.json"
        tmp = f"{final}.{os.getpid()}.tmp"
        with open(tmp, "w") as f:
            json.dump(slim, f)
        os.replace(tmp, final)
    else:
        print(f"  fetch failed for {vid}, will retry next run: {err}", flush=True)
    with done_lock:
        done += 1
        n = done
    if n % 100 == 0:
        print(f"{n}/{len(todo)}", flush=True)

with ThreadPoolExecutor(max_workers=5) as ex:
    list(ex.map(fetch, todo))
print("backfill complete", flush=True)

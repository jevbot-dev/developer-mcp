#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Topic search over the local guitaripod/wwdc-sessions clone.

  wwdc.py search "app intents" --year 2024-2026     rank sessions by relevance
  wwdc.py search --event wwdc2026 --topic design    no terms: list everything matching filters
  wwdc.py grep "Liquid Glass" --event wwdc2025 -C 1  transcript hits with timestamps
  wwdc.py show wwdc2025-219                          one session: metadata + file paths
  wwdc.py frames wwdc2026-250 2:00-2:03 5:10.5       every frame of those ranges (4K jpg)
  wwdc.py clip wwdc2026-292 0:27-0:37                cut a trimmed mp4 (video+audio)
  wwdc.py topics                                     topic list with counts
  wwdc.py update                                     git pull the data repo

Repo path: $WWDC_REPO, default ~/ghq/github.com/guitaripod/wwdc-sessions
"""

import argparse
import json
import math
import os
import re
import subprocess
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin

REPO = Path(os.environ.get("WWDC_REPO", "~/ghq/github.com/guitaripod/wwdc-sessions")).expanduser()


def load_catalog():
    path = REPO / "catalog.json"
    if not path.exists():
        sys.exit(f"catalog not found: {path}  (run: ghq get guitaripod/wwdc-sessions)")
    return json.loads(path.read_text())["sessions"]


def load_transcript(s):
    p = REPO / s["path"] / "transcript.json"
    return json.loads(p.read_text())["segments"] if p.exists() else []


def parse_years(spec):
    if not spec:
        return None
    lo, _, hi = spec.partition("-")
    return int(lo), int(hi or lo)


def filter_sessions(sessions, args):
    years = parse_years(args.year)
    out = []
    for s in sessions:
        if years and not years[0] <= s["year"] <= years[1]:
            continue
        if args.event and s["event"] not in args.event:
            continue
        if args.topic and not any(t.lower() in x.lower() for t in args.topic for x in s["topics"]):
            continue
        if args.platform and not any(p.lower() == x.lower() for p in args.platform for x in s["platforms"]):
            continue
        out.append(s)
    return out


def compile_terms(args):
    flags = 0 if args.case else re.IGNORECASE
    if args.regex:
        return [re.compile(t, flags) for t in args.terms]
    return [re.compile(re.escape(t), flags) for t in args.terms]


def fmt_time(sec):
    sec = int(sec)
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def time_url(s, sec):
    return f"{s['url']}/?time={int(sec)}"


def emit(rows, args, render):
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    elif not rows:
        print("no matches", file=sys.stderr)
    else:
        for r in rows:
            render(r)


def cmd_search(args):
    """Every term must appear somewhere (title/description/keywords/transcript)."""
    terms = compile_terms(args)
    rows = []
    for s in filter_sessions(load_catalog(), args):
        meta = {
            "title": s["title"],
            "keywords": " ".join(s["keywords"]),
            "description": s.get("description") or "",
        }
        segs = [] if args.no_transcript or not terms else load_transcript(s)
        body = "\n".join(seg["text"] for seg in segs)
        score, hits = 0.0, {}
        for t in terms:
            h = {
                "title": len(t.findall(meta["title"])),
                "keywords": len(t.findall(meta["keywords"])),
                "description": len(t.findall(meta["description"])),
                "transcript": len(t.findall(body)),
            }
            if not any(h.values()):
                break
            hits[t.pattern] = h
            score += 10 * bool(h["title"]) + 5 * bool(h["keywords"]) + 3 * bool(h["description"])
            score += 2 * math.log2(1 + h["transcript"])
        else:
            first = next((seg["start"] for seg in segs if any(t.search(seg["text"]) for t in terms)), None)
            rows.append({
                "id": s["id"], "title": s["title"], "year": s["year"], "duration": s["duration"],
                "score": round(score, 1), "hits": hits,
                "transcriptHits": sum(h["transcript"] for h in hits.values()),
                "firstHit": first, "url": time_url(s, first) if first is not None else s["url"],
                "path": str(REPO / s["path"]), "topics": s["topics"],
            })
    rows.sort(key=lambda r: (r["score"], r["year"]), reverse=True)
    rows = rows[: args.limit]

    def render(r):
        dur = fmt_time(r["duration"]) if r["duration"] else "?"
        first = f" first@{fmt_time(r['firstHit'])}" if r["firstHit"] is not None else ""
        print(f"{r['score']:5.1f}  {r['id']:<22} {r['title']}  [{dur}]")
        print(f"       hits={r['transcriptHits']}{first}  {r['url']}")

    emit(rows, args, render)


def cmd_grep(args):
    """Segment-level hits; a line matches when every term appears in it."""
    terms = compile_terms(args)
    rows, total = [], 0
    for s in filter_sessions(load_catalog(), args):
        segs = load_transcript(s)
        idx = [i for i, seg in enumerate(segs) if all(t.search(seg["text"]) for t in terms)]
        if not idx:
            continue
        matches = []
        for i in idx[: args.max_per_session]:
            lo, hi = max(0, i - args.context), min(len(segs), i + args.context + 1)
            matches.append({
                "start": segs[i]["start"], "url": time_url(s, segs[i]["start"]),
                "text": " ".join(seg["text"] for seg in segs[lo:hi]),
            })
        rows.append({"id": s["id"], "title": s["title"], "count": len(idx), "matches": matches})
        total += len(idx)
    rows.sort(key=lambda r: r["count"], reverse=True)
    found = len(rows)
    rows = rows[: args.limit]

    def render(r):
        print(f"\n== {r['id']}  {r['title']}  ({r['count']} hits)")
        for m in r["matches"]:
            print(f"  [{fmt_time(m['start'])}] {m['text']}")
            print(f"           {m['url']}")

    emit(rows, args, render)
    if not args.json and rows:
        print(f"\n{total} hits across {found} sessions (showing {len(rows)})", flush=True)


def cmd_show(args):
    s = next((s for s in load_catalog() if s["id"] == args.id), None)
    if not s:
        sys.exit(f"unknown id: {args.id}")
    base = REPO / s["path"]
    meta = json.loads((base / "metadata.json").read_text())
    info = {
        **{k: s[k] for k in ("id", "title", "year", "event", "duration", "url", "sosumiURL", "topics", "platforms", "keywords")},
        "description": s.get("description"),
        "transcriptWords": s.get("transcriptWordCount"),
        "hls": (meta.get("media") or {}).get("hls"),
        "codeSnippets": len(meta.get("codeSnippets") or []),
        "resources": [{"title": r.get("title"), "url": r.get("sosumiURL") or r.get("url")} for r in meta.get("resources") or []],
        "files": {k: str(REPO / v) for k, v in (meta.get("files") or {}).items()},
    }
    if args.json:
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return
    for k, v in info.items():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            print(f"{k}:")
            for r in v:
                print(f"  - {r['title']}  {r['url']}")
        elif isinstance(v, dict):
            print(f"{k}:")
            for kk, vv in v.items():
                print(f"  {kk}: {vv}")
        else:
            print(f"{k}: {', '.join(v) if isinstance(v, list) else v}")


def cmd_topics(args):
    counts = {}
    for s in filter_sessions(load_catalog(), args):
        for t in s["topics"]:
            counts[t] = counts.get(t, 0) + 1
    for t, n in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"{n:5}  {t}")


def parse_ts(v):
    sec = 0.0
    for part in v.split(":"):
        sec = sec * 60 + float(part)
    return sec


def fetch(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read()


def pick_variant(master_url, height):
    """Highest variant with height <= requested; HEVC preferred on ties (1440p/4K are HEVC-only)."""
    text = fetch(master_url).decode()
    variants, attrs = [], None
    for line in text.splitlines():
        if line.startswith("#EXT-X-STREAM-INF:"):
            attrs = line
        elif attrs and line and not line.startswith("#"):
            res = re.search(r"RESOLUTION=\d+x(\d+)", attrs)
            bw = re.search(r"[^-]BANDWIDTH=(\d+)", attrs)
            variants.append((int(res.group(1)) if res else 0, int(bw.group(1)) if bw else 0,
                             "hvc1" in attrs, urljoin(master_url, line)))
            attrs = None
    if not variants:  # already a media playlist
        return master_url, 0
    fit = [v for v in variants if v[0] <= height] or [min(variants)]
    # identical BANDWIDTH tags exist (2160p_11600 vs 2160p_16800); the path's kbps suffix breaks the tie
    kbps = lambda v: int(m.group(1)) if (m := re.search(r"_(\d+)\.m3u8", v[3])) else 0
    best = max(fit, key=lambda v: (v[0], v[2], kbps(v), v[1]))
    return best[3], best[0]


def segments_for(media_url, start, end):
    """(init_url, [segment urls], first segment start) covering [start, end]."""
    init, t, out, first = None, 0.0, [], None
    dur = None
    for line in fetch(media_url).decode().splitlines():
        if line.startswith("#EXT-X-MAP:"):
            init = urljoin(media_url, re.search(r'URI="([^"]+)"', line).group(1))
        elif line.startswith("#EXTINF:"):
            dur = float(line[8:].split(",")[0])
        elif line and not line.startswith("#") and dur is not None:
            if t + dur > start and t < end:
                out.append(urljoin(media_url, line))
                first = t if first is None else first
            t += dur
            dur = None
    return init, out, first or 0.0


DOWNLOAD_DIRS = [
    Path("~/Library/Containers/developer.apple.wwdc-Release/Data/Library/Caches/com.apple.nsurlsessiond/Downloads/developer.apple.wwdc-Release").expanduser(),
    Path("~/Library/Containers/developer.apple.wwdc-Release/Data/Library/com.apple.UserManagedAssets.SKHMBD").expanduser(),
]


def local_streams(hls):
    """[(NetworkURL, stream dir)] of the complete streams of this session's .movpkg, if downloaded."""
    base = hls.rsplit("/", 1)[0] + "/"
    for d in DOWNLOAD_DIRS:
        for pkg in d.glob("*.movpkg") if d.exists() else []:
            boot = pkg / "boot.xml"
            if not boot.exists():
                continue
            streams = [(url, pkg / path) for url, path, done in
                       re.findall(r'<Stream ID="[^"]*" NetworkURL="([^"]+)" Path="([^"]+)">\s*<Complete>(\w+)', boot.read_text())
                       if url.startswith(base) and done == "YES"]
            if any("/hvc/" in url or "/avc/" in url for url, _ in streams):
                return streams
    return []


def local_video(streams, height):
    videos = [(int(m.group(1)), d) for url, d in streams if (m := re.search(r"/(?:hvc|avc)/(\d+)p_", url))]
    if not videos:
        return None
    fit = [v for v in videos if v[0] <= height] or [min(videos)]
    return max(fit)


def local_audio(streams):
    return next((d for url, d in streams if "/aac/" in url or "/audio" in url), None)


def audio_playlist(master_url):
    """URI of the default audio rendition in a master playlist."""
    text = fetch(master_url).decode()
    for line in text.splitlines():
        if line.startswith("#EXT-X-MEDIA:") and "TYPE=AUDIO" in line and (m := re.search(r'URI="([^"]+)"', line)):
            return urljoin(master_url, m.group(1))
    return None


def local_parts(stream_dir, start, end):
    info = (stream_dir / "StreamInfoBoot.xml").read_text()
    init = re.search(r'<ISEG [^>]*PATH="([^"]+)"', info).group(1)
    segs = [(float(t), float(d), p) for d, p, t in
            re.findall(r'<SEG Dur="([\d.]+)"[^>]*PATH="([^"]+)"[^>]*Tim="([\d.]+)"', info)]
    hit = sorted(x for x in segs if x[0] + x[1] > start and x[0] < end)
    if not hit:
        return [], 0.0
    return [(stream_dir / init).read_bytes()] + [(stream_dir / p).read_bytes() for _, _, p in hit], hit[0][0]


def remote_parts(media_url, start, end):
    init, segs, seg_start = segments_for(media_url, start, end)
    if not segs:
        return [], 0.0
    with ThreadPoolExecutor(8) as pool:
        return list(pool.map(fetch, ([init] if init else []) + segs)), seg_start


def resolve_source(args):
    """(session, video part getter, height, audio part getter or None)."""
    s = next((s for s in load_catalog() if s["id"] == args.id), None)
    if not s:
        sys.exit(f"unknown id: {args.id}")
    hls = (json.loads((REPO / s["path"] / "metadata.json").read_text()).get("media") or {}).get("hls")
    if not hls:
        sys.exit(f"{args.id} has no HLS stream")
    want_audio = getattr(args, "audio", False)
    streams = [] if args.remote else local_streams(hls)
    local = local_video(streams, args.res) if streams else None
    if local:
        height, vdir = local
        get_video = lambda a, b: local_parts(vdir, a, b)
        adir = local_audio(streams) if want_audio else None
        get_audio = (lambda a, b: local_parts(adir, a, b)) if adir else None
        print(f"source: local {height}p  {vdir.parent.name}")
    else:
        media_url, height = pick_variant(hls, args.res)
        get_video = lambda a, b: remote_parts(media_url, a, b)
        aurl = audio_playlist(hls) if want_audio else None
        get_audio = (lambda a, b: remote_parts(aurl, a, b)) if aurl else None
        print(f"source: remote {height}p  {media_url}")
    if want_audio and not get_audio:
        print("no audio stream found; writing video only", file=sys.stderr)
    return s, get_video, height, get_audio


def cmd_frames(args):
    """Use the Developer app's local download if present, else fetch only the covering HLS segments."""
    s, get_parts, height, _ = resolve_source(args)

    for spec in args.ranges:
        a, _, b = spec.partition("-")
        start = parse_ts(a)
        end = parse_ts(b) if b else start + 1 / 30  # single timestamp = one frame
        parts, seg_start = get_parts(start, end)
        if not parts:
            print(f"{spec}: out of range", file=sys.stderr)
            continue
        out = Path(args.out).expanduser() / args.id / f"{fmt_time(start).replace(':', '')}-{fmt_time(end).replace(':', '')}"
        out.mkdir(parents=True, exist_ok=True)
        clip = out / "source.mp4"
        clip.write_bytes(b"".join(parts))

        ext = args.format
        vf = ["showinfo"] + ([f"fps={args.fps}"] if args.fps else [])
        if args.fps:
            vf.reverse()
        cmd = ["ffmpeg", "-hide_banner", "-y", "-hwaccel", "videotoolbox",
               "-ss", f"{start - seg_start:.3f}", "-i", str(clip), "-t", f"{end - start:.3f}",
               "-map", "0:v:0", "-vf", ",".join(vf), "-fps_mode", "passthrough"]
        cmd += ["-q:v", "2"] if ext == "jpg" else ["-compression_level", "1"]
        cmd += [str(out / f"tmp_%05d.{ext}")]
        for old in out.glob(f"t*.{ext}"):
            old.unlink()
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode:
            sys.exit(proc.stderr[-2000:])
        pts = [float(m) for m in re.findall(r"pts_time:([\d.]+)", proc.stderr)]
        frames = sorted(out.glob(f"tmp_*.{ext}"))
        index = []
        for i, f in enumerate(frames):
            t = start + (pts[i] if i < len(pts) else i / 30)
            name = f"t{int(t) // 60:02d}m{t % 60:06.3f}s.{ext}"
            f.rename(out / name)
            index.append({"file": name, "time": round(t, 3), "url": time_url(s, t)})
        (out / "frames.json").write_text(json.dumps(index, indent=2))
        if not args.keep_video:
            clip.unlink()
        print(f"{spec}: {len(index)} frames -> {out}")


BITRATE = {2160: "40M", 1440: "20M", 1080: "12M", 720: "6M", 540: "3M", 360: "1500k"}


def cmd_clip(args):
    """Cut a trimmed mp4 for each range, re-encoded so the cut is frame-accurate."""
    s, get_video, height, get_audio = resolve_source(args)
    out_dir = Path(args.out).expanduser() / args.id
    out_dir.mkdir(parents=True, exist_ok=True)

    for spec in args.ranges:
        a, _, b = spec.partition("-")
        start, end = parse_ts(a), parse_ts(b)
        if end <= start:
            sys.exit(f"{spec}: end must be after start")
        vparts, vstart = get_video(start, end)
        if not vparts:
            print(f"{spec}: out of range", file=sys.stderr)
            continue
        tmp = out_dir / ".src"
        tmp.mkdir(exist_ok=True)
        (tmp / "v.mp4").write_bytes(b"".join(vparts))
        cmd = ["ffmpeg", "-hide_banner", "-v", "error", "-y", "-hwaccel", "videotoolbox",
               "-ss", f"{start - vstart:.3f}", "-i", str(tmp / "v.mp4")]
        maps = ["-map", "0:v:0"]
        if get_audio:
            aparts, astart = get_audio(start, end)
            if aparts:
                (tmp / "a.mp4").write_bytes(b"".join(aparts))
                cmd += ["-ss", f"{start - astart:.3f}", "-i", str(tmp / "a.mp4")]
                maps += ["-map", "1:a:0", "-c:a", "aac", "-b:a", "192k"]
        out = out_dir / f"{fmt_time(start).replace(':', '')}-{fmt_time(end).replace(':', '')}.mp4"
        cmd += ["-t", f"{end - start:.3f}", *maps,
                "-c:v", args.vcodec, "-b:v", args.bitrate or BITRATE.get(height, "12M"),
                "-tag:v", "hvc1" if "hevc" in args.vcodec else "avc1",
                "-movflags", "+faststart", str(out)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        for f in tmp.iterdir():
            f.unlink()
        tmp.rmdir()
        if proc.returncode:
            sys.exit(proc.stderr[-2000:])
        size = out.stat().st_size / 1e6
        print(f"{spec}: {end - start:.2f}s {height}p {size:.1f}MB -> {out}")


def cmd_update(args):
    subprocess.run(["git", "-C", str(REPO), "pull", "--ff-only"], check=True)


def main():
    filters = argparse.ArgumentParser(add_help=False)
    filters.add_argument("--year", help="2025 or 2023-2026")
    filters.add_argument("--event", action="append", help="wwdc2025, tech-talks, meet-with-apple (repeatable)")
    filters.add_argument("--topic", action="append", help="substring of topic, e.g. swiftui (repeatable, OR)")
    filters.add_argument("--platform", action="append", help="iOS, visionOS... (repeatable, OR)")
    filters.add_argument("--json", action="store_true")

    matching = argparse.ArgumentParser(add_help=False, parents=[filters])
    matching.add_argument("-e", "--regex", action="store_true", help="terms are regexes")
    matching.add_argument("-s", "--case", action="store_true", help="case sensitive")
    matching.add_argument("-n", "--limit", type=int, default=20)

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("search", parents=[matching], help="rank sessions (no terms = list filtered)")
    sp.add_argument("terms", nargs="*", help="all terms must match (AND)")
    sp.add_argument("--no-transcript", action="store_true", help="metadata only (fast)")
    sp.set_defaults(func=cmd_search)

    gp = sub.add_parser("grep", parents=[matching], help="transcript lines with timestamps")
    gp.add_argument("terms", nargs="+", help="all terms must match (AND)")
    gp.add_argument("-C", "--context", type=int, default=0, help="neighbor segments to include")
    gp.add_argument("-m", "--max-per-session", type=int, default=5)
    gp.set_defaults(func=cmd_grep)

    shp = sub.add_parser("show", help="one session")
    shp.add_argument("id")
    shp.add_argument("--json", action="store_true")
    shp.set_defaults(func=cmd_show)

    fp = sub.add_parser("frames", help="extract frames for time ranges")
    fp.add_argument("id")
    fp.add_argument("ranges", nargs="+", help="2:00-2:05, 1:02:03.5-1:02:04, or a single timestamp")
    fp.add_argument("--res", type=int, default=2160, help="max height: 2160/1440/1080/720 (default 2160)")
    fp.add_argument("--fps", type=float, help="sample rate; default every frame")
    fp.add_argument("--format", choices=["jpg", "png"], default="jpg")
    fp.add_argument("--out", default="~/media/reference/wwdc/frames")
    fp.add_argument("--remote", action="store_true", help="ignore local Developer app downloads")
    fp.add_argument("--keep-video", action="store_true", help="keep downloaded segments as source.mp4")
    fp.set_defaults(func=cmd_frames)

    cp = sub.add_parser("clip", help="cut trimmed mp4 clips (video+audio)")
    cp.add_argument("id")
    cp.add_argument("ranges", nargs="+", help="00:27-00:37 (start-end)")
    cp.add_argument("--res", type=int, default=2160, help="max height (default 2160)")
    cp.add_argument("--vcodec", default="hevc_videotoolbox", choices=["hevc_videotoolbox", "h264_videotoolbox"])
    cp.add_argument("--bitrate", help="override video bitrate, e.g. 20M")
    cp.add_argument("--no-audio", dest="audio", action="store_false", help="video only")
    cp.add_argument("--out", default="~/media/reference/wwdc/clips")
    cp.add_argument("--remote", action="store_true", help="ignore local Developer app downloads")
    cp.set_defaults(func=cmd_clip, audio=True)

    sub.add_parser("topics", parents=[filters], help="topic counts").set_defaults(func=cmd_topics)
    sub.add_parser("update", help="git pull data repo").set_defaults(func=cmd_update)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

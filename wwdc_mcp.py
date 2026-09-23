#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["mcp>=2.2,<3"]
# ///
"""WWDC sessions over MCP: find the moment in a talk, open it in the Developer app.

  ./wwdc_mcp.py                 serve on http://127.0.0.1:6791/mcp
  WWDC_MCP_PORT=6800 ./wwdc_mcp.py

Search is wwdc.py's (same directory), called with --json; transcripts come from
the local guitaripod/wwdc-sessions clone it points at. Opening goes through
`open -a Developer <session URL>?time=N` — a plain `open` of the URL lands in the
default browser instead. The Developer app then shows the session ready to
start at that second; playing is the person's (or a separate AX control's) call.
"""

from __future__ import annotations

import base64
import json
import os
import plistlib
import subprocess
import tempfile
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.types import Icon, ToolAnnotations

HERE = Path(__file__).resolve().parent
WWDC = HERE / "wwdc.py"
DEVELOPER_APP = Path("/Applications/Developer.app")
PORT = int(os.environ.get("WWDC_MCP_PORT", "6791"))

# Nothing here changes anything: searching reads files, and opening only shows
# a page. `open_at` does bring the Developer app forward — like turning to a
# page, not like editing one.
LOOKING = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)

INSTRUCTIONS = """\
Apple WWDC sessions (2014–2026, Tech Talks, Meet with Apple): 1,600+ talks with timecoded English transcripts, searched locally.

To find a moment and show it:
1. `search` to find candidate sessions (ranked; several words are ANDed). Filter by year / event / topic when the user implies them.
2. `grep` for the exact lines and their start times, or `transcript` to read the talk around a time and confirm it says what the user asked about. A hit on a keyword is not yet the answer — read the lines around it.
3. `open_at` with the session id and the second where the relevant passage starts (a few seconds before the first line is fine). It opens the Developer app on that session, ready to start there; it does not press play.

Session ids look like `wwdc2025-219`. Transcripts are English; coverage before 2019 is sparse. Times are seconds.
"""


def wwdc(*args: str) -> object:
    """Run wwdc.py with --json and return what it printed."""
    out = subprocess.run([str(WWDC), *args, "--json"], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError((out.stderr or out.stdout).strip()[:500] or f"wwdc.py {args[0]} failed")
    return json.loads(out.stdout)


def filters(year: str | None, event: str | None, topic: str | None) -> list[str]:
    args: list[str] = []
    if year:
        args += ["--year", year]
    if event:
        args += ["--event", event]
    if topic:
        args += ["--topic", topic]
    return args


def session(session_id: str) -> dict:
    found = wwdc("show", session_id)
    if not isinstance(found, dict) or "url" not in found:
        raise ValueError(f"no session {session_id}")
    return found


def clock(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def app_icon() -> list[Icon]:
    """The Developer app's own icon, so the host shows what this opens."""
    try:
        info = plistlib.loads((DEVELOPER_APP / "Contents/Info.plist").read_bytes())
        name = info.get("CFBundleIconFile", "AppIcon")
        icns = DEVELOPER_APP / "Contents/Resources" / (name if name.endswith(".icns") else f"{name}.icns")
        with tempfile.TemporaryDirectory() as tmp:
            png = Path(tmp) / "icon.png"
            subprocess.run(["sips", "-s", "format", "png", "-Z", "256", str(icns), "--out", str(png)],
                           capture_output=True, check=True, timeout=20)
            data = base64.b64encode(png.read_bytes()).decode()
        return [Icon(src=f"data:image/png;base64,{data}", mime_type="image/png", sizes=["256x256"])]
    except Exception:
        return []


server = MCPServer(name="wwdc", title="WWDC", version="0.1.0", instructions=INSTRUCTIONS, icons=app_icon())
last_opened: dict | None = None


@server.tool(annotations=LOOKING)
def status() -> dict:
    """Where the data comes from, and the last session opened in the Developer app."""
    return {
        "dataRepo": os.environ.get("WWDC_REPO", str(Path.home() / "ghq/github.com/guitaripod/wwdc-sessions")),
        "developerApp": DEVELOPER_APP.exists(),
        "lastOpened": last_opened,
    }


@server.tool(annotations=LOOKING)
def search(query: str = "", year: str | None = None, event: str | None = None, topic: str | None = None,
           limit: int = 10) -> object:
    """Rank sessions by relevance to `query` (several words must all appear). With no query, list the sessions the filters match.

    year: "2025" or "2023-2026". event: e.g. "wwdc2025", "tech-talks". topic: substring, e.g. "swiftui".
    Each result has the session id, title, year, duration, first hit time and a link.
    """
    args = ["search", *([query] if query.strip() else []), *filters(year, event, topic), "-n", str(max(1, min(limit, 50)))]
    return wwdc(*args)


@server.tool(annotations=LOOKING)
def grep(pattern: str, session_id: str | None = None, year: str | None = None, event: str | None = None,
         topic: str | None = None, limit: int = 20) -> object:
    """Transcript lines that say `pattern` (case-insensitive substring), each with its start second.

    Matches within one caption segment, so a phrase split across two segments can be missed — then search, or grep for fewer words.
    Pass session_id to look inside one talk only.
    """
    args = ["grep", pattern, *filters(year, event, topic), "-n", str(max(1, min(limit, 100)))]
    hits = wwdc(*args)
    if session_id and isinstance(hits, list):
        hits = [h for h in hits if h.get("id") == session_id]
    return hits


@server.tool(annotations=LOOKING)
def show(session_id: str) -> dict:
    """One session's metadata: title, event, duration, topics, keywords, description, resources and link."""
    return session(session_id)


@server.tool(annotations=LOOKING)
def transcript(session_id: str, start: float = 0, end: float | None = None) -> dict:
    """The talk's words between `start` and `end` seconds (default: two minutes from start), one line per caption with its start time."""
    s = session(session_id)
    data = json.loads(Path(s["files"]["transcriptJSON"]).read_text())
    stop = end if end is not None else start + 120
    lines = [f"[{clock(seg['start'])}] {seg['text']}" for seg in data.get("segments", [])
             if start <= seg["start"] <= stop]
    return {"id": session_id, "title": s.get("title"), "from": clock(start), "to": clock(stop), "lines": lines}


@server.tool(annotations=LOOKING)
def open_at(session_id: str, seconds: float = 0) -> dict:
    """Open the session in the Developer app, ready to start at `seconds`. It does not press play; the user does."""
    global last_opened
    s = session(session_id)
    url = f"{s['url'].rstrip('/')}/?time={int(max(0, seconds))}"
    subprocess.run(["open", "-a", "Developer", url], check=True, timeout=20)
    last_opened = {"id": session_id, "title": s.get("title"), "seconds": int(seconds), "url": url}
    return {"opened": s.get("title"), "at": clock(seconds), "url": url,
            "note": "The Developer app now shows this session, ready to start here. Playing is the user's to press."}


if __name__ == "__main__":
    import anyio

    anyio.run(lambda: server.run_streamable_http_async(host="127.0.0.1", port=PORT, stateless_http=True,
                                                       json_response=True))

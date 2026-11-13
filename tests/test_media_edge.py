"""Real-courseware media test with Microsoft Edge (Playwright msedge channel).

Uses the public WE Learn courseware host for the iframe and a synthetic outer
StudyCourse page; verifies muted autoplay starts and media completion allows
the native NextSCO click. No account or platform write is involved.
"""
from __future__ import annotations

import base64
import io
import json
import sys
import wave
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).parent))
import test_integration as ti  # noqa: E402

SCO = "4/3-1"
FAKE_MEDIA_URL = "https://centercourseware.sflep.com/fake-media.html"


def silent_wav(seconds=0.6):
    buf = io.BytesIO()
    w = wave.open(buf, "wb")
    w.setnchannels(1)
    w.setsampwidth(1)
    w.setframerate(8000)
    w.writeframes(b"\x80" * int(8000 * seconds))
    w.close()
    return base64.b64encode(buf.getvalue()).decode()


_WAV = silent_wav()
FAKE_MEDIA_HTML = ("<!DOCTYPE html><html><body>"
                   "<audio src=\"data:audio/wav;base64," + _WAV + "\"></audio>"
                   "<div id=\"shadowHost\"></div>"
                   "<script>const r=document.getElementById('shadowHost').attachShadow({mode:'open'});"
                   "r.innerHTML='<audio src=\"data:audio/wav;base64," + _WAV + "\"></audio>';</script>"
                   "</body></html>")
CONFIG_REAL = ("try { localStorage.setItem('wl_autopager_cfg_v7', JSON.stringify({sectionPolicy:1,enabled:true,minDwell:300,jitterMin:0,jitterMax:0,"
               "maxPages:10,mode:'duration',autoAnswer:false,minAccuracy:100,muteMedia:true})); } catch (e) {}")
CONFIG_END = ("try { localStorage.setItem('wl_autopager_cfg_v7', JSON.stringify({sectionPolicy:1,enabled:true,minDwell:1,jitterMin:0,jitterMax:0,"
              "maxPages:10,mode:'duration',autoAnswer:false,minAccuracy:100,muteMedia:true})); } catch (e) {}")
MEDIA_EVENTS = """window.__MEDIA_LOG__ = [];
for (const type of ['play', 'ended']) document.addEventListener(type, event => {
  const el = event.target;
  if (el.matches && el.matches('audio,video')) window.__MEDIA_LOG__.push({
    type, time: el.currentTime, duration: el.duration, source: el.currentSrc
  });
}, true);"""


def main() -> int:
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="msedge", headless=True)
            engine = "Edge " + browser.version
        except Exception:
            browser = p.chromium.launch(headless=True)
            engine = "Chromium " + browser.version
        ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.add_init_script(ti.STUB)
        page.add_init_script(CONFIG_REAL)
        page.add_init_script(MEDIA_EVENTS)
        page.add_init_script(ti.SCRIPT)
        page.route("https://welearn.sflep.com/Student/StudyCourse.aspx*",
                   lambda route: route.fulfill(status=200, content_type="text/html; charset=utf-8",
                                               body=ti.TOP_HTML.replace("__SCO_URL__", ti.BASE + "index.html#/" + SCO)))
        page.goto("https://welearn.sflep.com/Student/StudyCourse.aspx?cid=edge-media", wait_until="domcontentloaded", timeout=90000)
        page.wait_for_selector("#wl-ap-hud", timeout=30000)

        frame = None
        for _ in range(120):
            frame = next((f for f in page.frames if "centercourseware" in (f.url or "")), None)
            if frame:
                try:
                    if frame.evaluate("() => document.querySelectorAll('audio,video').length > 0"):
                        break
                except Exception:
                    pass
            page.wait_for_timeout(500)
        if not frame:
            raise RuntimeError("courseware frame with media not found")

        frame.wait_for_function(
            "() => Array.from(document.querySelectorAll('audio,video')).some(e => !e.paused && e.currentTime > 0.3)",
            timeout=45000)
        page.wait_for_timeout(1500)
        state = frame.evaluate("""() => Array.from(document.querySelectorAll('audio,video')).map(e => ({
            tag: e.tagName, paused: e.paused, ended: e.ended, muted: e.muted,
            time: Number(e.currentTime.toFixed(2)), duration: Number((e.duration || 0).toFixed(2))
        }))""")
        all_muted = all(m["muted"] for m in state)
        any_playing = any(not m["paused"] and m["time"] > 0 for m in state)

        out = Path(__file__).parent / "artifacts"
        out.mkdir(exist_ok=True)
        page.screenshot(path=str(out / "edge-media.png"), full_page=False)

        # 切换“自动静音”应立即作用于正在播放的媒体。
        page.uncheck("#wl-ap-hud .wl-ap-mute")
        page.wait_for_timeout(1600)
        muted_off = frame.evaluate("() => Array.from(document.querySelectorAll('audio,video')).every(e => !e.muted)")
        page.check("#wl-ap-hud .wl-ap-mute")
        page.wait_for_timeout(1600)
        muted_on = frame.evaluate("() => Array.from(document.querySelectorAll('audio,video')).every(e => e.muted)")

        page.wait_for_timeout(2000)
        state2 = frame.evaluate("""() => Array.from(document.querySelectorAll('audio,video')).map(e => ({
            tag: e.tagName, paused: e.paused, ended: e.ended, muted: e.muted,
            time: Number(e.currentTime.toFixed(2)), duration: Number((e.duration || 0).toFixed(2))
        }))""")
        advanced = any(state2[i]["time"] > state[i]["time"] + 0.5 for i in range(min(len(state), len(state2))))
        hud = page.inner_text("#wl-ap-hud")

        # Wait for the real 39.71s audio to finish naturally. The courseware
        # rewinds it in its ended handler, which must not trigger autoplay again.
        frame.wait_for_function("() => window.__MEDIA_LOG__.some(e => e.type === 'ended')", timeout=75000)
        page.wait_for_timeout(5500)  # Longer than the 4s playback retry window.
        events = frame.evaluate("() => window.__MEDIA_LOG__")
        finished = frame.evaluate("""() => Array.from(document.querySelectorAll('audio,video')).map(e => ({
            paused: e.paused, ended: e.ended, time: e.currentTime, duration: e.duration
        }))""")
        finished_once = (sum(e["type"] == "play" for e in events) == 1
                         and sum(e["type"] == "ended" for e in events) == 1)
        rewound = all(m["paused"] and not m["ended"] and m["time"] == 0 for m in finished)
        dwell_held = page.evaluate("() => window.__NEXT__") == 0
        page.evaluate("() => { window.__WLAP_ENGINE__.config.minDwell = 1; }")
        page.wait_for_function("() => window.__NEXT__ === 1", timeout=15000)

        entry = {
            "engine": engine,
            "media": state,
            "media_after_2s": state2,
            "all_muted": all_muted,
            "any_playing": any_playing,
            "time_advanced": advanced,
            "mute_toggle_immediate": muted_off and muted_on,
            "hud_media_playing": "播放中" in hud,
            "media_events": events,
            "media_after_natural_end": finished,
            "played_once": finished_once,
            "rewound_by_courseware": rewound,
            "held_until_min_dwell": dwell_held,
            "next_clicks": page.evaluate("() => window.__NEXT__ || 0"),
            "page_errors": errors[:5],
        }
        ok = (all_muted and any_playing and advanced and muted_off and muted_on and finished_once
              and rewound and dwell_held and entry["next_clicks"] == 1 and not entry["page_errors"])
        print(json.dumps(entry, ensure_ascii=False, indent=1))
        page.close()

        # 合成短音频：验证静音自动播放到结束后能触发原生 NextSCO。
        ctx.route(FAKE_MEDIA_URL, lambda route: route.fulfill(status=200, content_type="text/html; charset=utf-8", body=FAKE_MEDIA_HTML))
        page2 = ctx.new_page()
        page2.add_init_script(ti.STUB)
        page2.add_init_script(CONFIG_END)
        page2.add_init_script(ti.SCRIPT)
        page2.route("https://welearn.sflep.com/Student/StudyCourse.aspx*",
                    lambda route: route.fulfill(status=200, content_type="text/html; charset=utf-8",
                                                body=ti.TOP_HTML.replace("__SCO_URL__", FAKE_MEDIA_URL)))
        page2.goto("https://welearn.sflep.com/Student/StudyCourse.aspx?cid=edge-media-end", wait_until="domcontentloaded", timeout=90000)
        page2.wait_for_selector("#wl-ap-hud", timeout=30000)
        frame2 = None
        for _ in range(60):
            frame2 = next((f for f in page2.frames if "fake-media.html" in (f.url or "")), None)
            if frame2:
                try:
                    if frame2.evaluate("() => !!document.querySelector('audio')"):
                        break
                except Exception:
                    pass
            page2.wait_for_timeout(300)
        if not frame2:
            raise RuntimeError("fake media frame not found")
        frame2.wait_for_function("() => { const a = document.querySelector('audio'); return a && a.ended; }", timeout=30000)
        page2.wait_for_function("() => (window.__NEXT__ || 0) >= 1", timeout=30000)
        media_count = frame2.evaluate("() => window.__WLAP_ENGINE__.mediaCount()")
        media_state = frame2.evaluate("() => window.__WLAP_ENGINE__.mediaState()")
        entry2 = {
            "media_count": media_count,
            "media_state": media_state,
            "next_clicks": page2.evaluate("() => window.__NEXT__ || 0"),
            "page_errors": [],
        }
        ok2 = (media_count == 2 and all(m["ended"] and m["muted"] for m in media_state)
               and entry2["next_clicks"] >= 1)
        print(json.dumps(entry2, ensure_ascii=False, indent=1))
        ok = ok and ok2
        browser.close()
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

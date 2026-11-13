"""Offline regression: a player's ended handler rewinds before the next tick.

Real WAV playback, ordinary/shadow media, both iframe origins, no account.
Run: python tests/test_media_replay.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).parent))
import test_integration as ti
from test_media_edge import silent_wav

CONFIG = """localStorage.setItem('wl_autopager_cfg_v7', JSON.stringify({
  enabled:true, minDwell:6, jitterMin:0, jitterMax:0, maxPages:10,
  mode:'duration', autoAnswer:false, muteMedia:true
}));"""
HTML = """<!doctype html><html><body><et-item><et-media><audio></audio></et-media></et-item><div id="shadow"></div>
<script>
const item = {id:'media-replay', type:'subjective', submit() {}, isSubmitted:false,
  isEndTab:true, scormInfo:{progressMeasure:'0', score:{scaled:'0'}}};
const root = {item};
const controller = {};
window.angular = {element(el) { return {
  injector() { return {get() { return root; }}; },
  controller(name) { return el.localName === 'et-media' && name === 'etMedia' ? controller : null; }
}; }};
const shadow = document.getElementById('shadow').attachShadow({mode:'open'});
shadow.innerHTML = '<audio></audio>';
window.media = [document.querySelector('audio'), shadow.querySelector('audio')];
window.resetMedia = (el, index) => {
  el.src = 'data:audio/wav;base64,__WAV__';
  el.plays = 0; el.ends = 0;
  const nativePlay = el.play;
  el.play = function() { this.plays++; return nativePlay.call(this); };
  // Matches etAudio's native ended callback: ended becomes false after rewind.
  el.addEventListener('ended', () => { el.ends++; el.currentTime = 0; });
};
window.media.forEach(window.resetMedia);
</script></body></html>""".replace("__WAV__", silent_wav(0.6))


def state(frame):
    return frame.evaluate("() => window.media.map(e => ({plays:e.plays, ends:e.ends, "
                          "paused:e.paused, ended:e.ended, time:e.currentTime}))")


def main() -> None:
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        for same_origin, lifecycle in [(False, False), (True, False), (False, True), (True, True)]:
            ctx = browser.new_context()
            page = ctx.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.add_init_script(CONFIG.replace('minDwell:6', 'minDwell:300') if lifecycle else CONFIG)
            page.add_init_script(ti.SCRIPT)
            host = "welearn.sflep.com" if same_origin else "centercourseware.sflep.com"
            child_url = f"https://{host}/media-replay.html"
            ctx.route(child_url + "*", lambda route: route.fulfill(content_type="text/html", body=HTML))
            ctx.route("https://welearn.sflep.com/Student/StudyCourse.aspx*", lambda route:
                      route.fulfill(content_type="text/html", body=ti.TOP_HTML.replace("__SCO_URL__", child_url)))
            page.goto("https://welearn.sflep.com/Student/StudyCourse.aspx?cid=media-replay")
            page.wait_for_selector("#wl-ap-hud")
            frame = page.frame(url=child_url)
            assert frame is not None
            frame.wait_for_function("() => window.media.every(e => e.ends >= 1)")
            if lifecycle:
                # Stay on the section so the parent keeps granting autoplay.
                page.wait_for_timeout(5000)
            else:
                page.wait_for_function("() => window.__NEXT__ >= 1", timeout=12000)
            media = state(frame)
            assert all(e["plays"] == 1 and e["ends"] == 1 and e["paused"] and not e["ended"] for e in media), media
            assert frame.evaluate("() => window.__WLAP_ENGINE__.analyze().done") == 1
            assert page.evaluate("() => window.__NEXT__") == (0 if lifecycle else 1)
            assert not errors, errors
            results.append({"case": "no-repeat-during-dwell" if lifecycle else "rewind-after-ended", "same_origin": same_origin,
                            "media": media, "next_clicks": 0 if lifecycle else 1, "pass": True})

            if lifecycle:
                # Reusing a finished element with a new URL must require playback.
                frame.evaluate("() => { window.media[0].src += '#replacement'; }")
                assert frame.evaluate("() => window.__WLAP_ENGINE__.analyze().done") == 0
                frame.wait_for_function("() => window.media[0].ends >= 2", timeout=10000)
                media = state(frame)
                assert media[0]["plays"] == 2 and media[1]["plays"] == 1, media
                results.append({"case": "source-change-replays-only-new-source", "same_origin": same_origin, "pass": True})

                # Loading the same source again starts a new media lifecycle.
                frame.evaluate("() => window.media[0].load()")
                frame.wait_for_function("() => window.media[0].ends >= 3", timeout=10000)
                media = state(frame)
                assert media[0]["plays"] == 3 and media[1]["plays"] == 1, media
                results.append({"case": "same-source-reload", "same_origin": same_origin, "pass": True})

                # An SPA route may reuse both the element and its original source.
                frame.evaluate("() => { location.hash = '/next-section'; }")
                assert frame.evaluate("() => window.__WLAP_ENGINE__.analyze().done") == 0
                frame.wait_for_function("() => window.media[0].ends >= 4 && window.media[1].ends >= 2", timeout=10000)
                media = state(frame)
                assert media[0]["plays"] == 4 and media[1]["plays"] == 2, media
                assert frame.evaluate("() => window.__WLAP_ENGINE__.analyze().done") == 1
                assert not errors, errors
                results.append({"case": "route-change-clears-completion", "same_origin": same_origin, "pass": True})
            ctx.close()
        browser.close()
    for result in results:
        print(json.dumps(result))
    print(f"PASS {len(results)}/{len(results)}")


if __name__ == "__main__":
    main()

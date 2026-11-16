"""Offline browser regressions for native next-section acknowledgement.

All pages and progress reports are local fixtures; no learning account or API.
Run: python tests/test_navigation_confirm.py [--script PATH]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

import test_integration as ti

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).parent / "artifacts" / "navigation-confirm"
CHILD_URL = "https://centercourseware.sflep.com/navigation-player.html#/101"
CHILD_HTML = """<!doctype html><html><body>Navigation fixture<script>
window.__grant = false;
window.__doc = Math.random().toString(36).slice(2);
window.__submitted = false;
window.__send = (override = {}) => parent.postMessage({protocol:'wl-ap-v4', type:'status', warning:'',
  media:{count:0,done:true,ready:true,playing:false,blocked:false},
  progress:{page:'fixture', href:location.pathname + location.hash, docId:window.__doc,
    completion:window.__submitted ? 100 : 55, accuracy:100, total:1, done:0,
    manual:0, voice:0, submitted:window.__submitted, type:'objective', ...override}}, '*');
addEventListener('message', e => {
  if (e.data.protocol === 'wl-ap-v4' && e.data.type === 'config') window.__grant = e.data.allow;
});
setInterval(() => { if (!window.__silent) window.__send(); }, 250);
</script></body></html>"""


def main() -> int:
    args = argparse.ArgumentParser()
    args.add_argument("--script", type=Path, default=ROOT / "welearn-autopager.user.js")
    args = args.parse_args()
    script = args.script.read_text(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    scenarios = {
        "src-load-stale-catalog": ("document.getElementById('contentFrame').src = '__NEW__';", True),
        "spa-route-stale-catalog": ("document.getElementById('contentFrame').contentWindow.postMessage('move', '*');", True),
        "normal-catalog-and-src": ("setCurrent(102); document.getElementById('contentFrame').src = '__NEW__';", True),
        "catalog-on-child-link": ("setCurrent(102); document.getElementById('contentFrame').src = '__NEW__';", True),
        "catalog-only-no-navigation": ("setCurrent(102);", False),
        "no-op-old-reports": ("", False),
        "same-src-reload": ("document.getElementById('contentFrame').src += '';", False),
        "late-first-report-no-op": ("", False),
        "first-report-after-new-src": ("document.getElementById('contentFrame').src = '__NEW__';", True),
        "replacement-frame": ("const old = document.getElementById('contentFrame'); const f = old.cloneNode(); f.src = '__NEW__'; old.replaceWith(f);", True),
        "old-report-after-new-load": ("document.getElementById('contentFrame').src = '__NEW__';", True),
        "manual-back-with-stale-catalog": ("document.getElementById('contentFrame').src = '__NEW__';", True),
    }
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for name, (navigate, expected) in scenarios.items():
            ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
            page = ctx.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.clock.install()
            page.add_init_script("if (window.top === window) { localStorage.clear(); sessionStorage.clear(); "
                                 "localStorage.setItem('wl_autopager_cfg_v7', JSON.stringify({sectionPolicy:1,enabled:true,"
                                 "minDwell:300,jitterMin:0,jitterMax:0,mode:'duration',autoAnswer:false})); }")
            page.add_init_script("if (window.top === window) {\n" + script + "\n}")
            child_html = CHILD_HTML.replace("setInterval(() =>", "addEventListener('message', e => { if (e.data === 'move') { location.hash = '/102'; window.__send(); } });\nsetInterval(() =>")
            if "first-report" in name:
                child_html = child_html.replace("window.__grant = false;", "window.__grant = false; window.__silent = location.hash === '#/101';")
            if name == "old-report-after-new-load":
                child_html = child_html.replace("window.__grant = false;", "window.__grant = false; window.__silent = location.hash === '#/102';")
            ctx.route("https://centercourseware.sflep.com/navigation-player.html*",
                      lambda route: route.fulfill(content_type="text/html", body=child_html))
            top = ti.TOP_HTML_MULTI.replace("__SCO_URL__", CHILD_URL)
            if name == "catalog-on-child-link":
                top = top.replace(' courseware_current', '').replace('onclick="SelectSCO(101);', 'class="courseware_current" onclick="SelectSCO(101);')
                top = top.replace("document.getElementById('liSCO_' + id).classList.add('courseware_current');",
                                  "document.querySelectorAll('.courseware_current').forEach(el => el.classList.remove('courseware_current')); document.querySelector('#liSCO_' + id + ' a').classList.add('courseware_current');")
            start = top.index("  function NextSCO() {")
            end = top.index("</script>", start)
            # Subsequent calls are counted but intentionally do not navigate.
            top = top[:start] + "function NextSCO() { window.__NEXT__++; if (window.__NEXT__ === 1) { " + navigate.replace("__NEW__", CHILD_URL.replace("#/101", "?section=102#/102")) + " } }\n" + top[end:]
            ctx.route("https://welearn.sflep.com/Student/StudyCourse.aspx*",
                      lambda route: route.fulfill(content_type="text/html", body=top))
            url_sco = "999" if name == "catalog-on-child-link" else "101"
            page.goto("https://welearn.sflep.com/Student/StudyCourse.aspx?cid=" + name + "&sco=" + url_sco)
            page.wait_for_selector("#wl-ap-hud")
            page.clock.run_for(1600)
            old_child = next(f for f in page.frames if "navigation-player" in f.url)
            old_report = old_child.evaluate("() => ({docId:window.__doc, href:location.pathname + location.hash, completion:100, submitted:true, studySeconds:1800})")
            page.click("#wl-ap-hud [data-act='next']")
            page.wait_for_timeout(250)
            page.clock.run_for(2200)
            child = next(f for f in page.frames if "navigation-player" in f.url)
            stale_rejected = True
            if name == "old-report-after-new-load":
                child.evaluate("p => window.__send(p)", old_report)
                page.clock.run_for(1000)
                stale_rejected = ("完成度：100%" not in page.inner_text("#wl-ap-hud") and
                                  not child.evaluate("() => window.__grant") and
                                  not page.evaluate("() => Object.keys(JSON.parse(localStorage.getItem('wl_ap_records_v32') || '{}')).length"))
            if name == "late-first-report-no-op":
                child.evaluate("() => { window.__silent = false; window.__send(); }")
            if expected:
                child.evaluate("() => { window.__silent = false; window.__submitted = true; window.__send(); }")
            page.clock.run_for(31000)
            hud = page.inner_text("#wl-ap-hud")
            records = page.evaluate("() => JSON.parse(localStorage.getItem('wl_ap_records_v32') || '{}')")
            grant = child.evaluate("() => window.__grant")
            clicks = page.evaluate("() => window.__NEXT__")
            timed_out = "30秒内未确认课件加载" in hud
            recorded_next = any(k.endswith("|102") for k in records)
            passed = (stale_rejected and not errors and clicks == 1 and
                      ((not timed_out and grant and recorded_next and len(records) == 1) if expected
                       else (timed_out and not grant and not records)))
            if name in ("src-load-stale-catalog", "no-op-old-reports"):
                page.screenshot(path=str(OUT / (name + ".png")))
            if not expected:
                # Continuing after a timeout must never issue another click or
                # grant the old page permission while still awaiting evidence.
                page.click("#wl-ap-hud [data-act='resume']")
                page.clock.run_for(31000)
                passed = (passed and page.evaluate("() => window.__NEXT__") == 1 and
                          not child.evaluate("() => window.__grant") and
                          "30秒内未确认课件加载" in page.inner_text("#wl-ap-hud"))
            if name == "no-op-old-reports":
                # A genuinely delayed load is recognized, but an explicit
                # timeout pause persists until the user chooses to continue.
                page.evaluate("url => document.getElementById('contentFrame').src = url",
                              CHILD_URL.replace("#/101", "?section=102#/102"))
                page.wait_for_timeout(250)
                page.clock.run_for(2200)
                recovered = next(f for f in page.frames if "navigation-player" in f.url)
                passed = passed and not recovered.evaluate("() => window.__grant")
                page.click("#wl-ap-hud [data-act='resume']")
                page.clock.run_for(1200)
                passed = passed and recovered.evaluate("() => window.__grant")
            # A late catalog acknowledgement must not erase progress or reset dwell.
            if expected and "stale-catalog" in name:
                if name == "manual-back-with-stale-catalog":
                    page.click("#liSCO_101 a")
                    page.wait_for_timeout(250)
                    page.clock.run_for(1500)
                    passed = (passed and not child.evaluate("() => window.__grant") and
                              "完成度：100%" not in page.inner_text("#wl-ap-hud") and
                              not page.evaluate("() => Object.keys(JSON.parse(localStorage.getItem('wl_ap_records_v32') || '{}')).some(k => k.endsWith('|101'))"))
                    page.evaluate("url => document.getElementById('contentFrame').src = url", CHILD_URL)
                    page.wait_for_timeout(500)
                    page.clock.run_for(3000)
                    back = next(f for f in page.frames if "navigation-player" in f.url)
                    passed = passed and back.evaluate("() => window.__grant")
                    page.clock.run_for(31000)
                    passed = passed and "30秒内未确认课件加载" not in page.inner_text("#wl-ap-hud")
                else:
                    elapsed_before = page.evaluate("() => JSON.parse(sessionStorage.getItem('wl_ap_dwell_v3')).elapsed")
                    page.evaluate("() => setCurrent(102)")
                    page.clock.run_for(2200)
                    page.clock.run_for(5000)
                    elapsed_after = page.evaluate("() => JSON.parse(sessionStorage.getItem('wl_ap_dwell_v3')).elapsed")
                    passed = (passed and "完成度：100%" in page.inner_text("#wl-ap-hud") and
                              elapsed_after >= elapsed_before)
            entry = {"case": name, "expected_confirmed": expected, "timed_out": timed_out,
                     "grant": grant, "clicks": clicks, "record_keys": list(records),
                     "page_errors": errors, "pass": bool(passed)}
            results.append(entry)
            print(json.dumps(entry, ensure_ascii=False), flush=True)
            ctx.close()
        browser.close()
    (OUT / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{'PASS' if all(r['pass'] for r in results) else 'FAIL'} {sum(r['pass'] for r in results)}/{len(results)}")
    return 0 if all(r["pass"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())

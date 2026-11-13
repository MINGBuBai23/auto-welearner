"""Manual voice page: hang the configured dwell, skip completion/madia gating, then page."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).parent))
import test_integration as ti  # noqa: E402

SCO = "5/3-1"  # 11 blanks + 2 recorders
CONFIG = ("try { localStorage.setItem('wl_autopager_cfg_v7', JSON.stringify({enabled:true,minDwell:1,jitterMin:0,jitterMax:0,"
          "maxPages:10,mode:'completion',autoAnswer:true,minAccuracy:100,muteMedia:true})); } catch (e) {}")


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.add_init_script(ti.STUB)
        page.add_init_script(CONFIG)
        page.add_init_script(ti.SCRIPT)
        page.route("https://welearn.sflep.com/Student/StudyCourse.aspx*",
                   lambda route: route.fulfill(status=200, content_type="text/html; charset=utf-8",
                                               body=ti.TOP_HTML.replace("__SCO_URL__", ti.BASE + "index.html#/" + SCO)))
        page.goto("https://welearn.sflep.com/Student/StudyCourse.aspx?cid=voice-manual", wait_until="domcontentloaded", timeout=90000)
        page.wait_for_selector("#wl-ap-hud", timeout=30000)

        frame = None
        for _ in range(120):
            frame = next((f for f in page.frames if "centercourseware" in (f.url or "")), None)
            if frame:
                try:
                    if frame.evaluate("() => window.__WLAP_ENGINE__ && window.__WLAP_ENGINE__.isCourseware() && window.__WLAP_ENGINE__.analyze()"):
                        break
                except Exception:
                    pass
            page.wait_for_timeout(500)
        if not frame:
            raise RuntimeError("courseware frame not found")
        frame.wait_for_function("() => { const a = window.__WLAP_ENGINE__.analyze(); return a && a.voice === 2; }", timeout=60000)
        page.wait_for_function("() => (window.__NEXT__ || 0) >= 1", timeout=60000)
        page.wait_for_timeout(800)

        report = frame.evaluate("() => window.__WLAP_ENGINE__.analyze()")
        scorm = frame.evaluate("() => window.__SCORM_MODEL__")
        records = page.evaluate("() => JSON.parse(localStorage.getItem('wl_ap_records_v32') || '{}')")
        hud = page.inner_text("#wl-ap-hud")
        entry = {
            "voice": report.get("voice"),
            "completion": report.get("completion"),
            "submitted": report.get("submitted"),
            "next_clicks": page.evaluate("() => window.__NEXT__ || 0"),
            "scorm_status": scorm.get("cmi.completion_status"),
            "records": len(records),
            "hud_voice_line": [line for line in hud.splitlines() if "人工语音" in line],
            "page_errors": errors[:5],
        }
        out = Path(__file__).parent / "artifacts"
        out.mkdir(exist_ok=True)
        page.screenshot(path=str(out / "voice-manual.png"), full_page=False)
        ok = (entry["voice"] == 2 and entry["completion"] < 100 and entry["submitted"] is False
              and entry["next_clicks"] >= 1 and entry["records"] == 0
              and entry["hud_voice_line"] and not entry["page_errors"])
        print(json.dumps(entry, ensure_ascii=False, indent=1))
        browser.close()
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

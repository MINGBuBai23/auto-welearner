"""Integration test: synthetic StudyCourse page + real courseware iframe.

Verifies the 3.2 loop end to end:
  top page HUD -> config grant -> iframe engine fills/submits -> progress
  report over postMessage -> completion gate -> native NextSCO click.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "welearn-autopager.user.js").read_text(encoding="utf-8")
BASE = ("https://centercourseware.sflep.com/"
        "New%20Target%20College%20English_V2_Video%20Course%202/")
SCO = "3/5-4"  # five blanks, no media, no recorder

STUB = r"""
(() => {
  const model = {
    'cmi.mode': 'normal', 'cmi.progress_measure': '0', 'cmi.completion_status': 'not_attempted',
    'cmi.score.raw': '0', 'cmi.score.scaled': '0', 'cci.service.user.id': 'tester',
    'cci.service.user.name': 'Tester', 'cci.service.class.id': 'class', 'cci.service.class.name': 'C',
    'cci.service.play.baseurl': '', 'cci.submit_time': '', 'cci.retry_count': '0'
  };
  window.__SCORM_LOG__ = []; window.__SCORM_MODEL__ = model;
  window.API_1484_11 = {
    Initialize: () => 'true', Terminate: () => 'true',
    GetValue: k => (k in model ? model[k] : ''),
    SetValue: (k, v) => { model[k] = String(v); window.__SCORM_LOG__.push([k, String(v)]); return 'true'; },
    Commit: () => 'true', GetLastError: () => '0', GetErrorString: () => '', GetDiagnostic: () => ''
  };
})();
"""

TOP_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>StudyCourse fixture</title></head>
<body>
<ul id="catalog">
  <li id="liSCO_101" class="courseware_list_1_4 courseware_current"><a href="#" onclick="SelectSCO(101);return false;">Task 1</a></li>
  <li id="liSCO_102" class="courseware_list_1_4"><a href="#" onclick="SelectSCO(102);return false;">Task 2</a></li>
</ul>
<iframe id="contentFrame" src="__SCO_URL__" style="width:1200px;height:760px;border:1px solid #999"></iframe>
<a id="nativeNext" href="javascript:NextSCO();">native next</a>
<script>
  window.__NEXT__ = 0;
  function SelectSCO(id) { window.__SCO__ = id; }
  function NextSCO() { window.__NEXT__ = (window.__NEXT__ || 0) + 1; window.__LAST_NEXT_AT__ = Date.now(); }
</script>
</body></html>"""


TOP_HTML_MULTI = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>StudyCourse multi fixture</title></head>
<body>
<ul id="catalog">
  <li id="liSCO_101" class="courseware_list_1_4 courseware_current"><a href="#" onclick="SelectSCO(101);return false;">Task 1</a></li>
  <li id="liSCO_102" class="courseware_list_1_4"><a href="#" onclick="SelectSCO(102);return false;">Task 2</a></li>
  <li id="liSCO_103" class="courseware_list_1_4"><a href="#" onclick="SelectSCO(103);return false;">Task 3</a></li>
</ul>
<iframe id="contentFrame" src="__SCO_URL__" style="width:1200px;height:760px;border:1px solid #999"></iframe>
<a id="nativeNext" href="javascript:NextSCO();">native next</a>
<script>
  window.__NEXT__ = 0; window.__SCO__ = 101;
  var base = "__SCO_URL__";
  var urls = { 101: base, 102: base + "?run=102", 103: base + "?run=103" };
  function setCurrent(id) {
    var all = document.querySelectorAll('li[id^="liSCO_"]');
    for (var i = 0; i < all.length; i++) all[i].classList.remove('courseware_current');
    document.getElementById('liSCO_' + id).classList.add('courseware_current');
    window.__SCO__ = id;
  }
  function SelectSCO(id) { setCurrent(id); }
  function NextSCO() {
    window.__NEXT__ = (window.__NEXT__ || 0) + 1;
    if (window.__NEXT__ === 1) { setCurrent(102); document.getElementById('contentFrame').src = urls[102]; }
  }
</script>
</body></html>"""


FAKE_CHILD_URL = "https://centercourseware.sflep.com/fake-player.html"
FAKE_CHILD_HTML = """<!DOCTYPE html><html><body><p>fake player</p>
<script>
  window.__send = function (p) {
    parent.postMessage({ protocol: 'wl-ap-v4', type: 'status', media: { count: 0, done: true, ready: true, playing: false, blocked: false }, warning: '', progress: p }, '*');
  };
</script></body></html>"""


def main():
    ok = True
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
        ctx.route(FAKE_CHILD_URL + "*", lambda route: route.fulfill(status=200, content_type="text/html; charset=utf-8", body=FAKE_CHILD_HTML))
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.add_init_script(STUB)
        page.add_init_script(
            "try { localStorage.setItem('wl_autopager_cfg_v7', JSON.stringify({enabled:true,minDwell:1,jitterMin:0,jitterMax:0,maxPages:10,mode:'completion',autoAnswer:true})); } catch (e) {}")
        page.add_init_script(SCRIPT)

        def serve(route):
            route.fulfill(status=200, content_type="text/html; charset=utf-8",
                          body=TOP_HTML.replace("__SCO_URL__", BASE + "index.html#/" + SCO))

        page.route("https://welearn.sflep.com/Student/StudyCourse.aspx*", serve)
        page.goto("https://welearn.sflep.com/Student/StudyCourse.aspx?cid=fixture", wait_until="domcontentloaded", timeout=90000)
        page.wait_for_selector("#wl-ap-hud", timeout=30000)
        page.wait_for_function("() => !!window.__WLAP_ENGINE__", timeout=30000)
        frame = None
        for _ in range(120):
            frame = next((f for f in page.frames if "centercourseware" in (f.url or "")), None)
            if frame:
                try:
                    if frame.evaluate("() => window.__WLAP_ENGINE__ && window.__WLAP_ENGINE__.isCourseware()"):
                        break
                except Exception:
                    pass
            page.wait_for_timeout(500)
        if not frame:
            raise RuntimeError("courseware frame not found")
        # wait for the engine to submit via the top grant
        frame.wait_for_function("() => { const a = window.__WLAP_ENGINE__.analyze(); return a && a.submitted; }", timeout=120000)
        report = frame.evaluate("() => window.__WLAP_ENGINE__.analyze()")
        scorm = frame.evaluate("() => window.__SCORM_MODEL__")

        page.wait_for_function("() => (window.__NEXT__ || 0) >= 1", timeout=60000)
        hud = page.inner_text("#wl-ap-hud")
        out = Path(__file__).parent / "artifacts"
        out.mkdir(exist_ok=True)
        page.screenshot(path=str(out / "integration-hud.png"), full_page=False)
        # 面板开关与广播：取消勾选后立即显示“关闭”
        page.uncheck("#wl-ap-hud .wl-ap-auto")
        page.wait_for_function("() => document.querySelector('#wl-ap-hud').innerText.includes('自动作答：关闭')", timeout=10000)

        entry = {
            "report": {k: report.get(k) for k in ("total", "done", "completion", "accuracy", "submitted", "manual")},
            "scorm": {k: scorm.get(k) for k in ("cmi.progress_measure", "cmi.completion_status", "cmi.score.scaled")},
            "next_clicks": page.evaluate("() => window.__NEXT__"),
            "hud_has_completion": "完成度：100%" in hud,
            "hud_has_accuracy": "正确率：100%" in hud,
            "hud_has_auto": "自动作答：已提交" in hud,
            "page_errors": errors[:5],
        }
        ok = (entry["report"]["completion"] == 100 and entry["report"]["submitted"] is True
              and entry["scorm"]["cmi.completion_status"] == "completed"
              and entry["next_clicks"] >= 1 and entry["hud_has_completion"] and entry["hud_has_accuracy"]
              and entry["hud_has_auto"] and not entry["page_errors"])
        print(json.dumps(entry, ensure_ascii=False, indent=1))

        page.close()

        # --- 手动暂停不会被“检测到完成”自动恢复 ---
        page2 = ctx.new_page()
        errors2 = []
        page2.on("pageerror", lambda e: errors2.append(str(e)))
        page2.add_init_script(STUB)
        page2.add_init_script(
            "try { localStorage.setItem('wl_autopager_cfg_v7', JSON.stringify({enabled:true,minDwell:1,jitterMin:0,jitterMax:0,maxPages:10,mode:'completion',autoAnswer:false,minAccuracy:100})); } catch (e) {}")
        page2.add_init_script(SCRIPT)
        page2.route("https://welearn.sflep.com/Student/StudyCourse.aspx*", serve)
        page2.goto("https://welearn.sflep.com/Student/StudyCourse.aspx?cid=fixture2", wait_until="domcontentloaded", timeout=90000)
        page2.wait_for_selector("#wl-ap-hud", timeout=30000)
        frame2 = None
        for _ in range(120):
            frame2 = next((f for f in page2.frames if "centercourseware" in (f.url or "")), None)
            if frame2:
                try:
                    if frame2.evaluate("() => window.__WLAP_ENGINE__ && window.__WLAP_ENGINE__.isCourseware()"):
                        break
                except Exception:
                    pass
            page2.wait_for_timeout(500)
        if not frame2:
            raise RuntimeError("courseware frame not found (fixture2)")
        frame2.wait_for_selector("et-blank", timeout=60000)
        frame2.evaluate("() => window.__WLAP_ENGINE__.fillPage()")
        page2.wait_for_function("() => document.querySelector('#wl-ap-hud').innerText.includes('完成度：100%')", timeout=30000)
        hud_auto_off = page2.inner_text("#wl-ap-hud")
        page2.wait_for_function("() => document.querySelector('#wl-ap-hud').innerText.includes('等待本节完成')", timeout=60000)
        page2.click("#wl-ap-hud button[data-act='pause']")
        page2.wait_for_timeout(600)
        hud_paused = page2.inner_text("#wl-ap-hud")
        page2.evaluate("() => document.getElementById('liSCO_101').classList.add('course_disable')")
        page2.wait_for_timeout(3000)
        next_while_paused = page2.evaluate("() => window.__NEXT__ || 0")
        page2.click("#wl-ap-hud button[data-act='resume']")
        page2.wait_for_function("() => (window.__NEXT__ || 0) >= 1", timeout=60000)
        entry2 = {
            "auto_off_progress": "完成度：100%" in hud_auto_off and "自动作答：关闭" in hud_auto_off,
            "paused_action_shown": "已暂停" in hud_paused,
            "next_while_paused": next_while_paused,
            "next_after_resume": page2.evaluate("() => window.__NEXT__ || 0"),
            "page_errors": errors2[:5],
        }
        ok2 = entry2["paused_action_shown"] and next_while_paused == 0 and entry2["next_after_resume"] >= 1 and not entry2["page_errors"]
        print(json.dumps(entry2, ensure_ascii=False, indent=1))
        ok = ok and ok2
        page2.close()

        # --- 被闸门拦截的 100% 不写入历史；修正并提交后才记录 ---
        page3 = ctx.new_page()
        errors3 = []
        page3.on("pageerror", lambda e: errors3.append(str(e)))
        page3.add_init_script(STUB)
        page3.add_init_script(
            "try { localStorage.removeItem('wl_ap_records_v32'); localStorage.setItem('wl_autopager_cfg_v7', JSON.stringify({enabled:true,minDwell:1,jitterMin:0,jitterMax:0,maxPages:10,mode:'duration',autoAnswer:false,minAccuracy:100})); } catch (e) {}")
        page3.add_init_script(SCRIPT)
        page3.route("https://welearn.sflep.com/Student/StudyCourse.aspx*",
                    lambda route: route.fulfill(status=200, content_type="text/html; charset=utf-8",
                                                body=TOP_HTML.replace("__SCO_URL__", BASE + "index.html#/4/7-2")))
        page3.goto("https://welearn.sflep.com/Student/StudyCourse.aspx?cid=fixture3", wait_until="domcontentloaded", timeout=90000)
        page3.wait_for_selector("#wl-ap-hud", timeout=30000)
        frame3 = None
        for _ in range(120):
            frame3 = next((f for f in page3.frames if "centercourseware" in (f.url or "")), None)
            if frame3:
                try:
                    if frame3.evaluate("() => window.__WLAP_ENGINE__ && window.__WLAP_ENGINE__.isCourseware()"):
                        break
                except Exception:
                    pass
            page3.wait_for_timeout(500)
        if not frame3:
            raise RuntimeError("courseware frame not found (fixture3)")
        frame3.wait_for_selector("et-choice li", timeout=60000)
        frame3.evaluate("() => document.querySelector('et-choice').querySelectorAll('li')[0].click()")
        page3.check("#wl-ap-hud .wl-ap-auto")
        page3.wait_for_function("() => document.querySelector('#wl-ap-hud').innerText.includes('已拦截：正确率')", timeout=90000)
        records_blocked = page3.evaluate("() => JSON.parse(localStorage.getItem('wl_ap_records_v32') || '{}')")
        frame3.evaluate("() => document.querySelector('et-choice').querySelectorAll('li')[2].click()")
        frame3.wait_for_function("() => { const a = window.__WLAP_ENGINE__.analyze(); return a && a.submitted; }", timeout=90000)
        page3.wait_for_function("() => Object.keys(JSON.parse(localStorage.getItem('wl_ap_records_v32') || '{}')).length >= 1", timeout=30000)
        records_after = page3.evaluate("() => JSON.parse(localStorage.getItem('wl_ap_records_v32') || '{}')")
        entry3 = {
            "records_when_blocked": len(records_blocked),
            "records_after_submit": len(records_after),
            "record_submitted": [r.get("submitted") for r in records_after.values()],
            "page_errors": errors3[:5],
        }
        ok3 = (len(records_blocked) == 0 and len(records_after) == 1
               and all(r.get("submitted") is True for r in records_after.values()) and not entry3["page_errors"])
        print(json.dumps(entry3, ensure_ascii=False, indent=1))
        ok = ok and ok3
        page3.close()

        # --- 正确率阈值 0 是合法值，面板不能回显成 100 ---
        page4 = ctx.new_page()
        errors4 = []
        page4.on("pageerror", lambda e: errors4.append(str(e)))
        page4.add_init_script(STUB)
        page4.add_init_script(
            "try { localStorage.setItem('wl_autopager_cfg_v7', JSON.stringify({enabled:true,minDwell:300,jitterMin:0,jitterMax:0,maxPages:10,mode:'duration',autoAnswer:true,minAccuracy:100})); } catch (e) {}")
        page4.add_init_script(SCRIPT)
        page4.route("https://welearn.sflep.com/Student/StudyCourse.aspx*",
                    lambda route: route.fulfill(status=200, content_type="text/html; charset=utf-8",
                                                body=TOP_HTML.replace("__SCO_URL__", BASE + "index.html#/" + SCO)))
        page4.goto("https://welearn.sflep.com/Student/StudyCourse.aspx?cid=fixture4", wait_until="domcontentloaded", timeout=90000)
        page4.wait_for_selector("#wl-ap-hud", timeout=30000)
        frame4 = None
        for _ in range(120):
            frame4 = next((f for f in page4.frames if "centercourseware" in (f.url or "")), None)
            if frame4:
                try:
                    if frame4.evaluate("() => window.__WLAP_ENGINE__ && window.__WLAP_ENGINE__.isCourseware()"):
                        break
                except Exception:
                    pass
            page4.wait_for_timeout(500)
        if not frame4:
            raise RuntimeError("courseware frame not found (fixture4)")
        frame4.wait_for_function("() => { const a = window.__WLAP_ENGINE__.analyze(); return a && a.submitted; }", timeout=120000)
        page4.fill("#wl-ap-hud .wl-ap-min", "0")
        page4.click("#wl-ap-hud button[data-act='apply']")
        page4.wait_for_function("() => document.querySelector('#wl-ap-hud').innerText.includes('要求 ≥0%')", timeout=30000)
        hud4 = page4.inner_text("#wl-ap-hud")
        entry4 = {
            "min0_shown": "要求 ≥0%" in hud4,
            "next_clicks": page4.evaluate("() => window.__NEXT__ || 0"),
            "page_errors": errors4[:5],
        }
        ok4 = entry4["min0_shown"] and not entry4["page_errors"]
        print(json.dumps(entry4, ensure_ascii=False, indent=1))
        ok = ok and ok4
        page4.close()

        # --- 无交互页只有在目录出现 course_disable 后才写入历史 ---
        page5 = ctx.new_page()
        errors5 = []
        page5.on("pageerror", lambda e: errors5.append(str(e)))
        page5.add_init_script(STUB)
        page5.add_init_script(
            "try { localStorage.removeItem('wl_ap_records_v32'); localStorage.setItem('wl_autopager_cfg_v7', JSON.stringify({enabled:true,minDwell:1,jitterMin:0,jitterMax:0,maxPages:10,mode:'completion',autoAnswer:false,minAccuracy:100})); } catch (e) {}")
        page5.add_init_script(SCRIPT)
        page5.route("https://welearn.sflep.com/Student/StudyCourse.aspx*",
                    lambda route: route.fulfill(status=200, content_type="text/html; charset=utf-8",
                                                body=TOP_HTML.replace("__SCO_URL__", BASE + "index.html#/1/1-1")))
        page5.goto("https://welearn.sflep.com/Student/StudyCourse.aspx?cid=fixture5", wait_until="domcontentloaded", timeout=90000)
        page5.wait_for_selector("#wl-ap-hud", timeout=30000)
        for _ in range(120):
            frame5 = next((f for f in page5.frames if "centercourseware" in (f.url or "")), None)
            if frame5:
                try:
                    if frame5.evaluate("() => window.__WLAP_ENGINE__ && window.__WLAP_ENGINE__.isCourseware()"):
                        break
                except Exception:
                    pass
            page5.wait_for_timeout(500)
        page5.wait_for_timeout(4500)
        records_before = page5.evaluate("() => JSON.parse(localStorage.getItem('wl_ap_records_v32') || '{}')")
        page5.evaluate("() => document.getElementById('liSCO_101').classList.add('course_disable')")
        page5.wait_for_function("() => Object.keys(JSON.parse(localStorage.getItem('wl_ap_records_v32') || '{}')).length >= 1", timeout=30000)
        records_verified = page5.evaluate("() => JSON.parse(localStorage.getItem('wl_ap_records_v32') || '{}')")
        entry5 = {
            "records_before_marker": len(records_before),
            "records_after_marker": len(records_verified),
            "record_verified": [bool(r.get("verified")) for r in records_verified.values()],
            "record_submitted": [bool(r.get("submitted")) for r in records_verified.values()],
            "page_errors": errors5[:5],
        }
        ok5 = (len(records_before) == 0 and len(records_verified) == 1
               and all(r.get("verified") is True and r.get("submitted") is False for r in records_verified.values())
               and not entry5["page_errors"])
        print(json.dumps(entry5, ensure_ascii=False, indent=1))
        ok = ok and ok5
        page5.close()

        # --- 切换目录但保留旧 iframe：旧课件的 100% 不能写给新小节 ---
        page6 = ctx.new_page()
        errors6 = []
        page6.on("pageerror", lambda e: errors6.append(str(e)))
        page6.add_init_script(STUB)
        page6.add_init_script(
            "try { localStorage.removeItem('wl_ap_records_v32'); localStorage.setItem('wl_autopager_cfg_v7', JSON.stringify({enabled:true,minDwell:60,jitterMin:0,jitterMax:0,maxPages:10,mode:'completion',autoAnswer:true,minAccuracy:100})); } catch (e) {}")
        page6.add_init_script(SCRIPT)
        page6.route("https://welearn.sflep.com/Student/StudyCourse.aspx*",
                    lambda route: route.fulfill(status=200, content_type="text/html; charset=utf-8",
                                                body=TOP_HTML.replace("__SCO_URL__", BASE + "index.html#/" + SCO)))
        page6.goto("https://welearn.sflep.com/Student/StudyCourse.aspx?cid=fixture6", wait_until="domcontentloaded", timeout=90000)
        page6.wait_for_selector("#wl-ap-hud", timeout=30000)
        frame6 = None
        for _ in range(120):
            frame6 = next((f for f in page6.frames if "centercourseware" in (f.url or "")), None)
            if frame6:
                try:
                    if frame6.evaluate("() => window.__WLAP_ENGINE__ && window.__WLAP_ENGINE__.isCourseware()"):
                        break
                except Exception:
                    pass
            page6.wait_for_timeout(500)
        if not frame6:
            raise RuntimeError("courseware frame not found (fixture6)")
        frame6.wait_for_function("() => { const a = window.__WLAP_ENGINE__.analyze(); return a && a.submitted; }", timeout=120000)
        page6.wait_for_function("() => Object.keys(JSON.parse(localStorage.getItem('wl_ap_records_v32') || '{}')).length >= 1", timeout=30000)
        page6.click("#wl-ap-hud button[data-act='pause']")
        page6.wait_for_timeout(500)
        page6.evaluate("""() => {
          document.getElementById('liSCO_101').classList.remove('courseware_current');
          document.getElementById('liSCO_102').classList.add('courseware_current');
        }""")
        page6.wait_for_timeout(2500)
        hud_after_switch = page6.inner_text("#wl-ap-hud")
        records_switch = page6.evaluate("() => JSON.parse(localStorage.getItem('wl_ap_records_v32') || '{}')")
        page6.fill("#wl-ap-hud .wl-ap-dwell", "1")
        page6.click("#wl-ap-hud button[data-act='apply']")
        page6.click("#wl-ap-hud button[data-act='resume']")
        page6.wait_for_timeout(3000)
        entry6 = {
            "records_keys": list(records_switch.keys()),
            "record_for_102": any(k.endswith("|102") for k in records_switch.keys()),
            "old_progress_leaked": "完成度：100%" in hud_after_switch,
            "next_clicks": page6.evaluate("() => window.__NEXT__ || 0"),
            "page_errors": errors6[:5],
        }
        ok6 = (not entry6["record_for_102"] and not entry6["old_progress_leaked"]
               and entry6["next_clicks"] == 0 and not entry6["page_errors"])
        print(json.dumps(entry6, ensure_ascii=False, indent=1))
        ok = ok and ok6
        page6.close()

        # --- 自动翻到 102 后再手动切 103：旧 iframe 的 100% 不能写 103 ---
        page7 = ctx.new_page()
        errors7 = []
        page7.on("pageerror", lambda e: errors7.append(str(e)))
        page7.add_init_script(STUB)
        page7.add_init_script(
            "try { localStorage.removeItem('wl_ap_records_v32'); localStorage.setItem('wl_autopager_cfg_v7', JSON.stringify({enabled:true,minDwell:1,jitterMin:0,jitterMax:0,maxPages:10,mode:'completion',autoAnswer:true,minAccuracy:100})); } catch (e) {}")
        page7.add_init_script(SCRIPT)
        page7.route("https://welearn.sflep.com/Student/StudyCourse.aspx*",
                    lambda route: route.fulfill(status=200, content_type="text/html; charset=utf-8",
                                                body=TOP_HTML_MULTI.replace("__SCO_URL__", BASE + "index.html#/" + SCO)))
        page7.goto("https://welearn.sflep.com/Student/StudyCourse.aspx?cid=fixture7", wait_until="domcontentloaded", timeout=90000)
        page7.wait_for_selector("#wl-ap-hud", timeout=30000)
        frame7 = None
        for _ in range(120):
            frame7 = next((f for f in page7.frames if "centercourseware" in (f.url or "")), None)
            if frame7:
                try:
                    if frame7.evaluate("() => window.__WLAP_ENGINE__ && window.__WLAP_ENGINE__.isCourseware()"):
                        break
                except Exception:
                    pass
            page7.wait_for_timeout(500)
        if not frame7:
            raise RuntimeError("courseware frame not found (fixture7)")
        # 等待 101 自动提交并由原生 NextSCO 翻到 102，随后 102 也提交
        page7.wait_for_function("() => Object.keys(JSON.parse(localStorage.getItem('wl_ap_records_v32') || '{}')).length >= 2", timeout=180000)
        page7.click("#wl-ap-hud button[data-act='pause']")
        page7.wait_for_timeout(500)
        page7.evaluate("""() => {
          document.getElementById('liSCO_102').classList.remove('courseware_current');
          document.getElementById('liSCO_103').classList.add('courseware_current');
        }""")
        page7.wait_for_timeout(2500)
        hud7 = page7.inner_text("#wl-ap-hud")
        records7 = page7.evaluate("() => JSON.parse(localStorage.getItem('wl_ap_records_v32') || '{}')")
        baseline7 = page7.evaluate("() => window.__NEXT__ || 0")
        frame7b = next((f for f in page7.frames if "centercourseware" in (f.url or "")), None)
        grant7 = frame7b.evaluate("() => window.__WLAP_ENGINE__.state().grant") if frame7b else None
        page7.click("#wl-ap-hud button[data-act='resume']")
        page7.wait_for_timeout(3000)
        entry7 = {
            "records_keys": list(records7.keys()),
            "record_for_103": any(k.endswith("|103") for k in records7.keys()),
            "old_progress_leaked": "完成度：100%" in hud7,
            "grant_after_switch": grant7,
            "next_delta": page7.evaluate("() => (window.__NEXT__ || 0)") - baseline7,
            "page_errors": errors7[:5],
        }
        ok7 = (not entry7["record_for_103"] and not entry7["old_progress_leaked"]
               and grant7 is False and entry7["next_delta"] == 0 and not entry7["page_errors"])
        print(json.dumps(entry7, ensure_ascii=False, indent=1))
        ok = ok and ok7
        page7.close()

        # --- 切换目录后立即撤销旧 iframe 的作答授权 ---
        page8 = ctx.new_page()
        errors8 = []
        page8.on("pageerror", lambda e: errors8.append(str(e)))
        page8.add_init_script(STUB)
        page8.add_init_script(
            "try { localStorage.removeItem('wl_ap_records_v32'); localStorage.setItem('wl_autopager_cfg_v7', JSON.stringify({enabled:true,minDwell:60,jitterMin:0,jitterMax:0,maxPages:10,mode:'duration',autoAnswer:false,minAccuracy:100})); } catch (e) {}")
        page8.add_init_script(SCRIPT)
        page8.route("https://welearn.sflep.com/Student/StudyCourse.aspx*",
                    lambda route: route.fulfill(status=200, content_type="text/html; charset=utf-8",
                                                body=TOP_HTML.replace("__SCO_URL__", BASE + "index.html#/" + SCO)))
        page8.goto("https://welearn.sflep.com/Student/StudyCourse.aspx?cid=fixture8", wait_until="domcontentloaded", timeout=90000)
        page8.wait_for_selector("#wl-ap-hud", timeout=30000)
        frame8 = None
        for _ in range(120):
            frame8 = next((f for f in page8.frames if "centercourseware" in (f.url or "")), None)
            if frame8:
                try:
                    if frame8.evaluate("() => window.__WLAP_ENGINE__ && window.__WLAP_ENGINE__.isCourseware()"):
                        break
                except Exception:
                    pass
            page8.wait_for_timeout(500)
        if not frame8:
            raise RuntimeError("courseware frame not found (fixture8)")
        page8.check("#wl-ap-hud .wl-ap-auto")
        frame8.wait_for_function("() => window.__WLAP_ENGINE__.state().busy === true", timeout=30000)
        page8.evaluate("""() => {
          document.getElementById('liSCO_101').classList.remove('courseware_current');
          document.getElementById('liSCO_102').classList.add('courseware_current');
        }""")
        page8.wait_for_timeout(4000)
        analysis8 = frame8.evaluate("() => window.__WLAP_ENGINE__.analyze()")
        scorm8 = frame8.evaluate("() => window.__SCORM_MODEL__")
        grant8 = frame8.evaluate("() => window.__WLAP_ENGINE__.state().grant")
        records8 = page8.evaluate("() => JSON.parse(localStorage.getItem('wl_ap_records_v32') || '{}')")
        entry8 = {
            "submitted": analysis8.get("submitted"),
            "progress_measure": scorm8.get("cmi.progress_measure"),
            "grant_after_switch": grant8,
            "records": len(records8),
            "page_errors": errors8[:5],
        }
        ok8 = (analysis8.get("submitted") is False and scorm8.get("cmi.progress_measure") == "0"
               and grant8 is False and len(records8) == 0 and not entry8["page_errors"])
        print(json.dumps(entry8, ensure_ascii=False, indent=1))
        ok = ok and ok8

        # --- 首次进度上报前切换：旧 iframe 的迟到首报不能写给新章节 ---
        def fake_page(cid):
            pg = ctx.new_page()
            pg.add_init_script(STUB)
            pg.add_init_script(
                "try { localStorage.removeItem('wl_ap_records_v32'); localStorage.setItem('wl_autopager_cfg_v7', JSON.stringify({enabled:true,minDwell:60,jitterMin:0,jitterMax:0,maxPages:10,mode:'duration',autoAnswer:false,minAccuracy:100})); } catch (e) {}")
            pg.add_init_script(SCRIPT)
            pg.route("https://welearn.sflep.com/Student/StudyCourse.aspx*",
                     lambda route: route.fulfill(status=200, content_type="text/html; charset=utf-8",
                                                 body=TOP_HTML.replace("__SCO_URL__", FAKE_CHILD_URL)))
            pg.goto("https://welearn.sflep.com/Student/StudyCourse.aspx?cid=" + cid, wait_until="domcontentloaded", timeout=90000)
            pg.wait_for_selector("#wl-ap-hud", timeout=30000)
            frame = None
            for _ in range(60):
                frame = next((f for f in pg.frames if "fake-player.html" in (f.url or "")), None)
                if frame:
                    try:
                        if frame.evaluate("() => typeof window.__send === 'function'"):
                            break
                    except Exception:
                        pass
                pg.wait_for_timeout(300)
            if not frame:
                raise RuntimeError("fake child frame not found")
            try:
                frame.wait_for_function("() => document.readyState === 'complete'", timeout=15000)
            except Exception:
                pass
            pg.wait_for_timeout(600)
            return pg, frame

        def report(completion, doc, href, item="item", submitted=False):
            return {"page": "fake", "href": href, "docId": doc, "itemId": item, "completion": completion,
                    "accuracy": 100, "total": 5, "done": 5, "manual": 0, "submitted": submitted,
                    "type": "objective", "error": "", "blockReason": "", "minAccuracy": 100, "issues": 0}

        pageA, frameA = fake_page("fixtureA")
        pageA.wait_for_timeout(1200)
        pageA.evaluate("""() => {
          document.getElementById('liSCO_101').classList.remove('courseware_current');
          document.getElementById('liSCO_102').classList.add('courseware_current');
        }""")
        pageA.wait_for_timeout(200)
        frameA.evaluate("(p) => window.__send(p)", report(100, "docA", "/fake-player.html#/101"))
        pageA.wait_for_timeout(2000)
        hudA = pageA.inner_text("#wl-ap-hud")
        recordsA = pageA.evaluate("() => JSON.parse(localStorage.getItem('wl_ap_records_v32') || '{}')")
        # 再同源重载 iframe（src 不变），并等待超过旧版 1.5 秒自动解除窗口
        frameA.evaluate("() => location.reload()")
        pageA.wait_for_timeout(2500)
        frameA1 = next((f for f in pageA.frames if "fake-player.html" in (f.url or "")), None)
        frameA1.wait_for_function("() => typeof window.__send === 'function'", timeout=15000)
        frameA1.evaluate("(p) => window.__send(p)", report(100, "docA", "/fake-player.html#/101"))
        pageA.wait_for_timeout(1500)
        hudA_late = pageA.inner_text("#wl-ap-hud")
        recordsA_late = pageA.evaluate("() => JSON.parse(localStorage.getItem('wl_ap_records_v32') || '{}')")
        # 显式更换 src 才是新章节加载确认
        pageA.evaluate("() => { const f = document.getElementById('contentFrame'); f.src = f.src + '?fresh=1'; }")
        pageA.wait_for_timeout(1200)
        frameA2 = next((f for f in pageA.frames if "fake-player.html" in (f.url or "")), None)
        frameA2.evaluate("(p) => window.__send(p)", report(100, "docB", "/fake-player.html#/102"))
        pageA.wait_for_timeout(1500)
        hudA2 = pageA.inner_text("#wl-ap-hud")
        entryA = {
            "late_first_report_leaked": "完成度：100%" in hudA,
            "records_after_late_report": len(recordsA),
            "late_after_1_5s_leaked": "完成度：100%" in hudA_late,
            "records_after_same_src_reload": len(recordsA_late),
            "after_src_change_accepted": "完成度：100%" in hudA2,
        }
        okA = (not entryA["late_first_report_leaked"] and entryA["records_after_late_report"] == 0
               and not entryA["late_after_1_5s_leaked"] and entryA["records_after_same_src_reload"] == 0
               and entryA["after_src_change_accepted"])
        print(json.dumps(entryA, ensure_ascii=False, indent=1))
        ok = ok and okA
        pageA.close()

        # --- iframe 内路由变化早于下一次 tick：同一次切换只初始化一次 ---
        pageB, frameB = fake_page("fixtureB")
        frameB.evaluate("(p) => window.__send(p)", report(50, "docA", "/fake-player.html#/101"))
        pageB.wait_for_timeout(600)
        hudB0 = pageB.inner_text("#wl-ap-hud")
        pageB.evaluate("""() => {
          document.getElementById('liSCO_101').classList.remove('courseware_current');
          document.getElementById('liSCO_102').classList.add('courseware_current');
        }""")
        frameB.evaluate("(p) => window.__send(p)", report(77, "docA", "/fake-player.html#/102"))
        pageB.wait_for_timeout(2200)
        hudB = pageB.inner_text("#wl-ap-hud")
        entryB = {
            "hud_before_switch": hudB0,
            "hud_after_switch": hudB,
            "route_change_accepted": "完成度：77%" in hudB,
            "not_stuck_waiting": "等待课件" not in hudB,
        }
        okB = entryB["route_change_accepted"] and entryB["not_stuck_waiting"]
        print(json.dumps(entryB, ensure_ascii=False, indent=1))
        ok = ok and okB

        browser.close()
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

"""End-to-end tests for the WE Learn userscript 3.2 completion engine.

The official courseware player is public. Each test loads a real SCO through
the player, injects the userscript, stubs the SCORM 2004 API with an in-memory
data model, and drives the engine exactly as the userscript does in its iframe.

Run:  python tests/test_engine.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "welearn-autopager.user.js").read_text(encoding="utf-8")
BASE = ("https://centercourseware.sflep.com/"
        "New%20Target%20College%20English_V2_Video%20Course%202/")

STUB = r"""
(() => {
  const model = {
    'cmi.mode': 'normal', 'cmi.progress_measure': '0', 'cmi.completion_status': 'not_attempted',
    'cmi.success_status': 'unknown', 'cmi.score.raw': '0', 'cmi.score.scaled': '0',
    'cmi.score.min': '0', 'cmi.score.max': '100',
    'cci.service.user.id': 'tester-001', 'cci.service.user.name': 'Tester',
    'cci.service.class.id': 'class-001', 'cci.service.class.name': 'Test Class',
    'cci.service.play.baseurl': '', 'cci.submit_time': '', 'cci.retry_count': '0',
    'cci.response_status.response_count': '0', 'cci.response_status.average_score': '0',
    'cci.response_status.average_time': '0'
  };
  window.__SCORM_LOG__ = [];
  window.__SCORM_MODEL__ = model;
  window.API_1484_11 = {
    Initialize: () => 'true',
    Terminate: () => 'true',
    GetValue: k => (k in model ? model[k] : ''),
    SetValue: (k, v) => { model[k] = String(v); window.__SCORM_LOG__.push([k, String(v)]); return 'true'; },
    Commit: () => 'true',
    GetLastError: () => '0',
    GetErrorString: () => '',
    GetDiagnostic: () => ''
  };
})();
"""

CASES = [
    # (name, sco, expect)
    ("choice+blank", "4/7-2", {"completion": 100, "accuracy": 100, "submitted": True}),
    ("tick+tof", "6/4-2", {"completion": 100, "accuracy": 100, "submitted": True}),
    ("blank+multi+noinput", "2/4-2", {"completion": 100, "accuracy": 100, "submitted": True}),
    ("tof+blank", "8/4-3", {"completion": 100, "accuracy": 100, "submitted": True}),
]


def new_page(ctx):
    page = ctx.new_page()
    page.add_init_script(STUB)
    page.add_init_script(SCRIPT)
    return page


def load(page, sco, auto=True):
    page.goto(BASE + "index.html#/" + sco, wait_until="domcontentloaded", timeout=90000)
    page.wait_for_function("() => window.__WLAP_ENGINE__ && window.__WLAP_ENGINE__.isCourseware() && document.querySelector('et-item')", timeout=60000)
    page.wait_for_timeout(2500)
    if auto:
        page.evaluate("() => { window.__WLAP_ENGINE__.config.autoAnswer = true; }")


def report(page):
    return page.evaluate("() => window.__WLAP_ENGINE__.analyze()")


def scorm(page):
    return page.evaluate("() => ({model: window.__SCORM_MODEL__, log: window.__SCORM_LOG__})")


def run_all():
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
        # --- fresh install: duration mode and auto-answer off by default ---
        entry = {"case": "default-config-off", "sco": "4/7-2", "pass": False, "notes": []}
        page = new_page(ctx)
        try:
            load(page, "4/7-2", auto=False)
            cfg = page.evaluate("() => ({auto: window.__WLAP_ENGINE__.config.autoAnswer, mode: window.__WLAP_ENGINE__.config.mode, minAccuracy: window.__WLAP_ENGINE__.config.minAccuracy})")
            after = page.evaluate("() => window.__WLAP_ENGINE__.runPage()")
            value = page.evaluate("() => window.angular.element(document.querySelector('et-blank')).controller('etBlank').value")
            entry["config"] = cfg
            entry["after"] = {k: after.get(k) for k in ("submitted", "completion", "accuracy")}
            entry["blank_value"] = value
            entry["pass"] = cfg.get("auto") is False and cfg.get("mode") == "duration" and cfg.get("minAccuracy") == 100 and value == "" and after.get("submitted") is False
        except Exception as e:
            entry["notes"].append(repr(e)[:300])
        finally:
            page.close()
        results.append(entry)
        print(json.dumps(entry, ensure_ascii=False))

        # --- normal objective pages: fill -> submit -> SCORM commit ---
        for name, sco, expect in CASES:
            entry = {"case": name, "sco": sco, "pass": False, "notes": []}
            page = new_page(ctx)
            try:
                load(page, sco)
                before = report(page)
                after = page.evaluate("() => window.__WLAP_ENGINE__.runPage()")
                data = scorm(page)
                entry["before"] = {k: before.get(k) for k in ("total", "completion", "accuracy", "submitted", "manual")}
                entry["after"] = {k: after.get(k) for k in ("total", "completion", "accuracy", "submitted", "manual", "type", "error")}
                entry["scorm"] = {k: data["model"].get(k) for k in ("cmi.progress_measure", "cmi.completion_status", "cmi.score.raw", "cmi.score.scaled")}
                ok = (after.get("completion") == expect["completion"] and after.get("accuracy") == expect["accuracy"]
                      and after.get("submitted") == expect["submitted"]
                      and data["model"].get("cmi.progress_measure") == "1"
                      and data["model"].get("cmi.completion_status") == "completed")
                entry["pass"] = bool(ok)
                if not ok:
                    entry["notes"].append("未达到预期")
            except Exception as e:
                entry["notes"].append(repr(e)[:300])
            finally:
                page.close()
            results.append(entry)
            print(json.dumps(entry, ensure_ascii=False))

        # --- 80% rule: 2 notscored + 8 scored blanks on 1/4-2 ---
        entry = {"case": "notscored-80-percent", "sco": "1/4-2", "pass": False, "notes": []}
        page = new_page(ctx)
        try:
            load(page, "1/4-2")
            partial = page.evaluate("() => { window.__WLAP_ENGINE__.fillPage({skipNotScored:true}); return window.__WLAP_ENGINE__.analyze(); }")
            entry["partial"] = {k: partial.get(k) for k in ("total", "done", "notscored", "completion", "accuracy", "submitted")}
            scorm_partial = scorm(page)
            entry["partial_scorm"] = {k: scorm_partial["model"].get(k) for k in ("cmi.progress_measure", "cmi.completion_status")}
            full = page.evaluate("() => window.__WLAP_ENGINE__.runPage()")
            entry["full"] = {k: full.get(k) for k in ("total", "done", "completion", "accuracy", "submitted")}
            data = scorm(page)
            entry["full_scorm"] = {k: data["model"].get(k) for k in ("cmi.progress_measure", "cmi.completion_status", "cmi.score.scaled")}
            ok = (partial.get("completion") == 80 and partial.get("accuracy") == 100 and partial.get("submitted") is False
                  and full.get("completion") == 100 and full.get("accuracy") == 100 and full.get("submitted") is True
                  and data["model"].get("cmi.completion_status") == "completed")
            entry["pass"] = bool(ok)
        except Exception as e:
            entry["notes"].append(repr(e)[:300])
        finally:
            page.close()
        results.append(entry)
        print(json.dumps(entry, ensure_ascii=False))

        # --- recorder page: engine must fill answerable items but not fake completion ---
        entry = {"case": "manual-recorder-blocks-100", "sco": "5/3-1", "pass": False, "notes": []}
        page = new_page(ctx)
        try:
            load(page, "5/3-1")
            after = page.evaluate("() => window.__WLAP_ENGINE__.runPage()")
            data = scorm(page)
            entry["after"] = {k: after.get(k) for k in ("total", "done", "completion", "accuracy", "submitted", "manual", "voice", "missing")}
            entry["scorm_sets"] = [k for k, v in data["log"]]
            ok = (after.get("submitted") is False and after.get("manual") == 2 and after.get("voice") == 2
                  and after.get("completion") < 100 and "cci.submit_time" not in [k for k, v in data["log"]])
            entry["pass"] = bool(ok)
        except Exception as e:
            entry["notes"].append(repr(e)[:300])
        finally:
            page.close()
        results.append(entry)
        print(json.dumps(entry, ensure_ascii=False))

        # --- wrong answer: completion 100 but accuracy gate blocks auto-submit ---
        entry = {"case": "wrong-answer-blocked-by-accuracy", "sco": "4/7-2", "pass": False, "notes": []}
        page = new_page(ctx)
        try:
            load(page, "4/7-2")
            page.evaluate("() => window.__WLAP_ENGINE__.fillPage()")
            page.wait_for_timeout(700)
            good = report(page)
            page.evaluate("() => { const el = document.querySelector('et-choice'); const li = el.querySelectorAll('li'); if (li.length) li[0].click(); }")
            page.wait_for_timeout(700)
            wrong = report(page)
            after = page.evaluate("() => window.__WLAP_ENGINE__.runPage()")
            data = scorm(page)
            entry["good"] = {k: good.get(k) for k in ("completion", "accuracy")}
            entry["wrong"] = {k: wrong.get(k) for k in ("completion", "accuracy")}
            entry["after"] = {k: after.get(k) for k in ("submitted", "blockReason", "canSubmit")}
            entry["scorm"] = {k: data["model"].get(k) for k in ("cmi.progress_measure", "cmi.completion_status")}
            ok = (wrong.get("completion") == 100 and wrong.get("accuracy", 100) < 100
                  and after.get("submitted") is False and "正确率" in (after.get("blockReason") or "")
                  and data["model"].get("cmi.completion_status") != "completed")
            entry["pass"] = bool(ok)
        except Exception as e:
            entry["notes"].append(repr(e)[:300])
        finally:
            page.close()
        results.append(entry)
        print(json.dumps(entry, ensure_ascii=False))

        # --- cancelling auto-answer during the wait prevents the submit ---
        entry = {"case": "cancel-before-submit", "sco": "4/7-2", "pass": False, "notes": []}
        page = new_page(ctx)
        try:
            load(page, "4/7-2")
            page.evaluate("() => { window.__RUN__ = window.__WLAP_ENGINE__.runPage({wait: 1500}); }")
            page.wait_for_timeout(350)
            page.evaluate("() => { window.__WLAP_ENGINE__.config.autoAnswer = false; }")
            after = page.evaluate("() => window.__RUN__")
            data = scorm(page)
            entry["after"] = {k: after.get(k) for k in ("submitted", "completion", "accuracy")}
            entry["scorm"] = {k: data["model"].get(k) for k in ("cmi.progress_measure", "cmi.completion_status")}
            entry["pass"] = after.get("submitted") is False and data["model"].get("cmi.completion_status") != "completed"
        except Exception as e:
            entry["notes"].append(repr(e)[:300])
        finally:
            page.close()
        results.append(entry)
        print(json.dumps(entry, ensure_ascii=False))

        # --- existing answers are preserved ---
        entry = {"case": "keep-existing-answer", "sco": "4/7-2", "pass": False, "notes": []}
        page = new_page(ctx)
        try:
            load(page, "4/7-2")
            page.evaluate("""() => {
              const ng = window.angular;
              const el = document.querySelector('et-blank');
              const c = ng.element(el).controller('etBlank');
              const root = ng.element(document.documentElement).injector().get('$rootScope');
              const seen = new Set(), st = [root];
              let target = null;
              while (st.length) {
                const s = st.pop(); if (!s || seen.has(s)) continue; seen.add(s);
                if (Object.values(s).includes(c)) { target = s; break; }
                if (s.$$childHead) st.push(s.$$childHead);
                if (s.$$nextSibling) st.push(s.$$nextSibling);
              }
              target.$apply(() => { c.value = 'manual answer'; });
            }""")
            page.wait_for_timeout(500)
            before = page.evaluate("() => window.angular.element(document.querySelector('et-blank')).controller('etBlank').value")
            filled = page.evaluate("() => window.__WLAP_ENGINE__.fillPage()")
            actions = filled.get("actions") or []
            blank_action = next((a for a in actions if a.get("tag") == "et-blank" and a.get("index") == "4"), None)
            after = page.evaluate("() => window.angular.element(document.querySelector('et-blank')).controller('etBlank').value")
            entry["before"] = before
            entry["after"] = after
            entry["blank_action"] = blank_action
            entry["pass"] = before == "manual answer" and after == "manual answer" and blank_action is not None and blank_action.get("status") == "kept"
        except Exception as e:
            entry["notes"].append(repr(e)[:300])
        finally:
            page.close()
        results.append(entry)
        print(json.dumps(entry, ensure_ascii=False))

        # --- 确认弹窗前重新检查闸门：等待期间改错则取消提交 ---
        entry = {"case": "confirm-window-recheck", "sco": "4/7-2", "pass": False, "notes": []}
        page = new_page(ctx)
        try:
            load(page, "4/7-2")
            page.evaluate("() => window.__WLAP_ENGINE__.fillPage()")
            page.wait_for_timeout(700)
            hooked = page.evaluate("""() => {
              const submit = Array.from(document.querySelectorAll('et-button')).find(el => /submit/i.test(el.textContent) && el.offsetParent !== null);
              const btn = submit ? (submit.querySelector('button') || submit) : null;
              if (!btn) return false;
              btn.addEventListener('click', () => {
                const li = document.querySelector('et-choice').querySelectorAll('li');
                if (li.length) li[0].click();
              }, { once: true });
              return true;
            }""")
            after = page.evaluate("() => window.__WLAP_ENGINE__.runPage()")
            data = scorm(page)
            entry["hooked"] = hooked
            entry["after"] = {k: after.get(k) for k in ("submitted", "completion", "accuracy", "blockReason")}
            entry["scorm"] = {k: data["model"].get(k) for k in ("cmi.progress_measure", "cmi.completion_status")}
            entry["pass"] = bool(hooked and after.get("submitted") is False
                                 and "正确率" in (after.get("blockReason") or "")
                                 and data["model"].get("cmi.completion_status") != "completed")
        except Exception as e:
            entry["notes"].append(repr(e)[:300])
        finally:
            page.close()
        results.append(entry)
        print(json.dumps(entry, ensure_ascii=False))

        # --- 3.2.0 旧配置迁移：保留停留/模式，但自动作答强制关闭 ---
        entry = {"case": "legacy-config-migration", "sco": "4/7-2", "pass": False, "notes": []}
        page = ctx.new_page()
        page.add_init_script(STUB)
        page.add_init_script("try { Object.keys(localStorage).filter(k => k.indexOf('autosave-') === 0).forEach(k => localStorage.removeItem(k)); } catch (e) {}")
        page.add_init_script("try { localStorage.setItem('wl_autopager_cfg_v6', JSON.stringify({enabled:true,minDwell:33,jitterMin:0,jitterMax:0,maxPages:10,mode:'completion',autoAnswer:true})); } catch (e) {}")
        page.add_init_script(SCRIPT)
        try:
            load(page, "4/7-2", auto=False)
            cfg = page.evaluate("() => ({auto: window.__WLAP_ENGINE__.config.autoAnswer, dwell: window.__WLAP_ENGINE__.config.minDwell, mode: window.__WLAP_ENGINE__.config.mode})")
            stored = page.evaluate("() => JSON.parse(localStorage.getItem('wl_autopager_cfg_v7') || '{}')")
            after = page.evaluate("() => window.__WLAP_ENGINE__.runPage()")
            value = page.evaluate("() => window.angular.element(document.querySelector('et-blank')).controller('etBlank').value")
            entry["config"] = cfg
            entry["stored_auto"] = stored.get("autoAnswer")
            entry["blank_value"] = value
            entry["pass"] = (cfg.get("auto") is False and cfg.get("dwell") == 33 and cfg.get("mode") == "completion"
                             and stored.get("autoAnswer") is False and value == "" and after.get("submitted") is False)
        except Exception as e:
            entry["notes"].append(repr(e)[:300])
        finally:
            page.close()
        results.append(entry)
        print(json.dumps(entry, ensure_ascii=False))

        # --- SCORM progressMeasure stale: panel falls back to local done/total ---
        entry = {"case": "stale-scorm-completion", "sco": "1/4-2", "pass": False, "notes": []}
        page = new_page(ctx)
        try:
            load(page, "1/4-2")
            page.evaluate("() => window.__WLAP_ENGINE__.fillPage({skipNotScored: true})")
            page.wait_for_timeout(500)
            stale = """() => {
              const ng = window.angular;
              const root = ng.element(document.documentElement).injector().get('$rootScope');
              const seen = new Set(), st = [root];
              let item = null;
              while (st.length) {
                const s = st.pop(); if (!s || seen.has(s)) continue; seen.add(s);
                if (s.item && s.item.scormInfo && s.item.id) { item = s.item; break; }
                if (s.$$childHead) st.push(s.$$childHead);
                if (s.$$nextSibling) st.push(s.$$nextSibling);
              }
              if (!item) return false;
              item.scormInfo.progressMeasure = '0';
              return true;
            }"""
            page.evaluate(stale)
            a1 = report(page)
            page.evaluate("() => window.__WLAP_ENGINE__.fillPage()")
            page.wait_for_timeout(500)
            page.evaluate(stale)
            a2 = report(page)
            entry["partial"] = {k: a1.get(k) for k in ("completion", "siteCompletion", "localCompletion", "done", "total")}
            entry["full"] = {k: a2.get(k) for k in ("completion", "siteCompletion", "localCompletion", "done", "total")}
            entry["pass"] = (a1.get("completion") == 80 and a1.get("siteCompletion") == 0 and a1.get("localCompletion") == 80
                             and a2.get("completion") == 100 and a2.get("siteCompletion") == 0 and a2.get("localCompletion") == 100)
        except Exception as e:
            entry["notes"].append(repr(e)[:300])
        finally:
            page.close()
        results.append(entry)
        print(json.dumps(entry, ensure_ascii=False))

        # --- et-checking and no-interaction pages: site self-completes ---
        for name, sco in [("et-checking", "1/8-1"), ("no-interaction", "1/1-1")]:
            entry = {"case": name, "sco": sco, "pass": False, "notes": []}
            page = new_page(ctx)
            try:
                load(page, sco)
                page.wait_for_timeout(4000)
                a = report(page)
                data = scorm(page)
                entry["report"] = {k: a.get(k) for k in ("total", "completion", "submitted", "type")}
                entry["scorm"] = {k: data["model"].get(k) for k in ("cmi.progress_measure", "cmi.completion_status")}
                entry["pass"] = data["model"].get("cmi.progress_measure") == "1" and data["model"].get("cmi.completion_status") == "completed"
            except Exception as e:
                entry["notes"].append(repr(e)[:300])
            finally:
                page.close()
            results.append(entry)
            print(json.dumps(entry, ensure_ascii=False))

        browser.close()

    print("\n==== SUMMARY ====")
    failed = [r for r in results if not r["pass"]]
    for r in results:
        print(("PASS " if r["pass"] else "FAIL ") + r["case"] + " (" + r["sco"] + ")")
    print("passed", len(results) - len(failed), "/", len(results))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run_all())

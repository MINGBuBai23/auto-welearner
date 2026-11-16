"""Offline browser checks for the 30-minute section policy.

Uses a virtual clock, an in-memory read-only SCORM fixture, and native-next
navigation fixtures. No learning account or platform requests are involved.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "welearn-autopager.user.js").read_text(encoding="utf-8")
OUT = ROOT / "tests/artifacts/section-time"
URL = "https://welearn.sflep.com/Student/StudyCourse.aspx?cid=timer&sco=101"
CHILD = "https://centercourseware.sflep.com/timer.html"
KEY = "/student/studycourse.aspx|timer|"
LIMIT = 1800000

TOP = """<!doctype html><html><head><meta charset="utf-8"></head><body>
<ul>
<li id="liSCO_101" class="courseware_list_1_4 courseware_current"><a onclick="SelectSCO(101)">One</a></li>
<li id="liSCO_102" class="courseware_list_1_4"><a onclick="SelectSCO(102)">Two</a></li>
<li id="liSCO_103" class="courseware_list_1_4"><a onclick="SelectSCO(103)">Three</a></li>
</ul><iframe id="contentFrame" src="__CHILD__?sco=101"></iframe>
<a href="javascript:NextSCO();">Native next</a>
<script>
window.__NEXT__=0; window.__id=101;
function SelectSCO(id) {
 document.querySelectorAll('li').forEach(el => el.classList.remove('courseware_current'));
 document.getElementById('liSCO_'+id).classList.add('courseware_current');
 window.__id=id; document.getElementById('contentFrame').src='__CHILD__?sco='+id;
}
function NextSCO() { window.__NEXT__++; __NAVIGATE__ }
</script></body></html>"""

PLAYER = """<!doctype html><html><head><meta charset="utf-8"></head><body><et-item><et-media><audio></audio></et-media></et-item><script>
window.__reads=[]; window.__writes=[];
const item={id:new URLSearchParams(location.search).get('sco'),type:'subjective',submit(){__writes.push('submit')},isSubmitted:false,
 scormInfo:{progressMeasure:'0',score:{scaled:'0'}}};
const root={item};
window.__site=__SITE__;
window.angular={element(){return {
 injector(){return {get(name){if(name==='$rootScope') return root;
  if(name==='apiService') return {get(key){__reads.push(key);return __site},set(){__writes.push('set')}};
  throw new Error(name)}}}, controller(){return {isCompleted:false}}
}}};
HTMLMediaElement.prototype.play=function(){return Promise.reject(new Error('fixture blocked'))};
</script></body></html>"""


class Fixture:
    def __init__(self, browser, seed=None, cfg=None, site=None, navigate=False, top_extra="", url=URL, directory=""):
        self.ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
        self.page = self.ctx.new_page()
        self.errors = []
        self.key = '/student/studycourse.aspx|' + parse_qs(urlparse(url).query)['cid'][0] + '|'
        self.catalog_requests = []
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.page.clock.install()
        init = """if(window.top===window && !localStorage.__seeded){
          localStorage.__seeded='1';localStorage.setItem('wl_ap_section_times_v1',JSON.stringify(__SEED__));
          if(__CFG__!==null)localStorage.setItem('wl_autopager_cfg_v7',JSON.stringify(__CFG__));} """
        init = init.replace("__SEED__", json.dumps(seed or {})).replace("__CFG__", json.dumps(cfg))
        self.page.add_init_script(init)
        self.page.add_init_script(SCRIPT)
        player = PLAYER.replace("__SITE__", json.dumps(site))
        self.ctx.route(CHILD + "*", lambda r: r.fulfill(content_type="text/html", body=player))
        def serve_directory(r):
            self.catalog_requests.append(r.request.method)
            r.fulfill(content_type="text/html; charset=utf-8", body=directory)
        self.ctx.route("https://welearn.sflep.com/student/course_info.aspx*", serve_directory)
        top = TOP.replace("__CHILD__", CHILD).replace("__NAVIGATE__", "SelectSCO(__id+1);" if navigate else "")
        top = top.replace("</body>", top_extra + "</body>")
        self.ctx.route("https://welearn.sflep.com/Student/StudyCourse.aspx*", lambda r: r.fulfill(content_type="text/html", body=top))
        self.page.goto(url)
        self.page.wait_for_selector("#wl-ap-hud")
        self.page.wait_for_timeout(100)
        self.run(1500)

    def run(self, ms):
        self.page.clock.run_for(ms)
        self.page.wait_for_timeout(40)

    def elapsed(self, section="101"):
        self.page.evaluate("() => document.dispatchEvent(new Event('visibilitychange'))")
        return self.page.evaluate("key => (JSON.parse(localStorage.getItem('wl_ap_section_times_v1') || '{}')[key] || {}).elapsed || 0", self.key + section)

    def clicks(self):
        return self.page.evaluate("() => __NEXT__")

    def hud(self):
        return self.page.inner_text("#wl-ap-hud")

    def child(self):
        return next(f for f in self.page.frames if "timer.html" in f.url)

    def press(self, act):
        self.page.click(f"#wl-ap-hud [data-act='{act}']")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        def check(name, action, **kwargs):
            fixture = Fixture(browser, **kwargs)
            try:
                action(fixture)
                assert not fixture.errors, fixture.errors
                results.append({"case": name, "pass": True})
            except Exception as e:
                fixture.page.screenshot(path=str(OUT / (name + "-failed.png")))
                results.append({"case": name, "pass": False, "error": str(e), "hud": fixture.hud()})
            finally:
                fixture.ctx.close()
            print(json.dumps(results[-1], ensure_ascii=False), flush=True)

        def boundary(f):
            assert f.page.evaluate("() => __WLAP_ENGINE__.config.mode") == "section"
            # Leave a short safety margin so the platform's 30-minute inactivity
            # detector cannot fire before the native next action.
            f.run(1788000)
            assert f.clicks() == 0 and f.elapsed() < LIMIT, (f.clicks(), f.elapsed())
            f.run(3000)
            assert f.clicks() == 1 and 1790000 <= f.elapsed() < LIMIT
            f.run(40000)
            assert f.clicks() == 1 and "30秒内未确认课件加载" in f.hud()
        check("full-30-minute-boundary-blocked-media", boundary)

        def no_custom_dwell(f):
            assert f.page.locator("#wl-ap-hud .wl-ap-dwell").count() == 0
            assert f.page.locator("#wl-ap-hud .wl-ap-jit").count() == 0
            assert f.page.locator("#wl-ap-hud .wl-ap-mode option").all_text_contents() == ["自动识别学时：30分钟上限", "完成度：30分钟上限"]
            threshold = f.page.locator("#wl-ap-hud .wl-ap-min")
            threshold.fill("invalid")
            f.press("apply")
            assert f.page.evaluate("() => __WLAP_ENGINE__.config.minAccuracy") == 100
            assert "正确率阈值请填 0-100" in f.hud()
            threshold.fill("101")
            threshold.press("Enter")
            assert f.page.evaluate("() => __WLAP_ENGINE__.config.minAccuracy") == 100
            threshold.fill("0")
            threshold.press("Enter")
            assert f.page.evaluate("() => JSON.parse(localStorage.getItem('wl_autopager_cfg_v7')).minAccuracy") == 0
        check("custom-dwell-controls-removed", no_custom_dwell)

        def migration(f):
            cfg = f.page.evaluate("() => JSON.parse(localStorage.getItem('wl_autopager_cfg_v7'))")
            assert cfg["mode"] == "section" and cfg["sectionPolicy"] == 1 and cfg["minDwell"] == 20
            f.run(30000)
            assert f.clicks() == 0
        check("old-20-second-config-migrates", migration, cfg={"mode": "duration", "minDwell": 20})

        def partial(f):
            f.run(11000)
            assert f.clicks() == 1 and 1790000 <= f.elapsed() <= LIMIT
        check("partial-local-time-only-remainder", partial, seed={KEY+"101": {"elapsed": 1780000}})

        def full(f):
            f.run(3000)
            assert f.clicks() == 1 and 1790000 <= f.elapsed() <= LIMIT
        check("saved-full-section-skips", full, seed={KEY+"101": {"elapsed": LIMIT}})

        def chain(f):
            for _ in range(5):
                f.run(1500)
            assert f.clicks() == 2 and f.page.evaluate("() => __id") == 103
            assert f.elapsed("103") < 15000
            f.page.screenshot(path=str(OUT / "skip-full-sections.png"))
        check("consecutive-full-sections-confirm-each-load", chain, navigate=True,
              seed={KEY+"101": {"elapsed": LIMIT}, KEY+"102": {"elapsed": LIMIT}})

        def site_full(f):
            f.run(2500)
            assert f.clicks() == 1
            assert f.child().evaluate("() => __reads.length > 0 && __reads.every(k => k==='cmi.total_time')")
            assert f.child().evaluate("() => __writes.length") == 0
            assert "参考网站课件用时" in f.hud()
        for val in ["1800", "PT30M", "00:30:00", "P1D"]:
            check("site-total-" + val.replace(":", "-"), site_full, site=val)

        def invalid_site(f):
            f.run(5000)
            assert f.clicks() == 0 and f.elapsed() < 10000 and "本机计时" in f.hud()
        check("unavailable-site-time-falls-back", invalid_site, site="unknown")

        def no_double(f):
            f.run(40000)
            assert f.clicks() == 0 and 1730000 <= f.elapsed() < 1750000, f.elapsed()
        check("site-and-local-time-not-added-twice", no_double, site="1700")

        def reload(f):
            f.run(20000)
            before = f.elapsed()
            f.page.reload()
            f.page.wait_for_selector("#wl-ap-hud")
            f.run(1500)
            assert before <= f.elapsed() <= before + 3000, (before, f.elapsed())
            assert f.clicks() == 0
        check("partial-time-persists-on-reload", reload, seed={KEY+"101": {"elapsed": 1700000}})

        def paused(f):
            f.press("pause")
            before = f.elapsed()
            f.run(60000)
            assert f.elapsed() == before and f.clicks() == 0
            f.press("resume")
            f.run(10000)
            assert f.clicks() == 1
        check("manual-pause-does-not-count-or-skip", paused, seed={KEY+"101": {"elapsed": 1780000}})

        def freeze(f):
            before = f.elapsed()
            f.page.clock.fast_forward(120000)
            assert f.elapsed() <= before + 1000 and f.clicks() == 0
        check("sleep-gap-not-counted", freeze, seed={KEY+"101": {"elapsed": 1780000}})

        def isolated(f):
            f.run(3000)
            assert f.clicks() == 0 and f.elapsed() < 10000
        check("other-course-time-isolated", isolated, seed={KEY.replace("timer", "other")+"101": {"elapsed": LIMIT}})
        check("other-section-time-isolated", isolated, seed={KEY+"102": {"elapsed": LIMIT}})

        def completion_cap(f):
            f.press("next")
            assert "等待本节完成" in f.hud()
            partial(f)
        check("completion-wait-has-30-minute-cap", completion_cap,
              cfg={"sectionPolicy": 1, "mode": "completion", "minDwell": 0, "jitterMin": 0, "jitterMax": 0},
              seed={KEY+"101": {"elapsed": 1780000}})

        def last(f):
            f.page.evaluate("() => SelectSCO(103)")
            for _ in range(3):
                f.run(1500)
            assert f.clicks() == 0 and "已到课程末尾" in f.hud()
        check("last-full-section-stops", last, seed={KEY+"103": {"elapsed": LIMIT}})

        def warning(f):
            f.run(5000)
            assert f.clicks() == 0 and "网站提示，已暂停" in f.hud()
        check("site-verification-still-pauses", warning, seed={KEY+"101": {"elapsed": LIMIT}},
              top_extra='<div role="dialog">请完成人机验证</div>')

        def disabled(f):
            assert f.clicks() == 0
            f.run(30000)
            assert f.clicks() == 0
            f.press("toggle")
            f.run(2000)
            assert f.clicks() == 1
        check("disabled-does-not-skip", disabled, cfg={"enabled": False}, seed={KEY+"101": {"elapsed": LIMIT}})

        directory = '''<!doctype html><meta charset="utf-8"><ul>
          <li class="stu_testlist_2" onclick="javascript:StartSCO('101');">
          <span>01. Unit Goals</span><span class="pull-right"><a>开始学习</a></span>
          <span class="pull-right">用时 __TIME__</span></li></ul>
          <script>window.__catalogExecuted=true;</script>'''
        directory_url = URL.replace('cid=timer', 'cid=2416')

        def directory_full(f):
            f.run(3000)
            assert f.clicks() == 1 and 1790000 <= f.elapsed() <= LIMIT
            assert "参考网站目录用时" in f.hud()
            assert f.catalog_requests == ['GET']
            assert not f.page.evaluate("() => window.__catalogExecuted || false")
        for value in ['30:00', '30:09', '01:00:00']:
            check('directory-' + value.replace(':', '-'), directory_full,
                  url=directory_url, directory=directory.replace('__TIME__', value))

        def directory_and_scorm_use_later_value(f):
            f.run(2500)
            state = f.page.evaluate("() => window.__WLAP_ENGINE__.state()")
            assert f.clicks() == 1 and state["siteTime"] == "目录+课件" and state["studySeconds"] == 1800
        check('directory-and-scorm-use-later-value', directory_and_scorm_use_later_value,
              url=directory_url, directory=directory.replace('__TIME__', '29:00'), site='1800')

        def directory_partial(f):
            assert f.clicks() == 0 and 1780000 <= f.elapsed() < 1790000
            f.run(11000)
            assert f.clicks() == 1
        check('directory-partial-waits-to-safety-margin', directory_partial, url=directory_url,
              directory=directory.replace('__TIME__', '29:40'))

        def seconds_not_minutes(f):
            assert f.clicks() == 0 and 30000 <= f.elapsed() < 35000
        check('directory-00-30-means-30-seconds', seconds_not_minutes, url=directory_url,
              directory=directory.replace('__TIME__', '00:30'))
        check('directory-title-time-not-used', isolated, url=directory_url,
              directory=directory.replace('__TIME__', 'invalid').replace('01. Unit Goals', '30:00 Unit Goals'))
        check('directory-other-section-not-used', isolated, url=directory_url,
              directory=directory.replace('__TIME__', '30:00').replace("StartSCO('101')", "StartSCO('102')"))
        check('directory-failed-read-falls-back', site_full, url=directory_url, site='1800', directory='Login required')

        def inline_full(f):
            f.page.evaluate("() => {const s=document.createElement('span');s.textContent='用时 30:00';document.getElementById('liSCO_101').appendChild(s);}")
            f.run(1200)
            assert f.clicks() == 1 and "参考网站目录用时" in f.hud()
        check('study-page-inline-directory-time', inline_full)
        browser.close()
    (OUT / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    passed = sum(r["pass"] for r in results)
    print(f"PASS {passed}/{len(results)}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

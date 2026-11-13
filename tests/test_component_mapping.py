"""Offline browser regression for manual component status/controller mapping.

Uses the public engine API with a small Angular injector/controller fixture.
No network, microphone, camera, learning account, or SCORM writes are needed.
Run: python tests/test_component_mapping.py
"""
from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "welearn-autopager.user.js").read_text(encoding="utf-8")
FIXTURE = r"""
() => {
  const item = {id: 'manual-components', type: 'subjective', submit() {},
    isSubmitted: false, isEndTab: true,
    scormInfo: {progressMeasure: '0', score: {scaled: '0'}}};
  const root = {item, $apply(fn) { fn(); }, $evalAsync(fn) { fn(); }};
  const controllers = {
    etTalk: {recordingCount: 0, isCompleted() { return false; }},
    etFollowMe: {recordingCount: 0, finished: false,
      isCompleted() { return this.finished; }},
    etCamera: {recordingCount: 0}
  };
  const names = {'et-talk': 'etTalk', 'et-follow-me': 'etFollowMe', 'et-camera': 'etCamera'};
  window.__controllers = controllers;
  window.angular = {element(el) { return {
    injector() { return {get(name) {
      if (name !== '$rootScope') throw new Error('unexpected service: ' + name);
      return root;
    }}; },
    controller(name) { return names[el.localName] === name ? controllers[name] : null; }
  }; }};
}
"""


def main() -> None:
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.set_content("<et-item><et-talk></et-talk><et-follow-me></et-follow-me>"
                         "<et-camera></et-camera></et-item>")
        page.evaluate(FIXTURE)
        page.add_script_tag(content=SCRIPT)

        def check(case, done, manual):
            report = page.evaluate("() => window.__WLAP_ENGINE__.analyze()")
            actual = {key: report[key] for key in ("total", "done", "manual", "voice", "completion")}
            expected = {"total": 3, "done": done, "manual": manual,
                        "voice": manual, "completion": round(done / 3 * 100)}
            assert actual == expected, (case, actual, expected)
            results.append({"case": case, **actual, "pass": True})

        check("unfinished", 0, 3)
        actions = page.evaluate("() => window.__WLAP_ENGINE__.fillPage().actions")
        assert [a["status"] for a in actions] == ["manual"] * 3, actions
        results.append({"case": "unfinished-controllers-resolved", "pass": True})

        # Talk's native progress status uses recordingCount, including restored roles.
        page.evaluate("() => { window.__controllers.etTalk.recordingCount = 1; }")
        check("talk-completed", 1, 2)
        page.evaluate("() => { window.__controllers.etCamera.recordingCount = '1'; }")
        check("camera-completed", 2, 1)

        # Follow-me needs every sentence; a recording alone is insufficient.
        page.evaluate("() => { window.__controllers.etFollowMe.recordingCount = 1; }")
        check("follow-me-partial", 2, 1)
        page.evaluate("() => { window.__controllers.etFollowMe.finished = true; }")
        check("all-completed", 3, 0)

        before = page.evaluate("() => JSON.stringify(window.__controllers)")
        actions = page.evaluate("() => window.__WLAP_ENGINE__.fillPage().actions")
        after = page.evaluate("() => JSON.stringify(window.__controllers)")
        assert [a["status"] for a in actions] == ["kept"] * 3, actions
        assert before == after, "fillPage changed manual component data"
        results.append({"case": "completed-values-preserved", "pass": True})

        page.evaluate("() => { window.__controllers.etFollowMe.finished = false; }")
        check("follow-me-reset", 2, 1)
        page.evaluate("() => { window.__controllers.etFollowMe.isCompleted = () => { throw new Error('not ready'); }; }")
        check("completion-read-error", 2, 1)
        page.evaluate("() => { delete window.__controllers.etCamera; }")
        check("missing-controller", 1, 2)
        assert not errors, errors
        browser.close()

    for result in results:
        print(json.dumps(result))
    print(f"PASS {len(results)}/{len(results)}")


if __name__ == "__main__":
    main()

// ==UserScript==
// @name         WE Learn 自动挂机翻页
// @namespace    local.welearn.autopager
// @version      3.3.3
// @description  单标签页按时翻页、媒体播放、自动作答与完成度核算；可选择仅在网站标记完成后翻页
// @match        https://welearn.sflep.com/*
// @match        https://*.sflep.com/*
// @match        https://*.sflep.cn/*
// @match        https://*.sflep.com.cn/*
// @match        https://*.sfs.com.cn/*
// @run-at       document-idle
// @grant        none
// ==/UserScript==
(function () {
  'use strict';
  const W = window;
  if (W.__WL_AP_V32__) return;
  W.__WL_AP_V32__ = true;
  const TOP = W.top === W, HUD = 'wl-ap-hud', CONFIG = 'wl_autopager_cfg_v7', LEGACY_CONFIG = 'wl_autopager_cfg_v6';
  const POS = 'wl_ap_hud_position_v1', PROTOCOL = 'wl-ap-v4';
  const RECORDS = 'wl_ap_records_v32', TOTAL = 'wl_ap_total_v32';
  function storage(name) { try { return W[name]; } catch (_) { return null; } }
  const LS = storage('localStorage'), SS = storage('sessionStorage');
  const C = { enabled: true, minDwell: 20, jitterMin: 0, jitterMax: 9, maxPages: 300, mode: 'duration', autoAnswer: false, minAccuracy: 100, muteMedia: true };
  const S = { owner: false, pending: false, release: null, candidate: 0, lockError: '', paused: false,
    stopped: false, warning: '', reentry: false, key: '', elapsed: 0, jitter: 0, lastTick: Date.now(),
    awaiting: null, frame: null, busy: false, src: '', observer: null, reports: new Map(),
    grantAt: 0, grant: false, parentOrigin: '', action: '初始化', clicks: 0, clickedAt: 0, savedAt: 0,
    media: { count: 0, done: true, ready: true, playing: false, blocked: false }, hud: null, position: null, dragging: false,
    awaitingCompletion: false, autoBox: null, muteBox: null, progress: null, total: 0, records: {}, userPaused: false, totalSavedAt: 0, migrated: false,
    progressArmed: true, lastDocId: '', lastHref: '', oldDocId: '', oldHref: '', sectionSwitching: false, sectionChangedAt: 0,
    frameLoadedAt: 0, observedCurrent: '', switchKey: '', srcAtSwitch: '', docIdBySection: {}, hrefBySection: {},
    docId: Math.random().toString(36).slice(2) + Date.now().toString(36) };
  function read(storage, key, fallback) { try { return JSON.parse(storage.getItem(key)) || fallback; } catch (_) { return fallback; } }
  function write(storage, key, value) { try { storage.setItem(key, JSON.stringify(value)); return true; } catch (_) { return false; } }
  function clamp(n, a, b) { return Math.min(Math.max(n, a), Math.max(a, b)); }
  function sleep(ms) { return new Promise(resolve => setTimeout(resolve, ms)); }
  function fmt(s) { s = Math.max(0, Math.floor(s)); return s < 60 ? s + '秒' : Math.floor(s / 60) + '分' + s % 60 + '秒'; }
  function duration(value) { const m = /^(\d+(?:\.\d+)?)\s*(s|m|h|秒|分|分钟|时|小时)?$/i.exec(String(value).trim()); return m ? Number(m[1]) * (/^(m|分|分钟)$/i.test(m[2]) ? 60 : /^(h|时|小时)$/i.test(m[2]) ? 3600 : 1) : NaN; }
  function apply(obj) {
    if (!obj || typeof obj !== 'object') return;
    for (const key of ['minDwell', 'jitterMin', 'jitterMax']) if (typeof obj[key] === 'number' && Number.isFinite(obj[key])) C[key] = clamp(Math.round(obj[key]), 0, 86400);
    C.jitterMin = Math.min(C.jitterMin, C.jitterMax);
    if (typeof obj.enabled === 'boolean') C.enabled = obj.enabled;
    if (obj.mode === 'duration' || obj.mode === 'completion') C.mode = obj.mode;
    if (typeof obj.autoAnswer === 'boolean') C.autoAnswer = obj.autoAnswer;
    if (typeof obj.muteMedia === 'boolean' && obj.muteMedia !== C.muteMedia) {
      C.muteMedia = obj.muteMedia;
      setMuted(C.muteMedia);
    }
    if (typeof obj.minAccuracy === 'number' && Number.isFinite(obj.minAccuracy)) C.minAccuracy = clamp(Math.round(obj.minAccuracy), 0, 100);
  }
  function load() {
    let obj = read(LS, CONFIG, null) || read(SS, CONFIG, null);
    let migrated = false;
    if (!obj) {
      // 3.2.0/3.2.1 的旧配置迁移：保留停留、模式等设置，但自动作答必须重新手动开启。
      const old = read(LS, LEGACY_CONFIG, null) || read(SS, LEGACY_CONFIG, null);
      if (old && typeof old === 'object') {
        obj = { minDwell: old.minDwell, jitterMin: old.jitterMin, jitterMax: old.jitterMax, enabled: old.enabled,
          mode: old.mode, minAccuracy: old.minAccuracy, autoAnswer: false };
        migrated = true;
      }
    }
    if (!obj) { try { const i = W.name.indexOf('__WLAP_CFG__'); if (i >= 0) obj = JSON.parse(W.name.slice(i + '__WLAP_CFG__'.length)); } catch (_) {} }
    apply(obj);
    if (migrated) { C.autoAnswer = false; write(LS, CONFIG, C); write(SS, CONFIG, C); S.migrated = true; }
    S.total = Number(read(SS, TOTAL, 0)) || 0;
    S.records = read(LS, RECORDS, {}) || {};
  }
  function saveConfig() { write(LS, CONFIG, C); write(SS, CONFIG, C); broadcast(); }
  function jitter() { return C.jitterMin + Math.random() * (C.jitterMax - C.jitterMin); }
  function label(el) { return String(el && (el.innerText || el.textContent) || '').replace(/\s+/g, ' ').trim(); }
  function visible(el) { if (!el || !el.isConnected || !el.getClientRects().length) return false; const style = el.ownerDocument.defaultView.getComputedStyle(el); return style.display !== 'none' && style.visibility !== 'hidden' && Number(style.opacity || 1) > 0; }
  // course_disable is the site's completed marker. It must not be treated as a disabled next link.
  function enabled(el) { return !!el && !el.disabled && el.getAttribute('aria-disabled') !== 'true' && !el.closest('.disabled,.course_locked,.course_forbid,[disabled]'); }
  function itemFor(el) { return el && (el.matches('li[id^="liSCO_"]') ? el : el.closest('li[id^="liSCO_"]')); }
  function completed(el) { const item = itemFor(el); return !!item && item.classList.contains('course_disable'); }
  function currentItem() { const id = current(); return id ? document.getElementById('liSCO_' + id) : null; }
  function action(text) { S.action = text; paint(); }
  function frame() { return document.querySelector('#contentFrame'); }
  // URL 的 sco 在原生页内翻页后可能不变，以目录选中项为准。
  function current() { const el = document.querySelector('.courseware_current[id^="liSCO_"],.course_current[id^="liSCO_"]'); return el ? el.id.slice(6) : new URLSearchParams(location.search).get('sco') || ''; }
  function pageKey() { return location.pathname.toLowerCase() + '|' + (new URLSearchParams(location.search).get('cid') || '') + '|' + current(); }
  function sections() {
    return Array.from(document.querySelectorAll('li[id^="liSCO_"]'))
      .filter(li => li.classList.contains('courseware_list_1_4'))
      .map(li => ({ id: li.id.slice(6), el: li.querySelector('a[onclick*="SelectSCO"]') }))
      .filter(item => item.el);
  }
  function nextInfo() { const list = sections(), index = list.findIndex(item => item.id === current()); return { list, index, next: index >= 0 ? list[index + 1] || null : null }; }
  function nextButton() { return Array.from(document.querySelectorAll('a[href]')).find(el => /^javascript:\s*NextSCO\(\s*\)\s*;?$/i.test(el.getAttribute('href') || '')) || null; }
  // Web Locks 跨标签页互斥，复制标签页也不能共用控制权。
  function own() {
    if (!TOP) return false;
    if (navigator.locks && navigator.locks.request) {
      if (!S.owner && !S.pending) {
        S.pending = true;
        navigator.locks.request('welearn-autopager-v3', { ifAvailable: true }, async lock => {
          if (!lock) return;
          S.owner = true; S.lockError = ''; S.lastTick = Date.now();
          await new Promise(resolve => { S.release = resolve; });
          S.owner = false; S.release = null;
        }).catch(() => { S.owner = false; S.lockError = '互斥锁不可用，已停止操作'; }).finally(() => { S.pending = false; });
      }
      return S.owner;
    }
    S.owner = false; S.lockError = '浏览器不支持互斥锁，请使用新版 Edge / Chrome'; return false;
  }
  function release() {
    S.owner = false; broadcast(); if (S.release) S.release();
  }
  function warningText(text) { return /多开|多个页面|请勿同时|同时打开|另一课件|其他课件|另一处|已在其[它他]|学习票据|刷课|锁定|暂停学习|验证码|人机验证|验证后|30分钟没有|长时间未操作|登录.*(失效|过期)|已到达结尾/.test(text); }
  function scan() {
    if (visible(document.querySelector('#nocaptchaPopModal'))) return '请完成网站人工验证';
    for (const el of document.querySelectorAll('[role="dialog"],.modal,.dialog,.layui-layer,.alert,.toast,.message,.tip,.confirm')) {
      if (el.closest('#' + HUD) || !visible(el)) continue;
      const text = label(el); if (text.length < 800 && warningText(text)) return text.slice(0, 120);
    }
    return '';
  }
  function halt(text) { S.warning = text; S.paused = true; if (/另一课件|其他课件|票据|登录.*(失效|过期)|刷课|锁定|30分钟没有/.test(text)) S.reentry = true; saveDwell(); broadcast(); action(text); }
  function check() { const text = scan(); if (text) halt(text); return !!text; }
  function observeDialogs() { const original = W.alert; W.alert = function (message) { const text = String(message); if (warningText(text)) halt(text.slice(0, 120)); return original.call(W, message); }; }
  function running() { return C.enabled && S.owner && !S.paused && !S.stopped && !S.warning; }
  function shadowMedia(root, found, depth) {
    if (!root || depth > 3) return;
    for (const host of root.querySelectorAll('*')) {
      if (!host.shadowRoot) continue;
      for (const el of host.shadowRoot.querySelectorAll('audio,video')) found.add(el);
      shadowMedia(host.shadowRoot, found, depth + 1);
    }
  }
  function mediaEls(doc = document, depth = 0) {
    const found = new Set();
    try { for (const el of doc.querySelectorAll('audio,video')) found.add(el); } catch (_) {}
    try { shadowMedia(doc, found, 0); } catch (_) {}
    if (depth < 3) for (const el of doc.querySelectorAll('iframe,frame')) { try { if (el.contentDocument) for (const m of mediaEls(el.contentDocument, depth + 1)) found.add(m); } catch (_) {} }
    return Array.from(found);
  }
  // 立即把静音状态应用到当前媒体（包括正在播放的媒体）。
  function setMuted(flag) {
    for (const el of mediaEls()) {
      try {
        el.muted = flag;
        if (flag) el.dataset.wlMuted = '1'; else delete el.dataset.wlMuted;
      } catch (_) {}
    }
  }
  const MEDIA = new WeakMap();
  function mediaRecord(el) {
    let page = '';
    try { page = el.ownerDocument.defaultView.location.href; } catch (_) {}
    const key = JSON.stringify([page, el.getAttribute('src'), el.currentSrc,
      Array.from(el.querySelectorAll('source'), s => [s.getAttribute('src'), s.type, s.media])]);
    let record = MEDIA.get(el);
    if (!record) {
      record = { key: key, stream: el.srcObject, done: false };
      MEDIA.set(el, record);
      // 课件会在 ended 回调中归零；先捕获事件，保留本媒体的播放完成状态。
      el.addEventListener('ended', () => { mediaRecord(el).done = true; }, true);
      el.addEventListener('emptied', () => {
        mediaRecord(el).done = false;
        delete el.dataset.wlPlayAt;
      }, true);
    } else if (record.key !== key || record.stream !== el.srcObject) {
      record.key = key; record.stream = el.srcObject; record.done = false;
      delete el.dataset.wlPlayAt;
    }
    return record;
  }
  function mediaEnded(el) { return mediaRecord(el).done || el.ended; }
  function localMedia() { const list = mediaEls(); return { count: list.length, done: list.every(el => mediaEnded(el) || Number.isFinite(el.duration) && el.duration > 0 && el.currentTime >= el.duration - 0.5), playing: list.some(el => !el.paused && !mediaEnded(el)), blocked: list.some(el => el.paused && !mediaEnded(el)), ready: true }; }
  // 自动播放并静音：静音是浏览器允许无手势自动播放的关键；失败后每隔几秒重试，不再永久放弃。
  function play() {
    for (const el of mediaEls()) {
      if (mediaEnded(el) || !el.paused) continue;
      try { if (!el.hasAttribute('playsinline')) el.setAttribute('playsinline', ''); } catch (_) {}
      if (C.muteMedia) { try { el.muted = true; el.defaultMuted = true; el.dataset.wlMuted = '1'; } catch (_) {} }
      else if (el.dataset.wlMuted === '1') { try { el.muted = false; delete el.dataset.wlMuted; } catch (_) {} }
      const now = Date.now(), last = Number(el.dataset.wlPlayAt || 0);
      if (last && now - last < 4000) continue;
      el.dataset.wlPlayAt = String(now);
      try {
        const p = el.play();
        if (p && p.catch) p.catch(err => { el.dataset.wlPlayError = String(err && err.name || err); });
      } catch (e) { el.dataset.wlPlayError = String(e && e.name || e); }
    }
  }
  function children() { return TOP ? (frame() ? [frame()] : []) : Array.from(document.querySelectorAll('iframe,frame')); }
  function origin(el) { try { return new URL(el.getAttribute('src') || '', location.href).origin; } catch (_) { return ''; } }

  // ===== 3.2 课件页引擎：读取课件内答案、填充、核算完成度与正确率 =====
  // 完成度与正确率全部取自课件自身的 etItem 状态机：
  //   完成度 = 已完成进度项 / 全部进度项（[noprogress] 不计，[notscored] 计入）
  //   正确率 = 计分项得分 / 计分项总权重
  const E = { page: '', busy: false, done: false, report: null, at: 0, error: '', blockReason: '', issues: [], tries: 0, submitTries: 0, testMode: false };
  const P_SELECTOR = ['et-blank:not(et-multi-blank et-blank,et-tick-blank et-blank)', 'et-multi-blank', 'et-choice', 'et-select',
    'et-tof', 'et-recorder:not(et-media et-recorder)', 'et-follow-me', 'et-talk', 'et-score-table', 'et-crossword:not([static])',
    'et-tick-list', 'et-matching', 'et-sort', 'et-mindmap:not([static])', 'et-writing', 'et-translate', 'et-tick-blank',
    'et-checking', 'et-camera:not(et-media et-camera)', 'et-media', 'et-multi-noinput'].join(',');
  let SCACHE = { at: 0, list: [] };

  function isCourseware() { return !!(document.querySelector('et-item') && W.angular); }
  function injector() {
    if (!W.angular) return null;
    try { return W.angular.element(document.documentElement).injector() || W.angular.element(document.body).injector(); } catch (_) { return null; }
  }
  function scopes() {
    if (Date.now() - SCACHE.at < 120 && SCACHE.list.length) return SCACHE.list;
    const inj = injector(); if (!inj) return [];
    let root; try { root = inj.get('$rootScope'); } catch (_) { return []; }
    const list = [], seen = new Set(), stack = [root];
    while (stack.length) {
      const s = stack.pop(); if (!s || seen.has(s)) continue; seen.add(s); list.push(s);
      if (s.$$childHead) stack.push(s.$$childHead);
      if (s.$$nextSibling) stack.push(s.$$nextSibling);
    }
    SCACHE = { at: Date.now(), list };
    return list;
  }
  function ctrlFor(el) {
    if (!W.angular) return null;
    const tag = el.tagName.toLowerCase();
    const names = { 'et-blank': 'etBlank', 'et-multi-blank': 'etMultiBlank', 'et-choice': 'etChoice', 'et-select': 'etSelect',
      'et-tof': 'etTof', 'et-tick-blank': 'etTickBlank', 'et-writing': 'etWriting', 'et-translate': 'etTranslate',
      'et-score-table': 'etScoreTable', 'et-media': 'etMedia', 'et-recorder': 'etRecorder', 'et-multi-noinput': 'etMultiNoinput',
      'et-talk': 'etTalk', 'et-follow-me': 'etFollowMe', 'et-camera': 'etCamera' };
    for (const name of [names[tag], 'etBlank'].filter(Boolean)) {
      try { const c = W.angular.element(el).controller(name); if (c) return c; } catch (_) {}
    }
    return null;
  }
  function findItem() {
    for (const s of scopes()) { const item = s && s.item; if (item && typeof item.submit === 'function' && item.id) return item; }
    return null;
  }
  function itemEl() { return document.querySelector('et-item'); }
  function route() { return (location.hash || location.pathname).replace(/^#\/?/, ''); }
  function digest(fn) {
    const inj = injector(); const root = inj && inj.get('$rootScope');
    if (!root) { fn(); return; }
    try {
      if (root.$$phase) { fn(); root.$evalAsync(() => {}); }
      else root.$apply(fn);
    } catch (e) { try { fn(); } catch (_) {} }
  }
  function trim(v) { return String(v == null ? '' : v).replace(/\u00a0/g, ' ').trim(); }
  function keyText(c) { if (!c || !Array.isArray(c.key)) return ''; for (const k of c.key) { if (trim(k)) return String(k); } return ''; }
  function isNotScored(el) { return !!(el.hasAttribute('notscored') || el.closest('[notscored]')); }
  function progressEls() {
    const root = itemEl(); if (!root) return [];
    let list = [];
    try {
      if (W.jQuery) list = W.jQuery(root).find(P_SELECTOR).toArray();
      else list = Array.from(root.querySelectorAll(P_SELECTOR));
    } catch (_) { list = []; }
    return list.filter(el => !el.closest('[noprogress]'));
  }
  function componentComplete(el, c) {
    const tag = el.tagName.toLowerCase();
    if (tag === 'et-checking') return true;
    if (!c) return null;
    if (tag === 'et-blank') return trim(c.value).length > 0;
    if (tag === 'et-multi-blank') return Array.isArray(c.value) && c.value.length > 0 && c.value.every(v => trim(v));
    if (tag === 'et-multi-noinput') return trim(c.value).length > 0;
    if (tag === 'et-choice' || tag === 'et-select' || tag === 'et-tof') return (Array.isArray(c.value) ? c.value.length : trim(c.value).length) > 0;
    if (tag === 'et-tick-blank') return !!(c.tickedItems && c.tickedItems.length);
    if (tag === 'et-recorder') return (c.submitFlag || Number(c.recordingCount) > 0 || Number(c.score) > 0) ? true : null;
    // 口语/摄像头的原生进度按录制次数判定；跟读必须完成全部句子。
    if (tag === 'et-talk' || tag === 'et-camera') return Number(c.recordingCount) > 0 ? true : null;
    if (tag === 'et-follow-me') return (typeof c.isCompleted === 'function' ? c.isCompleted() : c.isCompleted) === true ? true : null;
    if (tag === 'et-media') {
      const media = el.querySelector('video,audio');
      return media ? !!mediaEnded(media) : (c.isCompleted === true ? true : null);
    }
    if (tag === 'et-writing' || tag === 'et-translate') { const ta = el.querySelector('textarea'); return trim((c && c.value) || (ta && ta.value)).length > 0; }
    return null;
  }
  function refText(el) {
    const root = el.closest('et-item'); if (!root) return '';
    for (const r of root.querySelectorAll('[visible-on-key],.visible-on-key')) {
      const text = trim(r.innerText);
      if (text && text.length <= 400 && (el.compareDocumentPosition(r) & Node.DOCUMENT_POSITION_FOLLOWING)) return text;
    }
    return '';
  }
  function analyze() {
    if (!isCourseware()) return null;
    const item = findItem(); if (!item) return null;
    const list = progressEls();
    let done = 0, unknown = 0, notscored = 0, voice = 0;
    const missing = [];
    const VOICE_TAGS = { 'et-recorder': 1, 'et-talk': 1, 'et-camera': 1, 'et-follow-me': 1 };
    for (const el of list) {
      const tag = el.tagName.toLowerCase();
      if (isNotScored(el)) notscored++;
      let state = null;
      try { state = componentComplete(el, ctrlFor(el)); } catch (_) { state = null; }
      if (state === true) done++;
      else if (state === false) missing.push({ tag: tag, index: el.getAttribute('et-index') || '', reason: 'empty' });
      else { unknown++; missing.push({ tag: tag, index: el.getAttribute('et-index') || '', reason: 'manual' }); }
      if (VOICE_TAGS[tag] && state !== true) voice++;
    }
    const info = item.scormInfo || {};
    const rawSite = info.progressMeasure;
    const siteNum = Number(rawSite);
    const siteValid = rawSite !== '' && rawSite != null && Number.isFinite(siteNum);
    const siteCompletion = siteValid ? Math.round(clamp(siteNum, 0, 1) * 100) : null;
    const localRatio = list.length ? done / list.length : null;
    const localCompletion = localRatio == null ? null : Math.round(localRatio * 100);
    // 课件 SCORM 值可能滞后于组件状态；显示与闸门取网站值与本地已完成的较大者，避免卡在旧完成度。
    let completion;
    if (localCompletion != null) completion = Math.max(siteCompletion == null ? 0 : siteCompletion, localCompletion);
    else completion = siteCompletion == null ? 100 : siteCompletion;
    // 无交互页由课件 3 秒后自行 commit，控制器的 scormInfo 不会回填，按结构完成处理。
    if (!list.length && item.type === 'no_interaction') completion = 100;
    const accuracy = Math.round(Number(info.score && info.score.scaled) || 0);
    const report = { page: route(), href: location.pathname + (location.hash || ''), docId: S.docId, itemId: item.id, type: item.type || '', submitted: !!item.isSubmitted, browse: !!item.isBrowseMode, endTab: !!item.isEndTab,
      total: list.length, done: done, unknown: unknown, notscored: notscored, manual: unknown, voice: voice, completion: completion,
      accuracy: accuracy, raw: Number(info.score && info.score.raw) || 0, siteCompletion: siteCompletion, localCompletion: localCompletion, missing: missing.slice(0, 10),
      error: E.error || '', minAccuracy: C.minAccuracy, issues: E.issues.length, at: Date.now() };
    const reason = gateFor(report);
    report.blockReason = report.submitted ? '' : reason;
    report.canSubmit = !report.submitted && !reason;
    return report;
  }
  // 提交闸门：完成度、缺答案、正确率三项都满足才允许自动提交。
  function gateFor(a) {
    if (!a) return '未读取到课件状态';
    if (a.completion < 100) return '完成度 ' + a.completion + '%';
    if (E.issues.length) return '有 ' + E.issues.length + ' 项答案缺失或无法解析';
    if (a.type === 'objective' && a.accuracy < C.minAccuracy) return '正确率 ' + a.accuracy + '% 低于 ' + C.minAccuracy + '%';
    return '';
  }
  function fillOne(el, opts) {
    const tag = el.tagName.toLowerCase();
    const index = el.getAttribute('et-index') || '';
    const keep = opts.keepAnswered !== false;
    if (opts.skipNotScored && isNotScored(el)) return { tag: tag, index: index, status: 'skipped' };
    const c = ctrlFor(el);
    if (!c) return { tag: tag, index: index, status: 'no-controller' };
    if (keep && componentComplete(el, c) === true) return { tag: tag, index: index, status: 'kept' };
    if (tag === 'et-blank') {
      const text = keyText(c) || refText(el);
      if (!text) return { tag: tag, index: index, status: 'no-answer' };
      c.value = text;
      return { tag: tag, index: index, status: 'filled', text: text.slice(0, 60) };
    }
    if (tag === 'et-multi-noinput') {
      const text = keyText(c) || refText(el);
      if (!text) return { tag: tag, index: index, status: 'no-answer' };
      c.value = text;
      return { tag: tag, index: index, status: 'filled', text: text.slice(0, 60) };
    }
    if (tag === 'et-multi-blank') {
      const kids = Array.from(el.querySelectorAll('et-blank'));
      let filled = 0, kept = 0, missing = 0;
      for (const kid of kids) {
        const k = ctrlFor(kid); if (!k) { missing++; continue; }
        if (keep && trim(k.value)) { kept++; continue; }
        const text = keyText(k) || refText(kid);
        if (!text) { missing++; continue; }
        k.value = text; filled++;
      }
      if (missing && !filled) return { tag: tag, index: index, status: 'no-answer', missing: missing };
      return { tag: tag, index: index, status: filled ? 'filled' : 'kept', filled: filled, kept: kept, missing: missing };
    }
    if (tag === 'et-choice') {
      if (!c.key || !c.key.length) return { tag: tag, index: index, status: 'no-key' };
      c.value = c.key.slice().sort((a, b) => Number(a) - Number(b));
      return { tag: tag, index: index, status: 'filled', key: c.key.slice() };
    }
    if (tag === 'et-tof') {
      if (!c.key || !c.key.length) return { tag: tag, index: index, status: 'no-key' };
      const raw = String(c.key[0]).toLowerCase();
      c.value = [raw.charAt(0) === 't' ? 't' : 'f'];
      return { tag: tag, index: index, status: 'filled', key: c.value[0] };
    }
    if (tag === 'et-select') {
      if (!c.key || !c.key.length) return { tag: tag, index: index, status: 'no-key' };
      c.value = 'choice' + (Number(c.key[0]) + 1);
      try { if (typeof c.updateStatus === 'function') c.updateStatus(); } catch (_) {}
      return { tag: tag, index: index, status: 'filled', key: c.key[0] };
    }
    if (tag === 'et-tick-blank') {
      if (!c.key || !c.key.length) return { tag: tag, index: index, status: 'no-key' };
      c.tickedItems = c.key.slice();
      for (const kid of el.querySelectorAll('et-blank')) {
        const k = ctrlFor(kid); if (!k) continue;
        if (keep && trim(k.value)) continue;
        const text = keyText(k); if (text) k.value = text;
      }
      return { tag: tag, index: index, status: 'filled', key: c.key.slice() };
    }
    if (tag === 'et-writing' || tag === 'et-translate') {
      const text = refText(el);
      if (!text) return { tag: tag, index: index, status: 'no-answer' };
      try { if ('value' in c) c.value = text; } catch (_) {}
      const ta = el.querySelector('textarea,[contenteditable]');
      if (ta) { ta.value !== undefined ? (ta.value = text) : (ta.textContent = text); ta.dispatchEvent(new Event('input', { bubbles: true })); }
      return { tag: tag, index: index, status: 'filled', text: text.slice(0, 40) };
    }
    return { tag: tag, index: index, status: 'manual' };
  }
  const ISSUE_STATUS = /^(no-key|no-answer|no-controller|error)$/;
  function fillPage(opts) {
    opts = opts || {};
    const item = findItem(); if (!item) return { actions: [], report: null };
    const list = progressEls();
    const actions = [];
    digest(() => {
      for (const el of list) {
        try { actions.push(fillOne(el, opts)); } catch (e) { actions.push({ tag: el.tagName.toLowerCase(), index: el.getAttribute('et-index') || '', status: 'error', error: String(e && e.message || e) }); }
      }
    });
    E.issues = actions.filter(a => ISSUE_STATUS.test(a.status));
    return { actions: actions, report: analyze() };
  }
  function clickEl(el) { const target = el.querySelector('button') || el; try { target.click(); } catch (_) {} }
  function pageToken() { const item = findItem(); return { page: route(), itemId: item ? item.id : '', at: Date.now() }; }
  // 每次等待后、点击提交/确认前都复查：开关、授权、页面身份。
  function canContinue(token) {
    if (!C.enabled || !C.autoAnswer || S.warning) return false;
    if (!E.testMode && !granted()) return false;
    if (token && (token.page !== route() || token.itemId !== (findItem() && findItem().id))) return false;
    return true;
  }
  function cancelDialog() {
    const btn = Array.from(document.querySelectorAll('button')).find(el => visible(el) && /^(取消|关闭|Cancel|Close)$/i.test(label(el)) && !/primary/i.test(el.className));
    if (btn) clickEl(btn);
  }
  async function submitPage(token) {
    token = token || pageToken();
    if (!canContinue(token)) return { ok: false, cancelled: true };
    const item = findItem(); if (!item) return { ok: false, reason: 'no-item' };
    if (item.isSubmitted) return { ok: true, already: true };
    let guard = 0;
    while (!item.isEndTab && guard++ < 8) {
      if (!canContinue(token)) return { ok: false, cancelled: true };
      const next = Array.from(document.querySelectorAll('et-button.nextTab-btn')).find(el => visible(el) && !el.classList.contains('ng-hide'));
      if (!next) break;
      clickEl(next); await sleep(350);
      if (!canContinue(token)) { cancelDialog(); return { ok: false, cancelled: true }; }
    }
    const blocked = gateFor(analyze());
    if (blocked) return { ok: false, blocked: blocked };
    if (!canContinue(token)) return { ok: false, cancelled: true };
    const submit = Array.from(document.querySelectorAll('et-button')).find(el => /submit/i.test(label(el)) && visible(el) && !el.classList.contains('ng-hide'));
    if (!submit) return { ok: false, reason: 'no-submit' };
    clickEl(submit); await sleep(500);
    if (!canContinue(token)) { cancelDialog(); return { ok: false, cancelled: true }; }
    // 等待确认弹窗期间答案可能被改动：点击“继续提交”前重新核算闸门。
    const blockedAfterSubmit = gateFor(analyze());
    if (blockedAfterSubmit) { cancelDialog(); return { ok: false, blocked: blockedAfterSubmit }; }
    const confirm = Array.from(document.querySelectorAll('button')).find(el => visible(el) && /继续提交|确认提交|^提交$|^确定$|^OK$/i.test(label(el)) && /primary/i.test(el.className));
    if (confirm) {
      if (!canContinue(token)) { cancelDialog(); return { ok: false, cancelled: true }; }
      const blockedAtConfirm = gateFor(analyze());
      if (blockedAtConfirm) { cancelDialog(); return { ok: false, blocked: blockedAtConfirm }; }
      clickEl(confirm); await sleep(600);
    }
    for (let i = 0; i < 10 && !(findItem() && findItem().isSubmitted); i++) await sleep(200);
    const after = findItem();
    return { ok: !!(after && after.isSubmitted), reason: after && after.isSubmitted ? '' : 'not-submitted', report: analyze() };
  }
  async function runPage(opts) {
    opts = opts || {};
    if (!isCourseware()) return null;
    const token = pageToken();
    E.testMode = true;
    try {
      const first = analyze();
      if (!first) return null;
      if (first.submitted || first.browse) return first;
      if (!C.autoAnswer) return first;
      fillPage(opts);
      await sleep(opts.wait == null ? 600 : opts.wait);
      if (!canContinue(token)) return analyze();
      const filled = analyze();
      if (opts.submit !== false && filled.completion >= 100 && !filled.submitted && !gateFor(filled)) {
        await submitPage(token);
        await sleep(1200);
      }
      E.report = analyze();
      return E.report;
    } finally { E.testMode = false; }
  }
  async function engineStep() {
    if (!isCourseware() || !C.autoAnswer || !granted()) return;
    const item = findItem(); if (!item) return;
    const page = route() + '|' + item.id;
    if (E.page !== page) { E.page = page; E.done = false; E.busy = false; E.error = ''; E.blockReason = ''; E.issues = []; E.tries = 0; E.submitTries = 0; }
    if (E.busy) return;
    const a = analyze(); if (!a) return;
    E.report = a; E.at = Date.now();
    if (a.submitted || a.browse) { E.done = true; return; }
    if (!a.total) return; // 无交互题由课件自己 commit
    if (a.completion >= 100 && document.querySelector('et-checking')) { E.done = true; return; } // et-checking 由课件自行提交
    if (E.done) {
      const clear = a.completion >= 100 && !a.submitted && (a.type !== 'objective' || a.accuracy >= C.minAccuracy);
      if (!clear) return;
      E.done = false; E.error = ''; E.blockReason = ''; E.issues = [];
    }
    E.busy = true;
    const token = pageToken();
    try {
      E.issues = [];
      fillPage();
      await sleep(600);
      if (!canContinue(token)) { E.report = analyze(); return; }
      let b = analyze();
      let reason = gateFor(b);
      if (!reason && b.completion >= 100 && !b.submitted && E.submitTries < 3) {
        E.submitTries++;
        const result = await submitPage(token);
        if (result.cancelled) { E.report = analyze(); return; }
        await sleep(600);
        b = analyze(); reason = gateFor(b);
      }
      E.report = b;
      if (b.submitted) { E.done = true; E.blockReason = ''; }
      else if (reason) {
        E.blockReason = reason;
        if (/正确率/.test(reason) || b.manual > 0) E.done = true;
        else { E.tries = (E.tries || 0) + 1; if (E.tries >= 3) E.done = true; }
      } else if (b.completion >= 100 && E.submitTries >= 3) {
        E.done = true; E.error = '课件提交按钮不可用或提交未生效';
      }
    } catch (e) { E.error = String(e && e.message || e); }
    finally { E.busy = false; }
  }
  function engineTick() { if (isCourseware() && C.autoAnswer && granted()) engineStep(); }
  // 只读进度上报：关闭自动作答时也每秒刷新，面板和完成度模式仍能看到课件进度。
  function refreshProgress() {
    if (!isCourseware()) return;
    try { const a = analyze(); if (a) E.report = a; } catch (_) {}
  }

  // 供自动化测试与诊断使用；正式运行时同样可用。
  W.__WLAP_ENGINE__ = { version: '3.3.3', isCourseware: isCourseware, analyze: analyze, fillPage: fillPage, submitPage: submitPage,
    runPage: runPage, route: route, config: C, gate: gateFor, mediaCount: () => mediaEls().length,
    mediaState: () => mediaEls().map(e => ({ muted: !!e.muted, paused: !!e.paused, ended: !!e.ended })), state: () => ({ busy: E.busy, done: E.done, error: E.error, blockReason: E.blockReason, issues: E.issues, report: E.report, grant: S.grant, grantAt: S.grantAt }) };

  function granted() { return TOP ? (C.enabled && S.owner && !S.warning && !S.stopped && !S.userPaused && !S.busy && !S.awaiting && !S.sectionSwitching) : S.grant && Date.now() - S.grantAt < 7000 && !S.warning; }
  function broadcast() {
    for (const el of children()) { const target = origin(el); if (!target || target === 'null') continue; try { el.contentWindow.postMessage({ protocol: PROTOCOL, type: 'config', cfg: C, allow: granted() }, target); } catch (_) {} }
  }
  function summary() {
    const m = localMedia();
    for (const el of children()) {
      let same = false; try { same = !!el.contentDocument; } catch (_) {}
      if (same) continue;
      const report = S.reports.get(el.contentWindow);
      if (!report || report.origin !== origin(el) || Date.now() - report.at > 7000) { m.ready = false; continue; }
      m.count += report.media.count; m.done = m.done && report.media.done; m.ready = m.ready && report.media.ready;
      m.playing = m.playing || report.media.playing; m.blocked = m.blocked || report.media.blocked;
    }
    return m;
  }
  function messages() {
    if (!TOP) { try { S.parentOrigin = new URL(document.referrer).origin; } catch (_) {} if (!S.parentOrigin && location.ancestorOrigins) S.parentOrigin = location.ancestorOrigins[0] || ''; }
    W.addEventListener('message', event => {
      const d = event.data; if (!d || d.protocol !== PROTOCOL) return;
      if (!TOP && event.source === W.parent && event.origin === S.parentOrigin && d.type === 'config') { apply(d.cfg); S.grant = d.allow === true; S.grantAt = Date.now(); broadcast(); return; }
      const el = children().find(el => el.contentWindow === event.source && origin(el) === event.origin); if (!el) return;
      if (d.type === 'request') { broadcast(); return; }
      if (d.type === 'status' && d.media && Number.isFinite(d.media.count)) {
        S.reports.set(event.source, { origin: event.origin, at: Date.now(), media: { count: clamp(d.media.count, 0, 1000), done: d.media.done === true, ready: d.media.ready === true, playing: d.media.playing === true, blocked: d.media.blocked === true } });
        if (typeof d.warning === 'string' && d.warning) halt(d.warning.slice(0, 120));
        if (d.progress && typeof d.progress === 'object' && Number.isFinite(Number(d.progress.completion))) {
          const p = d.progress;
          if (!acceptProgress(p)) return;
          const siteC = p.siteCompletion == null ? null : clamp(Math.round(Number(p.siteCompletion)), 0, 100);
          const localC = p.localCompletion == null ? null : clamp(Math.round(Number(p.localCompletion)), 0, 100);
          S.progress = { page: String(p.page || ''), href: String(p.href || ''), completion: clamp(Math.round(Number(p.completion)), 0, 100), accuracy: clamp(Math.round(Number(p.accuracy)), 0, 100),
            siteCompletion: siteC, localCompletion: localC,
            total: clamp(Number(p.total) || 0, 0, 1000), done: clamp(Number(p.done) || 0, 0, 1000), manual: clamp(Number(p.manual) || 0, 0, 1000), voice: clamp(Number(p.voice) || 0, 0, 1000),
            submitted: p.submitted === true, type: String(p.type || ''), error: String(p.error || ''), blockReason: String(p.blockReason || ''),
            minAccuracy: clamp(Math.round(Number(p.minAccuracy == null ? 100 : p.minAccuracy)), 0, 100), issues: clamp(Number(p.issues) || 0, 0, 1000), at: Date.now(), origin: event.origin };
          recordAuto(S.progress);
        }
      }
    });
  }
  // 进度报告必须来自当前小节：用每次文档加载的 docId 和课件 href 双重核对。
  function acceptProgress(p) {
    const docId = String(p.docId || '');
    const href = String(p.href || '');
    if (S.sectionSwitching) {
      const srcNow = frame() ? (frame().getAttribute('src') || '') : '';
      const srcChanged = srcNow !== S.srcAtSwitch;
      const hasOld = !!(S.oldDocId || S.oldHref);
      let confirmed;
      if (!hasOld) {
        // 没有旧文档信息时，只接受切换后真正发生的 iframe 加载确认，避免迟到首报串节。
        confirmed = srcChanged && S.frameLoadedAt > S.sectionChangedAt;
      } else {
        const freshDoc = !!docId && docId !== S.oldDocId && (href !== S.oldHref || srcChanged);
        const movedHref = !!href && !!S.oldHref && href !== S.oldHref;
        const reloaded = srcChanged && S.frameLoadedAt > S.sectionChangedAt;
        confirmed = freshDoc || movedHref || reloaded;
      }
      if (!confirmed) return false;
      S.sectionSwitching = false;
      S.progressArmed = true;
    }
    S.lastDocId = docId; S.lastHref = href;
    const key = pageKey();
    if (!S.docIdBySection[key]) { S.docIdBySection[key] = docId; S.hrefBySection[key] = href; }
    const keys = Object.keys(S.docIdBySection);
    if (keys.length > 8) for (const k of keys.slice(0, keys.length - 8)) { delete S.docIdBySection[k]; delete S.hrefBySection[k]; }
    return true;
  }
  function recordAuto(a) {
    // 只有引擎确认提交成功的小节才记入历史；被闸门拦截的 100% 不算提交。
    if (!TOP || !a || a.submitted !== true) return;
    const key = pageKey();
    const old = S.records[key];
    if (old && old.completion === a.completion && old.accuracy === a.accuracy && old.submitted === true) return;
    S.records[key] = { completion: a.completion, accuracy: a.accuracy, submitted: true, verified: true,
      type: a.type || '', scored: a.type === 'objective', dwell: Math.round(S.elapsed / 1000), at: Date.now() };
    write(LS, RECORDS, S.records);
  }
  // 目录出现 course_disable 是可验证的网站完成标记；无交互/et-checking 页只能等这个标记。
  function recordVerified() {
    if (!TOP || !completed(currentItem())) return;
    const a = S.progress;
    if (!a || Date.now() - a.at > 15000 || Number(a.completion) < 100) return;
    const key = pageKey();
    const old = S.records[key];
    if (old && (old.submitted === true || old.verified === true)) return;
    S.records[key] = { completion: clamp(Math.round(Number(a.completion) || 0), 0, 100), accuracy: clamp(Math.round(Number(a.accuracy) || 0), 0, 100),
      submitted: false, verified: true, type: a.type || '', scored: a.type === 'objective',
      dwell: Math.round(S.elapsed / 1000), at: Date.now() };
    write(LS, RECORDS, S.records);
  }
  function recordStats() {
    const all = Object.keys(S.records).map(k => S.records[k]).filter(r => r && (r.submitted === true || r.verified === true));
    const scored = all.filter(r => r.scored === true);
    const accuracy = scored.length ? Math.round(scored.reduce((sum, r) => sum + (Number(r.accuracy) || 0), 0) / scored.length) : 0;
    return { count: all.length, accuracy: accuracy };
  }
  function verifiedComplete() {
    if (completed(currentItem())) return true;
    return !!(S.progress && S.progress.submitted && S.progress.completion >= 100 && Date.now() - S.progress.at < 15000);
  }
  // 含未完成的人工语音项：只挂停留时长，不要求完成度/提交。
  function voicePending() { return !!(S.progress && Number(S.progress.voice) > 0 && Date.now() - S.progress.at < 15000); }
  function completionWaitText() {
    const a = S.progress;
    if (voicePending()) return '人工语音页：按停留时长放行';
    if (a && !a.submitted && a.total > 0) {
      if (a.blockReason) return '已暂停自动提交：' + a.blockReason + '，请人工核对';
      if (a.manual > 0 && a.completion < 100) return '完成度 ' + a.completion + '%：有 ' + a.manual + ' 项需人工完成（录音/口语/媒体等）';
      return '完成度 ' + a.completion + '%（' + a.done + '/' + a.total + ' 项），等待自动提交';
    }
    return '网站尚未标记本节完成，请按课件要求完成并提交';
  }
  function reportParent() { if (S.parentOrigin && S.parentOrigin !== 'null') try { W.parent.postMessage({ protocol: PROTOCOL, type: 'status', media: summary(), warning: S.warning, progress: E.report }, S.parentOrigin); } catch (_) {} }
  function saveDwell() { if (TOP) write(SS, 'wl_ap_dwell_v3', { key: S.key, elapsed: S.elapsed, jitter: S.jitter }); }
  function saveTotal() { if (TOP) write(SS, TOTAL, Math.round(S.total)); }
  // 同一次切换只初始化一次；先到的新进度不会被下一次 tick 再重置。
  function beginSectionSwitch(key) {
    if (!key || S.switchKey === key) return;
    S.switchKey = key;
    const oldKey = S.key;
    S.oldDocId = S.lastDocId || S.docIdBySection[oldKey] || '';
    S.oldHref = S.lastHref || S.hrefBySection[oldKey] || '';
    S.srcAtSwitch = frame() ? (frame().getAttribute('src') || '') : '';
    S.sectionChangedAt = Date.now();
    S.sectionSwitching = true;
    S.awaiting = null;
    S.progress = null;
    S.progressArmed = false;
    S.key = key; S.elapsed = 0; S.jitter = jitter(); S.lastTick = Date.now();
    saveDwell();
    broadcast();
  }
  function reset(key = pageKey()) { S.key = key; S.elapsed = 0; S.jitter = jitter(); S.lastTick = Date.now(); S.progress = null; saveDwell(); }
  function restore() { const d = read(SS, 'wl_ap_dwell_v3', null); if (d && d.key === S.key && Number.isFinite(d.elapsed) && d.elapsed >= 0) { S.elapsed = clamp(d.elapsed, 0, 86400000); if (Number.isFinite(d.jitter)) S.jitter = clamp(d.jitter, C.jitterMin, C.jitterMax); } }
  function bindFrame() {
    const el = frame(); if (!el || el === S.frame) return;
    if (S.observer) S.observer.disconnect(); S.frame = el; S.src = el.getAttribute('src') || '';
    el.addEventListener('load', () => { if (el !== frame()) return; S.busy = false; S.reports.clear(); S.progress = null; S.progressArmed = true; S.frameLoadedAt = Date.now(); const pk = pageKey(); if (S.awaiting && pk !== S.awaiting.key) { S.awaiting = null; beginSectionSwitch(pk); } else S.lastTick = Date.now(); broadcast(); });
    S.observer = new MutationObserver(() => { const src = el.getAttribute('src') || ''; if (src === S.src) return; S.src = src; S.busy = true; S.reports.clear(); S.progress = null; S.progressArmed = false; reset(); broadcast(); });
    S.observer.observe(el, { attributes: true, attributeFilter: ['src'] });
  }
  function stats() { return read(SS, 'wl_ap_stats_v3', { clicks: 0 }); }
  function next(manual = false) {
    check();
    if (!own() || !running() || S.awaiting || S.busy) { action(S.warning || S.lockError || (!S.owner ? '另一标签页持有控制权' : '请先继续，或等待课件加载')); return false; }
    if (Date.now() - S.clickedAt < 2500) return false;
    const info = nextInfo();
    if (info.index < 0) { S.paused = true; action('找不到当前目录小节，请重新进入课件'); broadcast(); return false; }
    if (!info.next) { S.stopped = true; action('已到课程末尾'); broadcast(); return false; }
    const voiceBypass = C.mode === 'completion' && !verifiedComplete() && voicePending();
    if (C.mode === 'completion' && !verifiedComplete() && !voiceBypass) {
      S.paused = true;
      S.awaitingCompletion = true;
      action(completionWaitText());
      broadcast();
      return false;
    }
    if (!enabled(info.next.el)) { S.paused = true; action('下一小节未开放，请先完成当前要求'); broadcast(); return false; }
    const button = nextButton();
    if (!button || !visible(button) || !enabled(button)) { S.paused = true; action('网站下一节按钮不可用，请检查页面'); broadcast(); return false; }
    S.clickedAt = Date.now(); S.awaiting = { key: pageKey(), at: Date.now() }; broadcast();
    try {
      button.click(); // 唯一导航入口，保留原生 EndSCO / SelectSCO / StartSCO 流程。
      S.clicks++; const count = stats(); count.clicks = (Number(count.clicks) || 0) + 1; write(SS, 'wl_ap_stats_v3', count);
      action((manual ? '手动' : '定时') + '翻到：' + label(info.next.el).slice(0, 40) + (voiceBypass ? '（人工语音页，按停留放行）' : '')); return true;
    } catch (_) { S.awaiting = null; S.paused = true; action('原生翻页失败，已暂停'); return false; }
  }
  function tick() {
    const now = Date.now(), delta = now - S.lastTick; S.lastTick = now; check();
    if (!TOP) { if (granted()) play(); engineTick(); refreshProgress(); broadcast(); reportParent(); return; } // 子框架永远不导航。
    own(); bindFrame(); const key = pageKey(); if (key !== S.key) beginSectionSwitch(key); recordVerified(); broadcast();
    if (!C.enabled) { action('已关闭'); return; }
    if (!S.owner) { action(S.lockError || '其他标签页正在控制，当前页待命'); return; }
    // 本地学习时长独立累计：等待完成、自动作答的时间也计入，但系统睡眠的大间隔不计入。
    if (delta >= 0 && delta <= 15000) { S.total += delta / 1000; }
    if (now - S.totalSavedAt > 5000) { S.totalSavedAt = now; saveTotal(); }
    if (S.warning || S.stopped) { paint(); return; }
    if (S.awaitingCompletion) {
      if (S.userPaused) { paint(); return; }
      if (verifiedComplete() || voicePending()) {
        const voice = !verifiedComplete() && voicePending();
        S.awaitingCompletion = false; S.paused = false; S.lastTick = now;
        action(voice ? '人工语音页：按停留时长放行' : '网站已标记本节完成，继续推进');
      } else { action(completionWaitText()); paint(); return; }
    }
    if (S.paused) { paint(); return; }
    if (S.awaiting) { if (now - S.awaiting.at > 30000) { S.awaiting = null; S.paused = true; action('30秒内未确认课件加载，已暂停；不会补点'); broadcast(); } return; }
    if (S.busy) { action('等待课件加载'); return; }
    if ((Number(stats().clicks) || 0) >= C.maxPages) { S.stopped = true; action('已达到本标签页翻页上限'); broadcast(); return; }
    // 系统睡眠、后台冻结的整段间隔不计入停留，不修改平台活动检测或心跳。
    if (delta >= 0 && delta <= 15000) S.elapsed += delta;
    play(); S.media = summary(); if (now - S.savedAt > 5000) { S.savedAt = now; saveDwell(); }
    if (S.elapsed / 1000 < C.minDwell + S.jitter) { action('停留 ' + fmt(S.elapsed / 1000) + ' / ' + fmt(C.minDwell + S.jitter)); return; }
    if (!voicePending()) {
      if (!S.media.ready) { action('等待课件脚本回执，暂不翻页'); return; }
      if (!S.media.done) { action(S.media.blocked ? '媒体未播完，请在课件中点播放' : '等待媒体播完'); return; }
    }
    next();
  }
  function resume() {
    if (check()) return;
    if (S.reentry) { action('平台已结束本次学习，请返回课程后重新进入'); return; }
    if (!own()) { action(S.lockError || '另一标签页正在运行，请先关闭那一页'); return; }
    S.warning = ''; S.paused = false; S.stopped = false; S.userPaused = false; S.awaitingCompletion = false;
    if (!verifiedComplete() && C.mode === 'completion') S.awaitingCompletion = true;
    S.lastTick = Date.now();
    for (const el of mediaEls()) delete el.dataset.wlPlayFailed;
    saveConfig(); action('已继续');
  }
  function pause() { S.paused = true; S.userPaused = true; saveDwell(); broadcast(); action('已暂停'); }
  function toggle() { C.enabled = !C.enabled; saveConfig(); if (C.enabled) resume(); else action('已关闭'); }
  function setDwell() {
    const value = duration(S.dwell.value), extra = duration(S.extra.value), min = Number(S.min.value);
    if (!Number.isFinite(value) || !Number.isFinite(extra)) { action('时间格式：20、29m 或 1h'); return; }
    if (!Number.isFinite(min) || min < 0 || min > 100) { action('正确率阈值请填 0-100'); return; }
    C.minDwell = clamp(Math.round(value), 0, 86400); C.jitterMin = 0; C.jitterMax = clamp(Math.round(extra), 0, 86400);
    C.minAccuracy = clamp(Math.round(min), 0, 100);
    S.jitter = jitter(); saveConfig(); saveDwell(); sync(); action('设置已保存');
  }
  function position(x, y, width, height, vw = innerWidth, vh = innerHeight) { return { x: clamp(x, 8, vw - width - 8), y: clamp(y, 8, vh - height - 8) }; }
  function place(x, y, persist = false) { const r = S.hud.getBoundingClientRect(), p = position(x, y, r.width, r.height); S.position = p; S.hud.style.left = p.x + 'px'; S.hud.style.top = p.y + 'px'; if (persist) write(LS, POS, p); }
  function resetPosition() { place(12, innerHeight - S.hud.getBoundingClientRect().height - 12, true); }
  function drag(header) {
    let active = null;
    header.addEventListener('pointerdown', e => { if (e.button !== 0 || e.target.closest('button,input,a,select,textarea')) return; const r = S.hud.getBoundingClientRect(); active = { id: e.pointerId, x: e.clientX, y: e.clientY, left: r.left, top: r.top }; S.dragging = true; header.setPointerCapture(e.pointerId); e.preventDefault(); });
    header.addEventListener('pointermove', e => { if (active && active.id === e.pointerId) place(active.left + e.clientX - active.x, active.top + e.clientY - active.y); });
    const finish = e => { if (!active || active.id !== e.pointerId) return; active = null; S.dragging = false; if (S.position) place(S.position.x, S.position.y, true); if (header.hasPointerCapture(e.pointerId)) header.releasePointerCapture(e.pointerId); };
    for (const name of ['pointerup', 'pointercancel', 'lostpointercapture']) header.addEventListener(name, finish);
    header.addEventListener('keydown', e => { if (e.target !== header) return; if (e.key === 'Home') { resetPosition(); e.preventDefault(); return; } const v = { ArrowLeft: [-1,0], ArrowRight: [1,0], ArrowUp: [0,-1], ArrowDown: [0,1] }[e.key]; if (v && S.position) { const step = e.shiftKey ? 40 : 10; place(S.position.x + v[0] * step, S.position.y + v[1] * step, true); e.preventDefault(); } });
    W.addEventListener('resize', () => { if (S.position) place(S.position.x, S.position.y, true); });
    if (typeof ResizeObserver === 'function') new ResizeObserver(() => { if (S.position && !S.dragging) place(S.position.x, S.position.y); }).observe(S.hud);
  }
  function sync() { if (S.dwell && document.activeElement !== S.dwell) S.dwell.value = String(C.minDwell); if (S.extra && document.activeElement !== S.extra) S.extra.value = String(C.jitterMax); if (S.min && document.activeElement !== S.min) S.min.value = String(C.minAccuracy); if (S.mode && document.activeElement !== S.mode) S.mode.value = C.mode; if (S.autoBox) S.autoBox.checked = C.autoAnswer; if (S.muteBox) S.muteBox.checked = C.muteMedia; }
  function paint() {
    if (!S.status) return; const info = nextInfo(), m = S.media;
    const a = S.progress, rec = recordStats();
    const ahead = !!(a && a.siteCompletion != null && a.localCompletion != null && a.localCompletion > a.siteCompletion);
    S.status.textContent = ['状态：' + (!C.enabled ? '已关闭' : S.warning ? '网站提示，已暂停' : !S.owner ? '等待控制权' : S.stopped ? '已结束' : S.paused ? (S.awaitingCompletion ? '等待本节完成' : '已暂停') : '运行中'),
      '模式：' + (C.mode === 'completion' ? '完成度模式（需网站标记完成）' : '时长模式'),
      '当前：' + (info.index >= 0 ? (info.index + 1) + '/' + info.list.length + ' ' + label(info.list[info.index].el) : '等待目录'),
      '完成度：' + (a && a.total > 0 ? a.completion + '%（' + a.done + '/' + a.total + ' 项' + (a.manual ? '，' + a.manual + ' 项需人工' : '') + (ahead ? '，网站仍记录 ' + a.siteCompletion + '%' : '') + '）' : completed(currentItem()) ? '网站已标记完成' : '等待课件'),
      '正确率：' + (a ? a.accuracy + '%' + (a.type === 'objective' ? '（要求 ≥' + a.minAccuracy + '%）' : '') : '—'),
      '人工语音：' + (a && a.voice > 0 ? a.voice + ' 项，按停留时长放行（不要求完成度）' : '—'),
      '学习时长：本页 ' + fmt(S.elapsed / 1000) + ' · 本地累计 ' + fmt(S.total),
      '自动作答：' + (!C.autoAnswer ? '关闭' : !a ? '等待课件' : a.submitted ? '已提交' : a.total > 0 ? '已填 ' + a.done + '/' + a.total + (a.manual ? '，待人工 ' + a.manual : '') + (a.blockReason ? '，已拦截：' + a.blockReason : '') + (a.error ? '（' + a.error + '）' : '') : '无交互题'),
      '记录：' + rec.count + ' 节 · 平均正确率 ' + rec.accuracy + '%',
      '媒体：' + (!m.ready ? '等待回执' : m.count ? m.done ? '已播完' : m.blocked ? '等待播放' : '播放中' : '本页无音视频'),
      '翻页：本次 ' + S.clicks + '，累计 ' + (Number(stats().clicks) || 0), S.action, '实际学时由网站记录'].join('\n');
  }
  function buildHud() {
    const hud = document.createElement('aside'); hud.id = HUD; hud.dataset.version = '3.3.3'; hud.setAttribute('aria-label', 'WE Learn 自动翻页面板');
    hud.style.cssText = 'position:fixed;left:12px;top:12px;z-index:2147483647;width:330px;max-width:calc(100vw - 16px);max-height:calc(100vh - 16px);box-sizing:border-box;background:rgba(19,24,32,.96);color:#edf1f7;border:1px solid #536278;border-radius:10px;box-shadow:0 5px 22px #0006;font:13px/1.6 system-ui,sans-serif;overflow:hidden;';
    const bs = 'background:#2d3a4e;color:#edf1f7;border:1px solid #536278;border-radius:5px;padding:3px 8px;font:inherit;cursor:pointer';
    hud.innerHTML = '<div class="wl-ap-drag" tabindex="0" role="group" aria-label="拖动面板；方向键移动，Home复位" style="padding:9px 11px;display:flex;align-items:center;justify-content:space-between;gap:8px;background:#283448;cursor:move;touch-action:none;user-select:none"><strong>WE Learn 自动翻页 3.3.3</strong><button data-act="reset" title="面板回到左下角" style="' + bs + '">复位</button></div>' +
      '<div style="padding:10px 12px;overflow-y:auto;max-height:calc(100vh - 80px);box-sizing:border-box"><div class="wl-ap-status" style="white-space:pre-wrap;overflow-wrap:anywhere"></div>' +
      '<label style="display:block;margin-top:8px">模式 <select aria-label="运行模式" class="wl-ap-mode" style="background:#172030;color:#fff;border:1px solid #6b7c94;border-radius:4px;padding:3px"><option value="duration">时长模式：停留并播放后翻页</option><option value="completion">完成度模式：仅网站标记完成后翻页</option></select></label>' +
      '<label style="display:flex;gap:6px;align-items:center;margin-top:7px"><input type="checkbox" class="wl-ap-auto"> 自动作答（保留已填答案，默认关闭）</label>' +
      '<label style="display:flex;gap:6px;align-items:center;margin-top:5px"><input type="checkbox" class="wl-ap-mute"> 自动静音播放媒体</label>' +
      '<div style="display:flex;gap:5px;align-items:center;flex-wrap:wrap;margin-top:8px"><label>停留 <input aria-label="每页停留" class="wl-ap-dwell" title="支持秒数、29m、1h" style="width:60px;background:#172030;color:#fff;border:1px solid #6b7c94;border-radius:4px;padding:3px"></label><label>随机≤ <input aria-label="随机停留上限" class="wl-ap-jit" style="width:45px;background:#172030;color:#fff;border:1px solid #6b7c94;border-radius:4px;padding:3px"></label><label>正确率≥ <input aria-label="自动提交最低正确率" class="wl-ap-min" title="0-100，默认100" style="width:42px;background:#172030;color:#fff;border:1px solid #6b7c94;border-radius:4px;padding:3px"></label></div>' +
      '<div style="display:flex;gap:5px;flex-wrap:wrap;margin-top:8px">' + [['apply','应用'],['pause','暂停'],['resume','继续'],['next','下一节'],['toggle','开/关']].map(([act,text]) => '<button data-act="' + act + '" style="' + bs + '">' + text + '</button>').join('') +
      '</div><div style="color:#b4c2d5;font-size:11px;margin-top:7px">拖动标题栏移动 · 回车保存时间<br>Ctrl+Alt+S 暂停/继续 · Ctrl+Alt+A 开关</div></div>';
    document.documentElement.appendChild(hud); S.hud = hud; S.status = hud.querySelector('.wl-ap-status'); S.dwell = hud.querySelector('.wl-ap-dwell'); S.extra = hud.querySelector('.wl-ap-jit'); S.mode = hud.querySelector('.wl-ap-mode'); S.autoBox = hud.querySelector('.wl-ap-auto'); S.muteBox = hud.querySelector('.wl-ap-mute'); S.min = hud.querySelector('.wl-ap-min');
    const actions = { reset: resetPosition, apply: setDwell, pause, resume, next: () => next(true), toggle };
    hud.addEventListener('click', e => { const b = e.target.closest('button[data-act]'); if (b) actions[b.dataset.act](); });
    S.mode.addEventListener('change', () => { C.mode = S.mode.value === 'completion' ? 'completion' : 'duration'; S.awaitingCompletion = false; S.paused = false; S.userPaused = false; saveConfig(); S.lastTick = Date.now(); action(C.mode === 'completion' ? '已切换到完成度模式' : '已切换到时长模式'); });
    S.autoBox.addEventListener('change', () => { C.autoAnswer = S.autoBox.checked; saveConfig(); action(C.autoAnswer ? '已开启自动作答' : '已关闭自动作答'); });
    S.muteBox.addEventListener('change', () => { C.muteMedia = S.muteBox.checked; setMuted(C.muteMedia); saveConfig(); action(C.muteMedia ? '已开启静音自动播放' : '已关闭静音自动播放'); });
    for (const input of [S.dwell, S.extra, S.min]) input.addEventListener('keydown', e => { if (e.key === 'Enter') { setDwell(); input.blur(); e.stopPropagation(); } });
    sync(); paint(); drag(hud.querySelector('.wl-ap-drag'));
    const p = read(LS, POS, null); if (p && Number.isFinite(p.x) && Number.isFinite(p.y)) place(p.x, p.y); else resetPosition();
  }
  function observeCatalog() {
    const first = document.querySelector('li[id^="liSCO_"]');
    if (!first || !first.parentElement || typeof MutationObserver !== 'function') return;
    S.observedCurrent = current();
    new MutationObserver(() => {
      const now = current();
      if (now === S.observedCurrent) return;
      S.observedCurrent = now;
      beginSectionSwitch(pageKey());
    }).observe(first.parentElement, { attributes: true, attributeFilter: ['class'], subtree: true });
  }
  function keys() { W.addEventListener('keydown', e => { if (!e.ctrlKey || !e.altKey || e.repeat) return; const k = e.key.toLowerCase(); if (k === 's') { if (S.paused) resume(); else pause(); e.preventDefault(); } if (k === 'a') { toggle(); e.preventDefault(); } }); }
  function boot() {
    load(); if (TOP && !(/\/student\/studycourse\.aspx$/i.test(location.pathname) && frame())) return;
    messages(); observeDialogs();
    if (TOP) { S.key = pageKey(); S.jitter = jitter(); restore(); bindFrame(); own(); check(); buildHud(); observeCatalog(); if (S.migrated) action('已迁移旧设置：自动作答已关闭，请按需手动开启'); keys(); W.addEventListener('pagehide', () => { saveDwell(); saveTotal(); release(); }); W.addEventListener('pageshow', () => { S.lastTick = Date.now(); own(); }); document.addEventListener('visibilitychange', saveDwell); }
    else if (S.parentOrigin && S.parentOrigin !== 'null') W.parent.postMessage({ protocol: PROTOCOL, type: 'request' }, S.parentOrigin);
    setInterval(tick, 1000); tick();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, { once: true }); else boot();
})();

// ==UserScript==
// @name         WE Learn 自动挂机翻页
// @namespace    local.welearn.autopager
// @version      3.0.0
// @description  单标签页按时顺序翻页、媒体播放和可拖动面板；平台正常记录学时
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
  if (W.__WL_AP_V3__) return;
  W.__WL_AP_V3__ = true;
  const TOP = W.top === W, HUD = 'wl-ap-hud', CONFIG = 'wl_autopager_cfg_v5';
  const POS = 'wl_ap_hud_position_v1', PROTOCOL = 'wl-ap-v3';
  function storage(name) { try { return W[name]; } catch (_) { return null; } }
  const LS = storage('localStorage'), SS = storage('sessionStorage');
  const C = { enabled: true, minDwell: 20, jitterMin: 0, jitterMax: 9, maxPages: 300 };
  const S = { owner: false, pending: false, release: null, candidate: 0, lockError: '', paused: false,
    stopped: false, warning: '', reentry: false, key: '', elapsed: 0, jitter: 0, lastTick: Date.now(),
    awaiting: null, frame: null, busy: false, src: '', observer: null, reports: new Map(),
    grantAt: 0, grant: false, parentOrigin: '', action: '初始化', clicks: 0, clickedAt: 0, savedAt: 0,
    media: { count: 0, done: true, ready: true, playing: false, blocked: false }, hud: null, position: null, dragging: false };
  function read(storage, key, fallback) { try { return JSON.parse(storage.getItem(key)) || fallback; } catch (_) { return fallback; } }
  function write(storage, key, value) { try { storage.setItem(key, JSON.stringify(value)); return true; } catch (_) { return false; } }
  function clamp(n, a, b) { return Math.min(Math.max(n, a), Math.max(a, b)); }
  function fmt(s) { s = Math.max(0, Math.floor(s)); return s < 60 ? s + '秒' : Math.floor(s / 60) + '分' + s % 60 + '秒'; }
  function duration(value) { const m = /^(\d+(?:\.\d+)?)\s*(s|m|h|秒|分|分钟|时|小时)?$/i.exec(String(value).trim()); return m ? Number(m[1]) * (/^(m|分|分钟)$/i.test(m[2]) ? 60 : /^(h|时|小时)$/i.test(m[2]) ? 3600 : 1) : NaN; }
  function apply(obj) {
    if (!obj || typeof obj !== 'object') return;
    for (const key of ['minDwell', 'jitterMin', 'jitterMax']) if (typeof obj[key] === 'number' && Number.isFinite(obj[key])) C[key] = clamp(Math.round(obj[key]), 0, 86400);
    C.jitterMin = Math.min(C.jitterMin, C.jitterMax);
    if (typeof obj.enabled === 'boolean') C.enabled = obj.enabled;
  }
  function load() {
    let obj = read(LS, CONFIG, null) || read(SS, CONFIG, null);
    if (!obj) { try { const i = W.name.indexOf('__WLAP_CFG__'); if (i >= 0) obj = JSON.parse(W.name.slice(i + '__WLAP_CFG__'.length)); } catch (_) {} }
    apply(obj);
  }
  function saveConfig() { write(LS, CONFIG, C); write(SS, CONFIG, C); broadcast(); }
  function jitter() { return C.jitterMin + Math.random() * (C.jitterMax - C.jitterMin); }
  function label(el) { return String(el && (el.innerText || el.textContent) || '').replace(/\s+/g, ' ').trim(); }
  function visible(el) { if (!el || !el.isConnected || !el.getClientRects().length) return false; const style = el.ownerDocument.defaultView.getComputedStyle(el); return style.display !== 'none' && style.visibility !== 'hidden' && Number(style.opacity || 1) > 0; }
  function enabled(el) { return !!el && !el.disabled && el.getAttribute('aria-disabled') !== 'true' && !el.closest('.course_disable,.disabled,[disabled]'); }
  function action(text) { S.action = text; paint(); }
  function frame() { return document.querySelector('#contentFrame'); }
  // URL 的 sco 在原生页内翻页后可能不变，以目录选中项为准。
  function current() { const el = document.querySelector('.courseware_current[id^="liSCO_"]'); return el ? el.id.slice(6) : new URLSearchParams(location.search).get('sco') || ''; }
  function pageKey() { return location.pathname.toLowerCase() + '|' + (new URLSearchParams(location.search).get('cid') || '') + '|' + current(); }
  function sections() { return Array.from(document.querySelectorAll('li[id^="liSCO_"]')).map(li => ({ id: li.id.slice(6), el: li.querySelector('a[onclick*="SelectSCO"]') })).filter(item => item.el); }
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
  function mediaEls(doc = document, depth = 0) {
    const list = Array.from(doc.querySelectorAll('audio,video'));
    if (depth < 3) for (const el of doc.querySelectorAll('iframe,frame')) { try { if (el.contentDocument) list.push(...mediaEls(el.contentDocument, depth + 1)); } catch (_) {} }
    return list;
  }
  function localMedia() { const list = mediaEls(); return { count: list.length, done: list.every(el => el.ended || Number.isFinite(el.duration) && el.duration > 0 && el.currentTime >= el.duration - 0.5), playing: list.some(el => !el.paused && !el.ended), blocked: list.some(el => el.paused && !el.ended), ready: true }; }
  function play() {
    for (const el of mediaEls()) if (el.paused && !el.ended && el.dataset.wlPlayFailed !== '1') {
      try { const p = el.play(); if (p && p.catch) p.catch(() => { el.dataset.wlPlayFailed = '1'; }); } catch (_) { el.dataset.wlPlayFailed = '1'; }
    }
  }
  function children() { return TOP ? (frame() ? [frame()] : []) : Array.from(document.querySelectorAll('iframe,frame')); }
  function origin(el) { try { return new URL(el.getAttribute('src') || '', location.href).origin; } catch (_) { return ''; } }
  function granted() { return TOP ? running() && !S.busy && !S.awaiting : S.grant && Date.now() - S.grantAt < 7000 && !S.warning; }
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
      }
    });
  }
  function reportParent() { if (S.parentOrigin && S.parentOrigin !== 'null') try { W.parent.postMessage({ protocol: PROTOCOL, type: 'status', media: summary(), warning: S.warning }, S.parentOrigin); } catch (_) {} }
  function saveDwell() { if (TOP) write(SS, 'wl_ap_dwell_v3', { key: S.key, elapsed: S.elapsed, jitter: S.jitter }); }
  function reset(key = pageKey()) { S.key = key; S.elapsed = 0; S.jitter = jitter(); S.lastTick = Date.now(); saveDwell(); }
  function restore() { const d = read(SS, 'wl_ap_dwell_v3', null); if (d && d.key === S.key && Number.isFinite(d.elapsed) && d.elapsed >= 0) { S.elapsed = clamp(d.elapsed, 0, 86400000); if (Number.isFinite(d.jitter)) S.jitter = clamp(d.jitter, C.jitterMin, C.jitterMax); } }
  function bindFrame() {
    const el = frame(); if (!el || el === S.frame) return;
    if (S.observer) S.observer.disconnect(); S.frame = el; S.src = el.getAttribute('src') || '';
    el.addEventListener('load', () => { if (el !== frame()) return; S.busy = false; S.reports.clear(); if (S.awaiting && pageKey() !== S.awaiting.key) { S.awaiting = null; reset(); } else S.lastTick = Date.now(); broadcast(); });
    S.observer = new MutationObserver(() => { const src = el.getAttribute('src') || ''; if (src === S.src) return; S.src = src; S.busy = true; S.reports.clear(); reset(); broadcast(); });
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
    if (!enabled(info.next.el)) { S.paused = true; action('下一小节未开放，请先完成当前要求'); broadcast(); return false; }
    const button = nextButton();
    if (!button || !visible(button) || !enabled(button)) { S.paused = true; action('网站下一节按钮不可用，请检查页面'); broadcast(); return false; }
    S.clickedAt = Date.now(); S.awaiting = { key: pageKey(), at: Date.now() }; broadcast();
    try {
      button.click(); // 唯一导航入口，保留原生 EndSCO / SelectSCO / StartSCO 流程。
      S.clicks++; const count = stats(); count.clicks = (Number(count.clicks) || 0) + 1; write(SS, 'wl_ap_stats_v3', count);
      action((manual ? '手动' : '定时') + '翻到：' + label(info.next.el).slice(0, 40)); return true;
    } catch (_) { S.awaiting = null; S.paused = true; action('原生翻页失败，已暂停'); return false; }
  }
  function tick() {
    const now = Date.now(), delta = now - S.lastTick; S.lastTick = now; check();
    if (!TOP) { if (granted()) play(); broadcast(); reportParent(); return; } // 子框架永远不导航。
    own(); bindFrame(); const key = pageKey(); if (key !== S.key) reset(key); broadcast();
    if (!C.enabled) { action('已关闭'); return; }
    if (!S.owner) { action(S.lockError || '其他标签页正在控制，当前页待命'); return; }
    if (S.warning || S.paused || S.stopped) { paint(); return; }
    if (S.awaiting) { if (now - S.awaiting.at > 30000) { S.awaiting = null; S.paused = true; action('30秒内未确认课件加载，已暂停；不会补点'); broadcast(); } return; }
    if (S.busy) { action('等待课件加载'); return; }
    if ((Number(stats().clicks) || 0) >= C.maxPages) { S.stopped = true; action('已达到本标签页翻页上限'); broadcast(); return; }
    // 系统睡眠、后台冻结的整段间隔不计入停留，不修改平台活动检测或心跳。
    if (delta >= 0 && delta <= 15000) S.elapsed += delta;
    play(); S.media = summary(); if (now - S.savedAt > 5000) { S.savedAt = now; saveDwell(); }
    if (S.elapsed / 1000 < C.minDwell + S.jitter) { action('停留 ' + fmt(S.elapsed / 1000) + ' / ' + fmt(C.minDwell + S.jitter)); return; }
    if (!S.media.ready) { action('等待课件脚本回执，暂不翻页'); return; }
    if (!S.media.done) { action(S.media.blocked ? '媒体未播完，请在课件中点播放' : '等待媒体播完'); return; }
    next();
  }
  function resume() {
    if (check()) return;
    if (S.reentry) { action('平台已结束本次学习，请返回课程后重新进入'); return; }
    if (!own()) { action(S.lockError || '另一标签页正在运行，请先关闭那一页'); return; }
    S.warning = ''; S.paused = false; S.stopped = false; S.lastTick = Date.now();
    for (const el of mediaEls()) delete el.dataset.wlPlayFailed;
    saveConfig(); action('已继续');
  }
  function pause() { S.paused = true; saveDwell(); broadcast(); action('已暂停'); }
  function toggle() { C.enabled = !C.enabled; saveConfig(); if (C.enabled) resume(); else action('已关闭'); }
  function setDwell() {
    const value = duration(S.dwell.value), extra = duration(S.extra.value);
    if (!Number.isFinite(value) || !Number.isFinite(extra)) { action('时间格式：20、29m 或 1h'); return; }
    C.minDwell = clamp(Math.round(value), 0, 86400); C.jitterMin = 0; C.jitterMax = clamp(Math.round(extra), 0, 86400);
    S.jitter = jitter(); saveConfig(); saveDwell(); sync(); action('停留设置已保存');
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
  function sync() { if (S.dwell && document.activeElement !== S.dwell) S.dwell.value = String(C.minDwell); if (S.extra && document.activeElement !== S.extra) S.extra.value = String(C.jitterMax); }
  function paint() {
    if (!S.status) return; const info = nextInfo(), m = S.media;
    S.status.textContent = ['状态：' + (!C.enabled ? '已关闭' : S.warning ? '网站提示，已暂停' : !S.owner ? '等待控制权' : S.stopped ? '已结束' : S.paused ? '已暂停' : '运行中'),
      '当前：' + (info.index >= 0 ? (info.index + 1) + '/' + info.list.length + ' ' + label(info.list[info.index].el) : '等待目录'),
      '本页停留：' + fmt(S.elapsed / 1000) + ' / ' + fmt(C.minDwell + S.jitter),
      '媒体：' + (!m.ready ? '等待回执' : m.count ? m.done ? '已播完' : m.blocked ? '等待播放' : '播放中' : '本页无音视频'),
      '翻页：本次 ' + S.clicks + '，累计 ' + (Number(stats().clicks) || 0), S.action, '实际学时由网站记录'].join('\n');
  }
  function buildHud() {
    const hud = document.createElement('aside'); hud.id = HUD; hud.dataset.version = '3.0.0'; hud.setAttribute('aria-label', 'WE Learn 自动翻页面板');
    hud.style.cssText = 'position:fixed;left:12px;top:12px;z-index:2147483647;width:320px;max-width:calc(100vw - 16px);max-height:calc(100vh - 16px);box-sizing:border-box;background:rgba(19,24,32,.96);color:#edf1f7;border:1px solid #536278;border-radius:10px;box-shadow:0 5px 22px #0006;font:13px/1.6 system-ui,sans-serif;overflow:hidden;';
    const bs = 'background:#2d3a4e;color:#edf1f7;border:1px solid #536278;border-radius:5px;padding:3px 8px;font:inherit;cursor:pointer';
    hud.innerHTML = '<div class="wl-ap-drag" tabindex="0" role="group" aria-label="拖动面板；方向键移动，Home复位" style="padding:9px 11px;display:flex;align-items:center;justify-content:space-between;gap:8px;background:#283448;cursor:move;touch-action:none;user-select:none"><strong>WE Learn 自动翻页 3.0</strong><button data-act="reset" title="面板回到左下角" style="' + bs + '">复位</button></div>' +
      '<div style="padding:10px 12px;overflow-y:auto;max-height:calc(100vh - 80px);box-sizing:border-box"><div class="wl-ap-status" style="white-space:pre-wrap;overflow-wrap:anywhere"></div>' +
      '<div style="display:flex;gap:5px;align-items:center;flex-wrap:wrap;margin-top:8px"><label>停留 <input aria-label="每页停留" class="wl-ap-dwell" title="支持秒数、29m、1h" style="width:60px;background:#172030;color:#fff;border:1px solid #6b7c94;border-radius:4px;padding:3px"></label><label>随机≤ <input aria-label="随机停留上限" class="wl-ap-jit" style="width:45px;background:#172030;color:#fff;border:1px solid #6b7c94;border-radius:4px;padding:3px"></label></div>' +
      '<div style="display:flex;gap:5px;flex-wrap:wrap;margin-top:8px">' + [['apply','应用'],['pause','暂停'],['resume','继续'],['next','下一节'],['toggle','开/关']].map(([act,text]) => '<button data-act="' + act + '" style="' + bs + '">' + text + '</button>').join('') +
      '</div><div style="color:#b4c2d5;font-size:11px;margin-top:7px">拖动标题栏移动 · 回车保存时间<br>Ctrl+Alt+S 暂停/继续 · Ctrl+Alt+A 开关</div></div>';
    document.documentElement.appendChild(hud); S.hud = hud; S.status = hud.querySelector('.wl-ap-status'); S.dwell = hud.querySelector('.wl-ap-dwell'); S.extra = hud.querySelector('.wl-ap-jit');
    const actions = { reset: resetPosition, apply: setDwell, pause, resume, next: () => next(true), toggle };
    hud.addEventListener('click', e => { const b = e.target.closest('button[data-act]'); if (b) actions[b.dataset.act](); });
    for (const input of [S.dwell, S.extra]) input.addEventListener('keydown', e => { if (e.key === 'Enter') { setDwell(); input.blur(); e.stopPropagation(); } });
    sync(); paint(); drag(hud.querySelector('.wl-ap-drag'));
    const p = read(LS, POS, null); if (p && Number.isFinite(p.x) && Number.isFinite(p.y)) place(p.x, p.y); else resetPosition();
  }
  function keys() { W.addEventListener('keydown', e => { if (!e.ctrlKey || !e.altKey || e.repeat) return; const k = e.key.toLowerCase(); if (k === 's') { if (S.paused) resume(); else pause(); e.preventDefault(); } if (k === 'a') { toggle(); e.preventDefault(); } }); }
  function boot() {
    load(); if (TOP && !(/\/student\/studycourse\.aspx$/i.test(location.pathname) && frame())) return;
    messages(); observeDialogs();
    if (TOP) { S.key = pageKey(); S.jitter = jitter(); restore(); bindFrame(); own(); check(); buildHud(); keys(); W.addEventListener('pagehide', () => { saveDwell(); release(); }); W.addEventListener('pageshow', () => { S.lastTick = Date.now(); own(); }); document.addEventListener('visibilitychange', saveDwell); }
    else if (S.parentOrigin && S.parentOrigin !== 'null') W.parent.postMessage({ protocol: PROTOCOL, type: 'request' }, S.parentOrigin);
    setInterval(tick, 1000); tick();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, { once: true }); else boot();
})();

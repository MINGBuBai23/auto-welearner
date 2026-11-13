# WE Learn 自动翻页 3.3.5 测试报告

验证日期：2026-11-13。测试对象：`welearn-autopager.user.js` 3.3.5。

## 验证结果

以下检查全部通过，退出码均为 0。浏览器测试使用 Playwright；分节计时、组件、导航和媒体归零使用离线夹具，课件引擎与联动使用公开静态课件及内存 SCORM API。

| 命令 | 结果 |
| --- | --- |
| `node --check welearn-autopager.user.js` | JavaScript 语法检查通过 |
| `python tests/test_section_time.py` | `PASS 29/29` |
| `python tests/test_navigation_confirm.py` | `PASS 12/12` |
| `python tests/test_media_replay.py` | `PASS 10/10` |
| `python tests/test_component_mapping.py` | `PASS 10/10` |
| `python tests/test_engine.py` | `passed 15 / 15` |
| `python tests/test_integration.py` | `PASS` |
| `python tests/test_media_edge.py` | `PASS` |
| `python tests/test_voice_manual.py` | `PASS` |

## 30分钟与目录用时

E1：只读核对真实课程目录，确认时长位于小节的 `span.pull-right`，文本如 `用时 27:05`、`用时 30:09`，小节身份来自 `li` 的 `StartSCO('…')`。核对期间没有进入课件或修改真实学习记录。

新模式按小节 ID 读取目录用时，与本机已存累计取较大值，再计剩余时间。目录读取失败时回退到只读的 `cmi.total_time`，最后回退到本机分节计时。达到 30 分钟走原生下一节入口，仍检查用户暂停、网站提示、下一节开放状态和加载确认。

E2：29 项离线用例全部通过，覆盖：

- 从零逐次执行完整 1800 秒虚拟时钟：1799 秒不翻，1800 秒翻；媒体阻塞也不能延长上限；空导航超时不补点。
- 旧 20 秒配置迁移；本机部分累计只补剩余、已满跳过、连续已满小节逐个确认加载。
- 目录 `30:00`、`30:09`、`01:00:00` 跳过；`29:50` 补 10 秒；`00:30` 按 30 秒处理。
- 标题中的时间、其他小节的时间不误用；目录只发起 GET，返回 HTML 中的脚本不执行；StudyCourse 内联目录兼容。
- SCORM 数字秒、ISO duration、时钟格式；读取累计时长不写 SCORM、不提交；目录无有效时间时可回退。
- 本机与网站时长不重复叠加；刷新保留；课程、小节隔离；人工暂停、冻结长间隔不计时。
- 完成度等待仍受 30 分钟上限限制；末节停止；网站验证及功能关闭继续阻止翻页。

这些用例使用虚拟时钟，没有在真实学习账号等待或累计 30 分钟。真实平台最终入账的学时未在本轮验证。

## 导航、媒体及其他回归

E3：旧回归全部通过：

- 导航 12 项：目录迟到同步、选中 class 位于子链接、iframe 换源、SPA 路由、iframe 替换、旧报告隔离、30 秒超时与再次继续不补点。查询参数加入进度身份，覆盖只改变 `?sco=` 的课件切换。
- 媒体归零 10 项：同源/跨域 iframe、普通 DOM/Shadow DOM、结束归零后不重播、翻页一次及换源/重新加载/路由变化重置。
- Edge 真实公开课件音频自然播放完整的 39.706122 秒，归零后等待 5.5 秒仍不重播，原生 `NextSCO()` 一次，页面异常为 0。静音开关与普通 DOM/Shadow DOM 媒体回归通过。
- 组件 10 项：口语、摄像头按录制次数判定，跟读要求全部完成，控制器缺失或状态读取异常不会误报完成。
- 引擎 15 项：默认每节30分钟且关闭自动作答、题型填答、已有答案保留、正确率闸门、取消提交、旧配置迁移、SCORM 进度滞后、无交互页与人工录音项。
- 整页联动：配置与只读进度上报、原生翻页、手动暂停、切节撤销授权、拒绝旧报告及历史记录隔离。
- 人工语音页：显式选择旧模式时，未完成录音项报告 `voice=2`、完成度 85%、未提交，按停留翻页，完成历史为 0。

旧模式回归夹具显式设置 `sectionPolicy:1`，避免自动迁移改变其原有测试目标。引擎旧配置迁移夹具先清除先前用例保存的 v7 配置，再验证 v6 的 33 秒参数保留、模式升级和自动作答关闭；首轮夹具串用配置的失败已修复，重跑为 15/15。

## 本地复现

```sh
python -m pip install playwright
python -m playwright install chromium
node --check welearn-autopager.user.js
python tests/test_section_time.py
python tests/test_navigation_confirm.py
python tests/test_media_replay.py
python tests/test_component_mapping.py
python tests/test_engine.py
python tests/test_integration.py
python tests/test_media_edge.py
python tests/test_voice_manual.py
```

媒体归零回归使用本机 Microsoft Edge；真实媒体测试优先使用 Edge，无 Edge 时尝试 Playwright Chromium。课件引擎和联动测试需要访问公开静态课件，离线专项测试无需网络。不登录、不写入真实学习账号。

# WE Learn 自动翻页 3.3.8 测试报告

验证日期：2026-11-17。测试对象：`welearn-autopager.user.js` 3.3.8。

## 目录不足29分钟却误跳

E1：旧版取目录、课件和本机记录的最大值。离线复现：目录 `02:00`，本机记录29分钟或课件上报30分钟时，进入约5秒就点击下一节。该复现确认了时长冲突可触发误跳，未读取用户真实账号的记录。

E2：修复后首次取得当前小节目录用时时，重新建立“目录起点 + 本次有效停留”的基准；目录有效时不再采用偏大的旧本机记录或课件累计。修正后的本地值可以覆盖旧高值。刷新或重新进入同节时重新建立基准，目录尚未入账的停留不会通过旧记录补算。目录不可读时沿用课件与本机回退。

| 命令 | 结果 |
| --- | --- |
| `node --check welearn-autopager.user.js` | 通过，退出码0 |
| `python tests/test_section_time.py` | `PASS 41/41`，退出码0 |
| `python tests/test_navigation_confirm.py` | `PASS 12/12`，退出码0 |
| `python tests/test_integration.py` | `PASS`，退出码0 |
| `git diff --check` | 通过，退出码0 |

E3：专项新增目录低值覆盖旧高值、有效零时长、补足剩余时间、刷新时旧session隔离、目录延迟返回、下一小节不连续误跳、目录实时更新不重复累加及内联目录覆盖回退值。保留29分钟边界、已满跳过、暂停、冻结、末节、只读SCORM及正确率控件验证。

本轮使用离线夹具和虚拟时钟，未在真实学习账号等待29分钟；真实平台入账与自动退出行为仍未实测。日志与发布收据位于 `tests/artifacts/section-time/`。

本地备份：`C:\Users\明不白\Documents\welearn脚本\.backups\3.3.7-before-catalog-priority`。回滚脚本核对8份备份哈希后恢复源工程和发布副本；先用 `-WhatIf` 预览。它只恢复本地文件，GitHub回滚需要对本轮发布提交执行 `git revert`。

```powershell
& 'C:\Users\明不白\Documents\welearn脚本\.backups\3.3.7-before-catalog-priority\rollback.ps1' -WhatIf
& 'C:\Users\明不白\Documents\welearn脚本\.backups\3.3.7-before-catalog-priority\rollback.ps1'
```

## 3.3.7 测试存档

验证日期：2026-11-16。测试对象：`welearn-autopager.user.js` 3.3.7。

## 本次改动与验证

自动翻页由累计29分50秒提前至累计29分钟（1740秒），面板、模式选项与文档同步更新。目录、课件只读时长与本机累计仍取较大值；原有存储记录可继续使用。

| 命令 | 结果 |
| --- | --- |
| `node --check welearn-autopager.user.js` | 通过，退出码0 |
| `python tests/test_section_time.py` | `PASS 33/33`，退出码0 |
| `python tests/test_navigation_confirm.py` | `PASS 12/12`，退出码0 |
| `git diff --check` | 通过，退出码0 |

E1：离线虚拟时钟验证29分钟边界：阈值前不翻页，到1740秒调用一次网站原生下一节；媒体未播完及完成度等待不能延长。无有效导航时，30秒后暂停且不补点。

E2：目录用时 `29:00`、`29:40`、`30:00`、`30:09` 和 `01:00:00` 均跳过；`28:50` 只计剩余时间。已存满时小节连续跳过时，逐次确认新课件加载。

E3：其余专项覆盖目录/课件时长取较大值、SCORM时长格式、本机持久化、不重复叠加、课程与小节隔离、人工暂停、冻结间隔、末节停止、控件移除及正确率输入校验。导航12项覆盖目录延迟、iframe换源、SPA路由、旧报告隔离与手动返回。

日志：`tests/artifacts/section-time/section-time-3.3.7-final.log`、`navigation-3.3.7-final.log`；命令、哈希与退出码：`verification-3.3.7.json`。

本轮使用离线夹具和虚拟时钟，未在真实账号等待29分钟，不能据此确认平台不再退出。媒体、组件、引擎及整页联动的上一轮完整回归见下方3.3.6存档，本次未重复这些无关测试。检测提示、会话失效、下一节未开放及加载超时仍会暂停。

## 3.3.6 测试存档

验证日期：2026-11-16。测试对象：`welearn-autopager.user.js` 3.3.6。

## 验证结果

以下检查全部通过，退出码均为 0。浏览器测试使用 Playwright；分节计时、组件、导航和媒体归零使用离线夹具，课件引擎与联动使用公开静态课件及内存 SCORM API。

| 命令 | 结果 |
| --- | --- |
| `node --check welearn-autopager.user.js` | JavaScript 语法检查通过 |
| `python tests/test_section_time.py` | `PASS 31/31` |
| `python tests/test_navigation_confirm.py` | `PASS 12/12` |
| `python tests/test_media_replay.py` | `PASS 10/10` |
| `python tests/test_component_mapping.py` | `PASS 10/10` |
| `python tests/test_engine.py` | `passed 15 / 15` |
| `python tests/test_integration.py` | `PASS` |
| `python tests/test_media_edge.py` | `PASS` |
| `python tests/test_voice_manual.py` | `PASS` |

## 30分钟与目录用时

E1：只读核对真实课程目录，确认时长位于小节的 `span.pull-right`，文本如 `用时 27:05`、`用时 30:09`，小节身份来自 `li` 的 `StartSCO('…')`。核对期间没有进入课件或修改真实学习记录。

新模式按小节 ID 读取目录用时，与只读的 `cmi.total_time`、本机已存累计取较大值，再计剩余时间。达到 29 分 50 秒安全窗口时走原生下一节入口，仍检查用户暂停、网站提示、下一节开放状态和加载确认。

E2：31 项离线用例全部通过，覆盖：

- 从零逐次执行虚拟时钟：达到 1790 秒安全窗口即调用原生下一节，较 30 分钟提前 10 秒，媒体阻塞也不能延长；空导航超时不补点。
- 自定停留与随机等待控件移除；正确率阈值仍可保存，非数值或越界输入不会覆盖原设置。
- 旧 20 秒配置迁移；本机部分累计只补剩余、已满跳过、连续已满小节逐个确认加载。
- 目录 `30:00`、`30:09`、`01:00:00` 跳过；接近30分钟时提前切换；`00:30` 按 30 秒处理。
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

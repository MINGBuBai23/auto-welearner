# WE Learn 自动翻页 3.3.4 测试报告

验证日期：2026-11-13。测试对象：`welearn-autopager.user.js` 3.3.4。

## 验证结果

以下检查全部通过，退出码均为 0。浏览器测试使用 Playwright，课件测试以公开静态课件和内存 SCORM API 运行。

| 命令 | 结果 |
| --- | --- |
| `node --check welearn-autopager.user.js` | JavaScript 语法检查通过 |
| `python tests/test_navigation_confirm.py` | `PASS 12/12` |
| `python tests/test_media_replay.py` | `PASS 10/10` |
| `python tests/test_component_mapping.py` | `PASS 10/10` |
| `python tests/test_engine.py` | `passed 15 / 15` |
| `python tests/test_integration.py` | `PASS` |
| `python tests/test_media_edge.py` | `PASS` |
| `python tests/test_voice_manual.py` | `PASS` |

## 翻页后的加载确认

3.3.3 只在外层目录标记改变时解除待确认导航。iframe 已换源或 SPA 路由已变化、目录仍未同步时，会在 30 秒后错误暂停；此时新进度还可能被写入上一小节。

3.3.4 在点击前保存旧文档 ID、报告地址、iframe 源和预期下一节。换源并加载完成，或收到明确的新文档/路由报告后确认加载；目录未同步时，只在本地把新课件绑定到预期下一节。支持目录标记位于子链接、替换 iframe 和目录迟到同步。网站目录、完成标记与原生翻页入口保持由网站管理。

12 项离线浏览器场景全部通过：

- 目录不变时换源加载、SPA 路由变化；目录正常更新和选中 class 位于子链接。
- 只有目录变化但 iframe 未导航、无效点击后旧报告、同地址重载、无旧身份的迟到首报均不解除等待。
- 尚无旧报告时换源完成加载、整个 iframe 替换、加载后的旧报告隔离。
- 目录标记未同步时手动点回旧小节，立即撤销授权，旧进度不会写回旧小节。

虚拟时钟覆盖 30 秒超时及点击“继续”后再等待，确认不重复补点、授权保持撤销；实际延迟加载后仍保留用户暂停，手动继续才恢复。新进度只写入下一节，目录迟到同步不会重置完成度与停留。

联动测试的提交闸门用例将停留改为 300 秒，使它不再触发不导航的 NextSCO 空夹具；正确率拦截和提交后历史断言保持。空导航及超时行为由独立导航回归验证。

## 媒体结束后归零

课件播放器会在 `ended` 回调中把播放位置设置为 0，原生 `ended` 随后变回 false。旧版因此再次播放媒体，面板持续等待媒体播完。

离线回归使用真实短 WAV，并在结束时立即归零。10 项用例覆盖同源与跨域 iframe、普通 DOM 与 Shadow DOM、结束后不重播且翻页一次、停留期间不重播、换源、同源重新加载以及 SPA 路由切换。`et-media` 完成状态在归零后保留，在媒体源或路由变化后重置。

真实课件媒体验证使用 Microsoft Edge 157.0.4341.46：

- 课件 `4/3-1` 的音频自然播放完整的 39.706122 秒，记录一次 `play` 和一次 `ended`。
- 结束后课件将媒体归零，状态为 `time=0, paused=true, ended=false`。
- 继续等待 5.5 秒，超过自动播放重试间隔，仍未重播。
- 停留门槛满足后，原生 `NextSCO()` 调用一次，页面异常为 0。
- 播放中静音开关立即生效；普通 DOM 与 Shadow DOM 的合成短音频也能播放结束并翻页。

## 其他回归

- 组件映射：口语、摄像头按录制次数判定，跟读要求全部完成；缺失控制器与状态读取异常不会误报完成，已完成数据保留。
- 引擎：默认关闭自动作答、题型填答、已有答案保留、正确率闸门、取消提交、旧配置迁移、SCORM 进度滞后、无交互页与人工录音项。
- 整页联动：父子页配置与进度上报、网站原生翻页、手动暂停、切换章节撤销授权与拒绝旧报告、历史记录隔离。
- 人工语音页：未完成录音项仍报告 `voice=2`、完成度 85%、未提交，按停留时长翻页，完成历史为 0 条。

测试不使用真实学习账号；真实账号的服务端学习记录未在本轮验证。

## 本地复现

```sh
python -m pip install playwright
python -m playwright install chromium
node --check welearn-autopager.user.js
python tests/test_navigation_confirm.py
python tests/test_media_replay.py
python tests/test_component_mapping.py
python tests/test_engine.py
python tests/test_integration.py
python tests/test_media_edge.py
python tests/test_voice_manual.py
```

媒体归零回归使用本机安装的 Microsoft Edge；真实媒体测试优先使用 Edge，无 Edge 时尝试 Playwright Chromium。其余课件测试需要访问公开静态课件，离线组件、导航与媒体归零回归无需网络。

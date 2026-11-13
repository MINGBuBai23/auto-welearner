# WE Learn 自动翻页 3.3.3 测试报告

验证日期：2026-11-13。测试对象：`welearn-autopager.user.js` 3.3.3。

## 验证结果

以下检查全部通过，退出码均为 0。浏览器测试使用 Playwright，课件测试以公开静态课件和内存 SCORM API 运行。

| 命令 | 结果 |
| --- | --- |
| `node --check welearn-autopager.user.js` | JavaScript 语法检查通过 |
| `python tests/test_media_replay.py` | `PASS 10/10` |
| `python tests/test_component_mapping.py` | `PASS 10/10` |
| `python tests/test_engine.py` | `passed 15 / 15` |
| `python tests/test_integration.py` | `PASS` |
| `python tests/test_media_edge.py` | `PASS` |
| `python tests/test_voice_manual.py` | `PASS` |

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
python tests/test_media_replay.py
python tests/test_component_mapping.py
python tests/test_engine.py
python tests/test_integration.py
python tests/test_media_edge.py
python tests/test_voice_manual.py
```

媒体归零回归使用本机安装的 Microsoft Edge；真实媒体测试优先使用 Edge，无 Edge 时尝试 Playwright Chromium。其余课件测试需要访问公开静态课件，离线组件与媒体归零回归无需网络。

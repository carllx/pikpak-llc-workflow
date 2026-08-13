# 架构探针证据记录 (Architectural Probe Evidence)

**主题**: PikPak CDN 匿名 Range 下载能力验证
**日期**: 2026-08-13

## 结论状态

### PROVEN (已证实的事实)
本探针针对当前 PikPak 测试样本 (`vrkm-962-3.mp4`，通过分享链接提取到的转码媒体直链) 得出以下明确结论：
* 带有有效签名 (`token` / `sign`) 的转码媒体 URL 支持**完全匿名**的 HTTP Range 下载。
* 请求成功返回了 `HTTP 206 Partial Content`。
* 成功接收并读取了完整的 `65536 / 65536 bytes`。
* **不需要**在代码中注入任何账户 Cookie 即可完成上述 CDN URL 的请求。
* 对该特定 CDN URL 进行下载时，`User-Agent` 和 `Referer` 不是强制必填的验证项。

### UNRESOLVED (尚未解决/待证实的未知项)
*纯 Python 环境下，如何**不依赖浏览器拦截**直接获取带签名的媒体直链（Share URL -> Media URLs 的纯接口逆向）。
* 原画 (Origin) 媒体的 URL 发现机制。
* 原画 (Origin) 媒体的 Range 下载表现与安全限制。
* 完整的 480p 代理视频下载测试（大文件传输稳定性）。
* 并发/多连接下载的性能表现和连接数限制。
* 上述发现在其他 PikPak 文件或不同分享场景下的普适性。

> **架构指令**: 严禁将上述 UNRESOLVED 项转化为架构上的既定事实。在取得进一步探针证据前，后续实现必须围绕这些未知项进行渐进式消除。

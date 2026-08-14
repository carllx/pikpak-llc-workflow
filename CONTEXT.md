# PikPak LLC Workflow Context

## 项目愿景
本项目是由 IDE 内 Project Agent 驱动的自动化脚本集合。核心目标是建立 **PikPak → 低清代理 → LosslessCut → 原画片段** 的自动化工作流，旨在最大化节省海外代理和 VPN 流量。项目将作为 Agent 自身的“工具箱”，通过 GitHub Issues 进行任务下达和验收。

## 架构红线 (Architectural Guardrails)
* **防全片下载阻断**：任何针对原画的局部下载在执行前必须先探测 Range/Seek 支持能力。如果服务器不支持，禁止退化为完整原片下载，必须立即 ABORT 并报错。
* **无状态优先 (Stateless/Anonymous Preference)**：在已经证实的范围内（如通过签名的 CDN URL 下载），尽可能依赖无 Cookie、无状态的纯 HTTP 请求，禁止过早引入复杂的身份鉴权（Auth/Cookie）机制，除非遇到不可逾越的阻断。
* **极简工具链**：禁止自行开发 GUI、后台常驻服务、Chrome 扩展或重型下载引擎。重度依赖轻量级 Python 脚本以及如 aria2、FFmpeg 等成熟 CLI。
* **严格代码规范**：所有手写源码和测试文件硬性限制 600 物理行数，500 行触发设计审查。不允许通过强行截断来规避行数，必须按职责拆分模块。

## Ubiquitous Language (统一语言)
* **Share URL / File ID**：PikPak 中定位资源的用户输入。
* **Media Variants / Resolutions**：同一个视频的不同转码版本，包括 Origin (原画), 1080p, 720p, 480p 等。
* **Proxy Video (代理片)**：被完整下载到本地供粗剪用的低清版本（通常为 480p）。
* **LLC File**：LosslessCut 输出的 `.llc` 格式项目文件，用于承载被选中的时间片段 (`cutSegments`)。
* **Origin Segments**：对应 `.llc` 切片范围的原始超清视频的字节块。
* **Range Fetch**：使用 HTTP `Range` 头只下载文件的局部。
* **Share Video Candidate**：Share 中可作为 Proxy/Origin 源的视频文件；由稳定 `file_id` 标识，并携带真实 `filename`。Folder Share 默认处理全部候选，非视频文件不参与。
* **LLC Source Selection**：使用 LLC `mediaFileName` 与候选的唯一 filename/stem 匹配，再以匹配项的 `file_id` 获取 Origin；禁止用 API 数组位置选择源。

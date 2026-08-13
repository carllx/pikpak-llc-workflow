# PikPak LLC Workflow Context & Spec

## 项目愿景
本项目是由 IDE 内 Project Agent 驱动的自动化脚本集合。核心目标是建立 **PikPak → 低清代理 → LosslessCut → 原画片段** 的自动化工作流，旨在最大化节省海外代理和 VPN 流量。项目将作为 Agent 自身的“工具箱”，通过 GitHub Issues 进行任务下达和验收。

## 核心业务流程 (User Workflow)
1. **源数据**：用户提供 PikPak 视频的标识（如 Share URL 或 File ID）。
2. **代理获取**：脚本通过 API 识别所有可用的视频清晰度（如 Origin, 1080p, 720p, 480p），并完整下载一个相对低清的代理版本（默认 480p）到本地。
3. **本地剪辑决策**：用户使用 **LosslessCut (v3.69.0)** 打开 480p 代理视频进行粗剪，选取想要的精彩片段，并保存出 `.llc` 剪辑项目文件。
4. **精细原画下载**：Agent 接收 `.llc` 文件，解析其中的 `cutSegments` (包含 start 和 end 时间范围)，重新获取该视频的原画 (Origin) 直链。
5. **安全 Range 下载**：在严格验证原画链接支持安全局部 Range/Seek 的前提下，**仅下载 LLC 中指定的原画时间区间对应的字节块**。

## 架构红线 (Architectural Guardrails)
* **防全片下载阻断**：任何针对原画的局部下载在执行前必须先探测 Range/Seek 支持能力。如果服务器不支持，禁止退化为完整原片下载，必须立即 ABORT 并报错。
* **无状态优先 (Stateless/Anonymous Preference)**：在已经证实的范围内（如通过签名的 CDN URL 下载），尽可能依赖无 Cookie、无状态的纯 HTTP 请求，禁止过早引入复杂的身份鉴权（Auth/Cookie）机制，除非遇到不可逾越的阻断。
* **极简工具链**：禁止自行开发 GUI、后台常驻服务、Chrome 扩展或重型下载引擎引擎。重度依赖轻量级 Python 脚本以及如 aria2、FFmpeg 等成熟 CLI。

## Ubiquitous Language (统一语言)
* **Share URL / File ID**：PikPak 中定位资源的用户输入。
* **Media Variants / Resolutions**：同一个视频的不同转码版本，包括 Origin (原画), 1080p, 720p, 480p 等。
* **Proxy Video (代理片)**：被完整下载到本地供粗剪用的低清版本（通常为 480p）。
* **LLC File**：LosslessCut 输出的 `.llc` 格式项目文件，用于承载被选中的时间片段 (`cutSegments`)。
* **Origin Segments**：对应 `.llc` 切片范围的原始超清视频的字节块。
* **Range Fetch**：使用 HTTP `Range` 头只下载文件的局部。

---
name: pikpak-llc
description: 运行 PikPak 代理下载、LosslessCut 片段提取与批量验收流程。
disable-model-invocation: true
---

# PikPak LLC operator

在项目根目录工作。根据用户当前产物选择一个模式，执行后报告完成标准与下一步。

## `proxy`

1. 获取 Share URL/token 和期望输出路径。
2. 运行 `python download_proxy.py <share> [output]`。
3. 对生成的 H.264 MP4 运行 `ffprobe`。

完成标准：LosslessCut-compatible proxy 存在，且 `ffprobe` 成功。然后请用户在 LosslessCut 中剪辑并保存 `.llc`。

## `segments`

1. 获取 Share URL/token、LLC 路径、空输出目录和用户确认的 Origin 传输上限。
2. 运行 `python experimental_workflow.py segments <share> <project.llc> <output-dir> --max-origin-bytes <bytes>`。
3. 读取单份 JSON report，不单独重跑其中已 PASS 的检查。

完成标准：非空 `cutSegments` 已提取；所有输出存在且可 `ffprobe`；`STATUS=PASS`、`RANGE_ONLY=PASS`、`UPSTREAM_HTTP_206=PASS`、`HTTP_200_FULL_BODY=NONE`。

## `verify`

1. 获取有效 Share、真实 LLC、空输出目录与 Origin 传输上限。如用户有 PikPak 官方下载文件，同时获取其路径。
2. 一次运行 `python experimental_workflow.py verify <share> <project.llc> <output-dir> --max-origin-bytes <bytes> [--official-file <path>]`。
3. 保留这一份 report 作为 evidence。整体 FAIL 时只调查 report 中的失败项。

完成标准：单份 report 包含 identity（提供官方文件时）、Range telemetry、累计传输量、packet mapping、preroll/keyframe 元数据与 playability，且 `STATUS=PASS`。

## 操作边界

- Proxy Video 可做 H.264 transcode；Origin Segments 始终由 guarded localhost input 执行 stream copy。
- 把 `--max-origin-bytes` 当作硬保险丝，使用户在执行前确认。
- report 只传递安全 telemetry；不转述 signed Origin URL、token 或 private Share URL。
- 真实流程成功后返回 evidence；保持 Issue #5 gate 与 PR #13 FROZEN。

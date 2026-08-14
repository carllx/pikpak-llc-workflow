---
name: pikpak-llc
description: 处理本仓库的 PikPak Share、proxy preparation、LosslessCut .llc 项目和 authenticated Origin segments。仅匹配 PikPak→LosslessCut 工作流，不用于其他媒体下载或剪辑。
---

# PikPak LLC operator

在 canonical operator worktree 工作。一个 Share invocation 是一个 Job；正常流程只向用户报告绝对 `PROXY_DIR` 与 `SEGMENTS_DIR`。

## Preflight

1. 从 `E:\PROJECTS\pikpak-llc-workflow`、`master` 运行 daily workflow；开发只在 `_codex-temp-*` worktree 进行。
2. 运行程序内置 operator preflight，确认 HEAD、production modules、Skill 和 tracked workflow source clean。
3. 如果检测到 `origin_segment_extractor.py`，报告 `LEGACY_OPERATOR_FILE_DETECTED` 并停止；该文件是 legacy operator code，不是可选入口。

完成标准：canonical/master/clean/module/Skill 全部 PASS，且 legacy extractor 不存在。

## Proxy：用户提供 Share

1. 运行 `python download_proxy.py <share>`，创建 Job 并处理 Share 内全部 video candidates。
2. 确认每个候选都有显式 PASS/FAIL；PASS 输出为 LosslessCut-compatible P480/H.264 且 `ffprobe` 成功。
3. 返回 `PROXY_DIR`，请用户在 LosslessCut 中为所需视频保存 `.llc` 到当前 Job 的 `projects/`。

完成标准：全部候选都有结果；成功 proxy 保留原 proxy 与 H.264 输出；不存在静默跳过。

## Origin：用户说 LLC 已完成

1. 从 `workspace/LATEST.txt` 定位当前 Job；自动发现 `projects/` 中全部 `.llc`。
2. secure profile 有效时直接运行 `python -m pikpak_llc.authenticated_workflow`。
3. profile 缺失或明确失效时，运行一次 `python -m pikpak_llc.profile_setup`，完成后自动重试 authenticated workflow。
4. 检查 batch report：每个 LLC 都有 PASS/FAIL、唯一 source、outputs、budget 与实际 Range bytes；输出位于 `segments/<source-stem>/`。
5. 返回 `SEGMENTS_DIR`。单项 FAIL 时只调查该项，不重跑已 PASS 的片段。

完成标准：全部 LLC 被处理且无静默跳过；每个 PASS 项满足非空可播放输出、stream inventory preserved、`-map 0 -c copy`、RangeGuard PASS、仅 upstream 206、无 HTTP 200 body、累计 bytes 不超过自动 hard fuse。

只有 batch `STATUS=PASS` 且每个 segment 均通过上述 completion gate，才向用户报告 Origin 下载成功。文件存在或进程 exit code 0 不构成成功。

## Daily guardrails

- 正常 Origin 入口固定为 `python -m pikpak_llc.authenticated_workflow`；`experimental_workflow.py segments` 仅保留 evidence/compatibility 用途，`origin_segment_extractor.py` 禁止用于 daily workflow。
- 日常 Origin 从 LATEST Job 恢复 Share、LLC 和输出目录，并自动计算预算；不向用户索取 Share URL、LLC path、output path、`--max-origin-bytes`、rclone config、config password、file ID、file index 或 Range。
- authenticated transport 使用 CurrentUser DPAPI、`%LOCALAPPDATA%\PikPakLLC`、loopback-only rclone 与 `--pikpak-no-media-link`；runtime 明文配置必须在 `finally` 清理。
- report 只传递安全 telemetry；不转述 signed Origin URL、token、credential 或 private Share URL。
- 遇到任何 production FAIL 时，在进行任何诊断推断或代码变更前，必须完整读取并遵循 `docs/operations/origin-troubleshooting.md` 中的排障决策树；禁止直接在 canonical master 修改源码。

## Evidence-only verify

只有 Browser Review Lead 或用户明确要求正式 evidence 时，才运行 `experimental_workflow.py verify`。保留单份 report，整体 FAIL 时只调查其中失败项。

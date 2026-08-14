# ADR 0002: Job Workspace and Output Contract

## Status

Accepted

## Context

Production modules、tests、用户媒体与运行 evidence 曾混在仓库根目录。Agent 无法稳定判断当前 Share job，也难以向用户提供固定输出位置。

## Decision

- Production modules 位于 `src/pikpak_llc/`，tests 位于 `tests/`。
- 一次 Share invocation 创建一个 `workspace/jobs/<job-id>/`。
- 一个 Job 固定包含 `proxies/projects/segments/reports/temp`。
- `workspace/LATEST.txt` 只保存 job-id。Share invocation 仅保存在 gitignored Job 内部 `job.json`，供“LLC 已完成”后自动恢复；不得进入 report、log 或 Git。
- 一个 Job 可包含多个 LLC；daily workflow 稳定发现全部项目。LLC 仍使用 `mediaFileName` 做唯一 source matching，输出写入 `segments/<source-stem>/`。
- 用户可见 interface 只有绝对 `PROXY_DIR` 与 `SEGMENTS_DIR`。
- Root Python 文件仅作为旧调用方的 thin compatibility entrypoints。

## Consequences

Agent 可以从 LATEST Job 自动恢复 Proxy → LLC → Origin 流程。运行文件不再污染 Git；旧脚本调用方式仍可逐步迁移，而不要求一次性破坏兼容性。

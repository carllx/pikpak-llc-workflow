# ADR 0003: Zero-friction authenticated PikPak profile

## Status

Accepted for Issue #22 implementation.

## Context

匿名 `MEDIA_ORIGIN` 对真实文件存在不可用 byte region；authenticated original-file transport 已在真实 LLC segment 上证明可行。实验阶段要求用户反复操作 `rclone config`、输入 config password 和提供路径，不符合 Agent 驱动的 MVP UX。

## Decision

- PikPak credential provisioning 是一次性动作；日常 workflow 只使用本机 secure profile。
- Windows profile 使用 CurrentUser DPAPI 保护，固定存放于 `%LOCALAPPDATA%\PikPakLLC\profiles\`。
- portable `rclone.exe`、runtime 与内部日志分别进入同一 local root 的 `bin/`、`runtime/`、`logs/`，均不进入 repo。
- 每次运行临时 materialize 明文 config，强制 `--pikpak-no-media-link`，仅在 `127.0.0.1` 启动服务，并在 `finally` 中停止服务、删除明文。
- normal entrypoint 从 LATEST Job 自动定位 LLC/source/output，不暴露 config path、file ID、Range 或 max bytes。
- hard fuse 根据 Origin total、source duration、selected duration、2x headroom 和 seek/index overhead 自动估算；若接近完整 Origin，则 fail closed 并要求明确确认，不静默扩大预算。

## Consequences

账号切换或 profile 失效时需要一次新的可见 provisioning；正常剪辑周期无需重复输入。anonymous Share 仍用于 proxy/Job 边界，authenticated original transport 只承担已证明需要登录态的 Origin 局部读取。

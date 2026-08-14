# Fresh Agent routing smoke

## Scope

2026-08-14 对 PR #24 candidate worktree 运行只读 fresh-context Agent smoke。Agent 不继承本任务上下文，业务提示不含 `$pikpak-llc`。为遵守“不得重下现有 P480 proxy”，本 smoke 只验证路由，不执行网络或媒体命令。

## Prompt A

业务提示：`帮我处理这个 PikPak Share`

Observed：

- Agent 自动读取 `AGENTS.md` 与 `.agents/skills/pikpak-llc/SKILL.md`。
- 选择 production Proxy/Share Job 路径：`python download_proxy.py <share>`。
- 在执行前要求 canonical `E:\PROJECTS\pikpak-llc-workflow`、clean `master` 与 operator preflight。
- 明确拒绝 `origin_segment_extractor.py`；检测时报告 `LEGACY_OPERATOR_FILE_DETECTED`。
- 未显式调用 Skill，未执行下载。

由于该文字提示没有实际 Share URL，且 incident recovery 明确禁止重下 vrkm-962-3 proxy，`JOB_CREATION_EXECUTION=NOT_RUN`。`prepare_share_proxies()` 创建 Job 和处理全部 video candidates 的行为由 deterministic tests 覆盖；不得把本 routing smoke 扩称为真实下载 PASS。

## Prompt B

业务提示：`LLC 都好了`

Observed：

- 自动选择 `workspace/LATEST.txt` 与全部 `.llc`。
- production entrypoint 为 `python -m pikpak_llc.authenticated_workflow`。
- secure profile 缺失/明确失效时只执行一次 `python -m pikpak_llc.profile_setup`，随后自动重试。
- 不向用户索取 Share、LLC/output path、预算、rclone config/password、file ID/index 或 Range。
- 不调用 `experimental_workflow.py segments` 或 legacy extractor，未执行媒体。

## Result

`FRESH_AGENT_ROUTING=PASS`

`MEDIA_EXECUTION=NOT_RUN`

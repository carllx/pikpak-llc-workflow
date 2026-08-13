# ADR-0001: 使用稳定 file_id 选择 Share 视频

## 状态

Accepted

## 背景

PikPak Share 既可能指向单个文件，也可能包含多个视频和非视频文件。Proxy 模式需要处理全部视频；一份 LLC 则只对应其中一个源视频。API 数组位置不具备领域含义，不能作为用户或流程的选择依据。

## 决策

Share 解析模块一次枚举文件，输出 `file_id`、`filename` 和 candidate type。后续 media variants、P480 与 Origin 均以稳定 `file_id` 获取。

LLC 流程优先用 `mediaFileName` 对视频候选执行唯一 filename/stem 匹配，再使用匹配项的 `file_id` 获取 Origin。缺失或歧义必须显式失败。现有 single-file helpers 保留为 compatibility wrappers；Folder Share 不引入 `--file-index`。

## 设计审查

`experimental_workflow.py` 达到 500 行阈值后已审查 seam：Share 枚举、候选分类、稳定 ID media 查询与源匹配集中在 `pikpak_api.py` 的 `ShareMediaClient` 模块；workflow 仅负责读取 LLC 和编排。该 seam 提供 locality，避免在 proxy/segments/verify 中重复 API 结构知识。文件仍低于 600 行硬限制。

## 后果

- Folder Share 可以逐个报告所有视频的 proxy 结果。
- 非视频文件不会被当作 proxy candidate。
- LLC 不再依赖 `files[0]` 或其他数组位置。
- 当前不处理递归目录、filename filter 或账号/session bootstrap。

# Agents

## Agent skills

### Issue tracker

Issues are tracked on GitHub. See `docs/agents/issue-tracker.md`.

### Triage labels

Using default canonical triage labels. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context repository. See `docs/agents/domain.md`.

## Pull Request Governance

* Implementation / IDE Agent 不得自行 merge PR。
* 完成实现后，只允许执行：tests、`/code-review`、commit、push、open/update PR、report，然后 STOP。
* Browser Review Lead 是 merge gate。
* 只有当前 review cycle 明确返回 `DECISION: APPROVE` 后，才允许 merge。
* `REVISE` / `STOP` / `FROZEN` 状态绝对禁止 merge。
* Agent 自己执行的 `/code-review` 不等于 Browser Review Lead approval。
* 如果外部裁决尚未返回，默认状态是 `DO NOT MERGE`。

## 工程规范 (Engineering Rules)

* **文件行数硬限制**：所有手写的源码和测试代码文件**不得超过 600 行**物理行数。
* **设计审查阈值**：当文件达到 500 行时，在添加大量新行为前必须进行设计审查。
* **模块拆分原则**：必须按照真实的职责/模块边界进行拆分，而不能仅仅为了满足行数限制强行切断代码。优先采用能让全新 Agent 上下文独立理解的模块结构。
* **豁免项**：自动生成的文件、锁文件 (lockfiles)、第三方引入的代码 (vendored code) 以及测试数据夹 (data fixtures) 不受此限制。

## 沟通规范 (Communication Rules)

* Agent 与用户/协作者的交流默认使用中文。
* 阶段汇报、Review 报告、Issue/PR 说明默认使用中文。
* 代码标识符、API 字段、命令及必要技术术语可以保留英文。

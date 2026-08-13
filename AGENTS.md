# Agents

## Agent skills

### Issue tracker

Issues are tracked on GitHub. See `docs/agents/issue-tracker.md`.

### Triage labels

Using default canonical triage labels. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context repository. See `docs/agents/domain.md`.

## 工程规范 (Engineering Rules)

* **文件行数硬限制**：所有手写的源码和测试代码文件**不得超过 600 行**物理行数。
* **设计审查阈值**：当文件达到 500 行时，在添加大量新行为前必须进行设计审查。
* **模块拆分原则**：必须按照真实的职责/模块边界进行拆分，而不能仅仅为了满足行数限制强行切断代码。优先采用能让全新 Agent 上下文独立理解的模块结构。
* **豁免项**：自动生成的文件、锁文件 (lockfiles)、第三方引入的代码 (vendored code) 以及测试数据夹 (data fixtures) 不受此限制。

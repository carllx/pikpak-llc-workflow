# Issue tracker

This repository uses **GitHub Issues** as its issue tracker.

## For Agents

When creating, reading, updating, or commenting on issues, use the `gh` CLI.

* **List issues:** `gh issue list --state all`
* **Read issue:** `gh issue view <number> --comments`
* **Create issue:** `gh issue create --title "..." --body "..."`
* **Comment:** `gh issue comment <number> --body "..."`
* **Close:** `gh issue close <number>`

Do not use PRs as a request surface.

# Triage labels

This repository uses the following labels for issue triage:

* `needs-triage`: Newly created issue, hasn't been reviewed yet.
* `needs-info`: Blocked waiting for the author to provide more information.
* `ready-for-agent`: Fully specified and ready for an agent to pick up and execute.
* `ready-for-human`: Fully specified but requires a human to execute (e.g. requires physical devices, secret keys, or human judgment).
* `wontfix`: Will not be implemented (includes duplicates and works-as-intended).

## For Agents

When updating an issue's status, use the `gh` CLI to remove the old label and add the new one.

* `gh issue edit <number> --remove-label "needs-triage" --add-label "ready-for-agent"`

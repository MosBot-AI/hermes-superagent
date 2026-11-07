# GitHub Project Execution

English | [简体中文](github-project-workflow-zh.md)

Use the [Hermes Personal Agent Project](https://github.com/orgs/MosBot-AI/projects/2) and [repository Issues](https://github.com/MosBot-AI/hermes-superagent/issues) for live engineering progress. The [roadmap](08-roadmap-and-acceptance.md) defines scope, dependencies and acceptance gates. Keep the Project and Issues consistent when scope changes. Runtime Hermes Projects and Kanban track the user's work inside Hermes.

## Issues and status

Track epics, work packages and implementation slices with repository Issues linked to the Project. Keep the roadmap ID in each epic and work package, and preserve existing numbers and evidence. Convert legacy draft items to Issues in place when possible. When a work package spans several changes, link smaller acceptance slices to the parent Issue and keep its full criteria intact.

| Project status | When to use it |
| --- | --- |
| Backlog | Waiting for ordinary dependencies or for scope to be defined. |
| Ready | Scope and acceptance criteria are clear, applicable dependencies have verified evidence, and the Issue is available to claim. |
| In Progress | The Issue has a current owner and work is underway. |
| Blocked | Progress requires a specific external condition or decision. Record the condition and how to verify that it has cleared. |
| In Review | A reviewable PR is linked with the checks run and any outstanding acceptance. |
| Done | Implementation is merged, all applicable Issue criteria are verified, evidence is linked, and the Issue is closed as completed. |

Cards migrated from the original board may still be In Progress based on earlier partial delivery. Treat a claim as current only when the Issue records an assignee and a branch, run or active PR.

Use the existing `Epic`, `Delivery milestone`, `Priority`, `Dependencies` and `Acceptance evidence` fields. Keep native Issue relationships aligned with the dependency notes when both are present. Apply optional-mode gates when the selected scope requires them. A cancelled or duplicate Issue does not satisfy a dependency. A narrower dependency may advance when its accepted slice is linked and verified even if its broader parent remains open.

## Claim, implement and verify

1. Inspect local changes and read the current Issue, Project fields, dependency evidence and relevant design. Preserve existing work and base the new branch on current `main`.
2. Before editing, self-assign an available Issue, record the agent or run identity, branch and scope in an English claim comment, and set In Progress. Re-read ownership and status. Project updates are not atomic claims. Resolve competing claims before editing and use an explicit handoff when taking over.
3. Implement on a task branch, run the applicable [development checks](../README.md#development-checks), and record meaningful progress or blockers in English on the Issue. Link evidence and name remaining checks. Avoid posting unchanged status.
4. Open a PR into `main` and link it to the Issue. Use a draft while work is underway, then set In Review when the diff and validation are ready for review. Routine project changes reach `main` through a PR. Use automatic closing keywords only when merging will satisfy the linked Issue's acceptance criteria.
5. Verify the merged revision and required CI, contract, security, deployment or live acceptance evidence for the scope. Add links to the Issue and the Project's `Acceptance evidence` field, close as completed, set Done, and recheck direct dependents. Leave outstanding gates visible in In Review or Blocked. A merged PR or offline CI run provides evidence only for the work and checks it covers.

## Read the live board

```sh
gh project view 2 --owner MosBot-AI
gh project item-list 2 --owner MosBot-AI --limit 100 --format json
gh project field-list 2 --owner MosBot-AI --format json
gh issue list --repo MosBot-AI/hermes-superagent --state all --limit 100
```

Resolve current Issue, Project item, field and status option identifiers before any write. If access fails, record which live state could not be verified. Keep credentials and private runtime data out of public Issues, PRs and evidence.

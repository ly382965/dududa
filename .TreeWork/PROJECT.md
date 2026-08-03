# Dududa S08-S11 Model Selection Runtime

## Purpose

Develop Dududa from the completed S01-S07 foundations through an integrated,
deterministic model-selection pipeline, an offline direct-chat runtime, and a
controlled shadow/canary rollout boundary.

## Documents

- Requirements: [requirements.md](requirements.md)
- Project Spec: [spec.md](spec.md)
- Global plan: [task_plan.md](task_plan.md)
- Global progress: [progress.md](progress.md)
- Global findings: [findings.md](findings.md)
- Tree: [tree.yaml](tree.yaml)

## Tree Strategy

### Shape

Hybrid: one model-selection epic owns difficulty assessment and static routing,
followed by milestone branches for the offline runtime and controlled rollout.

### Why

1. Difficulty assessment and routing share one accepted architecture while
   retaining separate contracts and dependency direction.
2. S08, S09, S10, and S11 remain sequential verification gates.
3. A final audit branch proves the cross-stage outcome instead of treating
   branch-local tests as project completion.

### Revisit Conditions

- A branch reveals a missing shared contract or circular dependency.
- Real Adapter behavior contradicts an accepted Provider contract.
- S10 integration requires a product behavior outside explicit mentions,
  direct chat, tools-off, and memory-off.
- S11 production evidence requires authority or infrastructure not currently
  available in the workspace.

## Current Direction

Establish a recoverable S01-S07 Git baseline without touching concurrent WebUI
or Sub2API work, then implement the model-selection epic before entering the
offline runtime and rollout branches.

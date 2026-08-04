# Dududa Long-Running Development

## Purpose

Develop Dududa as a deterministic QQ Agent runtime and a real NapCat-backed,
Mew-equivalent multi-account operator client through isolated, verified epics.

## Documents

- Requirements: [requirements.md](requirements.md)
- Project Spec: [spec.md](spec.md)
- Global plan: [task_plan.md](task_plan.md)
- Global progress: [progress.md](progress.md)
- Global findings: [findings.md](findings.md)
- Tree: [tree.yaml](tree.yaml)

## Tree Strategy

### Shape

Hybrid: the completed model-selection/runtime sequence remains intact, while a
separate Mew/NapCat epic owns a shared Web foundation followed by parallel chat
and directory slices and a joint audit.

### Why

1. Difficulty assessment and routing share one accepted architecture while
   retaining separate contracts and dependency direction.
2. S08, S09, S10, and S11 remain sequential verification gates.
3. A final audit branch proves the cross-stage outcome instead of treating
   branch-local tests as project completion.
4. Web protocol, persistence and account isolation are frozen once in the
   foundation; chat and directory work can then proceed without redefining the
   NapCat boundary.
5. The Web audit depends on both user-facing slices and proves cross-account,
   security and responsive behavior at their integration point.
6. Real group-chat validation is a terminal release gate. It is added as the
   final Tree leaf only after the accepted module topology is complete, so any
   later module audit must remain a predecessor rather than being bypassed.

### Revisit Conditions

- A branch reveals a missing shared contract or circular dependency.
- Real Adapter behavior contradicts an accepted Provider contract.
- S10 integration requires a product behavior outside explicit mentions,
  direct chat, tools-off, and memory-off.
- S11 production evidence requires authority or infrastructure not currently
  available in the workspace.
- NapCat action behavior contradicts the inspected schemas or requires an
  unbounded/raw action proxy.
- Mew behavior cannot remain account-scoped without changing an accepted Web
  foundation contract.

## Current Direction

The local S08-S11 implementation and audit are complete. Authorized real-group
scenario testing is deliberately deferred until every accepted module, local
integration audit and Web testing task is complete. Current work remains on the
independent Mew/NapCat Web parity epic while preserving unrelated Sub2API work.

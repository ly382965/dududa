# Dududa Long-Running Development

## Purpose

Develop Dududa as a deterministic QQ Agent runtime with controlled proactive
outbound behavior, and a real NapCat-backed, Mew-equivalent multi-account
operator client through isolated, verified epics.

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
6. Real group-chat validation is a terminal release gate. The next Tree
   revision must add it as the final leaf after the accepted module topology is
   complete, so every later module audit remains a predecessor rather than
   being bypassed.
7. Answer length is an independent response-planning concern, while proactive
   probes and scheduled digests use a separate initiated-run boundary. Neither
   behavior is hidden inside Model Router, MCP, or the completed inbound S10/S11
   runtime scope.

### Revisit Conditions

- A branch reveals a missing shared contract or circular dependency.
- Real Adapter behavior contradicts an accepted Provider contract.
- S10 integration requires a product behavior outside explicit mentions,
  direct chat, tools-off, and memory-off.
- S11 production evidence requires authority or infrastructure not currently
  available in the workspace.
- A proactive source, scheduler, subscription, or Output Adapter cannot satisfy
  exact target binding, quiet-hour, deduplication, delivery-reconciliation, or
  unsubscribe requirements without revising the outbound Spec.
- NapCat action behavior contradicts the inspected schemas or requires an
  unbounded/raw action proxy.
- Mew behavior cannot remain account-scoped without changing an accepted Web
  foundation contract.

## Current Direction

The local S08-S11 implementation/audit and the independent Mew/NapCat Web
parity epic are complete and verified. The Web client is deployed against real
NapCat with account-scoped caching and explicit capability gaps. Alignment is
now reopened for the next Agent expansion: deterministic short/medium/long
answer planning, opt-in low-frequency conversation probes, and subscription-
based campus/industry/arXiv digests over governed read-only capabilities. No
implementation or real-group send is authorized by this design update. The
accepted Tree must be revised after review so the final real-group gate remains
terminal and depends on the new local audit.

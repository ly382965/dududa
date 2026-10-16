# Task Plan

Branch: demo-runtime-validation
Parent: agent-expansion
Title: Fixed Demo And Runtime Validation

## Scope

- Current-product video outline, fixed feature questions, latest no-send Runtime simulation, defect repair and final Markdown report.

## Acceptance

- [x] One 5–10 minute storyboard covers every implemented user-facing function and the core design, with exact screen path, narration and timing.
- [x] Every feature has one fixed question/action, expected answer criteria and observed evidence from the correct current boundary.
- [x] Latest deployed Runtime message-flow cases are semantically reviewed and prove zero QQ Output/Memory writes; reproduced defects are repaired, regressed and redeployed.
- [x] Final report distinguishes known-set success from generalization and implemented functions from deferred design, with no secrets/private chat content.

## Local Steps

- [x] Inventory current functions and map a compact known demonstration set.
- [x] Execute current Runtime/UI/MCP/plugin simulations and review answers.
- [x] Repair and retest observed defects, then publish the report and verification evidence.

## Out Of Scope

- Recording or generating the video, real QQ sends, B50 lookup, model fine-tuning, broad live canaries, new proactive digest sources or claiming unseen-input accuracy.

## Dependencies

1. Verified plugin-group-controls release and its current production Runtime/configuration.

## Branch Intake Gate

- Inspect: real-group-validation is paused and contains a unique obsolete API-key commit; it still owns separately authorized live canaries.
- Reuse check: existing 100-question runners and reports are inputs, but no current branch owns the requested compact full-product recording artifact plus repair loop.
- New branch rationale: Created from declarative `.TreeWork/tree.yaml`.

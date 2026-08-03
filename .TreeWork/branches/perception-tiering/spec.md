# S09 Perception And Tiering Spec

## Scope

Implement semantic perception, task-complexity evidence, deterministic tier
selection and the conservative social decision used by the first runtime.

## Pipeline

`RulePerception` extracts deterministic mention/reply/question/command and
bounded lexical signals. `ModelPerception` calls the S08 Router with
`PERCEPTION` pinned to Haiku and requires a strict output schema. The merger
prefers deterministic evidence, and the validator rejects the entire model
projection when any identity, reference, enum, confidence or evidence binding
is invalid.

Runtime maps the validated complexity assessment to `TierSelectionContext`.
Low-confidence or conflicting evidence selects Sonnet. Haiku requires clear
low-complexity evidence. Opus requires multiple high-complexity reasons,
configured confidence, role permission and budget. Prompt requests for model
names are ignored as data.

The initial social policy handles only ignore, direct reply, clarification and
defer results needed by S10. Explicit mention is deterministic; tool-required
requests defer because tools are outside this scope.

## Eval

Create a versioned synthetic/sanitized conversation dataset and a deterministic
runner. Labels include intent/entity/reference/tool need, social action,
complexity evidence and the lowest tier meeting a frozen quality threshold.
Split by full conversation/group and report sample distribution, schema-valid
rate, task metrics, under-routing, unnecessary Opus, calibration, latency and
cost. A small initial committed set may establish the harness; the accepted
200-500-case release set must be generated/reviewed before S09 completion.

## Acceptance

- Model failure or invalid output falls back to rules and reduces intervention.
- Prompt injection cannot set a tier, Provider, authorization or Scope.
- Same context, rules, policy revision and model fixture produce the same
  perception, tier and social decision receipts.
- Zero wrong-target, cross-scope, unauthorized-tool and hard-policy violations
  in negative fixtures.

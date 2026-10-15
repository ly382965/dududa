# S08-S11 Completion Audit Spec

## Scope

Perform the requirement-by-requirement audit after all implementation branches
return. Do not add unrelated features to make a narrow test look complete.

## Evidence

- Inspect current files and accepted branch verification, not conversation
  intent or historical claims.
- Run the complete Unit/Contract/integration/security suite, Python 3.10/3.12
  package/import checks, compile, secret scan, shell, Compose and whitespace
  gates, plus affected AstrBot image/plugin smoke tests.
- Reconcile model-selection, Runtime and rollout documents with implementation.
- Prove no unrelated WebUI/Sub2API path was integrated.
- Record real-canary evidence as satisfied only from an authorized run; missing
  external authority remains an explicit project gap and prevents claiming the
  entire objective complete.

## Acceptance

Every requirement has direct evidence and no required work remains, or the
project stays active with precise residual gaps. Bandit absence is verified by
imports, configuration and execution paths rather than assumed from naming.

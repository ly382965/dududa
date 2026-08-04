# Verification

Branch: controlled-rollout

## Latest Verification

- Command: `CPython 3.10/3.12: 350 tests each, 2 host-only skips; Runtime/rollout -W error: 109 tests each; Ruff 0.12.7; format; compileall; imports; JSON; rollback CLI; secrets; whitespace`
- Result: passed
- Coverage gap: Real AstrBot registry and authorized QQ shadow/canary require the derived image, credentials and explicit operator approval; no external send attempted.
- Recorded: unix:1785816445

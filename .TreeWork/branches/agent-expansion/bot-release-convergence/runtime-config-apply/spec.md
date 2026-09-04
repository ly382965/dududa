# One-Click External Model Configuration Apply

Parent: bot-release-convergence

Add an explicit authenticated one-click application of saved external pools,
with status visible in the API Key workbench. Saving remains separate from
applying. Reuse the existing private pool adapter, verified Provider request
behavior and explicitly approved DeepSeek provider-managed retention. Key,
Base URL, model and effort remain configuration, not business-core constants.

Web may not mount private AstrBot configuration, Docker socket, host commands
or raw keys into responses. Route through its existing plugin-scope credential
to a narrow AstrBot plugin API. Keep routes fixed, same-origin and allowlisted;
client supplies revision/intent, never filesystem path or shell command. Do not
return upstream exception bodies or secret fragments. Masked status only.

Reuse prepare/validation logic from apply_deepseek_runtime.py without a public
arbitrary-provider proof bypass. Implement inside the host a serial controlled
reassembly: refuse conflicting apply, pause new affected admission, drain or
refuse while active requests cannot be safely replaced, validate new providers,
write private config/rollback, reconstruct Provider and Dududa runtime objects,
restore previous configuration/instances on failure. Do not shut down old
provider objects while any caller retains them. If a narrowly scoped existing
host reload mechanism is safer, use it and poll actual readiness; do not expose
an OS restart command or generic admin bridge. Report applied only when live
bindings match the requested configuration. Reuse normal revisions/locks and
Git/private backup rather than new hash frameworks.

The shipped behavior must at least support the current official DeepSeek three
tiers, key rotation and Base URL/model edits within verified provider semantics;
unsupported protocol/policy combinations must explain why they cannot apply,
not silently change models or claim success. Generic expansion must not bypass
evidence requirements. Preserve current group policy, caps and non-target
Providers. A later revision must visibly become unapplied; diagnostics alone
must not falsely dirty a semantically unchanged configuration if distinguishable.

Own API Key page/types/service/server routes, new runtime apply service/module,
Core main.py route registration, private adapter and scoped tests. Avoid preview
history files, Arc and deployment. Coordinate composition lifecycle edits with
preview-context-repair. Lead owns live application and release.

Acceptance: browser request to host apply path works under mocks; real client
readiness and applied state drive UI; stale revisions/auth/rollback/active-call
cases tested; no secret responses; no Docker socket; current DeepSeek settings
can be applied by the operator button without a manual shell step.

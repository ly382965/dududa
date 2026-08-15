# Branch Spec

Branch: governed-operations
Parent: control-plane

## Development Design

### Projection Registry

Add a typed operational projection registry. Providers expose bounded snapshots
for Runs, Model Router, MCP/Capability, Plugin, Memory and Proactive/Scheduler.
Adapters translate existing Core registry/health/checkpoint facts; unavailable
or fixture-only subsystems remain explicitly unavailable/shadow rather than
being synthesized in Web. Projection queries are exact-Scope where applicable
and preserve evidence mode and revision.

### Governed Mutation Registry

There is no generic config mutation. A command appears in the Control Plane
only when a dedicated Core handler and its action/authorization contract exist.
Group service lifecycle handlers are registered first. Existing proactive or
Memory operations may be exposed only through their current typed command path;
otherwise the UI remains read-only/disabled with a reason.

Agent permission approval and draft approval are typed command candidates, not
NapCat mutations. If no production Output composition is present, they return
an honest unavailable receipt and cannot update browser state to success.

### Web Experience

The Agent Console reads authoritative sessions/runs/projections and receipts.
The settings and operations views use stable status, evidence mode, Desired/
Effective state and unavailable reasons. The browser neither selects physical
model endpoints nor derives health/permission from OneBot roles.

### Verification

Focused provider/HTTP/UI tests prove projection truthfulness, exact Scope,
unknown provider degradation, command allowlisting, disabled unsupported
mutations and zero direct Agent-to-NapCat send.

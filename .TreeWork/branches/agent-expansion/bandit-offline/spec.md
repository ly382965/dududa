# Branch Spec

Branch: bandit-offline
Parent: agent-expansion

## Development Design

### Purpose And Evidence Boundary

S20 adds a replayable offline foundation for a future Contextual Bandit without
changing any model route. The only eligible future decision point is ranking
endpoints after Static Router hard filters, inside one exact `ModelRole` and
`ModelTier`. S20 does not train a policy, run VW/OBP, call a Provider, consume
real traffic, recommend in Shadow, explore, or install a production hook.

The implementation lives in a framework-neutral `dududa.bandit` package. It
may depend on `dududa.models` endpoint contracts, canonical codec and domain
primitives. `dududa.models`, `dududa.runtime`, AstrBot adapters, proactive code
and Router composition must not import `dududa.bandit` in this branch.

### Eligible Actions And Context Evidence

A `BanditAction` binds one exact `ModelEndpointRef`, `ModelRole` and action ID.
Every action in a decision must have the same role and tier, unique action and
endpoint identities, and the endpoint descriptor digest selected by the Static
Router. A decision requires at least two actions; with fewer actions there is
no Bandit decision.

S20 stores only sanitized context evidence: versioned feature-schema identity
and digest, context-feature digest and optional non-reversible evaluation
cluster reference. It has no prompt, answer, QQ ID, group ID, user ID, raw
message, Memory content or arbitrary feature mapping field.

Router evidence binds routing/catalog/policy/operational snapshot identities
and digests plus model-request and route-plan fingerprints. It is evidence of
the hard-filtered action set, not authority to widen it.

### Decision And Static Baseline

`BanditDecision` is written conceptually before admission and contains the
complete action set, behavior policy identity/artifact digest, per-action
probability distribution, chosen action/propensity, static baseline action and
decision time. Cross-object validation binds any later execution receipt to the
decision digest and chosen action.

Only two offline modes exist:

- `STATIC_BASELINE`: deterministic priority/provider/endpoint ordering; chosen
  action and baseline have probability 1 and every other action has 0;
- `SYNTHETIC_EVALUATION`: all actions have finite positive support and the
  probabilities sum exactly to 1.

There is deliberately no `LIVE`, `SHADOW` or production exploration enum.
Invalid sums, missing actions, non-finite values, zero chosen propensity,
cross-role/tier actions or a chosen action outside the support fail closed.

### Execution And Feedback

An execution receipt is either `EXECUTED` for the exact chosen action with an
admission result and execution time, or `NOT_EXECUTED` with stable reason codes.
Admission rejection or Provider failover cannot replace the chosen action in
the original receipt; a future attempt would require a new decision.

Delayed feedback binds the exact executed receipt, action, reward-policy
identity/revision/digest and observation window. It keeps versioned raw reward
components and provenance before an optional combined reward. `OBSERVED`,
`CENSORED` and `INVALID` are distinct. Silence, missing feedback and censored
windows cannot become zero reward. Cross-object validation rejects feedback for
an unexecuted or different action, duplicate components, invalid windows and
policy/digest mismatches.

### Propensity, Support And OPE

An offline sample binds decision/action IDs, behavior propensity, evaluation
probability, optional observed reward, logged-action outcome prediction and the
evaluation-policy expected prediction. A versioned OPE policy freezes minimum
behavior propensity, maximum importance weight and decimal precision.

Validation reports support/reward coverage and offending sample IDs, then the
estimator refuses any support violation, missing/censored reward, duplicate
sample, sub-floor propensity, excessive weight or zero SNIPS denominator. DR
cannot repair missing support.

For accepted samples, with
`w_i = pi_e(a_i|x_i) / pi_b(a_i|x_i)`:

```text
IPS   = mean(w_i * r_i)
SNIPS = sum(w_i * r_i) / sum(w_i)
DR    = mean(q_e(x_i) + w_i * (r_i - q(x_i, a_i)))
ESS   = (sum(w_i) ** 2) / sum(w_i ** 2)
```

All arithmetic uses finite `Decimal` values and one declared rounding policy;
input order must not affect the report.

### Synthetic Golden

A committed fixed bundle contains no user data or real Endpoint claim. It has
known propensities, rewards and outcome predictions whose IPS, SNIPS, DR and
ESS are independently calculable. The bundle freezes samples, manifest,
report and data card; normal, reversed and fixed-shuffle execution must produce
the same report. Tampered input/report, support violation, zero propensity,
censored reward and invalid DR prediction fail closed.

The bundle is checked by a standalone evaluation API. S20 does not modify the
S18 release-required catalog or reinterpret S19 receipts.

### Verification And Explicit Non-Goals

Verification covers DTO/digest determinism, static baseline replay, exact
same-role/tier support, decision/execution/feedback binding, negative
propensity/support cases, formula goldens, bundle tamper detection, package
exports/import boundaries and dual-Python focused tests.

Out of scope: policy training, a VW Worker, OBP dependency, real Endpoint
conformance, production persistence, Runtime/Router/AstrBot integration,
Shadow recommendations, live exploration, confidence intervals/bootstrap and
learning Tier, AnswerProfile, permissions, Memory Scope, Tool access, reply/
ignore, proactive send/skip, target, schedule or frequency.

# Branch Spec

Branch: demo-runtime-validation
Parent: agent-expansion

## Development Design

Produce one Chinese Markdown report that can drive a five-to-ten-minute product
recording and truthfully describe current behavior. The report owns a timed
storyboard, the complete current user-facing feature inventory, one fixed known
question or operator action per feature, expected answer criteria, observed
results, repairs, runtime/deployment identity and limitations.

“Training set = test set” means the recording uses a frozen, known demonstration
set and the implementation is iterated until those cases pass. It is not model
fine-tuning, must not inject expected answers into production responses and is
not evidence of generalization. Questions may use fixed synthetic group history
or existing public/read-only fixtures so their expected facts are reviewable.

Use the deployed Dududa Runtime preview for model-mediated message flows. It
must use the current three-tier route and report real outcome, tier, model,
reasoning, Capability calls, latency and answer text while preserving zero QQ
Output and zero Memory writes. Do not send real QQ messages. UI/configuration,
MCP control-plane calls and passive plugins that are not ordinary Agent prompts
receive the nearest real boundary test instead of being mislabeled as a model
answer.

Each case has structural assertions and concise semantic criteria. A case passes
only when both pass; HTTP success, a model name or nonempty text alone is
insufficient. Repair every reproducible defect in the exercised scope at its
actual UI/Runtime/Tool/plugin boundary, add a focused regression, rebuild and
deploy changed Bot-only services, then rerun the failed case. Preserve auth,
secrets, group settings, API pools, B50 disabled state and existing no-send
controls. Do not hard-code demo questions or expected prose in production.

The storyboard may group related features visually, but the appendix must retain
one row per feature so “all functions and design” is auditable. Clearly separate
implemented/runnable behavior from design-only or deferred behavior such as live
digests, online Bandit learning, long-term Memory adaptation and B50 lookup.


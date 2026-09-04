# Task Plan

Branch: bot-release-convergence
Parent: agent-expansion
Title: Bot Runtime Repair And Stable Release

## Scope (owned work and boundary; not progress notes or implementation history)

- Formal Agent control-plane repair, clear per-tier connection setup, stable Bot-only release and sanitized GitHub publication.

## Acceptance (done checklist; not exploratory todos unless they decide completion)

- [x] Live Agent status/config/preview work without private historical corpus; errors identify actual readiness, not NO BANDIT.
- [x] Base URL/model setup is discoverable from Key creation; secrets stay write-only and saved/applied state is honest.
- [ ] Bot services run verified stable/source releases, old versions have private rollback artifacts, and excluded services remain unchanged.
- [x] Focused regression/build/deployed checks pass and sanitized implementation/documentation is pushed to GitHub.

## Local Steps (durable working steps toward acceptance; not session-only todos)

- [x] Recover history and inspect actual production source/image mounts and upstream stable versions.
- [x] Repair and test production status/policy/preview and credential UX.
- [x] Build candidate artifacts; preserve state and old releases; upgrade existing containers sequentially.
- [x] Add and test the explicit group proactive participation switch using existing scoped policy/save behavior without enabling any production group.
- [x] Activate five public cache-backed MCPs in the workbench with console-only mappings, real data/provenance and explicit truthful connection checks; deploy and publish sanitized evidence.
- [x] Verify public auth, Runtime and NapCat connections and record sanitized evidence.
- [x] Apply the explicitly approved DeepSeek migration and provider-managed retention, with fresh Provider evidence and a successful no-send Runtime preview.
- [x] Publish the DeepSeek follow-up, retaining the broader branch as partial.
- [x] Fix MCP workbench button/card/scroll layout and verify narrow/desktop browsers; Web `31441a3` deployed with unchanged dependent services.
- [x] Restore missing read-only notifai mounts in Console/AstrBot; both discover all seven tools and the public stats query succeeds. Preserve private rollback and record sanitized evidence.
- [ ] Integrate the three repair child branches and verify their cross-layer behavior.
- [ ] Publish the new 100-question Markdown and run bounded synthetic no-send model previews plus isolated fault/proactive cases; record actual results rather than claiming full human acceptance.
- [ ] Deploy verified Bot-only artifacts, test the apply action and context path, freeze superseded implementations privately, and publish sanitized GitHub changes.

## Out Of Scope (nearby work this branch must not absorb; not unrelated future ideas)

- Other websites, LLM proxies, Authentik, Caddy, databases, new QQ-send grants, password resets and human model-quality claims.

## Dependencies (local or external prerequisites; branch-to-branch order belongs in tree.yaml)

1. Existing authenticated plugin API, external policy/key stores and preserved QQ login state.

## Branch Intake Gate (inspect/reuse/create judgment; not after-the-fact branch sprawl justification)

- Inspect: Completed API Key branch and paused S23 real-group milestone.
- Reuse check: API Key implementation is terminal; S23 owns separate live/human quality evidence, not general release convergence.
- New branch rationale: Bounded maintenance/release successor without reopening completed acceptance or expanding S23 authority.

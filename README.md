# Dududa 2.0

**Dududa is a governed group-context adaptive Agent Runtime.** It keeps a small,
non-removable governance core and composes reversible, observable, scope-bound
capability assets around it. The current repository is an **active internal
canary**, not a production-ready release.

The repository contains the framework-neutral runtime, AstrBot/NapCat adapters,
campus MCP services, the bot control plane, and reproducible offline tests. It
does not contain provider credentials, QQ login state, runtime databases, or
production conversation data.

## Design

```text
QQ / group message
        |
   NapCat OneBot v11
        |
 AstrBot Connector
        |
 MessageEnvelope -> scoped context -> perception
        |             (rules + Haiku schema candidate)
        v
 deterministic eligibility / authorization / budget
        |
 Static Model Router (Haiku / Sonnet / Opus)
        |
 Capability Retrieval -> bounded Planner -> Executor -> Validator
        |                         |
        |                    Unified MCP or Builtin Provider
        v
 Observation -> Direct Chat -> ResponsePlan -> Persona -> final validation
        |
 Output Adapter -> DeliveryReceipt
```

The model proposes categories, entities, tool candidates, and wording. It does
not own identity, scope, permissions, budgets, capability grants, routing
eligibility, or side effects. Deterministic code owns those decisions. MCP is a
transport boundary; it does not grant a capability, schedule a task, choose a
recipient, or send a message.

The three important model dimensions are independent:

- `Tier`: `haiku`, `sonnet`, or `opus` (capability and cost);
- `Reasoning`: `off`, `light`, `balanced`, `deep`, or `maximum`;
- `AnswerProfile`: `short`, `medium`, or `long` (visible output budget).

An internal deployment commonly maps Luna/Terra/Sol to Haiku/Sonnet/Opus. The
model IDs, endpoint URL, and credentials are private runtime configuration and
are not repository guarantees. A static router filters for eligibility first;
quality or cost preferences are applied only after the hard constraints pass.

## Runtime and control plane

`packages/dududa-agent` is framework-neutral. AstrBot, MCP SDKs, model SDKs, and
the Vue/Node web application implement ports around it. The Web application is
the Bot Control Plane (the administrator's workbench), not a second Agent
Runtime. It writes typed Core commands and reads projected Runtime state.

After a bot joins a group, an authorized administrator can choose a versioned
`GroupServiceProfile` initial value. `adaptive` and `preferred` settings let the
Agent choose only within an administrator-approved range; `locked` prevents a
per-turn change. A Web setting never creates a model, grants a capability, or
bypasses Core authorization.

## Capabilities and MCP

Each production-mapped service has a separate server identity, session
lifecycle, schema snapshot, health state, and capability mapping. A Registry
entry alone does not grant a Capability. The five optional PR #10 services are
packaged and registered default-off, but have no Capability mapping and are not
visible to the Planner or production Provider-health composition.

| Service | Kind | Current scope |
| --- | --- | --- |
| iCourse / 评课社区 | Unified MCP | Anonymous public course, teacher, review, ranking, and statistics reads. This is the primary real MCP path. |
| USTC Young / 二课 | Unified MCP | `pyustc`-based activity search, facets, details, and connection status. Apply/cancel/applicant operations are not exposed as public capabilities. |
| USTC Academic / 教务处 | Unified MCP | Public semester, lesson, exam, and teaching-calendar reads. |
| NotifAI / 校园通知 | Unified MCP | Public notice search, details, calendar, deadlines, sources, categories, and statistics. |
| USTC Curriculum / 培养方案 | Unified MCP | Read-only queries over the documented research snapshot at `docs.mmdustc.top/curriculum`; not a live graduation audit. |
| USTC Shuttle / 校车 | Builtin Capability | Versioned local timetable data; no MCP session and no network crawl. |
| Local Recommendations | Optional MCP Server (Registry-only, default off) | Cache-only query over seeded food, activity, and study recommendations; no tool-call writes, refresh, or arbitrary map search. |
| Training Plan | Optional MCP Server (Registry-only, default off) | Cache-only undergraduate college/major overview; not a live graduation audit. |
| Campus Events | Optional MCP Server (Registry-only, default off) | Cache-only USTC home-site notice aggregate, separate from NotifAI's source. |
| College Notice | Optional MCP Server (Registry-only, default off) | Cache-only public notices from configured college sites. |
| Library | Optional MCP Server (Registry-only, default off) | Cache-only public library opening hours by campus. |
| Weather | Candidate Source/Capability adapter | `WttrWeatherSource` and provider contracts exist, but no production composition or daily subscription is enabled. |
| Campus, arXiv, and industry feeds | Reserved interface | Source contracts and fixtures exist; no claim of a live server or live digest. |

The Web MCP console accepts an approved capability ID and input schema. It does
not expose arbitrary `server/tool` passthrough. Discovery updates facts only;
it never grants permission.

## Plugins and local assets

| Component | Status in 2.0 |
| --- | --- |
| `astrbot_plugin_dududa_core` | Active AstrBot adapter for the single 2.0 Agent Runtime, command boundaries, Runtime composition, and delivery. |
| `astrbot_plugin_sub2api_readonly` | Explicit administrator-only read-only commands. `overview` produces one four-section merged forward (today, current billing cycle, history, upstream accounts). It is an independent host plugin, not automatic Agent tool routing. |
| `astrbot_plugin_proactive_chatter` | Side-effect-free policy extension consumed by Core before Bridge admission. It detects echo/robot-interaction contexts and can recommend silence; it does not listen, call a model, or send. Default off. |
| `astrbot_plugin_reply_review` | Conservative review policy asset. It never intercepts messages or calls a Provider by itself; `production_wired=false` until a Runtime secondary-review port is connected. |
| `astrbot_plugin_weather` | Read-only weather source/provider asset. Default off and not registered in production composition. |
| `astrbot_plugin_arc_proxy` | Governed local B50 renderer/provider asset. The caller supplies structured scores; Core owns authorization and delivery. Default off and not in production composition. |
| `astrbot_plugin_ustc_shuttle` | Local timetable Capability Provider used by the Runtime. |
| `astrbot_plugin_reread` | Legacy-compatible standalone plugin, default off and separately scoped; it is not the Agent's social decision layer. |
| `astrbot_plugin_reply_polish` | Legacy LONG-only compatibility layer, default off. The 2.0 Output path owns merged-forward decisions. |
| `astrbot_plugin_dududa_social` | Non-duplicate PR #10 social policy asset. It uses the `/dududa-social` namespace, has empty allowlists by default, and does not register global automatic handlers. |

The vendored Better Reminder, ChatSummary, and Iris sources remain under
`third_party/` for migration or rollback evidence. Their historical handlers,
SQLite state, and direct scheduling/sending are not 2.0 Runtime capabilities.
They must not be presented as active 2.0 features or used as a second control
plane. The old iCourse-specific client and the PR's iCourse implementation are
not part of this integration; iCourse is served through the Unified MCP path.

The standalone `apps/b50-renderer` tool is offline and has no AstrBot or network
dependency. It produces a `1920x1750` PNG from structured or local fixture data;
it does not fetch scores or send media.

## Repository layout

```text
packages/dududa-agent/       # framework-neutral 2.0 contracts and Runtime
apps/astrbot-plugins/        # AstrBot adapters and capability assets
apps/b50-renderer/            # offline B50 renderer
apps/web/                     # Vue/Node Bot Control Plane
services/mcp/icourse/         # iCourse MCP server
services/mcp/notifai/         # NotifAI campus-notice MCP server
services/mcp/ustc-campus/     # Young, Academic, and Curriculum MCP server
services/mcp/local-recs/       # Registry-only seeded recommendations MCP (default off)
services/mcp/training-plan/    # Registry-only program overview MCP (default off)
services/mcp/campus-events/    # Registry-only campus notices MCP (default off)
services/mcp/college-notice/   # Registry-only college notices MCP (default off)
services/mcp/library/          # Registry-only opening-hours MCP (default off)
services/mcp/console/         # MCP registry/capability console
configs/                      # credential-free server and capability mappings
deploy/                       # Compose and derived images
ops/                          # bootstrap, installation, and verification tools
third_party/                  # pinned compatibility sources and patches
docs/                         # design, research, and progress records
```

## Quick start

Requirements: Linux, Docker Compose v2, `uv 0.12.1`, Python 3.10/3.12, Node.js
22, npm 10, and an OpenAI-compatible provider configured privately in AstrBot.

```bash
cp deploy/env/.env.example .env
chmod 600 .env
./manage.sh init
./manage.sh plugins
./manage.sh web-up
```

Default loopback endpoints are:

- Web Control Plane: `http://127.0.0.1:5173`
- AstrBot: `http://127.0.0.1:6185`
- NapCat: `http://127.0.0.1:6099`

`./manage.sh up` builds the full local stack. It may recreate the local
AstrBot/Web services; it does not put credentials or QQ login state in Git.
NapCat must be logged in separately. For a Web-only development session:

```bash
cd apps/web
npm ci
npm run dev
```

Use `python ops/cli/install_plugins.py --owned-only` when testing only the
repository-owned 2.0 assets. The lock file under `third_party/` is retained for
compatibility and migration work; a locked source is not automatically an
Agent capability.

## Verification

The repository favors representative, executable checks over speculative gates:

```bash
uv lock --check
uv sync --project services/mcp/unified-worker --locked --python 3.12.13
uv run --locked python -m compileall -q packages apps services ops tests
uv run --locked python -m unittest discover -s tests -t .
PYTHONPATH=services/mcp/campus-events/src:services/mcp/college-notice/src:services/mcp/library/src:services/mcp/local-recs/src:services/mcp/training-plan/src \
  uv run --with pytest python -m pytest -q \
    services/mcp/campus-events/tests services/mcp/college-notice/tests \
    services/mcp/library/tests services/mcp/local-recs/tests services/mcp/training-plan/tests \
    tests/test_social_plugin.py tests/test_install_plugins.py tests/test_repository_contract.py
uv run --locked python ops/cli/check_secrets.py
cd apps/web && npm run typecheck && npm run test && npm run build
```

The Unified MCP worker `.venv` is an ignored local build artifact and must not be committed. Run the `uv sync`
step before worker-dependent tests. The full suite may still include S23 or historical-baseline failures; see
`docs/refactor/PROGRESS.md` for the evidence boundary before interpreting the summary.

Focused plugin checks include the 2.0 proactive policy, conservative review
policy, weather source, local B50 provider, Sub2API overview, the default-off
social plugin, and the five Registry-only MCP contract fixtures. The optional
MCP services are not Planner capabilities in this release. Real QQ sending,
live source freshness, human quality labels, online Bandit exploration, and
large-scale group rollout remain external acceptance work.

## Data, privacy, and learning boundaries

Do not commit `.env` files, API keys, cookies, tokens, QQ login directories,
databases, conversation exports, Memory records, generated runtime artifacts,
or private provider evidence. Runtime data belongs under ignored private data
roots. Memory v2 currently has offline lifecycle/retrieval and deletion-boundary
evidence, but is not enabled as production Context Builder or automatic writer.

S20 provides offline Bandit decision/feedback contracts and synthetic IPS,
SNIPS, and DR evaluation. There is no training worker, live exploration, or
production reward loop. Any future learning must rank only already-authorized,
security-equivalent candidates and remain observable and reversible.

## Documentation

- [Dududa 2.0 design overview](docs/design/dududa-2.0-overview.md)
- [Runtime progress ledger](docs/refactor/PROGRESS.md)
- [Model routing](docs/design/model-routing.md)
- [Capability and MCP design](docs/design/capability-and-mcp.md)
- [Bot Control Plane](docs/design/bot-control-plane.md)
- [PR #10 selective integration report](docs/integrations/pr10-selective-integration.md)
- [Local development](docs/development/local-environment.md)
- [Chinese README](README.zh-CN.md)

See `docs/refactor/PROGRESS.md` for the evidence-backed completion table and
the explicit external gates. The project is not described as production-ready
until those gates have evidence.

## License

Original Dududa code and documentation are MIT licensed. Third-party components
retain their upstream licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

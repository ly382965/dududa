# References

## Local Authoritative Design

- `docs/refactor/implementation-plan.md`: S08-S11 scope, order and gates.
- `docs/refactor/PROGRESS.md`: S01-S07 implementation reality and residual
  boundaries.
- `docs/design/model-routing.md`: Provider, endpoint, privacy, snapshot and
  fallback contracts.
- `docs/design/perception-and-social.md`: perception, social decision and Eval
  boundaries.
- `docs/design/runtime.md`: state, orchestration, delivery and rollout
  contracts.
- `docs/design/security.md` and `docs/design/persona.md`: deterministic safety,
  budget and rendering invariants.

## External Design Evidence Reviewed 2026-08-03

- LiteLLM `de706a3`: pre-call candidate filters, cooldown, retry and bounded
  fallback; dynamic shuffle/latency/cost routing is not adopted in S08.
- Portkey Gateway `669825c`: error-triggered retry/fallback and Retry-After
  behavior; recursive policy trees are not adopted.
- TensorZero `62eb8f6`: Provider/variant separation, retry/fallback layering and
  reproducible observability.
- RouteLLM `0b64fda` and Semantic Router `ec1dec7`: learned/semantic routing
  requires representative data and remains outside S08-S11.
- Envoy AI Gateway `3fc0f4f` and AIBrix `c54565d`: gateway and self-hosted
  cluster patterns inform future infrastructure, not this single-runtime Core.
- OpenAI current model guidance confirms `gpt-5.6-luna`, `gpt-5.6-terra`, and
  `gpt-5.6-sol`, their context limits, and that reasoning mode/effort are
  independent of Dududa's logical tiers.

## Evidence (external or project sources that materially informed requirements or Spec; not an undigested link dump)

- USTC-XeF2/mew-ui `97df34b3c8ca1747b92003fa3bb6566a58668a3f`
  is a Vue 3 browser QQ client with Router, Pinia, Dexie, TanStack Virtual,
  Tiptap, rich message composition/rendering, contacts, notifications, group
  management/resources and cache settings. Its runtime has one active Milky
  client even though persisted profiles are account-scoped.
- Dududa `apps/web` already has an authenticated server-side NapCat reverse
  WebSocket, a real concurrent account `Map`, real group/friend/recent/history
  data, SSE events and pure-text sending, but flattens rich segments and lacks
  cursor history and Mew's non-chat routes.
- The installed NapCat action schemas expose cursor history, rich OneBot message
  arrays, media/file upload, recall, forward, nudge, member/group management,
  group files, announcements, essence messages and request handling. They do
  not expose Milky-equivalent peer pins, group-folder rename or complete friend
  request history.
- The user's approved interpretation permits IndexedDB caching of real NapCat
  messages and drafts while forbidding demo or alternate local QQ data.

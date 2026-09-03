# Branch Spec

Branch: api-key-pools
Parent: agent-expansion

## Purpose

Provide a first-class, independent Web workbench for configuring LLM Provider
credentials used by Dududa 2.0. The workbench owns credential metadata and
write-time secret ingestion; it does not become a second model router or alter
the existing Haiku/Sonnet/Opus tier policy.

## Product Contract

The page is reachable at `/api-keys` and has one pool for each logical tier:

| Tier | Dududa label | Default role mapping |
| --- | --- | --- |
| `haiku` | Luna / 轻量推理 | perception and ordinary direct chat |
| `sonnet` | Terra / 标准推理 | tool-backed and medium-complexity work |
| `opus` | Sol / 深度推理 | high-complexity or long-context work |

Each pool contains Provider identity, supported protocol settings (OpenAI Chat
Completions or Anthropic Messages), model ID, reasoning effort, timeout, output
budget, enabled state, scheduling mode and a list of independently enabled key
entries. A key entry has a stable ID, display name, SecretRef, priority/weight
and operational state. The pool is the legal credential set for its tier; it is
not a replacement for the Core `TierPolicy`, endpoint admission, health or
rollout controls. Reasoning, budget, scheduling and weight are staging metadata
until a deployment explicitly consumes them.

The UI follows established AstrBot/Sub2API conventions: source/provider split,
multiple keys, priority and health/failure state, explicit Base URL and model,
optional custom headers, and a test action. It keeps the first release focused:
no billing ledger, quota accounting or unrestricted provider discovery.

## Secret Boundary

The browser may submit a secret only on an explicit create/replace request over
the same-origin HTTPS control surface. The server stores it outside Git in a
mode-`0600` JSON file (or an injected deployment path), returns a one-time
write receipt without the secret, and never includes secret values in GET
responses, error text, logs, DOM, localStorage, Runtime Trace or test fixtures.
Existing secrets remain unchanged when an update omits `secret`; an empty
secret is rejected for a new key and means “keep existing” for replacement.
The server returns a stable `secretRef`, masked suffix/prefix, status and
timestamps only. The Runtime receives credentials through its existing
AstrBot Provider Source/environment SecretRef boundary; this branch does not
make the browser a Provider client.

## HTTP Boundary

The Web adapter exposes:

- `GET /api/api-keys`: all three pools with metadata and masked key entries;
- `POST /api/api-keys/pools/:tier/keys`: create a key (secret accepted only here);
- `PUT /api/api-keys/pools/:tier`: replace pool metadata, preserving keys unless
  explicitly changed;
- `PUT /api/api-keys/pools/:tier/keys/:keyId`: update metadata or rotate secret;
- `DELETE /api/api-keys/pools/:tier/keys/:keyId`: disable/remove a key;
- `POST /api/api-keys/pools/:tier/test`: bounded provider probe with sanitized
  result.

All mutating routes require same-origin requests. A configured external
operator/authentication layer remains responsible for public identity; the
Node gateway retains its existing Host and same-origin checks. The API has no
route that returns a raw key.

## Runtime Compatibility

The deployment adapter can map validated pool metadata to AstrBot
`provider_sources[].key` and Provider records after separately checking the
existing `runtime_models_json` descriptors and conformance evidence. This
branch does not register a live reload hook. A pool can be empty or unavailable
without changing the deterministic tier decision; the Runtime keeps its
existing provider-unavailable/fallback behavior. Key rotation and scheduling
are provider-credential concerns only; they cannot widen capabilities, change
answer profile, select a cross-tier endpoint or grant delivery.

## Verification

Focused tests cover schema validation, three-pool isolation, transactional
atomic persistence, private-mode loading, masked GET responses, omitted-secret
rotation semantics, same-origin writes, invalid tier/key rejection, bounded
test results and absence of secret values from responses/log-shaped errors.
Web tests cover navigation, CRUD states, mobile layout and accessible controls.
Existing Runtime/Control Plane tests remain authoritative and are not
duplicated by a broad new gate.

# Findings

Branch: api-key-pools

## Decisions

- AstrBot's native `provider_sources.key` list is the downstream compatibility
  shape; Sub2API-style per-key metadata belongs in the Dududa control surface,
  not in the Core tier decision contract.
- A raw secret is write-only at the Web API boundary. Masked values and a
  SecretRef are sufficient for operator confirmation and avoid a second secret
  reader in the browser.
- The fixed Runtime bindings are `astrbot-luna`, `astrbot-terra` and
  `astrbot-sol`; Source IDs remain independently persisted so a reload cannot
  drift onto a different Provider Source.
- The pinned AstrBot 4.26.2 host registers OpenAI Chat Completion and Anthropic
  Chat Completion Sources, but not an OpenAI Responses Source. The first Web
  contract therefore accepts OpenAI Chat and Anthropic Messages only.
- Reasoning effort, output budget, scheduling mode, provider type and weight are
  staging/operations metadata. Priority and weight produce a deterministic
  credential order for projection, but the page does not claim live weighted
  scheduling or Runtime mutation.
- Persistence and public projection fail closed at concrete credential-loss or
  disclosure boundaries: unsafe file mode, unsupported schema, malformed pool
  or key shape, duplicate bindings, persistence failure, noncanonical masks,
  resolver exceptions, malformed JSON bodies and the shared 4 MiB store limit.
- Pool and Key writes carry a revision token. Provider probes persist health
  timestamps and advance that revision, after which the page refreshes its
  masked public snapshot before allowing the next edit.

## Interface Or Contract Effects

- Adds the versioned Web `/api/api-keys` contract and an external secret-store
  path configured by environment.
- Adds same-origin pool/key mutation routes and a bounded server-side Provider
  probe; GET and mutation responses contain only allow-listed metadata.
- Adds a read-only Python deployment adapter from the shared snapshot to
  AstrBot Source/Provider records. No automatic Provider Manager reload is
  registered.
- Does not modify `ModelTier`, `TierPolicy`, `ModelEndpointDescriptor` or
  Control Plane group profiles.

## Risks And Unknowns

- Public identity remains the responsibility of the deployment's existing
  operator/authentication layer; the Node boundary enforces Host and same-origin
  writes but is not a new identity provider.
- A controlled Provider Manager reload and a synthetic-to-real deployment
  check remain external rollout gates. They must not print the sensitive
  `for_astrbot()` mapping or treat a saved revision as proof of live sync.
- The external raw-key file is excluded from the ordinary S16 plaintext backup
  by design. Recovery requires Secret Manager reinjection plus Provider-side
  rotation; any credential escrow must be a separately encrypted, audited
  deployment facility.

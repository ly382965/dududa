# Findings

Branch: mew-chat-parity

## Decisions (conclusions or decision changes learned during implementation; planned pre-coding design belongs in spec.md)

- NapCat's ordinary forward behavior is `forward_group_single_msg` or
  `forward_friend_single_msg` based on the source scene; the merged-forward
  send actions are not an equivalent substitute.
- Real `get_forward_msg` responses are `node.data.message` trees. Nested nodes
  are inline content and cannot be fetched later with a synthetic ID.
- A media send timeout has an unknown outcome. Its upload token is consumed,
  while a definitive NapCat rejection releases the token for retry.
- Message-level media proxy URLs are ephemeral cache artifacts. IndexedDB keeps
  the real message/resource identity and reacquires a URL through `get_msg`.

## Interface Or Contract Effects (outward effects on commands, state, APIs, generated files, or public contracts)

- Adds typed upload, message refresh, file URL, recall, nudge, single-forward and
  merged-forward endpoints under account/conversation routes.
- Adds `message.download.file`, inline forwarded messages, staged outgoing media,
  upload/file receipts and account-scoped search cursor fields to the Web DTOs.
- File proxies use a separate attachment route; media proxies preserve valid
  Range/416 behavior and reject malformed ranges.

## Risks And Unknowns (latent hazards after branch work; not unfinished tasks)

- NapCat versions older than 4.8 are conservatively denied the version-gated
  forward, nudge and file-download actions. Additional implementation variants
  may need a future guarded capability probe table.
- QQ face assets are sourced from the same QFace catalog as Mew; when that
  external catalog is unavailable, the renderer uses the real segment URL or
  an explicit textual fallback.

# Findings

Branch: mew-directory-parity

## Decisions (conclusions or decision changes learned during implementation; planned pre-coding design belongs in spec.md)

- NapCat 4.18.7 group file actions always start at index zero but its core walks
  pages until `file_count`; Dududa requests a bounded 500 items and marks a
  500-item result as potentially truncated instead of silently hiding it.
- Folder rename remains explicitly unsupported because the inspected NapCat
  action set has no folder-rename operation.
- Ordinary friend-request history cannot be backfilled by NapCat. Observed
  browser records are retained as read-only evidence until a live session
  confirms actionability.
- Management-page account context is separate from the chat account filter so
  selecting an operator account never selects or marks a QQ conversation read.

## Interface Or Contract Effects (outward effects on commands, state, APIs, generated files, or public contracts)

- Added account-scoped directory, notification, member, group settings,
  essence, announcement and group-file HTTP endpoints and normalized SSE events.
- Added Vue Router management/deep-chat routes, a Pinia directory store and
  IndexedDB notification/history generations for bounded clearable persistence.
- Group file pages expose `truncated`; notifications expose `actionReason`;
  signed file/folder/announcement IDs are valid for exactly one account/group.
- Browser writes require a same-origin `Origin` and a loopback `Host`; the
  OneBot token remains server-side and reverse WebSocket authentication remains
  unchanged.

## Risks And Unknowns (latent hazards after branch work; not unfinished tasks)

- The production client bundle is about 918 kB before gzip and should be split
  if startup performance becomes material.
- Real destructive request/group/file receipts remain intentionally untested;
  the branch proves exact actions and denial behavior through Fake NapCat and
  leaves real mutations behind explicit operator authorization.

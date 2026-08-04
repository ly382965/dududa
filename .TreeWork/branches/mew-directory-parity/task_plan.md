# Task Plan

Branch: mew-directory-parity
Parent: mew-parity
Title: Mew Directory And Group Parity

## Scope (owned work and boundary; not progress notes or implementation history)

- Contacts, notifications, group members/management/resources and settings
  routes over Foundation APIs.

## Acceptance (done checklist; not exploratory todos unless they decide completion)

- [x] Real friend/group directories search and open the correct account-scoped
  conversation.
- [x] Requests and group lifecycle notifications update live and supported
  pending requests can be accepted/rejected with real receipts.
- [x] Member, group, announcement, essence and file workflows match mapped Mew
  behavior with role/capability gates and explicit protocol gaps.
- [x] Theme, storage statistics, backfill/cancel and cache cleanup work per
  account without QQ mutations.

## Local Steps (durable working steps toward acceptance; not session-only todos)

- [x] Add typed gateway endpoints/events for directory, request, member, group
  and resource capabilities.
- [x] Port Mew Router, stores, views and group/UI components account-safely.
- [x] Port settings and storage/backfill operations.
- [x] Adapt Mew tests and add cross-account/stale-request/capability coverage.
- [x] Verify, record and commit the branch.

## Out Of Scope (nearby work this branch must not absorb; not unrelated future ideas)

- Chat composer/rendering, Agent Runtime, unsupported NapCat action emulation
  and public-network authentication.

## Dependencies (local or external prerequisites; branch-to-branch order belongs in tree.yaml)

1. `mew-parity-foundation` must be complete and integrated.
2. Destructive real group/file/request actions require explicit user authority.

## Branch Intake Gate (inspect/reuse/create judgment; not after-the-fact branch sprawl justification)

- Inspect: Current Dududa Web has no directory routes; Mew already separates
  these stores/views from chat.
- Reuse check: One branch coherently owns the related non-chat QQ workflows and
  avoids competing server action definitions.
- New branch rationale: Created from declarative `.TreeWork/tree.yaml`.

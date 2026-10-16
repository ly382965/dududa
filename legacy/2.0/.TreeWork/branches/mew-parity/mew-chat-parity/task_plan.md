# Task Plan

Branch: mew-chat-parity
Parent: mew-parity
Title: Mew Chat Parity

## Scope (owned work and boundary; not progress notes or implementation history)

- Mew chat history, virtual scrolling, rich rendering, composition, drafts,
  search, media and message operations over Foundation APIs.

## Acceptance (done checklist; not exploratory todos unless they decide completion)

- [x] All accepted incoming segment types render or show an honest fallback.
- [x] All supported outgoing segments and message operations issue the correct
  account-scoped typed gateway action and expose real success/failure.
- [x] Cached-first bidirectional history, virtual anchors, unread/jump/latest,
  local search and drafts match adapted Mew behavior tests.
- [x] Desktop and mobile chat interactions remain usable with the account rail
  and Agent unavailable surface.

## Local Steps (durable working steps toward acceptance; not session-only todos)

- [x] Port Mew chat services/composables and make every singleton/account key
  account-scoped.
- [x] Port renderers, media/forward dialogs and message actions.
- [x] Port Tiptap composer, face/mention/reply/draft and upload flows.
- [x] Adapt Mew Unit/E2E tests and add NapCat/cross-account failure coverage.
- [x] Verify, record and commit the branch.

## Out Of Scope (nearby work this branch must not absorb; not unrelated future ideas)

- Contacts, notifications, group administration/resources, Agent Runtime and
  changes to Foundation contracts without a Spec revision.

## Dependencies (local or external prerequisites; branch-to-branch order belongs in tree.yaml)

1. `mew-parity-foundation` must be complete and integrated.
2. QQ-visible or destructive real-account operations require explicit audit
   authority; automated tests use transport fixtures only.

## Branch Intake Gate (inspect/reuse/create judgment; not after-the-fact branch sprawl justification)

- Inspect: Mew already owns coherent chat behavior; Dududa's current ChatPane is
  a text-only layout shell.
- Reuse check: This is the single chat behavior branch; no additional
  renderer/composer branches are needed unless file ownership later conflicts.
- New branch rationale: Created from declarative `.TreeWork/tree.yaml`.

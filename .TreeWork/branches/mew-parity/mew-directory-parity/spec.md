# Branch Spec

Branch: mew-directory-parity
Parent: mew-parity

## Development Design

Port Mew's contacts, notifications, group members, group settings/resources and
settings routes against Foundation account/capability contracts. Vue Router and
Pinia stores preserve one active account context; the combined inbox remains a
chat-only projection so management actions always show the acting account.

Contacts load real NapCat friend/group lists, support pinyin/number search and
open account-scoped conversations. Notifications combine real-time request and
group lifecycle events with bounded NapCat system-message retrieval. Friend
request history starts at observed events when NapCat cannot backfill it and the
UI states that limitation.

Group member views preserve role, level/title, card, join/last-sent metadata and
capability/role-gated admin, kick, card, group-name, whole-mute and quit actions.
Resources cover essence pagination, announcements and group files with safe
download/upload/move/rename/delete/create-folder operations. Folder rename stays
disabled for the inspected NapCat version.

Settings cover theme, implementation/capability information, account-scoped
message/event/cache statistics, history backfill/cancel and cache cleanup. Cache
controls never mutate QQ data. Mew tests are adapted for account switching,
unsupported capabilities, stale async request isolation and mobile routing.

Browser persistence is account-scoped, bounded and clearable. Persisted pending
requests are historical evidence and remain non-actionable until the current
NapCat session confirms them. Cleanup generations prevent responses that began
before an account/date/global clear from repopulating IndexedDB.

Every browser write requires a loopback same-origin request. Resource IDs are
server-signed for one account and one group, and group-file uploads use matching
browser-persistent and server in-flight/unknown-result guards so an uncertain
NapCat outcome is not replayed after refresh, concurrency or Web restart.

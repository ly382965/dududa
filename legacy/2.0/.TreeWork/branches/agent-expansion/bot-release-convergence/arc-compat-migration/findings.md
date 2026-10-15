# Findings

Branch: arc-compat-migration

## Decisions (conclusions or decision changes learned during implementation; planned pre-coding design belongs in spec.md)

- Operator subsequently deferred score lookup. `b50_enabled` is now independent and
  default-off; compatibility-on/B50-off serves bind/info/chart without any upstream query.
  Existing B50 protocol code and explicitly opted-in fake tests remain for future activation.

- Old B50 is not a read-only query: it serially unbinds/rebinds the fixed upstream account
  before requesting B50, then relays only image components to the requesting group. Lead
  explicitly approved retaining these user-command side effects as a compatibility boundary.
- Plain upstream failures must not be acknowledgements: failure/error/invalid text now
  pauses the flow before it can query a previously bound account. Delayed images likewise
  do not acknowledge unbind/bind phases.
- Import/startup lazily defers all compatibility storage/assets and sends nothing; this
  permits an enabled plugin to load even if an optional chart asset dependency is absent.

## Interface Or Contract Effects (outward effects on commands, state, APIs, generated files, or public contracts)

- All four existing QQ command names survive; invalid friend codes now get usage text
  before persistence and queries are bounded to 200 control-character-free characters.
- Added `_conf_schema.json` fields `compatibility_enabled`, `allowed_group_ids`,
  `upstream_bot_id`, `state_root`, `assets_root`, `catalog_root`, `renderer_assets_root`,
  `queue_capacity`, `request_timeout_seconds`, `transport_timeout_seconds`. `enabled`
  remains solely the old local-capability flag. All authority-bearing defaults are off/empty.
- Added `b50_enabled=false` for the reduced release; disabling B50 does not disable the
  other three compatibility commands or alter the local Capability.
- SQLite bindings retain their table/column keys; existing data can stay outside Git in its
  current directory. Catalog's four JSON files and game/rendering assets remain external.
- AstrBot's currently deployed `star_manager.py` detects schema at lines 1151–1165 and
  injects `config` at lines 1220–1225; the new constructor accepts that keyword unchanged.
- Root owns dependencies in the image; plugin has no startup installer. Vendor source
  retains its original `616 SB License` and upstream revision attribution.

## Risks And Unknowns (latent hazards after branch work; not unfinished tasks)

- Legacy upstream supplies no request correlation ID or documented success structure.
  Existing non-failure text acknowledgements remain; normal successful completion retains
  the original two-second grace but cannot prove every late duplicate belongs to a request.
  Timeout/uncertain state therefore pauses B50 and clears pending requests until an operator
  confirms upstream idle and reloads. This limitation is explicit, not silently called solved.
- For this release B50 remains off, so no new upstream-idle check is required. Restart can
  cancel old requests and cannot be described as lossless migration; live B50 acceptance
  is deferred by the operator rather than incorrectly marked verified.
- Binding schema is global per user as before, not per-group. Migration must preserve,
  not broaden, the original bot/group authorization scope.
- The vendor license grants redistribution with retained notices and an additional clause:
  `The person should speak loudly with "616 SB!", before using this Software.` Lead has
  been informed; no game assets are redistributed by this change.

# Third-Party Sources

This directory is the canonical source location for Dududa's pinned third-party
AstrBot plugins, local patches, and the vendored Better Reminder source.

`plugins.lock.json` remains schema v1 during the S17 compatibility release. The
root `plugins.lock.json`, `patches`, and `vendor` paths are one-Release
compatibility symlinks, not second editable authorities. The installer reads
only the canonical lock. S22 may remove these links only after consumer and
previous-Release recovery evidence exists.

ADR 0005 Manifest v2 is not active yet. It requires verified source tree
digests, dependency locks, license files, and redistribution evidence for every
component. Missing evidence, including the unresolved Iris license, must block
that authority cutover instead of being replaced with invented values.

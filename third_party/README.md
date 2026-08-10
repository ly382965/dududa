# Third-Party Sources

This directory is the canonical source location for Dududa's pinned third-party
AstrBot plugins, local patches, and the vendored Better Reminder source.

`plugins.lock.json` remains the canonical schema-v1 authority. S22 removed the
root `plugins.lock.json`, `patches`, and `vendor` compatibility symlinks after
consumer migration and previous-Release recovery evidence. The installer reads
only this directory.

ADR 0005 Manifest v2 is not active yet. It requires verified source tree
digests, dependency locks, license files, and redistribution evidence for every
component. Missing evidence, including the unresolved Iris license, must block
that authority cutover instead of being replaced with invented values.

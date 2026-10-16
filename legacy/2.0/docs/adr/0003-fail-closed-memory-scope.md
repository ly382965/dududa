# ADR 0003: Fail-Closed Memory Scope

Status: accepted for migration design
Date: 2026-07-18

## Context

Core JSON memory is keyed too narrowly and disconnected from model context.
Iris is independent and its local patch still permits records with missing user
metadata and global fallback when a scoped graph API is unavailable. Semantic
similarity cannot be trusted to determine conversation ownership.

## Decision

Agent Core owns a validated `MemoryScope` and `MemoryRepository` Protocol.
Repositories filter exact authorized Scope before semantic ranking. Missing any
field required by that `MemoryType` fails closed: every record requires platform,
Bot, conversation, Persona, and memory type; group-owned records require group,
and user-owned records require user. There is no unscoped fallback.

Iris remains an implementation adapter. Its patch is defense in depth, not the
primary privacy contract. Legacy records with incomplete Scope are quarantined
until an offline, reversible migration classifies them.

## Consequences

- Some legacy memories may be temporarily unavailable rather than risk leakage.
- Backend adapters need contract and negative isolation tests.
- Explicit policy is required for any user-profile reuse across conversations.
- Memory migration requires inventory, backup, dry run, and rollback.
- Model prompts cannot authorize a broader memory query.

## Alternatives Rejected

- Global vector search followed by model filtering: violates the trust boundary.
- Treating missing metadata as shared memory: silently leaks legacy data.
- Depending directly on Iris APIs: couples core behavior and privacy to one
  third-party plugin.

## Verification

Cross-group, cross-user, private-to-group, cross-Bot, cross-Persona, missing
metadata, expiry, export, and delete tests must pass for every repository
implementation. An adapter returning any out-of-scope record is a security
failure, not a partial result.

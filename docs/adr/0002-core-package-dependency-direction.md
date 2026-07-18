# ADR 0002: Core Package And Dependency Direction

Status: accepted for migration design
Date: 2026-07-18

## Context

Current policy, audit, state, Provider, MCP, command, and rendering behavior is
concentrated inside AstrBot plugin roots. Core modules import AstrBot types,
which prevents framework-neutral unit tests and future connectors. A new package
must coexist with working plugins before it becomes authoritative.

## Decision

Create the installable distribution `dududa-agent`, exposing import package
`dududa`. Dependency direction is adapters -> application Runtime -> domain and
owned Protocols. Concrete infrastructure implements those Protocols and is
injected at an application composition root.

The package will be installed into the derived AstrBot image before plugins
import it. Repository-root path behavior is not an allowed runtime dependency.
Initial package work is additive and receives no production events.

Core must not import AstrBot, NapCat, OneBot, Docker, Compose, a concrete MCP
server, Iris, or a Provider SDK.

## Consequences

- Domain and Runtime can run under normal Python tests without AstrBot.
- AstrBot adapters remain responsible for Event and component conversion.
- The Dockerfile and CI must install the package before adapter cutover.
- Protocol ownership and composition code require deliberate review.
- Some current convenience access to AstrBot config and Providers must be
  replaced by gateways rather than moved unchanged.

## Alternatives Rejected

- Mechanically splitting `main.py` inside the same plugin: improves file size
  but preserves framework coupling.
- Adding repository root to `PYTHONPATH`: fragile and different from packaged
  production behavior.
- Rewriting the entire plugin against the new package in one PR: not reviewable
  or safely rollback-capable.

## Verification

- Import-boundary tests detect forbidden imports.
- Package unit tests run without AstrBot installed.
- Derived image imports both `dududa` and all compatibility plugins.
- Existing command/event contracts remain green until selective cutover.

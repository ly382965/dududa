# Contributing

Use short-lived branches and pull requests. `main` must remain deployable.

## Workflow

1. Create a branch from the current `main`.
2. Keep runtime data and credentials outside the repository.
3. Add or update tests for behavioral changes.
4. Run the local verification commands from `README.md`.
5. Open a pull request describing behavior, migration impact and rollback.
6. Obtain review from the owners in `.github/CODEOWNERS`.

Changes to `third_party/plugins.lock.json`, `third_party/patches/`, persona safety boundaries, permission
logic or persistent-data formats require explicit review. Do not update an
upstream plugin to `HEAD`; lock a full 40-character commit.

Commits should be focused and use imperative subjects, for example:

```text
Add group isolation regression coverage
Pin ChatSummary plugin update
```

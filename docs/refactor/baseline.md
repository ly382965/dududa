# Dududa Refactor Baseline

Status: Phase 0 verified baseline
Recorded: 2026-07-18T15:55:53+08:00
Commit: `2767cc9768d4bce63d4b4ee811add951ebce6870`
Branch: `main`, tracking `origin/main`

## Rules Used For This Baseline

- No business source was edited.
- No production container was restarted, reconfigured, or given test data.
- No production database, `.env`, Provider configuration, QQ login state, or
  user data was read.
- Networked plugin checks used an isolated temporary directory that was removed
  on exit.
- MCP smoke testing used a new `--network none --rm` container with a temporary
  SQLite database.
- Docker image build was allowed, but no service was started from the rebuilt
  image.

## Environment

| Tool | Baseline value |
| --- | --- |
| Python | 3.12.3 |
| Git | 2.43.0 |
| Docker Engine client | 29.5.2 |
| Docker Compose | 5.1.4 |
| Tracked files | 75 |
| Compose services | `astrbot`, `napcat` |

The host's `/usr/bin/python3` does not have `pip`, `venv`, or the `mcp` package.
This matters for local developer commands but not for the derived AstrBot image,
which installs the iCourse package and its dependencies.

## Git Baseline

Initial command:

```bash
git status --porcelain=v1 --branch
git rev-parse HEAD
git branch --show-current
git remote -v
```

Result:

```text
## main...origin/main
2767cc9768d4bce63d4b4ee811add951ebce6870
main
origin git@github.com:ly382965/dududa.git
```

No untracked or modified repository file existed before the refactor documents
were added.

## CI-Equivalent Local Gates

| Check | Command | Result |
| --- | --- | --- |
| Shell syntax | `bash -n manage.sh` | Pass |
| Python compilation | `python3 -m compileall -q plugins services scripts tests` | Pass |
| Unit/contract tests | `PYTHONPATH=services/icourse-mcp/src python3 -m unittest discover -s tests -v` | Pass: 8 tests in 0.355 s |
| Repository scan | `python3 scripts/check_secrets.py` | Pass: 75 files |
| Compose parse | `docker compose --env-file .env.example config --quiet` | Pass |
| Compose service list | `docker compose --env-file .env.example config --services` | `astrbot`, `napcat` |
| Git whitespace check | `git diff --check` | Pass |

The eight tests were:

1. Compose contains only AstrBot and NapCat.
2. First-party plugin mounts remain read-only.
3. Plugin manifest has the expected six entries and exact Git commits.
4. Iris patch text contains the current user/group guards.
5. MCP template contains only iCourse at the expected cache path.
6. Persona seed is idempotent and selects `dududa`.
7. iCourse initializes its SQLite tables.
8. MCP sync preserves an unrelated existing server and writes mode `0600`.

## Third-Party Plugin Install Baseline

The installer was run twice against a new temporary data root:

```bash
python3 scripts/install_plugins.py --data-root "$temporary_root"
python3 scripts/install_plugins.py --data-root "$temporary_root"
```

First pass installed all declared components:

| Plugin | Declared version | Install result |
| --- | --- | --- |
| Better Reminder | v1.4 | Vendor copy succeeded |
| ChatSummary v2 | 1.7.1 | Exact commit checkout succeeded |
| Iris Chat Memory | 0.1.1+privacy.1 | Exact commit and privacy patch succeeded |
| PokePro | v2.1.0 | Exact commit checkout succeeded |
| Reread | v2.0.0 | Exact commit checkout succeeded |
| Meme Manager | v3.20 | Sparse exact-commit checkout succeeded |

The second pass reported every plugin as `locked plugin is current`, proving the
current marker is idempotent for an unchanged manifest. This does not prove an
upgrade works: a changed marker is refused unless `--force` is supplied, and
`manage.sh upgrade` does not supply it.

The baseline installer test also does not prove runtime dependencies are
installed. `install_plugins.py` places source only and relies on AstrBot for any
plugin `requirements.txt` behavior.

## Docker Build Baseline

Command:

```bash
docker compose --env-file .env.example build astrbot
```

Result: pass. The pinned AstrBot base resolved, the iCourse source was copied,
`icourse-mcp==0.1.0` built, and the local image `dududa/astrbot:local` was
exported successfully.

The build showed that package dependency resolution is not fully reproducible:
the base image is digest-pinned, while iCourse uses open-ended minimum versions.

## MCP Handshake Baseline

Running the MCP check directly on the host failed as expected from the missing
developer dependencies:

```text
ModuleNotFoundError: No module named 'mcp'
```

Attempting an isolated standard virtual environment also established that the
host lacks `python3.12-venv` and `ensurepip`. These are host prerequisites, not a
repository test failure.

The same check then ran in a fresh, network-disabled, automatically removed
container from `dududa/astrbot:local`:

```bash
docker run --rm --network none \
  -e PYTHONPATH=/opt/dududa/icourse-mcp/src \
  -e ICOURSE_MCP_DB_PATH=/tmp/icourse.sqlite3 \
  --entrypoint python dududa/astrbot:local \
  /opt/dududa/icourse-mcp/scripts/check_mcp.py
```

Result: pass. Tool discovery returned all ten tools:

```text
icourse_stats, search_courses, get_course, get_reviews, crawl_course,
crawl_courses, search_site_courses, crawl_latest_reviews, check_robots,
export_dataset
```

`icourse_stats` successfully initialized an empty temporary database and
returned zero courses and reviews.

## GitHub Actions State

`.github/workflows/ci.yml` defines a test job and a Gitleaks job. The test job
installs iCourse before running compilation, tests, shell validation, Compose
validation, and the repository scan.

The repository is private and no GitHub API credential was used during this
audit. Therefore the external Actions run status is **not verified** here. Local
equivalent checks pass, but that is not evidence that a particular remote run
completed.

## Coverage Gaps

The current green baseline does not cover:

- AstrBot plugin imports, registration, event priority, or event stopping.
- Command behavior, permissions, confirmation scope, or audit redaction.
- Cross-group, cross-user, private-to-group, Bot, or Persona memory isolation.
- Iris patch behavior with missing metadata or older APIs.
- TargetTalk decision behavior and history privacy.
- ReplyPolish splitting, truncation, and global result-hook behavior.
- MCP tool schemas, timeout, retry, path policy, or failure envelopes.
- Installer integrity, license completeness, dependency installation, or a
  changed-lock upgrade.
- Docker health, OneBot connectivity, backup, restore, and rollback.
- A complete `manage.sh up` on an empty host.

## Baseline Risks That Tests Must Not Hide

1. `manage.sh upgrade` cannot reliably replace a changed plugin lock.
2. NapCat has the complete AstrBot data directory mounted read-write.
3. Iris isolation is only string-checked and has fail-open paths.
4. Core lightweight memory lacks conversation and Persona scopes and is not
   retrieved into model context.
5. Model and MCP access are duplicated across concrete paths.
6. `export_dataset` accepts an arbitrary output path.
7. The host development instructions assume Python packaging tools that are not
   installed on this audited host.

This baseline is the rollback reference for subsequent phases. A future phase
must not call a regression acceptable merely because these initial checks stay
green; it must add behavior coverage before replacing the relevant code.

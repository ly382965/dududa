# Submission plugin sources

These sources were exported from the first successful submission-image build.
The installer checked out the commits in `third_party/plugins.lock.json` and
applied the declared Iris privacy patch. Each plugin retains its `.dududa-lock.json`.
The quickstart image uses this copy so rebuilding does not clone GitHub repositories.
The original locked installation workflow remains available in `ops/cli/install_plugins.py`.

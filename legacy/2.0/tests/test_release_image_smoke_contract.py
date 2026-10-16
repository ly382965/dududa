from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ops" / "cli" / "smoke_release_images.sh"


class ReleaseImageSmokeContractTests(unittest.TestCase):
    def test_script_uses_only_unique_disposable_network_none_containers(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertTrue(os.access(SCRIPT, os.X_OK))
        self.assertIn("trap cleanup EXIT INT TERM", source)
        self.assertIn('docker rm -f "$web_container"', source)
        self.assertEqual(source.count("--network none"), 2)
        self.assertIn('web_container="dududa-s19-web-${suffix}"', source)
        self.assertIn('--volume "$ROOT_DIR:/workspace:ro"', source)
        self.assertIn(
            '--volume "$ROOT_DIR/configs:/opt/dududa/config:ro"',
            source,
        )
        self.assertIn('(mode, reason) == ("unified", "unified_ready")', source)
        self.assertIn("--env ASTRBOT_ROOT=/tmp/astrbot", source)
        self.assertIn(
            '--volume "$token_file:/run/secrets/onebot_access_token:ro"', source
        )
        for forbidden in (
            "docker compose",
            "docker restart",
            "docker stop",
            "docker start",
            "mmdustc-edge",
            "STACK_DATA_ROOT",
            "/AstrBot/data:/AstrBot/data",
        ):
            self.assertNotIn(forbidden, source)

        completed = subprocess.run(
            ["bash", "-n", str(SCRIPT)],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_fake_docker_run_proves_command_shape_and_cleanup(self) -> None:
        image_id = "sha256:" + "a" * 64
        with tempfile.TemporaryDirectory(prefix="dududa-s19-fake-docker-") as temporary:
            workspace = Path(temporary)
            docker = workspace / "docker"
            log = workspace / "docker.log"
            docker.write_text(
                "#!/bin/sh\n"
                'printf \'%s\\n\' "$*" >>"$FAKE_DOCKER_LOG"\n'
                'if [ "$1" = image ] && [ "$2" = inspect ]; then\n'
                f"  printf '%s\\n' '{image_id}'\n"
                'elif [ "$1" = run ]; then\n'
                "  case \" $* \" in *' --detach '*) printf '%s\\n' fake-container ;; esac\n"
                "fi\n"
                "exit 0\n",
                encoding="utf-8",
            )
            os.chmod(docker, 0o700)
            environment = dict(os.environ)
            environment.update(
                {
                    "PATH": f"{workspace}:{environment['PATH']}",
                    "FAKE_DOCKER_LOG": str(log),
                    "DUDUDA_REPOSITORY_ROOT": str(ROOT),
                }
            )

            completed = subprocess.run(
                [str(SCRIPT)],
                cwd=ROOT,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(
                json.loads(completed.stdout),
                {
                    "astrbot_image_id": image_id,
                    "status": "passed",
                    "web_image_id": image_id,
                },
            )
            calls = log.read_text(encoding="utf-8").splitlines()
            run_calls = [line for line in calls if line.startswith("run ")]
            self.assertEqual(len(run_calls), 2)
            self.assertTrue(all("--network none" in line for line in run_calls))
            self.assertTrue(
                any(line.startswith("rm -f dududa-s19-web-") for line in calls)
            )
            self.assertFalse(any(line.startswith("compose ") for line in calls))


if __name__ == "__main__":
    unittest.main()

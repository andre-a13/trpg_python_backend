"""Exercise the real deployment shell with Docker/network commands simulated."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BASH = (str(Path(shutil.which("git")).parents[1] / "bin/bash.exe")
        if os.name == "nt" else shutil.which("bash"))

DOCKER = r'''#!/usr/bin/env bash
set -eu
echo "$*" >> "$TRPG_TEST_LOG"
if [ "$1" = network ]; then exit 0; fi
if [ "$1" = inspect ]; then
    if [ "$TRPG_TEST_RUNNING" = true ] || [ -f "$TRPG_TEST_READY" ]; then echo true; else echo false; fi
    exit 0
fi
if [ "$2" = ps ]; then echo demo-api; exit 0; fi
if [ "$2" = up ]; then touch "$TRPG_TEST_READY"; exit 0; fi
if [ "$2" = exec ] || [ "$2" = run ]; then
    case "$*" in
        *"/app/data/data.db"*) cat > "$TRPG_TEST_STREAM"; exit "$TRPG_TEST_BACKUP_EXIT" ;;
        *) cat > /dev/null ;;
    esac
fi
'''


class DeployScriptTests(unittest.TestCase):
    def deploy(self, running=True, backup_exit=0):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for folder in ["bin", "app", "data"]:
                (root / folder).mkdir()
            (root / ".env").write_text("# Test fixture only\n")
            (root / "data/data.db").write_bytes(b"Docker fixture; real SQLite tested separately")
            for name in ["deploy.sh", "app/sqlite_backup.py"]:
                (root / name).write_bytes((ROOT / name).read_bytes().replace(b"\r\n", b"\n"))
            for name, script in [("docker", DOCKER), ("curl", "#!/usr/bin/env bash\nexit 0\n")]:
                path = root / "bin" / name
                path.write_text(script, encoding="utf-8", newline="\n")
                path.chmod(0o755)
            # Relative fixture paths work in both Git Bash and Linux shells.
            env = {**os.environ, "PATH": str(root / "bin") + os.pathsep + os.environ["PATH"],
                   "TRPG_TEST_LOG": "docker.log", "TRPG_TEST_READY": "ready",
                   "TRPG_TEST_STREAM": "stream.py", "TRPG_TEST_RUNNING": str(running).lower(),
                   "TRPG_TEST_BACKUP_EXIT": str(backup_exit), "MSYS_NO_PATHCONV": "1"}
            result = subprocess.run([BASH, "deploy.sh"], cwd=root, env=env,
                                    capture_output=True, text=True, timeout=20)
            log = (root / "docker.log").read_text() if (root / "docker.log").exists() else ""
            stream = (root / "stream.py").read_text() if (root / "stream.py").exists() else ""
            return result, log, stream

    def test_running_api_uses_streamed_tool_before_rebuild(self):
        result, log, stream = self.deploy()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("compose exec -T api python - /app/data/data.db /app/data/backups/data-", log)
        self.assertLess(log.index("/app/data/backups/"), log.index("compose up -d --build"))
        self.assertIn('?mode=ro', stream)
        self.assertNotIn("compose run", log)

    def test_stopped_api_uses_one_off_python_without_starting_application(self):
        result, log, stream = self.deploy(running=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("compose run --rm --no-deps -T --entrypoint python api - /app/data/data.db", log)
        self.assertIn("source.backup(snapshot)", stream)
        self.assertIn("skipping pre-deploy S3 snapshot", result.stdout)

    def test_backup_failure_aborts_before_rebuild(self):
        result, log, _ = self.deploy(backup_exit=19)
        self.assertEqual(result.returncode, 19, result.stdout + result.stderr)
        self.assertNotIn("compose up", log)
        self.assertNotIn("Saved local backup:", result.stdout)


if __name__ == "__main__":
    unittest.main()

"""Open an idempotent frontend PR for a verified backend contract (CI only)."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
FRONTEND_REPOSITORY = "andre-a13/trpg-front-end"


def run_command(args: list[str], cwd: Path) -> str:
    return subprocess.run(args, cwd=cwd, check=True, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.strip()


def sync_frontend(frontend: Path, revision: str, *, backend: Path = ROOT, run=run_command) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Expected the immutable backend commit SHA")
    if run(["git", "rev-parse", "HEAD"], backend) != revision:
        raise ValueError("Backend checkout does not match the producer revision")
    latest = run(["git", "ls-remote", "origin", "refs/heads/master"], backend).split()
    if not latest or latest[0] != revision:
        return "Skipped superseded backend revision."

    contract = backend / "contracts" / "openapi.json"
    digest = hashlib.sha256(contract.read_bytes()).hexdigest()
    metadata_path = frontend / "contracts" / "source.json"
    current_schema = frontend / "contracts" / "openapi.json"
    if metadata_path.exists() and current_schema.exists():
        metadata = json.loads(metadata_path.read_bytes())
        if (metadata.get("source") == "commit" and metadata.get("revision")
                and metadata.get("repository") == "andre-a13/trpg_python_backend"
                and metadata.get("sha256") == digest
                and hashlib.sha256(current_schema.read_bytes()).hexdigest() == digest):
            return "Contract unchanged; no frontend PR required."

    branch = f"automation/api-contract-{digest}"

    def find_pr(head: str):
        return json.loads(run([
            "gh", "pr", "list", "--repo", FRONTEND_REPOSITORY, "--state", "all",
            "--head", head, "--json", "number,state", "--limit", "1",
        ], frontend))

    existing = find_pr(branch)
    if existing and existing[0]["state"] == "MERGED":
        # A later backend commit can legitimately restore a previously merged schema.
        branch = f"{branch}-{revision}"
        existing = find_pr(branch)
    if existing:
        return f"Contract PR #{existing[0]['number']} already exists ({existing[0]['state']}); preserved."

    remote_branch = run(["git", "ls-remote", "--heads", "origin", branch], frontend)
    if not remote_branch:
        run(["git", "checkout", "-b", branch], frontend)
        run(["node", "scripts/import-api-contract.mjs", "--source", str(contract),
             "--backend-sha", revision], frontend)
        run(["npm", "run", "api:generate"], frontend)
        run(["git", "add", "--", "contracts/openapi.json", "contracts/source.json", "src/api/generated"], frontend)
        run(["git", "-c", "user.name=github-actions[bot]", "-c",
             "user.email=41898282+github-actions[bot]@users.noreply.github.com",
             "commit", "-m", f"chore(api): synchronize contract {digest[:12]}"], frontend)
        run(["git", "push", "origin", f"HEAD:refs/heads/{branch}"], frontend)

    body = (
        f"Update the generated TRPG API client from backend commit `{revision}`.\n\n"
        f"Producer: https://github.com/andre-a13/trpg_python_backend/commit/{revision}\n\n"
        f"Contract SHA-256: `{digest}`.\n\n"
        "This PR contains the imported contract, its provenance and generated client. "
        "Frontend CI checks regeneration, transport tests, types, lint and build. "
        "Review any required consumer adaptations before merging.\n"
    )
    with tempfile.TemporaryDirectory(prefix="trpg-contract-pr-") as directory:
        body_path = Path(directory) / "body.md"
        body_path.write_text(body, encoding="utf-8", newline="\n")
        url = run(["gh", "pr", "create", "--repo", FRONTEND_REPOSITORY,
                   "--base", "master", "--head", branch,
                   "--title", f"chore(api): synchronize contract {digest[:12]}",
                   "--body-file", str(body_path)], frontend)
    return f"Created frontend contract PR: {url}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontend-dir", type=Path, required=True)
    parser.add_argument("--backend-sha", required=True)
    args = parser.parse_args()
    print(sync_frontend(args.frontend_dir.resolve(), args.backend_sha))


if __name__ == "__main__":
    main()

"""Export the API schema without entering lifespan or opening a database."""

import argparse
import json
import os
from pathlib import Path


DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "contracts" / "openapi.json"


def schema_bytes() -> bytes:
    # Set these before importing the app: db.py creates parent directories at import.
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
    os.environ["DB_SNAPSHOT_ON_SHUTDOWN"] = "false"
    from app.main import app

    return (json.dumps(app.openapi(), ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = schema_bytes()
    if args.check:
        if not args.output.exists() or args.output.read_bytes() != expected:
            print(f"OpenAPI contract is stale. Run python -m scripts.export_openapi: {args.output}")
            return 1
        print(f"OpenAPI contract is up to date: {args.output}")
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(expected)
    print(f"Exported OpenAPI contract: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

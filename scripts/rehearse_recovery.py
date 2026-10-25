"""Restore into a fresh password-protected, loopback-only PostgreSQL cluster, then stop it."""
import argparse
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
from uuid import uuid4

import psycopg

from recovery import ROOT, protect_dir, restore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postgres-bin", type=Path, required=True)
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    args = parser.parse_args()
    private = protect_dir(Path.home() / "SentinelRecovery/restore-tests" / uuid4().hex)
    assert ROOT not in private.parents
    data = private / "postgres-data"
    password = secrets.token_urlsafe(32)
    password_file = private / "init-password"
    password_file.write_text(password, encoding="utf8")
    suffix = ".exe" if sys.platform == "win32" else ""
    binary = lambda name: str(args.postgres_bin / (name + suffix))
    hidden = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
    process = None
    try:
        subprocess.run([binary("initdb"), "-D", str(data), "-U", "sentinel_recovery",
                        "--pwfile=" + str(password_file), "--auth=scram-sha-256",
                        "--encoding=UTF8", "--no-locale"], capture_output=True, check=True, **hidden)
        password_file.unlink()
        with socket.socket() as reserved:
            reserved.bind(("127.0.0.1", 0))
            port = reserved.getsockname()[1]
        with (private / "server.log").open("wb") as log:
            process = subprocess.Popen([binary("postgres"), "-D", str(data), "-h", "127.0.0.1",
                                        "-p", str(port), "-c", "max_connections=10", "-c", "shared_buffers=32MB"],
                                       stdout=log, stderr=log, **hidden)
            dsn = psycopg.conninfo.make_conninfo(host="127.0.0.1", port=port, user="sentinel_recovery",
                                               password=password, dbname="postgres", connect_timeout=2)
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError("Local test server stopped")
                try:
                    with psycopg.connect(dsn):
                        break
                except psycopg.OperationalError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("Local test server unavailable")
            restore(args.backup, args.key_file, dsn, private / "objects")
        return 0
    except Exception as exc:
        print("Isolated recovery rehearsal failed (" + type(exc).__name__ + "). Source unchanged.", file=sys.stderr)
        return 1
    finally:
        password_file.unlink(missing_ok=True)
        if process and process.poll() is None:
            subprocess.run([binary("pg_ctl"), "-D", str(data), "-m", "fast", "-w", "stop"],
                           capture_output=True, check=True, **hidden)
            process.wait(timeout=20)
            print("Isolated PostgreSQL test server stopped")


if __name__ == "__main__":
    sys.exit(main())

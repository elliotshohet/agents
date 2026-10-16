#!/usr/bin/env python3
"""Preview or atomically install an already-fetched AGENTS.md; no network access."""

import argparse
import hashlib
import os
from pathlib import Path
import stat
import sys
import uuid
from datetime import datetime, timezone

MAX_BYTES = 64 * 1024


def digest(data):
    return hashlib.sha256(data).hexdigest()


def open_parent(destination):
    """Walk directories without following symlinks (allow macOS's /tmp alias)."""
    destination = Path(os.path.abspath(destination))
    if destination.parts[1:2] == ("tmp",):
        destination = Path(os.path.realpath("/tmp")).joinpath(*destination.parts[2:])
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in destination.parent.parts[1:]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                              dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return destination, fd
    except BaseException:
        os.close(fd)
        raise


def read_target(fd, name):
    try:
        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        return None, 0o600
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("destination must be a regular file, never a symlink")
    file_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
    with os.fdopen(file_fd, "rb") as stream:
        return stream.read(), stat.S_IMODE(os.fstat(stream.fileno()).st_mode)


def write_new(fd, name, data, mode):
    file_fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                      0o600, dir_fd=fd)
    with os.fdopen(file_fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fchmod(stream.fileno(), mode)
        os.fsync(stream.fileno())


def sync(args):
    source = Path(args.source).expanduser()
    if source.name != "AGENTS.md" or not source.is_file():
        raise ValueError("source must be an existing AGENTS.md file")
    with source.open("rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    if not data or len(data) > MAX_BYTES or not data.decode("utf-8").strip():
        raise ValueError("source must be nonempty UTF-8 and at most 64 KiB")
    destination = Path(args.destination).expanduser()
    if destination.name != "AGENTS.md":
        raise ValueError("destination filename must be AGENTS.md")
    destination, fd = open_parent(destination)
    try:
        old, mode = read_target(fd, destination.name)
        print(f"Source: {source}")
        if args.revision:
            print(f"Source commit: {args.revision}")
        print(f"Destination: {destination}\nSHA256: {digest(data)}")
        try:
            override = os.stat("AGENTS.override.md", dir_fd=fd, follow_symlinks=False)
            if override.st_size:
                print("Warning: sibling AGENTS.override.md may shadow this AGENTS.md")
        except FileNotFoundError:
            pass
        if old == data:
            print("Status: unchanged")
            return
        if not args.apply:
            print("Status: preview (use --apply to write)")
            return
        token = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex
        if old is not None:
            backup = destination.name + ".backup-" + token
            write_new(fd, backup, old, 0o600)
            print(f"Backup: {destination.parent / backup}")
        temporary = ".AGENTS.md.tmp-" + token
        try:
            write_new(fd, temporary, data, mode)
            os.replace(temporary, destination.name, src_dir_fd=fd, dst_dir_fd=fd)
            os.fsync(fd)
            installed, _ = read_target(fd, destination.name)
            if digest(installed) != digest(data):
                raise ValueError("installed SHA256 verification failed")
        finally:
            try:
                os.unlink(temporary, dir_fd=fd)
            except FileNotFoundError:
                pass
        print("Status: applied (SHA256 verified)")
    finally:
        os.close(fd)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="local AGENTS.md fetched at an immutable commit")
    parser.add_argument("--destination", default=str(Path(os.environ.get("CODEX_HOME") or "~/.codex") / "AGENTS.md"))
    parser.add_argument("--revision", help="source commit to display (caller supplies provenance)")
    parser.add_argument("--apply", action="store_true", help="write after creating a private backup")
    args = parser.parse_args(argv)
    try:
        sync(args)
        return 0
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

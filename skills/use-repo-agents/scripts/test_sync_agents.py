"""Isolated stdlib tests; never writes the user's global instruction files."""

from contextlib import redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import sync_agents


class SyncAgentsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "source" / "AGENTS.md"
        self.source.parent.mkdir()
        self.source.write_bytes(b"# Shared instructions\n")
        self.target = self.root / "target" / "AGENTS.md"
        self.target.parent.mkdir()

    def invoke(self, *extra, source=None, target=None):
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(output):
            result = sync_agents.main([
                "--source", str(source or self.source),
                "--destination", str(target or self.target), *extra,
            ])
        return result, output.getvalue()

    def test_preview_does_not_write(self):
        self.target.write_bytes(b"old\n")
        before = self.target.stat()
        result, output = self.invoke("--revision", "abc123")
        self.assertEqual(result, 0)
        self.assertIn("Status: preview", output)
        self.assertIn("Source commit: abc123", output)
        self.assertEqual(self.target.read_bytes(), b"old\n")
        self.assertEqual(self.target.stat().st_mtime_ns, before.st_mtime_ns)
        self.assertEqual(list(self.target.parent.iterdir()), [self.target])

    def test_apply_backup_permissions_and_idempotence(self):
        old = b"old bytes\r\n\x00"
        self.target.write_bytes(old)
        self.target.chmod(0o640)
        result, output = self.invoke("--apply")
        self.assertEqual(result, 0, output)
        self.assertIn("SHA256 verified", output)
        self.assertEqual(self.target.read_bytes(), self.source.read_bytes())
        self.assertEqual(self.target.stat().st_mode & 0o777, 0o640)
        backups = list(self.target.parent.glob("AGENTS.md.backup-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), old)
        self.assertEqual(backups[0].stat().st_mode & 0o777, 0o600)
        before = self.target.stat()
        with patch.object(sync_agents, "write_new", side_effect=AssertionError("unexpected write")):
            result, output = self.invoke("--apply")
        self.assertEqual(result, 0, output)
        self.assertIn("Status: unchanged", output)
        self.assertEqual(self.target.stat().st_ino, before.st_ino)
        self.assertEqual(len(list(self.target.parent.glob("AGENTS.md.backup-*"))), 1)

    def test_new_destination(self):
        result, output = self.invoke("--apply")
        self.assertEqual(result, 0, output)
        self.assertEqual(self.target.read_bytes(), self.source.read_bytes())
        self.assertEqual(self.target.stat().st_mode & 0o777, 0o600)
        self.assertEqual(list(self.target.parent.iterdir()), [self.target])

    def test_invalid_sources(self):
        for data in (b"", b" \n", b"\xff", b"a" * (sync_agents.MAX_BYTES + 1)):
            with self.subTest(data_length=len(data)):
                self.source.write_bytes(data)
                self.assertEqual(self.invoke("--apply")[0], 1)
                self.assertFalse(self.target.exists())
        wrong = self.root / "instructions.md"
        wrong.write_text("instructions")
        self.assertEqual(self.invoke("--apply", source=wrong)[0], 1)
        self.assertEqual(self.invoke("--apply", source=self.root / "missing" / "AGENTS.md")[0], 1)
        self.assertEqual(self.invoke("--apply", source=self.source.parent)[0], 1)

    def test_destination_name_directory_and_symlink_refusal(self):
        wrong = self.target.parent / "other.md"
        self.assertEqual(self.invoke("--apply", target=wrong)[0], 1)
        self.target.mkdir()
        self.assertEqual(self.invoke("--apply")[0], 1)
        self.target.rmdir()
        self.target.symlink_to(self.source)
        self.assertEqual(self.invoke("--apply")[0], 1)
        self.assertEqual(self.source.read_bytes(), b"# Shared instructions\n")
        self.target.unlink()
        self.target.write_text("unchanged")
        linked = self.root / "linked"
        linked.symlink_to(self.target.parent, target_is_directory=True)
        self.assertEqual(self.invoke("--apply", target=linked / "AGENTS.md")[0], 1)
        self.assertEqual(self.target.read_text(), "unchanged")

    def test_file_parent_refusal(self):
        parent = self.root / "file"
        parent.write_text("not a directory")
        self.assertEqual(self.invoke("--apply", target=parent / "AGENTS.md")[0], 1)

    def test_override_warning(self):
        override = self.target.parent / "AGENTS.override.md"
        override.write_text("local override")
        result, output = self.invoke()
        self.assertEqual(result, 0)
        self.assertIn("may shadow", output)
        self.assertEqual(override.read_text(), "local override")

    def test_empty_codex_home_uses_home(self):
        destination = self.root / ".codex" / "AGENTS.md"
        destination.parent.mkdir()
        output = io.StringIO()
        with patch.dict(os.environ, {"HOME": str(self.root), "CODEX_HOME": ""}):
            with redirect_stdout(output), redirect_stderr(output):
                result = sync_agents.main(["--source", str(self.source), "--apply"])
        self.assertEqual(result, 0, output.getvalue())
        self.assertEqual(destination.read_bytes(), self.source.read_bytes())

    def test_codex_home_default(self):
        output = io.StringIO()
        with patch.dict(os.environ, {"CODEX_HOME": str(self.target.parent)}):
            with redirect_stdout(output), redirect_stderr(output):
                result = sync_agents.main(["--source", str(self.source), "--apply"])
        self.assertEqual(result, 0, output.getvalue())
        self.assertEqual(self.target.read_bytes(), self.source.read_bytes())


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Run with: python3 -m unittest discover -s skills/setup-osx/scripts -v"""

import contextlib
import io
import json
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch

import setup_osx as setup


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.assets = self.root / "assets"
        self.assets.mkdir()
        self.manifest = {"profile_name": "Midnight Bloom", "nvm_version": "v0.40.8",
                         "node_version": "v24.22.0", "codex_version": "0.163.0",
                         "scm_breeze_revision": "a" * 40,
                         "brew_formulae": ["tmux", "zsh-autosuggestions", "ripgrep", "gh"]}
        (self.assets / "manifest.json").write_text(json.dumps(self.manifest))
        for filename, content in {"shell.zsh": "# fixture shell\n", "tmux.conf": "set -g mouse on\n",
                                  "resources.sh": "#!/bin/sh\necho 1\n"}.items():
            (self.assets / filename).write_text(content)
        self.profile = {"name": "Midnight Bloom", "type": "Window Settings", "Font": b"font"}
        (self.assets / "Midnight Bloom.terminal").write_bytes(plistlib.dumps(self.profile))
        self.output = io.StringIO()
        redirect = contextlib.redirect_stdout(self.output)
        redirect.__enter__()
        self.addCleanup(redirect.__exit__, None, None, None)

    def installer(self, apply=True):
        return setup.Installer(self.home, apply=apply, assets=self.assets)

    def test_preview_has_no_writes_or_processes(self):
        with patch.object(setup, "run") as process:
            installer = self.installer(apply=False)
            installer.configuration()
            installer.terminal()
        self.assertEqual(list(self.home.iterdir()), [])
        process.assert_not_called()

    def test_apply_preserves_unrelated_content_and_is_idempotent(self):
        original = "export MY_SETTING=kept\n"
        (self.home / ".zshrc").write_text(original)
        first = self.installer()
        first.configuration()
        content = (self.home / ".zshrc").read_text()
        self.assertTrue(content.startswith(original))
        self.assertEqual(content.count(setup.BEGIN), 1)
        self.assertEqual((first.backup_dir / ".zshrc").read_text(), original)
        snapshot = {path: path.stat().st_mtime_ns for path in self.home.rglob("*") if path.is_file()}
        second = self.installer()
        second.configuration()
        self.assertEqual(second.changed, 0)
        self.assertIsNone(second.backup_dir)
        self.assertEqual(snapshot, {path: path.stat().st_mtime_ns for path in snapshot})
        self.assertIn("if [[ ! -o interactive ]]; then", (self.home / ".zprofile").read_text())

    def test_old_marker_is_replaced_in_place_with_backup(self):
        original = f"before\n{setup.BEGIN}\nold\n{setup.END}\nafter\n"
        (self.home / ".tmux.conf").write_text(original)
        installer = self.installer()
        installer.configuration()
        result = (self.home / ".tmux.conf").read_text()
        self.assertEqual(result, f"before\n{setup.BEGIN}\nsource-file ~/.config/setup-osx/tmux.conf\n{setup.END}\nafter\n")
        self.assertEqual((installer.backup_dir / ".tmux.conf").read_text(), original)

    def test_backups_have_unique_paths_and_preserve_previous_versions(self):
        target = self.home / ".zshrc"
        target.write_text("first\n")
        first = self.installer()
        first.configuration()
        target.write_text("second\n")
        second = self.installer()
        second.configuration()
        self.assertNotEqual(first.backup_dir, second.backup_dir)
        self.assertEqual((first.backup_dir / ".zshrc").read_text(), "first\n")
        self.assertEqual((second.backup_dir / ".zshrc").read_text(), "second\n")

    def test_symlink_file_and_parent_are_preserved_and_refused(self):
        external = self.root / "external"
        external.write_text("keep\n")
        link = self.home / ".zshrc"
        link.symlink_to(external)
        with self.assertRaisesRegex(setup.SetupError, "symlink"):
            self.installer().configuration()
        self.assertTrue(link.is_symlink())
        self.assertEqual(external.read_text(), "keep\n")
        self.assertFalse((self.home / ".config").exists())
        link.unlink()
        external_dir = self.root / "external-dir"
        external_dir.mkdir()
        (self.home / ".config").symlink_to(external_dir)
        with self.assertRaisesRegex(setup.SetupError, "symlink"):
            self.installer().configuration()
        self.assertEqual(list(external_dir.iterdir()), [])

    def test_broken_symlink_is_preserved_and_refused(self):
        target = self.home / ".tmux.conf"
        target.symlink_to(self.root / "does-not-exist")
        with self.assertRaisesRegex(setup.SetupError, "symlink"):
            self.installer().configuration()
        self.assertTrue(target.is_symlink())

    def test_bad_markers_fail_before_any_write(self):
        for original in (setup.BEGIN, setup.END + "\n" + setup.BEGIN,
                         (setup.BEGIN + "\n" + setup.END + "\n") * 2):
            with self.subTest(original=original):
                (self.home / ".zshrc").write_text(original)
                with self.assertRaisesRegex(setup.SetupError, "markers"):
                    self.installer().configuration()
                self.assertFalse((self.home / ".config").exists())
                self.assertEqual((self.home / ".zshrc").read_text(), original)

    def test_alternate_home_never_changes_preferences_or_installs(self):
        installer = self.installer()
        with patch.object(setup.platform, "system", return_value="Darwin"), patch.object(setup, "run") as process:
            installer.terminal()
            with self.assertRaisesRegex(setup.SetupError, "alternate --home"):
                installer.install_tools()
        process.assert_not_called()

    def test_missing_tools_fail_verification(self):
        installer = self.installer()
        installer.configuration()
        with patch.object(setup.shutil, "which", return_value=None), patch.object(setup, "run", side_effect=setup.SetupError("missing git")):
            self.assertFalse(installer.verify())
        self.assertIn("MISSING tool: tmux", self.output.getvalue())

    def test_changed_template_is_a_verification_failure(self):
        installer = self.installer()
        installer.configuration()
        (self.home / ".config/setup-osx/tmux.conf").write_text("drift\n")
        with patch.object(setup.shutil, "which", return_value=None), patch.object(setup, "run", side_effect=setup.SetupError("missing")):
            self.assertFalse(installer.verify())
        self.assertIn("MISSING/CHANGED configuration:", self.output.getvalue())

    def test_commented_tmux_source_fails_exact_startup_verification(self):
        installer = self.installer()
        installer.configuration()
        path = self.home / ".tmux.conf"
        path.write_text(path.read_text().replace("source-file", "# source-file"))
        with patch.object(setup.shutil, "which", return_value=None), patch.object(setup, "run", side_effect=setup.SetupError("missing")):
            self.assertFalse(installer.verify())
        self.assertIn(f"MISSING/CHANGED startup source: {path}", self.output.getvalue())

    def test_modified_zprofile_guard_fails_exact_startup_verification(self):
        installer = self.installer()
        installer.configuration()
        path = self.home / ".zprofile"
        path.write_text(path.read_text().replace("! -o interactive", "-o interactive"))
        with patch.object(setup.shutil, "which", return_value=None), patch.object(setup, "run", side_effect=setup.SetupError("missing")):
            self.assertFalse(installer.verify())
        self.assertIn(f"MISSING/CHANGED startup source: {path}", self.output.getvalue())

    def test_verification_accepts_unrelated_content_outside_exact_block(self):
        installer = self.installer()
        installer.configuration()
        path = self.home / ".zshrc"
        path.write_text("# custom before\n" + path.read_text() + "# custom after\n")
        with patch.object(setup.shutil, "which", return_value=None), patch.object(setup, "run", side_effect=setup.SetupError("missing")):
            installer.verify()
        self.assertIn(f"OK startup source: {path}", self.output.getvalue())

    def test_terminal_merge_preserves_other_preferences_and_does_not_quit(self):
        installer = self.installer()
        installer.sandbox = False  # Only mocked commands; no real preferences touched.
        state = {"Window Settings": {"Other": {"name": "Other"}}, "Unrelated": 123}
        calls = []

        def defaults(argv, **kwargs):
            calls.append(argv)
            self.assertEqual(argv[0], "defaults")
            if argv[1] == "export":
                return plistlib.dumps(state).decode()
            self.assertEqual(argv[1], "write")
            if argv[3] == "Window Settings":
                self.assertEqual(argv[4], "-dict-add")
                state[argv[3]][argv[5]] = plistlib.loads(argv[6].encode())
            else:
                state[argv[3]] = argv[5]
            return ""

        with patch.object(setup.platform, "system", return_value="Darwin"), patch.object(setup, "run", side_effect=defaults):
            installer.terminal()
            count = len(calls)
            installer.terminal()
        self.assertEqual(state["Unrelated"], 123)
        self.assertEqual(state["Window Settings"]["Other"], {"name": "Other"})
        self.assertEqual(state["Window Settings"]["Midnight Bloom"], self.profile)
        self.assertEqual(len(calls), count + 1)  # Second run only reads prefs.
        snapshot = plistlib.loads((self.home / ".local/state/setup-osx/terminal-before.plist").read_bytes())
        self.assertNotIn("Midnight Bloom", snapshot["Window Settings"])

    def test_repository_mismatch_and_dirt_are_never_reset(self):
        target = self.home / ".scm_breeze"
        (target / ".git").mkdir(parents=True)
        sentinel = target / "precious"
        sentinel.write_text("local work")
        for responses in ((setup.SCM_ORIGIN, "b" * 40, ""),
                          (setup.SCM_ORIGIN, "a" * 40, " M precious"),
                          ("https://untrusted.invalid/repo", "a" * 40, "")):
            with self.subTest(responses=responses), patch.object(setup, "run", side_effect=responses) as process:
                with self.assertRaisesRegex(setup.SetupError, "migration needed"):
                    self.installer().repository(target, setup.SCM_ORIGIN, revision="a" * 40)
                self.assertEqual(process.call_count, 3)
                self.assertEqual(sentinel.read_text(), "local work")

    def test_existing_clean_pinned_repository_is_accepted(self):
        target = self.home / ".scm_breeze"
        (target / ".git").mkdir(parents=True)
        with patch.object(setup, "run", side_effect=(setup.SCM_ORIGIN, "a" * 40, "")) as process:
            self.installer().repository(target, setup.SCM_ORIGIN, revision="a" * 40)
        self.assertEqual(process.call_count, 3)

    def test_missing_brew_prints_prerequisite_without_installing(self):
        installer = self.installer()
        installer.sandbox = False
        with patch.object(setup.platform, "system", return_value="Darwin"), \
                patch.object(setup.shutil, "which", return_value=None), \
                patch.object(setup.Path, "is_file", return_value=False), \
                patch.object(setup, "run") as process:
            with self.assertRaisesRegex(setup.SetupError, "raw.githubusercontent.com/Homebrew/install/HEAD/install.sh"):
                installer.install_tools()
        process.assert_not_called()

    def test_home_environment_override_does_not_authorize_global_changes(self):
        with patch.dict(setup.os.environ, {"HOME": str(self.home)}):
            installer = self.installer()
        self.assertTrue(installer.sandbox)

    def test_terminal_export_failure_does_not_write_preferences(self):
        installer = self.installer()
        installer.sandbox = False
        with patch.object(setup.platform, "system", return_value="Darwin"), \
                patch.object(setup, "run", side_effect=setup.SetupError("Access denied")) as process:
            with self.assertRaisesRegex(setup.SetupError, "Access denied"):
                installer.terminal()
        self.assertEqual(process.call_count, 1)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_install_uses_missing_formulae_only_and_pinned_node_and_codex(self):
        scm = self.home / ".scm_breeze"
        scm.mkdir()
        for name in ("scmbrc", "git.scmbrc"):
            (scm / f"{name}.example").write_text("defaults\n")
        (self.home / ".scmbrc").write_text("custom config\n")
        installer = self.installer()
        installer.sandbox = False
        calls = []

        def command(argv, **kwargs):
            calls.append((argv, kwargs))
            if argv[1:3] == ["list", "--formula"]:
                return "tmux\n"
            if argv[-1:] == ["--version"]:
                return "codex-cli 0.1.0"  # Pinned version installation is required.
            if argv[-1:] == ["codex completion zsh"]:
                return "# completion"
            return ""

        def which(name, **kwargs):
            return {"brew": "/custombrew/bin/brew", "codex": "/usr/bin/codex"}.get(name)

        with patch.object(setup.platform, "system", return_value="Darwin"), \
                patch.object(setup.shutil, "which", side_effect=which), \
                patch.object(installer, "repository") as repository, \
                patch.object(setup, "run", side_effect=command):
            installer.install_tools()
        repository.assert_any_call(self.home / ".nvm", setup.NVM_ORIGIN, tag="v0.40.8")
        repository.assert_any_call(self.home / ".scm_breeze", setup.SCM_ORIGIN, revision="a" * 40)
        self.assertIn(["/custombrew/bin/brew", "install", "zsh-autosuggestions", "ripgrep", "gh"], [call[0] for call in calls])
        npm_calls = [call for call in calls if "npm install --global" in call[0][-1]]
        self.assertEqual(len(npm_calls), 1)
        self.assertEqual(npm_calls[0][1]["env"]["SETUP_OSX_CODEX_VERSION"], "0.163.0")
        self.assertEqual(npm_calls[0][1]["env"]["SETUP_OSX_NODE_VERSION"], "v24.22.0")
        self.assertTrue(npm_calls[0][1]["env"]["PATH"].startswith("/custombrew/bin:"))
        self.assertEqual((self.home / ".scmbrc").read_text(), "custom config\n")
        self.assertEqual((self.home / ".git.scmbrc").read_text(), "defaults\n")
        self.assertTrue((self.home / ".config/setup-osx/codex.zsh").is_file())

    def test_zsh_verification_uses_target_home_and_prevents_autoattach(self):
        installer = self.installer()
        installer.configuration()
        calls = []

        def command(argv, **kwargs):
            calls.append((argv, kwargs))
            return ""

        with patch.object(setup.shutil, "which", side_effect=lambda name, **kw: "/bin/zsh" if name == "zsh" else None), \
                patch.object(setup, "run", side_effect=command):
            installer.verify()
        shells = [call for call in calls if "-dfic" in call[0]]
        self.assertEqual(len(shells), 1)
        self.assertEqual(shells[0][1]["env"]["HOME"], str(self.home))
        self.assertEqual(shells[0][1]["env"]["ZDOTDIR"], str(self.home))
        self.assertEqual(shells[0][1]["env"]["SETUP_OSX_VERIFY"], "1")
        self.assertIn('source "$HOME/.zshrc"', shells[0][0][-1])
        self.assertEqual(len([call for call in calls if "-n" in call[0]]), 3)


if __name__ == "__main__":
    unittest.main()

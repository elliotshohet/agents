#!/usr/bin/env python3
"""Install a portable terminal configuration. Preview by default; stdlib only."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import plistlib
import pwd
import re
import shutil
import subprocess
import sys
import tempfile
import uuid


ASSETS = Path(__file__).resolve().parent.parent / "assets"
NVM_ORIGIN = "https://github.com/nvm-sh/nvm.git"
SCM_ORIGIN = "https://github.com/scmbreeze/scm_breeze.git"
BREW_INSTALL = '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
BEGIN = "# >>> setup-osx managed >>>"
END = "# <<< setup-osx managed <<<"


class SetupError(Exception):
    pass


def run(argv, **kwargs):
    """Never pass user-controlled strings to a shell."""
    result = subprocess.run(argv, text=True, capture_output=True, **kwargs)
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise SetupError(f"Command failed ({result.returncode}): {argv[0]}: {detail}")
    return result.stdout.strip()


def managed_block(original, body):
    block = f"{BEGIN}\n{body.rstrip()}\n{END}"
    # Reject malformed/duplicate markers instead of deleting unexpected content.
    if (original.count(BEGIN) != original.count(END) or original.count(BEGIN) > 1
            or (BEGIN in original and original.index(BEGIN) > original.index(END))):
        raise SetupError("Malformed or duplicate setup-osx markers; repair them before continuing.")
    if BEGIN in original:
        if not all(re.search(r"(?m)^" + re.escape(marker) + r"$", original) for marker in (BEGIN, END)):
            raise SetupError("Malformed setup-osx markers must occupy their own lines.")
        pattern = re.escape(BEGIN) + r".*?" + re.escape(END)
        return re.sub(pattern, lambda _: block, original, count=1, flags=re.S)
    return original + ("\n" if original and not original.endswith("\n") else "") + block + "\n"


def startup_body(relative):
    if relative == ".tmux.conf":
        return "source-file ~/.config/setup-osx/tmux.conf"
    source = '[ -r "$HOME/.config/setup-osx/shell.zsh" ] && source "$HOME/.config/setup-osx/shell.zsh"'
    if relative == ".zprofile":
        return f"if [[ ! -o interactive ]]; then\n  {source}\nfi"
    if relative == ".zshrc":
        return source
    raise SetupError(f"Unknown startup file: {relative}")


class Installer:
    def __init__(self, home, apply=False, assets=ASSETS):
        self.home = Path(os.path.abspath(os.path.expanduser(str(home))))
        self.actual_home = Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()
        self.sandbox = self.home != self.actual_home
        self.apply = apply
        self.assets = Path(assets)
        self.manifest = json.loads((self.assets / "manifest.json").read_text())
        self.backup_dir = None
        self.changed = 0
        self.env = os.environ.copy()

    def command(self, argv, **kwargs):
        kwargs.setdefault("env", self.env)
        return run(argv, **kwargs)

    def safe(self, path):
        """Refuse symlinks, including broken links and linked parent directories."""
        path = Path(path)
        try:
            relative = path.relative_to(self.home)
        except ValueError as exc:
            raise SetupError(f"Destination escapes target home: {path}") from exc
        current = self.home
        if current.is_symlink():
            raise SetupError(f"Refusing symlink: {current}")
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise SetupError(f"Refusing symlink: {current}")
        return path

    def backup(self, path):
        if self.backup_dir is None:
            root = self.safe(self.home / ".local/state/setup-osx/backups")
            root.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
            self.backup_dir = root / f"{stamp}-{uuid.uuid4().hex[:8]}"
            self.backup_dir.mkdir()
        destination = self.backup_dir / path.relative_to(self.home)
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation protects prior backups even if called twice.
        with destination.open("xb") as handle:
            handle.write(path.read_bytes())
        shutil.copystat(path, destination)

    def write(self, relative, data, mode=None):
        path = self.safe(self.home / relative)
        if path.exists() and not path.is_file():
            raise SetupError(f"Expected a regular file: {path}")
        data = data.encode() if isinstance(data, str) else data
        if path.exists() and path.read_bytes() == data:
            print(f"Unchanged: {path}")
            return
        print(f"{'Write' if self.apply else 'Would write'}: {path}")
        self.changed += 1
        if not self.apply:
            return
        if path.exists():
            self.backup(path)
            mode = path.stat().st_mode & 0o777
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".setup-osx-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            os.chmod(temporary, mode if mode is not None else 0o644)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def configuration(self):
        files = {
            ".config/setup-osx/shell.zsh": "shell.zsh",
            ".config/setup-osx/tmux.conf": "tmux.conf",
            ".local/share/tmux/resources.sh": "resources.sh",
        }
        # Preflight every destination before making any configuration changes.
        for relative in [*files, ".zshrc", ".zprofile", ".tmux.conf"]:
            self.safe(self.home / relative)
        startup = {}
        for relative in (".zshrc", ".zprofile", ".tmux.conf"):
            path = self.home / relative
            original = path.read_text() if path.exists() else ""
            startup[relative] = managed_block(original, startup_body(relative))
        for relative, asset in files.items():
            self.write(relative, (self.assets / asset).read_bytes(),
                       0o755 if asset == "resources.sh" else None)
        for relative, content in startup.items():
            self.write(relative, content)

    def terminal(self):
        if self.sandbox:
            print("Terminal preferences skipped: alternate --home is isolated.")
            return
        if platform.system() != "Darwin":
            print("Terminal preferences skipped: macOS required.")
            return
        name = self.manifest["profile_name"]
        profile = plistlib.loads((self.assets / f"{name}.terminal").read_bytes())
        if profile.get("name") != name:
            raise SetupError("Terminal profile name does not match the manifest.")
        if not self.apply:
            print(f"Would merge Terminal profile {name!r} and set startup/default profile.")
            return
        # Read immediately before mutation, and only mutate these three keys.
        try:
            exported = self.command(["defaults", "export", "com.apple.Terminal", "-"])
        except SetupError as exc:
            if "Domain com.apple.Terminal does not exist" not in str(exc):
                raise
            exported = plistlib.dumps({}).decode()
        current = plistlib.loads(exported.encode())
        if (current.get("Window Settings", {}).get(name) == profile
                and current.get("Default Window Settings") == name
                and current.get("Startup Window Settings") == name):
            print("Terminal preferences unchanged.")
            return
        self.write(".local/state/setup-osx/terminal-before.plist", exported, mode=0o600)
        xml = plistlib.dumps(profile, fmt=plistlib.FMT_XML).decode()
        self.command(["defaults", "write", "com.apple.Terminal", "Window Settings", "-dict-add", name, xml])
        for key in ("Default Window Settings", "Startup Window Settings"):
            self.command(["defaults", "write", "com.apple.Terminal", key, "-string", name])
        confirmed = plistlib.loads(self.command(["defaults", "export", "com.apple.Terminal", "-"]).encode())
        if (confirmed.get("Window Settings", {}).get(name) != profile
                or any(confirmed.get(key) != name for key in ("Default Window Settings", "Startup Window Settings"))):
            raise SetupError("Terminal preferences did not verify after writing.")
        print("Terminal profile saved. Reopen Terminal windows to use its appearance; no app was quit.")

    def repository(self, target, origin, revision=None, tag=None):
        target = self.safe(target)
        expected = revision
        if tag:
            remote = self.command(["git", "ls-remote", "--tags", origin, f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}"])
            refs = dict(line.split()[::-1] for line in remote.splitlines() if line.strip())
            expected = refs.get(f"refs/tags/{tag}^{{}}") or refs.get(f"refs/tags/{tag}")
        if not expected or not re.fullmatch(r"[0-9a-f]{40}", expected):
            raise SetupError(f"Invalid or unavailable pinned revision for {origin}")
        if target.exists():
            if not (target / ".git").exists():
                raise SetupError(f"Existing {target} is not the expected Git repository; migration needed.")
            actual_origin = self.command(["git", "-C", str(target), "remote", "get-url", "origin"])
            actual_revision = self.command(["git", "-C", str(target), "rev-parse", "HEAD"])
            dirty = self.command(["git", "-C", str(target), "status", "--porcelain"])
            if actual_origin != origin or actual_revision != expected or dirty:
                raise SetupError(f"Existing {target} has a different origin/revision or local changes; migration needed. It was preserved.")
            print(f"Pinned repository verified: {target}")
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".setup-osx-repo-", dir=target.parent))
        try:
            argv = ["git", "clone", "--no-checkout"]
            if tag:
                argv += ["--depth", "1", "--branch", tag]
            self.command(argv + [origin, str(staging)])
            self.command(["git", "-C", str(staging), "checkout", "--detach", expected])
            if self.command(["git", "-C", str(staging), "rev-parse", "HEAD"]) != expected:
                raise SetupError(f"Pinned checkout failed: {origin}")
            staging.rename(target)
        finally:
            if staging.exists():
                shutil.rmtree(staging)

    def install_tools(self):
        if not self.apply:
            raise SetupError("--install-tools requires --apply.")
        if self.sandbox:
            raise SetupError("--install-tools is forbidden with an alternate --home.")
        if platform.system() != "Darwin":
            raise SetupError("Tool installation requires macOS.")
        brew = shutil.which("brew", path=self.env.get("PATH"))
        if not brew:
            for candidate in ("/opt/homebrew/bin/brew", "/usr/local/bin/brew"):
                if Path(candidate).is_file():
                    brew = candidate
                    break
        if not brew:
            raise SetupError(f"Homebrew prerequisite missing. Review its official installer: {BREW_INSTALL}")
        self.env["PATH"] = str(Path(brew).parent) + os.pathsep + self.env.get("PATH", "")
        installed = set(self.command([brew, "list", "--formula", "-1"]).splitlines())
        missing = [formula for formula in self.manifest["brew_formulae"] if formula not in installed]
        if missing:
            self.command([brew, "install", *missing])
        self.repository(self.home / ".nvm", NVM_ORIGIN, tag=self.manifest["nvm_version"])
        self.repository(self.home / ".scm_breeze", SCM_ORIGIN, revision=self.manifest["scm_breeze_revision"])
        for name in ("scmbrc", "git.scmbrc"):
            target = self.safe(self.home / f".{name}")
            default = (self.home / ".scm_breeze" / f"{name}.example").read_bytes()
            if not target.exists():
                self.write(f".{name}", default)
            elif target.read_bytes() != default:
                print(f"Baseline drift: {target} differs from upstream defaults; preserved.")
        env = self.env.copy()
        env.update(HOME=str(self.home), NVM_DIR=str(self.home / ".nvm"), SETUP_OSX_NODE_VERSION=self.manifest["node_version"])
        # Fixed shell program; versions/home travel in the environment, not shell syntax.
        self.command(["/bin/bash", "--noprofile", "--norc", "-c",
             'set -e; . "$NVM_DIR/nvm.sh"; nvm install "$SETUP_OSX_NODE_VERSION"; nvm alias default "$SETUP_OSX_NODE_VERSION"'], env=env)
        env["SETUP_OSX_CODEX_VERSION"] = self.manifest["codex_version"]
        codex = shutil.which("codex", path=self.env.get("PATH"))
        expected_codex = "codex-cli " + self.manifest["codex_version"]
        if codex and self.command([codex, "--version"]) == expected_codex:
            completion = self.command([codex, "completion", "zsh"])
        else:
            self.command(["/bin/bash", "--noprofile", "--norc", "-c",
                 'set -e; . "$NVM_DIR/nvm.sh"; nvm use "$SETUP_OSX_NODE_VERSION"; '
                 'npm install --global "@openai/codex@$SETUP_OSX_CODEX_VERSION"'], env=env)
            completion = self.command(["/bin/bash", "--noprofile", "--norc", "-c",
                              'set -e; . "$NVM_DIR/nvm.sh"; nvm use --silent "$SETUP_OSX_NODE_VERSION"; '
                              'codex completion zsh'], env=env)
        self.write(".config/setup-osx/codex.zsh", completion + "\n")
        print("Codex completion saved; no authentication or user configuration was copied.")

    def verify(self):
        okay = True
        if not self.sandbox and platform.system() == "Darwin":
            try:
                preferences = plistlib.loads(self.command(["defaults", "export", "com.apple.Terminal", "-"]).encode())
                name = self.manifest["profile_name"]
                expected = plistlib.loads((self.assets / f"{name}.terminal").read_bytes())
                valid = (preferences.get("Window Settings", {}).get(name) == expected
                         and preferences.get("Default Window Settings") == name
                         and preferences.get("Startup Window Settings") == name)
                print(f"{'OK' if valid else 'MISSING/CHANGED'} Terminal profile and startup/default preferences")
                okay = valid and okay
            except (SetupError, ValueError) as exc:
                print(f"FAILED Terminal verification: {exc}")
                okay = False
        else:
            print("Terminal verification skipped: alternate --home or non-macOS host.")
        brew = shutil.which("brew", path=self.env.get("PATH"))
        if brew:
            try:
                versions = json.loads(self.command([brew, "info", "--json=v2", "--installed"]))
                installed = {entry["name"]: entry.get("installed", []) for entry in versions["formulae"]}
                for formula, baseline in self.manifest.get("observed_versions", {}).items():
                    found = [entry["version"] for entry in installed.get(formula, [])]
                    print(f"{'OK' if baseline in found else 'Baseline drift'} Homebrew {formula}: "
                          f"installed {', '.join(found) or 'missing'}, baseline {baseline}")
            except (SetupError, ValueError, KeyError) as exc:
                print(f"FAILED Homebrew version inspection: {exc}")
                okay = False
        for tool in ("zsh", *self.manifest["brew_formulae"]):
            executable = "rg" if tool == "ripgrep" else tool
            if tool == "zsh-autosuggestions":
                candidates = [Path(prefix) / "share/zsh-autosuggestions/zsh-autosuggestions.zsh"
                              for prefix in ("/opt/homebrew", "/usr/local")]
                found = any(path.is_file() for path in candidates)
            else:
                found = bool(shutil.which(executable, path=self.env.get("PATH")))
            print(f"{'OK' if found else 'MISSING'} tool: {tool}")
            okay = found and okay
        for relative, asset in ((".config/setup-osx/shell.zsh", "shell.zsh"),
                                (".config/setup-osx/tmux.conf", "tmux.conf"),
                                (".local/share/tmux/resources.sh", "resources.sh")):
            path = self.safe(self.home / relative)
            matches = path.is_file() and path.read_bytes() == (self.assets / asset).read_bytes()
            print(f"{'OK' if matches else 'MISSING/CHANGED'} configuration: {path}")
            okay = matches and okay
        for relative in (".zshrc", ".zprofile", ".tmux.conf"):
            path = self.safe(self.home / relative)
            content = path.read_text() if path.is_file() else ""
            try:
                valid = managed_block(content, startup_body(relative)) == content
            except SetupError:
                valid = False
            print(f"{'OK' if valid else 'MISSING/CHANGED'} startup source: {path}")
            okay = valid and okay
        for target, origin, expected in ((self.home / ".nvm", NVM_ORIGIN, self.manifest["nvm_version"]),
                                         (self.home / ".scm_breeze", SCM_ORIGIN, self.manifest["scm_breeze_revision"])):
            try:
                self.safe(target)
                found_origin = self.command(["git", "-C", str(target), "remote", "get-url", "origin"])
                found_head = self.command(["git", "-C", str(target), "rev-parse", "HEAD"])
                expected_head = (self.command(["git", "-C", str(target), "rev-parse", f"refs/tags/{expected}^{{}}"])
                                 if target.name == ".nvm" else expected)
                if found_origin != origin or found_head != expected_head or self.command(["git", "-C", str(target), "status", "--porcelain"]):
                    raise SetupError("origin, pinned revision or clean working tree does not match")
                print(f"OK pinned repository: {target}")
            except SetupError as exc:
                print(f"FAILED pinned repository {target}: {exc}")
                okay = False
        alias = self.safe(self.home / ".nvm/alias/default")
        correct_alias = alias.is_file() and alias.read_text().strip() == self.manifest["node_version"]
        print(f"{'OK' if correct_alias else 'MISSING/CHANGED'} Node default alias: {alias}")
        okay = correct_alias and okay
        for name in ("scmbrc", "git.scmbrc"):
            config = self.safe(self.home / f".{name}")
            default = self.home / ".scm_breeze" / f"{name}.example"
            if not config.is_file():
                print(f"MISSING SCM Breeze configuration: {config}")
                okay = False
            elif default.is_file() and config.read_bytes() != default.read_bytes():
                print(f"Baseline drift: {config} differs from upstream defaults; preserved.")
        zsh = shutil.which("zsh", path=self.env.get("PATH"))
        if zsh:
            try:
                for relative in (".config/setup-osx/shell.zsh", ".zshrc", ".zprofile"):
                    path = self.safe(self.home / relative)
                    if not path.is_file():
                        raise SetupError(f"Missing shell configuration: {path}")
                    self.command([zsh, "-n", str(path)])
                env = self.env.copy()
                env.update(HOME=str(self.home), ZDOTDIR=str(self.home), SETUP_OSX_VERIFY="1",
                           SETUP_OSX_EXPECTED_NODE=self.manifest["node_version"],
                           SETUP_OSX_EXPECTED_NVM=self.manifest["nvm_version"].lstrip("v"),
                           SETUP_OSX_EXPECTED_CODEX="codex-cli " + self.manifest["codex_version"])
                output = self.command([zsh, "-dfic", 'source "$HOME/.zshrc"; '
                              'setup_osx_nvm=$(nvm --version 2>/dev/null); '
                              'setup_osx_node=$(node --version 2>/dev/null); '
                              'setup_osx_codex=$(codex --version 2>/dev/null); '
                              'print -r -- "nvm: ${setup_osx_nvm:-missing} (expected $SETUP_OSX_EXPECTED_NVM)"; '
                              'print -r -- "Node: ${setup_osx_node:-missing} (expected $SETUP_OSX_EXPECTED_NODE)"; '
                              'print -r -- "Codex: ${setup_osx_codex:-missing} (expected $SETUP_OSX_EXPECTED_CODEX)"; '
                              '[[ "$setup_osx_nvm" == "$SETUP_OSX_EXPECTED_NVM" ]] && '
                              '[[ "$setup_osx_node" == "$SETUP_OSX_EXPECTED_NODE" ]] && '
                              '[[ "$setup_osx_codex" == "$SETUP_OSX_EXPECTED_CODEX" ]] && '
                              '[[ -r "$HOME/.scm_breeze/scm_breeze.sh" ]] && '
                              '(( $+functions[git_status_shortcuts] )) && '
                              'print "setup-osx shell verified"'], env=env)
                print(output)
            except SetupError as exc:
                print(f"FAILED shell verification: {exc}")
                okay = False
        return okay


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write configuration; otherwise preview only")
    parser.add_argument("--install-tools", action="store_true", help="Install missing pinned tools (requires --apply and real macOS home)")
    parser.add_argument("--verify", action="store_true", help="Check installed files, tools and a fresh interactive zsh")
    parser.add_argument("--home", type=Path, default=Path.home(), help="Target home; alternate homes never change system tools/preferences")
    args = parser.parse_args(argv)
    if args.install_tools and not args.apply:
        parser.error("--install-tools requires --apply")
    try:
        installer = Installer(args.home, apply=args.apply)
        # Reject unsafe global operations before writing any target configuration.
        if args.install_tools and installer.sandbox:
            raise SetupError("--install-tools is forbidden with an alternate --home.")
        if args.install_tools:
            installer.install_tools()
        if args.apply or not args.verify:
            installer.configuration()
            installer.terminal()
        if args.verify and not installer.verify():
            print("Verification incomplete: resolve the MISSING/FAILED items above.", file=sys.stderr)
            return 1
        if not args.apply and not args.verify:
            print("Dry run complete. No files or preferences changed. Use --apply to write configuration.")
        elif args.apply:
            print("Configuration applied. Tool installation was " + ("requested." if args.install_tools else "not requested; use --verify to check readiness."))
        return 0
    except (SetupError, OSError, ValueError, KeyError) as exc:
        print(f"setup-osx: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

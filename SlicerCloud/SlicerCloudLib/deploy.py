"""Driving a local tool-server deployment: clone, docker, start, update, data.

Same dependency rule as `client.py` (see ARCHITECTURE.md): **this module
imports neither `slicer` nor `qt`**, so it runs — and is unit-tested — in plain
CI with no Slicer interpreter. Everything it does is `subprocess` plus the
standard library.

It is deliberately thin. The real logic lives in the server repository's
`scripts/server_ctl.py`, which this class clones and then calls: the panel and
the terminal therefore do exactly the same thing, and a fix to the deployment
logic ships with the server rather than needing a new extension release. The
one thing that cannot be delegated is the bootstrap — you cannot run a script
out of a clone that does not exist yet — so `probe_host()` and `clone()` are
implemented here and nothing else is.

`server_ctl.py --json` prints one JSON object on stdout and narrates on
stderr, which is what lets `run_ctl` stream a live log into the GUI *and*
return a parsed result from the same call.
"""

import json
import os
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.request

DEFAULT_REPO_URL = "https://github.com/Jules-GP/slicer-remote-tool-server.git"
DEFAULT_BRANCH = "main"
DEFAULT_SERVER_URL = "http://localhost:8000"

# Where a clone goes when the user has not said. The home directory, not
# anywhere under the Slicer install: this holds a git clone plus up to ~29 GB
# of model weights, and it must survive an extension update or a Slicer
# reinstall.
DEFAULT_INSTALL_DIR = os.path.join(os.path.expanduser("~"), "SlicerCloudServer")


class DeploymentError(Exception):
    """Something the user can act on, with a message written for them."""


def _emit(progress_cb, message: str) -> None:
    if progress_cb and message:
        progress_cb(message)


def _no_window_kwargs() -> dict:
    """Keep Windows from flashing a console window for every subprocess."""
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return {"startupinfo": startupinfo, "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}


def find_python() -> str:
    """A Python 3 interpreter able to run `server_ctl.py` (standard library only).

    `sys.executable` is checked LAST and only when it looks like a Python
    binary. Inside Slicer it can be the Slicer application itself, and handing
    that to `subprocess` would launch a second Slicer instead of running a
    script — a failure mode with no useful error message at all.
    """
    candidates = [shutil.which("python3"), shutil.which("python")]

    # Slicer ships its own interpreter next to the app binary; on a Windows or
    # macOS host with no system Python it is the only one there is.
    here = os.path.dirname(os.path.abspath(sys.executable))
    for name in ("PythonSlicer", "PythonSlicer.exe"):
        candidate = os.path.join(here, name)
        if os.path.isfile(candidate):
            candidates.append(candidate)

    if os.path.basename(sys.executable).lower().startswith("python"):
        candidates.append(sys.executable)

    for candidate in candidates:
        if not candidate:
            continue
        try:
            completed = subprocess.run(
                [candidate, "-c", "import sys; print(sys.version_info[0])"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                timeout=30, check=False, **_no_window_kwargs()
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if completed.returncode == 0 and completed.stdout.strip() == "3":
            return candidate

    raise DeploymentError(
        "No Python 3 interpreter was found. Install Python 3 and make sure it is in PATH "
        "(Debian/Ubuntu: sudo apt-get install -y python3)."
    )


def probe_host() -> dict:
    """The prerequisites, answered without a clone.

    Only ever used before `scripts/server_ctl.py` exists locally; once it does,
    `status()` delegates to it so the panel and the terminal never disagree
    about what "docker is fine" means.
    """
    def version(command):
        try:
            completed = subprocess.run(
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                timeout=30, check=False, **_no_window_kwargs()
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return None, str(exc)
        if completed.returncode != 0:
            return None, (completed.stderr or completed.stdout).strip()
        return completed.stdout.strip(), None

    git_version, _ = version(["git", "--version"]) if shutil.which("git") else (None, None)
    docker_version, _ = version(["docker", "--version"]) if shutil.which("docker") else (None, None)
    daemon, daemon_error = (None, "docker is not installed")
    if docker_version:
        daemon, daemon_error = version(["docker", "info", "--format", "{{.ServerVersion}}"])
    compose_version, _ = version(["docker", "compose", "version"]) if docker_version else (None, None)

    return {
        "git": {"available": bool(git_version), "version": git_version},
        "docker": {
            "available": bool(docker_version),
            "version": docker_version,
            "daemon": bool(daemon),
            "error": None if daemon else daemon_error,
        },
        "compose": {"available": bool(compose_version), "version": compose_version},
    }


def tool_names(payload):
    """Tool names out of a `GET /tools` body, or None if it is not one.

    The server sends a list of `{name, arguments, output_kind}`; a name-keyed
    mapping is accepted too, since that is the shape `ToolServerClient` hands
    around internally and the two are easy to confuse. Anything else is None
    — "unknown" is a state the panel renders, a wrong list is not.
    """
    if isinstance(payload, dict):
        return sorted(payload)
    if isinstance(payload, list):
        return sorted(entry["name"] for entry in payload if isinstance(entry, dict) and "name" in entry)
    return None


class LocalServerDeployment:
    """One local clone of the server repository, and the docker deployment in it."""

    def __init__(self, install_dir=None, repo_url=DEFAULT_REPO_URL, branch=DEFAULT_BRANCH,
                 python_executable=None):
        self.install_dir = install_dir or DEFAULT_INSTALL_DIR
        self.repo_url = repo_url
        self.branch = branch
        self._python = python_executable
        # The subprocess currently running, so cancel() can reach it. A tool
        # download is hours long; a Cancel button that only stops *listening*
        # would leave 12 GB still coming down the wire.
        self._process = None
        self._cancelled = False

    # -- paths ---------------------------------------------------------

    @property
    def script_path(self) -> str:
        return os.path.join(self.install_dir, "scripts", "server_ctl.py")

    @property
    def install_docker_script(self) -> str:
        return os.path.join(self.install_dir, "scripts", "install-docker.sh")

    @property
    def data_dir(self) -> str:
        return os.path.join(self.install_dir, "DATA")

    @property
    def is_cloned(self) -> bool:
        """A clone we can actually drive — the control script has to be there.

        Not `os.path.isdir(install_dir)`: a half-finished clone, or a folder
        the user made by hand, is not a deployment and pretending otherwise
        turns every later call into an obscure "file not found".
        """
        return os.path.isfile(self.script_path)

    @property
    def python(self) -> str:
        if self._python is None:
            self._python = find_python()
        return self._python

    # -- process plumbing ----------------------------------------------

    def cancel(self) -> None:
        """Terminate whatever is running. Safe to call from another thread."""
        self._cancelled = True
        process = self._process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass

    def _spawn(self, command, progress_cb=None, cwd=None):
        """Run `command`, streaming stderr to `progress_cb`, returning (rc, stdout).

        stderr is drained by its own thread while this one reads stdout. Both
        are pipes, and reading them one after the other deadlocks the moment
        the writer fills the one nobody is reading — which is exactly what a
        long `docker compose up` does.
        """
        self._cancelled = False
        _emit(progress_cb, "$ " + " ".join(command))
        try:
            process = subprocess.Popen(
                command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, bufsize=1, **_no_window_kwargs()
            )
        except OSError as exc:
            raise DeploymentError(f"Could not run {command[0]}: {exc}") from None

        self._process = process

        def drain_stderr():
            for line in process.stderr:
                _emit(progress_cb, line.rstrip())

        reader = threading.Thread(target=drain_stderr, daemon=True)
        reader.start()
        try:
            out = process.stdout.read()
        finally:
            process.wait()
            reader.join(timeout=5)
            process.stdout.close()
            process.stderr.close()
            self._process = None

        if self._cancelled:
            raise DeploymentError("Cancelled.")
        return process.returncode, out

    def run_ctl(self, args, progress_cb=None):
        """Call `scripts/server_ctl.py --json <args>` and return its parsed result."""
        if not self.is_cloned:
            raise DeploymentError(
                f"The server repository is not installed in {self.install_dir} yet. "
                f"Use 'Install and start' first."
            )
        command = [self.python, self.script_path, "--json"] + list(args)
        returncode, out = self._spawn(command, progress_cb, cwd=self.install_dir)

        try:
            result = json.loads(out) if out.strip() else {}
        except ValueError:
            raise DeploymentError(
                f"server_ctl.py {' '.join(args)} produced no usable result "
                f"(exit code {returncode}). See the log for what it printed."
            ) from None
        if "error" in result:
            raise DeploymentError(result["error"])
        if returncode != 0:
            raise DeploymentError(f"server_ctl.py {' '.join(args)} failed (exit code {returncode}).")
        return result

    # -- operations ----------------------------------------------------

    def clone(self, progress_cb=None) -> None:
        """Clone the server repository into `install_dir`.

        Refuses a non-empty destination that is not already this clone —
        `git clone` would fail on it anyway, but with a message about an
        existing directory rather than about what to do next.
        """
        if self.is_cloned:
            _emit(progress_cb, f"Already installed in {self.install_dir}.")
            return
        if not shutil.which("git"):
            raise DeploymentError(
                "git is not installed. Install it and restart Slicer.\n"
                "  Debian/Ubuntu: sudo apt-get install -y git\n"
                "  macOS:         xcode-select --install\n"
                "  Windows:       https://git-scm.com/download/win"
            )
        if os.path.isdir(os.path.join(self.install_dir, ".git")):
            raise DeploymentError(
                f"{self.install_dir} is a git clone but carries no scripts/server_ctl.py. "
                f"It is probably a different repository, or a branch predating it — check it, "
                f"or choose another folder."
            )
        if os.path.exists(self.install_dir) and os.listdir(self.install_dir):
            raise DeploymentError(
                f"{self.install_dir} already exists and is not empty. Choose an empty folder "
                f"or move that one aside."
            )

        parent = os.path.dirname(os.path.abspath(self.install_dir))
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)

        _emit(progress_cb, f"Cloning {self.repo_url} ({self.branch}) into {self.install_dir}...")
        returncode, _out = self._spawn(
            ["git", "clone", "--branch", self.branch, self.repo_url, self.install_dir],
            progress_cb,
        )
        if returncode != 0 or not self.is_cloned:
            raise DeploymentError(
                f"Cloning {self.repo_url} failed. If the repository is private, set up a git "
                f"credential helper or an SSH key first — see the log for git's own message."
            )

    def can_install_docker(self) -> bool:
        """Whether Docker can be installed from here, without a terminal.

        Linux with a graphical `pkexec` only. Everywhere else the answer is a
        GUI installer (Docker Desktop) or a root shell, and offering a button
        that cannot deliver either is worse than saying so.
        """
        if sys.platform.startswith("linux") and os.geteuid() == 0:
            return True
        return (
            sys.platform.startswith("linux")
            and bool(shutil.which("pkexec"))
            and bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
        )

    def install_docker(self, progress_cb=None, with_nvidia: bool = False) -> None:
        """Run the repository's install-docker.sh with administrator rights.

        The clone has to exist first — the script is in it. Deliberately not a
        curl-pipe-to-root from the GUI: what runs as root is a file the user
        already has on disk and can read.
        """
        if not os.path.isfile(self.install_docker_script):
            raise DeploymentError(
                "scripts/install-docker.sh is missing from the install — clone the server "
                "repository first."
            )
        if not sys.platform.startswith("linux"):
            raise DeploymentError(
                "Automatic installation is Linux only. On macOS and Windows, install Docker "
                "Desktop from https://docs.docker.com/get-docker/, start it, and come back here."
            )

        command = ["sh", self.install_docker_script]
        if with_nvidia:
            command.append("--nvidia")
        if os.geteuid() != 0:
            if not shutil.which("pkexec"):
                raise DeploymentError(
                    "Administrator rights are needed and no graphical helper (pkexec) is "
                    f"available. Run this in a terminal instead:\n\n    sudo sh {self.install_docker_script}"
                )
            command = ["pkexec"] + command

        _emit(progress_cb, "A password prompt will appear — the installer needs root.")
        returncode, _out = self._spawn(command, progress_cb)
        if returncode != 0:
            raise DeploymentError(
                "Installing Docker failed or was refused. The log has the installer's own "
                f"output. You can also run it by hand:\n\n    sudo sh {self.install_docker_script}"
            )

    def status(self, check_remote: bool = False, progress_cb=None) -> dict:
        """Everything the panel shows, in one shape whether or not it is cloned."""
        if not self.is_cloned:
            probed = probe_host()
            probed.update({
                "cloned": False,
                "repo_root": self.install_dir,
                "gpu": {"nvidia_runtime": False, "nvidia_smi": bool(shutil.which("nvidia-smi"))},
                "clone": {"is_git_repo": False, "behind": 0, "error": "not installed yet"},
                "container": {"running": False, "state": None},
                "server": {"url": DEFAULT_SERVER_URL, "healthy": False},
                "env": {"has_token": False},
            })
            return probed

        args = ["status", "--branch", self.branch]
        if check_remote:
            args.append("--check-remote")
        result = self.run_ctl(args, progress_cb)
        result["cloned"] = True
        return result

    def up(self, progress_cb=None, force_recreate: bool = False, port=None) -> dict:
        """Start the server. The result carries the URL and the API token.

        `port` is only needed when something else already holds the default —
        it is remembered in the deployment's `.env`, so it has to be passed
        once, not on every start.
        """
        args = ["up"]
        if port:
            args += ["--port", str(port)]
        if force_recreate:
            args.append("--force-recreate")
        return self.run_ctl(args, progress_cb)

    def update(self, progress_cb=None, force: bool = False) -> dict:
        """Fetch, fast-forward, relaunch — and put the clone on `self.branch`.

        The branch is passed on every update, not only when it changed: a
        clone is created once, so a deployment pointed at another branch
        afterwards would otherwise keep following the old one for ever, in
        silence. This is what makes the Branch field mean something after the
        first install.
        """
        args = ["update", "--branch", self.branch]
        if force:
            args.append("--force")
        return self.run_ctl(args, progress_cb)

    def down(self, progress_cb=None) -> dict:
        return self.run_ctl(["down"], progress_cb)

    def stop_detached(self) -> bool:
        """Ask docker to stop the container and return IMMEDIATELY.

        For the application-quit hook, where the ordinary `down()` cannot be
        used: `docker compose stop` waits out its grace period before killing
        the container, and this image's uvicorn (started with `--reload`) does
        not act on SIGTERM — so a stop measures **10.5 s**, every one of which
        would be Slicer refusing to close. Shortening the grace only trades
        that for a shorter hang; detaching removes it.

        Nothing is reported back, and that is the honest shape of the
        operation: by the time it finishes there is no window left to report
        into. The failure mode is the container staying up, which is exactly
        the state we were in anyway.

        Returns whether the stop was *launched*, not whether it succeeded.
        """
        if not self.is_cloned:
            return False
        try:
            command = [self.python, self.script_path, "down"]
        except DeploymentError:
            return False

        kwargs = dict(_no_window_kwargs())
        if os.name == "nt":
            # DETACHED_PROCESS: survives the parent, no console window.
            kwargs["creationflags"] = kwargs.get("creationflags", 0) | 0x00000008
        else:
            # Its own session, so closing Slicer's terminal cannot take it down
            # with a SIGHUP before docker has finished.
            kwargs["start_new_session"] = True

        try:
            subprocess.Popen(
                command, cwd=self.install_dir,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                **kwargs
            )
        except OSError:
            return False
        return True

    def logs(self, lines: int = 200, progress_cb=None) -> dict:
        return self.run_ctl(["logs", "-n", str(lines)], progress_cb)

    def token(self, progress_cb=None) -> str:
        return self.run_ctl(["token"], progress_cb)["token"]

    def catalog(self, progress_cb=None) -> dict:
        return self.run_ctl(["catalog"], progress_cb)

    def list_tools(self, url=None, timeout: float = 10.0):
        """Tool names **this deployment's** server exposes, or None if it is down.

        Asked directly rather than through `ServerToolsCoreLib`'s client: that
        one talks to whatever server the extension is configured against, which
        is not necessarily the deployment this panel is managing — and
        answering "which tools does it have?" about a different machine is
        worse than answering "unknown".

        `GET /tools` is the one unauthenticated endpoint besides `/health`, so
        this needs no token and stays inside the no-`requests` rule.
        """
        url = (url or DEFAULT_SERVER_URL).rstrip("/")
        try:
            with urllib.request.urlopen(f"{url}/tools", timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError):
            return None
        return tool_names(payload)

    def download_data(self, tools, progress_cb=None, force: bool = False) -> dict:
        """Fetch the selected tools' models and test files.

        An empty selection is refused rather than treated as "everything": the
        full manifest is ~29 GB, and a stray click on a button whose label says
        "Download selected" must not start that.

        Whatever is already on disk is skipped by the engine, so re-running
        after adding one tool costs only that tool, and an interrupted download
        resumes by simply being started again.
        """
        tools = [tool for tool in tools if tool]
        if not tools:
            raise DeploymentError("No tool selected. Tick at least one before downloading.")
        args = ["models"]
        for tool in tools:
            args += ["--tool", tool]
        if force:
            args.append("--force")
        return self.run_ctl(args, progress_cb)

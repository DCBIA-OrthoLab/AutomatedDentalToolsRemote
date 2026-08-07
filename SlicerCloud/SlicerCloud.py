"""Slicer Cloud — stand a tool server up from inside Slicer, and keep it current.

Every other module in this extension is a thin GUI over a tool the server
already exposes; this one is the GUI over the *server itself*. It clones the
server repository, checks docker, starts the container, tells you when the
clone has fallen behind and relaunches it, and lets you choose which tools'
model bundles land on disk — the manifest is ~29 GB and nobody uses all of it.

The logic lives in the server repository's `scripts/server_ctl.py`, driven
through `SlicerCloudLib.deploy`. This file is the panel: widgets, threading,
and turning a status dict into something readable. See ARCHITECTURE.md.
"""

import logging

import ctk
import qt
import slicer
from slicer.i18n import tr as _
from slicer.ScriptedLoadableModule import ScriptedLoadableModule, ScriptedLoadableModuleWidget

from ServerToolsCoreLib import design, get_client
from ServerToolsCoreLib.settings_qt import save_overrides
from ServerToolsCoreLib.worker import BackgroundJob
from SlicerCloudLib.deploy import (
    DEFAULT_BRANCH,
    DEFAULT_INSTALL_DIR,
    DEFAULT_REPO_URL,
    DEFAULT_SERVER_URL,
    DeploymentError,
    LocalServerDeployment,
)

logger = logging.getLogger("SlicerCloud")

_SETTINGS_GROUP = "SlicerCloud"
_KEY_INSTALL_DIR = f"{_SETTINGS_GROUP}/InstallDir"
_KEY_REPO_URL = f"{_SETTINGS_GROUP}/RepoUrl"
_KEY_BRANCH = f"{_SETTINGS_GROUP}/Branch"
_KEY_SELECTED_TOOLS = f"{_SETTINGS_GROUP}/SelectedTools"
_KEY_PORT = f"{_SETTINGS_GROUP}/Port"
_KEY_STOP_ON_EXIT = f"{_SETTINGS_GROUP}/StopOnExit"

_DEFAULT_PORT = 8000
# On by default: the panel manages a server on the user's OWN machine, and a
# container nobody asked to keep is a background process on a clinician's
# laptop. `stop` (never `down`) is what makes this cheap — see the checkbox
# tooltip and stopServerOnExit().
_DEFAULT_STOP_ON_EXIT = True

# The log pane is a ring buffer, not an archive: a `docker compose up` on a
# fresh host prints tens of thousands of layer-progress lines, and an
# unbounded QTextEdit makes the panel crawl long before anyone reads them.
_LOG_MAX_BLOCKS = 2000

_ROW_LABELS = (
    ("git", _("Git")),
    ("docker", _("Docker")),
    ("compose", _("Docker Compose")),
    ("gpu", _("GPU")),
    ("clone", _("Server repository")),
    ("container", _("Container")),
    ("health", _("Server")),
)


def stopServerOnExit() -> None:
    """Stop the managed container as Slicer quits, if the user asked for that.

    Wired from the module class rather than from the widget, and that is the
    whole reason it is a module-level function: a widget only exists once
    someone has *opened* the panel, so a server started last Monday and never
    revisited would never be stopped — which is precisely the case this
    setting is for.

    `stop`, never `down`: the container is kept, so its writable layer keeps
    the `pip install --user` the image's command performed. Dependencies are
    therefore installed once, on the first start, and a later start is a few
    seconds. Removing the container is what would make them reinstall.

    Everything is swallowed. This runs while Slicer is tearing itself down;
    there is no window left to show an error in, and an exception raised in an
    `aboutToQuit` handler is a crash on exit for a background convenience.
    """
    try:
        settings = qt.QSettings()
        raw = settings.value(_KEY_STOP_ON_EXIT)
        enabled = _DEFAULT_STOP_ON_EXIT if raw is None else str(raw).lower() in ("true", "1")
        if not enabled:
            return
        install_dir = str(settings.value(_KEY_INSTALL_DIR) or DEFAULT_INSTALL_DIR)
        deployment = LocalServerDeployment(install_dir)
        if deployment.stop_detached():
            logger.info("Slicer is quitting: asked docker to stop the server in %s", install_dir)
    except Exception:  # noqa: BLE001 - see the docstring: never break the quit path
        logger.exception("Could not stop the server on exit")


def _human(size) -> str:
    if not size:
        return "0 B"
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


class SlicerCloud(ScriptedLoadableModule):
    """Uses ScriptedLoadableModule base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = _("Slicer Cloud")
        self.parent.categories = ["Automated Dental Tools"]
        self.parent.dependencies = ["ServerToolsCore"]
        self.parent.contributors = ["Automated Dental Tools team"]
        self.parent.helpText = _("""
        Deploy and maintain the Automated Dental Tools inference server on this machine, or on
        one you can reach a terminal on. It clones the server repository, checks that Docker is
        installed and usable, starts the container, and points every module of this extension at
        it. <b>Update server</b> checks whether the clone has fallen behind its remote and
        relaunches the container when it has.
        <br><br>
        Model bundles are downloaded per tool rather than all at once — the full set is about
        29 GB. Tick only the tools you use; come back later to add another one and only that one
        is downloaded.
        See more information in <a href="https://github.com/DCBIA-OrthoLab/SlicerAutomatedDentalTools">documentation</a>.
        """)
        self.parent.acknowledgementText = ""

        # Runs once, when Slicer discovers this module at startup — before the
        # panel has ever been opened, which is the point: the server may have
        # been started in an earlier session and never revisited. Same place
        # ServerToolsCore applies its saved settings, for the same reason.
        slicer.app.connect("aboutToQuit()", stopServerOnExit)


class SlicerCloudWidget(ScriptedLoadableModuleWidget):
    """The panel. One background job at a time, always cancellable."""

    def __init__(self, parent=None):
        ScriptedLoadableModuleWidget.__init__(self, parent)
        self.uiWidget = None
        self._deployment = None
        self._job = None
        self._jobName = ""
        self._statusRows = {}
        self._toolRows = {}          # {tool name: (QCheckBox, QLabel)}
        self._catalog = None
        self._registeredTools = None  # tool names the running server exposes, None if unknown
        self._lastStatus = None
        self._jobBlocking = True      # False while a passive status check runs
        self._loadingSettings = False  # True while _loadSettings writes the widgets

    # ------------------------------------------------------------------
    # Slicer lifecycle
    # ------------------------------------------------------------------

    def setup(self) -> None:
        ScriptedLoadableModuleWidget.setup(self)

        self.uiWidget = qt.QWidget()
        self.layout.addWidget(self.uiWidget)
        root = qt.QVBoxLayout(self.uiWidget)

        self._statusBadge = design.status_badge()
        root.addWidget(self._statusBadge)

        root.addWidget(self._buildServerBox())
        root.addWidget(self._buildDataBox())
        root.addWidget(self._buildLogBox())

        self._progressLabel = design.progress_label()
        root.addWidget(self._progressLabel)
        self.cancelButton = design.danger_button(_("Cancel"))
        self.cancelButton.setVisible(False)
        self.cancelButton.clicked.connect(self.onCancel)
        root.addWidget(self.cancelButton)

        root.addStretch(1)
        design.apply(self.uiWidget)

        self._loadSettings()
        self.onRefresh()

    def cleanup(self) -> None:
        # Only on teardown. Leaving the module (`exit`) deliberately does
        # NOT cancel: an install or a download is minutes to hours long, and
        # looking at another module is not a reason to abandon it half-done.
        self._cancelJob()

    def enter(self) -> None:
        design.apply(self.uiWidget)
        # Cheap and offline: a status refresh never fetches from the remote, so
        # coming back to the panel cannot hang on a machine with no network.
        # Skipped only while real work runs, so re-entering the module during
        # an install neither disturbs it nor pops a dialog.
        if not self._busyWithWork():
            self.onRefresh()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _buildServerBox(self):
        box = ctk.ctkCollapsibleButton()
        box.text = _("Local server")
        layout = qt.QVBoxLayout(box)

        form = qt.QFormLayout()
        layout.addLayout(form)

        self.installDirEdit = ctk.ctkPathLineEdit()
        self.installDirEdit.filters = ctk.ctkPathLineEdit.Dirs
        self.installDirEdit.setToolTip(
            _("Where the server repository and its model bundles (up to ~29 GB) are kept. "
              "Outside the Slicer installation on purpose, so it survives an update.")
        )
        form.addRow(design.section_title(_("Install folder")), self.installDirEdit)

        advanced = ctk.ctkCollapsibleButton()
        advanced.text = _("Advanced")
        advanced.collapsed = True
        advancedForm = qt.QFormLayout(advanced)
        self.repoUrlEdit = qt.QLineEdit()
        self.repoUrlEdit.setToolTip(_("Clone a fork instead of the reference repository."))
        advancedForm.addRow(design.section_title(_("Repository URL")), self.repoUrlEdit)
        self.branchEdit = qt.QLineEdit()
        advancedForm.addRow(design.section_title(_("Branch")), self.branchEdit)
        self.portSpin = qt.QSpinBox()
        self.portSpin.setRange(1024, 65535)
        self.portSpin.setValue(_DEFAULT_PORT)
        self.portSpin.setToolTip(
            _("Host port the server is published on. Change it only if something else already "
              "holds 8000 — it is remembered, so it only has to be set once.")
        )
        advancedForm.addRow(design.section_title(_("Port")), self.portSpin)
        layout.addWidget(advanced)

        checks = qt.QGridLayout()
        checks.setColumnStretch(1, 1)
        layout.addLayout(checks)
        for row, (key, label) in enumerate(_ROW_LABELS):
            name = design.section_title(label)
            value = qt.QLabel(_("checking..."))
            value.setWordWrap(True)
            checks.addWidget(name, row, 0)
            checks.addWidget(value, row, 1)
            self._statusRows[key] = value

        self.hintLabel = design.hint_label("")
        layout.addWidget(self.hintLabel)

        buttons = qt.QHBoxLayout()
        layout.addLayout(buttons)
        self.installButton = design.primary_button(_("Install and start"))
        self.installButton.setToolTip(
            _("Clone the server repository if needed, then start its container and wait for it "
              "to answer. Safe to run again: an existing install is reused and its API key kept.")
        )
        self.updateButton = design.primary_button(_("Update server"))
        self.updateButton.setToolTip(
            _("Fetch the remote, fast-forward the clone if it has fallen behind, and relaunch "
              "the container. Does nothing when the clone is current and the server is answering.")
        )
        self.stopButton = design.danger_button(_("Stop"))
        buttons.addWidget(self.installButton)
        buttons.addWidget(self.updateButton)
        buttons.addWidget(self.stopButton)

        secondary = qt.QHBoxLayout()
        layout.addLayout(secondary)
        self.refreshButton = design.link_button(_("Refresh"))
        self.checkUpdateButton = design.link_button(_("Check for updates"))
        self.checkUpdateButton.setToolTip(_("Fetch the remote to see whether the clone is behind."))
        self.showLogsButton = design.link_button(_("Server logs"))
        secondary.addWidget(self.refreshButton)
        secondary.addWidget(self.checkUpdateButton)
        secondary.addWidget(self.showLogsButton)
        secondary.addStretch(1)

        self.useServerCheck = qt.QCheckBox(
            _("Point every Automated Dental Tools module at this server once it is up")
        )
        self.useServerCheck.setChecked(True)
        self.useServerCheck.setToolTip(
            _("Saves this server's address and API key as the extension's settings — the same "
              "thing the Server Tools Settings module edits.")
        )
        layout.addWidget(self.useServerCheck)

        self.stopOnExitCheck = qt.QCheckBox(_("Stop the server when Slicer closes"))
        self.stopOnExitCheck.setToolTip(_(
            "Leaves nothing running in the background once you are done. Idle, the container "
            "costs about 220 MB of memory and no CPU or GPU — but after a run it keeps the "
            "loaded models resident until it is restarted.\n\n"
            "Restarting is cheap: the container is stopped, not deleted, so its dependencies "
            "stay installed and a later start takes a few seconds.\n\n"
            "Turn this OFF if this machine serves other people — closing Slicer would stop "
            "their server too."
        ))
        self.stopOnExitCheck.toggled.connect(lambda _checked: self._saveSettings())
        layout.addWidget(self.stopOnExitCheck)

        self.installButton.clicked.connect(self.onInstall)
        self.updateButton.clicked.connect(self.onUpdate)
        self.stopButton.clicked.connect(self.onStop)
        # Wrapped rather than connected directly: `clicked` carries a `checked`
        # bool, and onRefresh's first parameter is `check_remote` — a direct
        # connection would let a widget detail decide whether Refresh hits the
        # network.
        self.refreshButton.clicked.connect(lambda: self.onRefresh())
        self.checkUpdateButton.clicked.connect(lambda: self.onRefresh(check_remote=True))
        self.showLogsButton.clicked.connect(self.onShowLogs)
        self.installDirEdit.currentPathChanged.connect(self._onInstallDirChanged)
        return box

    def _buildDataBox(self):
        box = ctk.ctkCollapsibleButton()
        box.text = _("Tool data")
        layout = qt.QVBoxLayout(box)

        layout.addWidget(design.hint_label(_(
            "Each tool needs its own model bundle on the server before it can run. Tick only "
            "what you use — the full set is about 29 GB. Anything already on disk is skipped, "
            "so coming back later to add one tool downloads only that tool."
        )))

        links = qt.QHBoxLayout()
        layout.addLayout(links)
        for label, action in (
            (_("All"), lambda: self._selectTools(lambda tool: True)),
            (_("None"), lambda: self._selectTools(lambda tool: False)),
            (_("Not downloaded"), lambda: self._selectTools(lambda tool: not tool["complete"])),
            (_("This server's tools"), self._selectRegisteredTools),
        ):
            button = design.link_button(label)
            button.clicked.connect(action)
            links.addWidget(button)
        links.addStretch(1)

        # A scroll area: fourteen tools today and the manifest only grows, and
        # this box must not push the download button off the panel.
        scroll = qt.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(design.TABS_MIN_HEIGHT)
        self._toolContainer = qt.QWidget()
        self._toolLayout = qt.QVBoxLayout(self._toolContainer)
        self._toolLayout.setSpacing(design.SPACING_XS)
        scroll.setWidget(self._toolContainer)
        layout.addWidget(scroll)

        self.selectionLabel = design.hint_label("")
        layout.addWidget(self.selectionLabel)

        self.downloadButton = design.primary_button(_("Download selected"))
        layout.addWidget(self.downloadButton)
        self.downloadButton.clicked.connect(self.onDownload)
        return box

    def _buildLogBox(self):
        box = ctk.ctkCollapsibleButton()
        box.text = _("Log")
        box.collapsed = True
        layout = qt.QVBoxLayout(box)
        self.logView = qt.QTextEdit()
        self.logView.setReadOnly(True)
        self.logView.setLineWrapMode(qt.QTextEdit.NoWrap)
        self.logView.setMinimumHeight(design.TABS_MIN_HEIGHT)
        self.logView.document().setMaximumBlockCount(_LOG_MAX_BLOCKS)
        layout.addWidget(self.logView)
        clear = design.link_button(_("Clear"))
        clear.clicked.connect(lambda: self.logView.clear())
        row = qt.QHBoxLayout()
        row.addWidget(clear)
        row.addStretch(1)
        layout.addLayout(row)
        return box

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def _loadSettings(self) -> None:
        # Assigning currentPath emits currentPathChanged, which is wired to
        # _onInstallDirChanged and would launch a refresh from inside setup() —
        # then setup()'s own refresh found one already running and popped a
        # modal "Something is already running" on every single module open.
        self._loadingSettings = True
        try:
            self._loadSettingsInto()
        finally:
            self._loadingSettings = False

    def _loadSettingsInto(self) -> None:
        settings = qt.QSettings()
        self.installDirEdit.currentPath = str(settings.value(_KEY_INSTALL_DIR) or DEFAULT_INSTALL_DIR)
        self.repoUrlEdit.text = str(settings.value(_KEY_REPO_URL) or DEFAULT_REPO_URL)
        self.branchEdit.text = str(settings.value(_KEY_BRANCH) or DEFAULT_BRANCH)
        self.portSpin.value = int(settings.value(_KEY_PORT) or _DEFAULT_PORT)
        raw = settings.value(_KEY_STOP_ON_EXIT)
        # `is None` rather than a falsy test: the setting is a BOOLEAN whose
        # default is True, so an unset value and a saved False must not
        # collapse to the same branch.
        self.stopOnExitCheck.checked = (
            _DEFAULT_STOP_ON_EXIT if raw is None else str(raw).lower() in ("true", "1")
        )

    def _saveSettings(self) -> None:
        settings = qt.QSettings()
        settings.setValue(_KEY_INSTALL_DIR, self.installDirEdit.currentPath)
        settings.setValue(_KEY_REPO_URL, self.repoUrlEdit.text.strip())
        settings.setValue(_KEY_BRANCH, self.branchEdit.text.strip())
        settings.setValue(_KEY_PORT, self.portSpin.value)
        settings.setValue(_KEY_STOP_ON_EXIT, self.stopOnExitCheck.checked)
        settings.setValue(_KEY_SELECTED_TOOLS, ",".join(sorted(self._selectedTools())))
        settings.sync()

    def _savedSelection(self):
        raw = qt.QSettings().value(_KEY_SELECTED_TOOLS)
        return {name for name in str(raw or "").split(",") if name}

    def deployment(self) -> LocalServerDeployment:
        """Rebuilt whenever the folder/URL/branch fields change, so the object
        can never describe a different install than the one on screen."""
        install_dir = self.installDirEdit.currentPath or DEFAULT_INSTALL_DIR
        repo_url = self.repoUrlEdit.text.strip() or DEFAULT_REPO_URL
        branch = self.branchEdit.text.strip() or DEFAULT_BRANCH
        if (self._deployment is None
                or self._deployment.install_dir != install_dir
                or self._deployment.repo_url != repo_url
                or self._deployment.branch != branch):
            self._deployment = LocalServerDeployment(install_dir, repo_url, branch)
        return self._deployment

    def _onInstallDirChanged(self, _path=None) -> None:
        if self._loadingSettings:
            return
        self._saveSettings()
        if not self._busyWithWork():
            self.onRefresh()

    # ------------------------------------------------------------------
    # Background jobs — one at a time
    # ------------------------------------------------------------------

    def _busyWithWork(self) -> bool:
        """A real job is running — as opposed to a passive status check, which
        never blocks anything and is superseded on demand."""
        return self._job is not None and self._jobBlocking

    def _setBusy(self, busy: bool, what: str = "", disable: bool = True) -> None:
        """`disable=False` for a passive job — it narrates without locking the panel.

        Greying every button during a *status check* is what made the panel
        feel dead: the check runs on setup() and on every enter(), so the first
        thing a new user meets is an Install button they cannot press, for
        reasons nothing on screen explains.
        """
        if disable:
            for button in (self.installButton, self.updateButton, self.stopButton,
                           self.downloadButton, self.refreshButton, self.checkUpdateButton,
                           self.showLogsButton):
                button.setEnabled(not busy)
            self.cancelButton.setVisible(busy)
        self._progressLabel.setVisible(busy or bool(what))
        self._progressLabel.setText(what)

    def _startJob(self, name: str, task, on_success, refresh_on_error: bool = True,
                  blocking: bool = True) -> None:
        if self._job is not None:
            if self._jobBlocking:
                slicer.util.warningDisplay(
                    _("Something is already running: {0}.").format(self._jobName))
                return
            # A passive status check is always superseded rather than waited
            # for: by real work, and by a newer check (the folder just changed,
            # so the one in flight is answering about the wrong deployment).
            self._cancelJob()
        self._jobName = name
        self._jobBlocking = blocking
        self._setBusy(True, name, disable=blocking)
        self._log(f"--- {name} ---")

        def succeeded(result):
            self._job = None
            self._setBusy(False, disable=blocking)
            on_success(result)

        def failed(exc):
            self._job = None
            self._setBusy(False, disable=blocking)
            self._onJobError(name, exc, refresh_on_error)

        self._job = BackgroundJob(task, on_success=succeeded, on_error=failed, on_progress=self._log)
        self._job.start()

    def _cancelJob(self) -> None:
        if self._deployment is not None:
            self._deployment.cancel()
        if self._job is not None:
            self._job.cancel()
            self._job = None
        self._setBusy(False)

    def onCancel(self) -> None:
        self._log(_("Cancelling..."))
        self._cancelJob()
        self.onRefresh()

    def _onJobError(self, name: str, exc: Exception, refresh: bool = True) -> None:
        message = str(exc)
        self._log(f"error: {message}")
        if isinstance(exc, DeploymentError):
            # Written for the user by deploy.py or by server_ctl.py — shown verbatim.
            slicer.util.errorDisplay(message)
        else:
            logger.exception("%s failed", name)
            slicer.util.errorDisplay(_("{0} failed: {1}").format(name, message))
        # `refresh` is False for the refresh job itself. Otherwise a status
        # check that fails every time — no Python 3 on the machine, say —
        # would re-launch itself from its own error handler, for ever.
        if refresh:
            self.onRefresh()

    def _log(self, message: str) -> None:
        if not message:
            return
        self.logView.append(str(message))
        self.logView.ensureCursorVisible()
        if self._job is not None:
            # The last line doubles as the progress caption: a `docker compose
            # up` is fifteen silent minutes otherwise, and a panel that shows
            # nothing reads as frozen and gets cancelled just before it works.
            self._progressLabel.setText(f"{self._jobName} — {str(message)[:120]}")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def onRefresh(self, check_remote: bool = False) -> None:
        deployment = self.deployment()

        def task(progress_cb):
            status = deployment.status(check_remote=check_remote, progress_cb=progress_cb)
            catalog = deployment.catalog(progress_cb=None) if status.get("cloned") else None
            registered = None
            if status.get("server", {}).get("healthy"):
                registered = deployment.list_tools(status.get("server", {}).get("url"))
            return status, catalog, registered

        self._startJob(_("Checking the server"), task, self._onRefreshed,
                       refresh_on_error=False, blocking=False)

    def _onRefreshed(self, result) -> None:
        status, catalog, registered = result
        self._lastStatus = status
        self._registeredTools = registered
        self._renderStatus(status)
        if catalog is not None:
            self._renderCatalog(catalog)

    def onInstall(self) -> None:
        deployment = self.deployment()
        configure = self.useServerCheck.checked
        port = self.portSpin.value
        self._saveSettings()

        # Handled before the job starts, not inside it: installing Docker needs
        # a decision and a password prompt, and neither can be asked for from a
        # worker thread.
        docker = (self._lastStatus or {}).get("docker", {})
        if self._lastStatus is not None and not docker.get("daemon"):
            self._offerDockerInstall(docker)
            return

        def task(progress_cb):
            deployment.clone(progress_cb=progress_cb)
            status = deployment.status(progress_cb=progress_cb)
            if not status.get("docker", {}).get("daemon"):
                raise DeploymentError(_(
                    "Docker is not usable yet: {0}\n\n"
                    "Install it by running this in a terminal, then log out and back in:\n\n"
                    "    sudo sh {1}"
                ).format(status.get("docker", {}).get("error") or _("the daemon did not answer"),
                         deployment.install_docker_script))
            return deployment.up(progress_cb=progress_cb, port=port)

        def done(result):
            if configure and result.get("token"):
                self._applyServerSettings(result.get("url") or DEFAULT_SERVER_URL, result["token"])
            if result.get("healthy"):
                slicer.util.showStatusMessage(_("The tool server is running."), 5000)
            else:
                slicer.util.warningDisplay(_(
                    "The container was started but {0}/health did not answer in time. It may "
                    "still be installing its dependencies — check the Log, or press Refresh in "
                    "a few minutes."
                ).format(result.get("url") or DEFAULT_SERVER_URL))
            self.onRefresh()

        self._startJob(_("Installing and starting the server"), task, done)

    def _offerDockerInstall(self, docker: dict) -> None:
        """Docker is missing or unusable. Offer to fix it, or say exactly how.

        The installer is a shell script from the cloned repository run through
        `pkexec` — a file the user has on disk and can read, rather than a
        curl-pipe-to-root started by a button.
        """
        deployment = self.deployment()
        reason = docker.get("error") or _("Docker is not installed on this machine.")

        if not deployment.can_install_docker():
            slicer.util.errorDisplay(_(
                "{0}\n\nDocker has to be installed before the server can run.\n\n"
                "On Linux, run this in a terminal, then log out and back in:\n"
                "    sudo sh {1}\n\n"
                "On macOS or Windows, install Docker Desktop from "
                "https://docs.docker.com/get-docker/ and start it.\n\n"
                "Then come back here and press Install again."
            ).format(reason, deployment.install_docker_script))
            return

        if not slicer.util.confirmOkCancelDisplay(
            _("{0}\n\nInstall Docker now? It needs administrator rights, so you will be asked "
              "for your password. This can take a few minutes.").format(reason),
            _("Install Docker"),
        ):
            return

        def task(progress_cb):
            # The installer lives in the repository, so the clone comes first.
            deployment.clone(progress_cb=progress_cb)
            deployment.install_docker(progress_cb=progress_cb)
            return deployment.status(progress_cb=progress_cb)

        def done(status):
            if status.get("docker", {}).get("daemon"):
                slicer.util.infoDisplay(_(
                    "Docker is installed and usable. Press 'Install and start' to bring the "
                    "server up."
                ))
            else:
                slicer.util.infoDisplay(_(
                    "Docker is installed, but this account cannot use it yet: {0}\n\n"
                    "Group membership only applies to a NEW login session — log out and back "
                    "in (or reboot), restart Slicer, and press Install again."
                ).format(status.get("docker", {}).get("error") or ""))
            self.onRefresh()

        self._startJob(_("Installing Docker"), task, done)

    def onUpdate(self) -> None:
        deployment = self.deployment()

        def task(progress_cb):
            return deployment.update(progress_cb=progress_cb)

        def done(result):
            clone = result.get("clone") or {}
            if result.get("pulled"):
                summary = _("Updated to {0} and relaunched.").format(clone.get("commit") or _("the latest commit"))
            elif result.get("recreated"):
                summary = _("Already up to date; the container was relaunched.")
            else:
                summary = _("Already up to date and running — nothing to do.")
            self._log(summary)
            slicer.util.showStatusMessage(summary, 5000)
            if result.get("recreated") and not result.get("healthy"):
                slicer.util.warningDisplay(_(
                    "The server was relaunched but did not answer in time. Check the Log."
                ))
            self.onRefresh()

        self._startJob(_("Updating the server"), task, done)

    def onStop(self) -> None:
        deployment = self.deployment()
        self._startJob(
            _("Stopping the server"),
            lambda progress_cb: deployment.down(progress_cb=progress_cb),
            lambda _result: self.onRefresh(),
        )

    def onShowLogs(self) -> None:
        deployment = self.deployment()
        self._startJob(
            _("Reading the server log"),
            lambda progress_cb: deployment.logs(200, progress_cb=progress_cb),
            lambda _result: None,
        )

    def onDownload(self) -> None:
        deployment = self.deployment()
        selected = sorted(self._selectedTools())
        if not selected:
            slicer.util.errorDisplay(_("Tick at least one tool before downloading."))
            return
        self._saveSettings()

        missing = self._missingBytes(selected)
        free = (self._catalog or {}).get("disk_free")
        question = _("Download data for: {0}?\n\nAbout {1} to transfer.").format(
            ", ".join(selected), _human(missing))
        if free is not None:
            question += _("\n{0} free on that disk.").format(_human(free))
            if missing and free < missing * 1.1:
                question += _("\n\nThat is cutting it fine — the download needs temporary space too.")
        if not slicer.util.confirmOkCancelDisplay(question, _("Download tool data")):
            return

        def task(progress_cb):
            return deployment.download_data(selected, progress_cb=progress_cb)

        def done(result):
            catalog = result.get("catalog")
            if catalog:
                self._renderCatalog(catalog)
            still = self._missingBytes(selected)
            if still:
                slicer.util.warningDisplay(_(
                    "Some items could not be downloaded ({0} still missing). The Log names "
                    "them; re-running fetches only those."
                ).format(_human(still)))
            else:
                slicer.util.showStatusMessage(_("Tool data is complete."), 5000)

        self._startJob(_("Downloading tool data"), task, done)

    def _applyServerSettings(self, url: str, token: str) -> None:
        """Make this deployment the one every other module talks to.

        `verify_tls` is deliberately left as it was rather than forced to
        False. It is irrelevant to an `http://localhost` URL, and turning it
        off here would silently disable certificate checking for whatever
        `https://` server the user points at next.
        """
        client = get_client()
        save_overrides(url, token, client.verify_tls, client.timeout)
        client.configure(server_url=url, token=token)
        self._log(_("Saved {0} as the server used by every module.").format(url))

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _renderStatus(self, status: dict) -> None:
        tokens = design.tokens()

        def paint(key, ok, text):
            label = self._statusRows[key]
            label.setText(text)
            label.setStyleSheet(f"color: {tokens['SUCCESS'] if ok else tokens['TEXT_MUTED']};")

        git = status.get("git", {})
        paint("git", git.get("available"), git.get("version") or _("not installed"))

        docker = status.get("docker", {})
        if docker.get("daemon"):
            paint("docker", True, docker.get("version") or _("running"))
        elif docker.get("available"):
            paint("docker", False, _("installed, but: {0}").format(docker.get("error") or "?"))
        else:
            paint("docker", False, _("not installed"))

        compose = status.get("compose", {})
        paint("compose", compose.get("available"), compose.get("version") or _("not installed"))

        gpu = status.get("gpu", {})
        if gpu.get("nvidia_runtime"):
            paint("gpu", True, _("nvidia runtime available — the GPU service will be used"))
        elif gpu.get("nvidia_smi"):
            paint("gpu", False, _("a card is present but docker has no nvidia runtime — running on CPU"))
        else:
            paint("gpu", False, _("no GPU — running on CPU (everything works, slowly)"))

        clone = status.get("clone", {})
        if not status.get("cloned"):
            paint("clone", False, _("not installed in {0}").format(status.get("repo_root", "")))
        elif not clone.get("is_git_repo"):
            paint("clone", False, clone.get("error") or _("not a git clone"))
        else:
            if clone.get("branch_mismatch"):
                paint("clone", False, _(
                    "on '{0}', but this deployment asks for '{1}' — press 'Update server' "
                    "to switch it"
                ).format(clone.get("branch"), clone.get("configured_branch")))
                return
            behind = clone.get("behind") or 0
            text = _("{0} at {1} — ").format(clone.get("branch"), clone.get("commit"))
            text += _("{0} commit(s) behind, press Update").format(behind) if behind else _("up to date")
            if not clone.get("checked_remote"):
                text += _(" (as of the last fetch)")
            if clone.get("dirty"):
                text += _(" [local changes]")
            paint("clone", not behind, text)

        container = status.get("container", {})
        paint("container", container.get("running"),
              _("{0}: {1}").format(status.get("service", "?"), container.get("state") or _("not created yet")))

        healthy = status.get("server", {}).get("healthy")
        url = status.get("server", {}).get("url", DEFAULT_SERVER_URL)
        paint("health", healthy, _("{0} — {1}").format(url, _("answering") if healthy else _("no answer")))
        design.update_status_badge(self._statusBadge, bool(healthy))

        self.hintLabel.setText(self._nextStep(status))
        self.installButton.setText(
            _("Install and start") if not status.get("cloned") else _("Start server")
        )
        self.stopButton.setEnabled(bool(container.get("running")))

    def _nextStep(self, status: dict) -> str:
        """One sentence naming the single next thing to do. A grid of red rows
        says what is wrong; it does not say what to press."""
        docker = status.get("docker", {})
        if not docker.get("available"):
            return _("Docker is missing. Press 'Install and start' — it will tell you the exact "
                     "command to run in a terminal.")
        if not docker.get("daemon"):
            return _("Docker is installed but not usable by this account: {0}").format(docker.get("error") or "")
        if not status.get("cloned"):
            return _("Nothing installed yet. Press 'Install and start' to clone the server and "
                     "bring it up.")
        if (status.get("clone") or {}).get("branch_mismatch"):
            return _("The clone is on branch '{0}' but this deployment asks for '{1}'. Press "
                     "'Update server' to switch it.").format(
                         (status.get("clone") or {}).get("branch"),
                         (status.get("clone") or {}).get("configured_branch"))
        if (status.get("clone") or {}).get("behind"):
            return _("A newer version of the server is available. Press 'Update server'.")
        if not (status.get("container") or {}).get("running"):
            return _("The server is installed but not running. Press 'Start server'.")
        if not status.get("server", {}).get("healthy"):
            return _("The container is running but not answering yet — it may still be installing "
                     "dependencies. Check the Log.")
        return _("The server is up. Pick the tools you need under 'Tool data'.")

    def _renderCatalog(self, catalog: dict) -> None:
        self._catalog = catalog
        previous = self._selectedTools() if self._toolRows else self._savedSelection()

        # Rebuilt wholesale rather than patched: the manifest can gain a tool
        # between two refreshes, and a row list that is only ever appended to
        # would keep showing one that was removed.
        for checkbox, label in self._toolRows.values():
            checkbox.setParent(None)
            label.setParent(None)
            checkbox.deleteLater()
            label.deleteLater()
        self._toolRows = {}
        while self._toolLayout.count():
            item = self._toolLayout.takeAt(0)
            if item.layout():
                item.layout().deleteLater()

        for tool in catalog.get("tools", []):
            row = qt.QHBoxLayout()
            checkbox = qt.QCheckBox(tool["name"])
            checkbox.setChecked(tool["name"] in previous)
            checkbox.toggled.connect(self._updateSelectionSummary)
            label = design.hint_label(self._toolSummary(tool))
            row.addWidget(checkbox)
            row.addStretch(1)
            row.addWidget(label)
            self._toolLayout.addLayout(row)
            self._toolRows[tool["name"]] = (checkbox, label)

        self._updateSelectionSummary()

    def _toolSummary(self, tool: dict) -> str:
        if tool["complete"]:
            state = _("downloaded ({0})").format(_human(tool["size"]))
        elif tool["partial"]:
            state = _("partial — {0} of {1} left").format(
                _human(tool["missing_size"]), _human(tool["size"]))
        else:
            state = _("{0} to download").format(_human(tool["size"]))
        if self._registeredTools is not None and tool["name"] not in self._registeredTools:
            state += _("  ·  not exposed by this server")
        return state

    def _selectedTools(self):
        return {name for name, (checkbox, _label) in self._toolRows.items() if checkbox.checked}

    def _selectTools(self, predicate) -> None:
        for tool in (self._catalog or {}).get("tools", []):
            checkbox, _label = self._toolRows.get(tool["name"], (None, None))
            if checkbox is not None:
                checkbox.setChecked(bool(predicate(tool)))

    def _selectRegisteredTools(self) -> None:
        if self._registeredTools is None:
            slicer.util.warningDisplay(_(
                "The server is not answering, so its list of tools is unknown. Start it first."
            ))
            return
        self._selectTools(lambda tool: tool["name"] in self._registeredTools)

    def _missingBytes(self, names) -> int:
        wanted = set(names)
        return sum(tool["missing_size"] for tool in (self._catalog or {}).get("tools", [])
                   if tool["name"] in wanted)

    def _updateSelectionSummary(self, _checked=None) -> None:
        selected = self._selectedTools()
        if not selected:
            self.selectionLabel.setText(_("No tool selected."))
            self.downloadButton.setEnabled(False)
            return
        missing = self._missingBytes(selected)
        free = (self._catalog or {}).get("disk_free")
        text = _("{0} tool(s) selected — {1} to download").format(len(selected), _human(missing))
        if free is not None:
            text += _(", {0} free").format(_human(free))
        if not missing:
            text += _("  ·  everything selected is already on disk")
        self.selectionLabel.setText(text)
        self.downloadButton.setEnabled(True)

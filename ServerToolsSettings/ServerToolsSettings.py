import logging

import ctk
import qt
import slicer
from slicer.i18n import tr as _
from slicer.ScriptedLoadableModule import ScriptedLoadableModule, ScriptedLoadableModuleWidget

from ServerToolsCoreLib import config, design, get_client
from ServerToolsCoreLib.settings_qt import clear_overrides, save_design, save_overrides
from ServerToolsCoreLib.worker import BackgroundJob

logger = logging.getLogger("ServerToolsCore.settings")


class ServerToolsSettings(ScriptedLoadableModule):
    """Uses ScriptedLoadableModule base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = _("Server Tools Settings")
        self.parent.categories = ["Automated Dental Tools.Advanced"]
        self.parent.dependencies = ["ServerToolsCore"]
        self.parent.contributors = ["Automated Dental Tools team"]
        self.parent.helpText = _(
            "Configure the remote tool server (URL, API key, TLS verification, timeout) used "
            "by every Automated Dental Tools module built on ServerToolsCore. Changes apply "
            "immediately and persist across Slicer restarts."
        )
        self.parent.acknowledgementText = ""


class ServerToolsSettingsWidget(ScriptedLoadableModuleWidget):
    """Thin settings panel over ServerToolsCoreLib.client.ToolServerClient.configure()."""

    def __init__(self, parent=None):
        ScriptedLoadableModuleWidget.__init__(self, parent)
        self.client = get_client()
        self.uiWidget = None
        self._statusBadge = None
        self._statusJob = None
        # Set while the panel writes into its own chooser, so reflecting the
        # saved treatment does not read as the user having picked one -- and
        # does not write the setting back on every open.
        self._syncingDesign = False

    def setup(self) -> None:
        ScriptedLoadableModuleWidget.setup(self)

        self.uiWidget = qt.QWidget()
        self.layout.addWidget(self.uiWidget)
        rootLayout = qt.QVBoxLayout(self.uiWidget)

        self._statusBadge = design.status_badge()
        rootLayout.addWidget(self._statusBadge)

        box = ctk.ctkCollapsibleButton()
        box.text = _("Server connection")
        formLayout = qt.QFormLayout(box)
        rootLayout.addWidget(box)

        self.urlEdit = qt.QLineEdit()
        self.urlEdit.setToolTip(_("e.g. https://tools.example.org"))
        formLayout.addRow(design.required_label(_("Server URL")), self.urlEdit)

        self.tokenEdit = qt.QLineEdit()
        self.tokenEdit.setEchoMode(qt.QLineEdit.Password)
        formLayout.addRow(design.required_label(_("API key")), self.tokenEdit)

        self.verifyTlsCheck = qt.QCheckBox()
        self.verifyTlsCheck.setToolTip(_("Disable only for local development against a non-HTTPS server."))
        formLayout.addRow(design.section_title(_("Verify TLS")), self.verifyTlsCheck)

        self.timeoutSpin = qt.QSpinBox()
        self.timeoutSpin.setRange(1, 3600)
        self.timeoutSpin.setSuffix(_(" s"))
        formLayout.addRow(design.section_title(_("Timeout")), self.timeoutSpin)

        self._buildAppearance(rootLayout)

        self.saveButton = design.primary_button(_("Save"))
        self.restoreButton = design.danger_button(_("Restore defaults"))
        rootLayout.addWidget(self.saveButton)
        rootLayout.addWidget(self.restoreButton)
        rootLayout.addStretch(1)

        self.saveButton.clicked.connect(self.onSaveButton)
        self.restoreButton.clicked.connect(self.onRestoreButton)

        design.apply(self.uiWidget)
        self._loadDesign()
        self._loadFromClient()

    def _buildAppearance(self, rootLayout) -> None:
        """A chooser between the design treatments, so they can be COMPARED.

        A palette read off a page is not a panel: the difference between two of
        these shows up on the sixth row of a crowded form, and the only way to
        judge that is to look at one. It lives in the advanced settings module
        rather than on every panel because it is a preference, and one a
        clinician sets once.
        """
        box = ctk.ctkCollapsibleButton()
        box.text = _("Appearance")
        layout = qt.QFormLayout(box)
        rootLayout.addWidget(box)

        self.designCombo = qt.QComboBox()
        for name in design.variants():
            # The name travels as item DATA, never as the label: the labels are
            # translated and the saved setting must not be.
            self.designCombo.addItem(_(design.VARIANT_LABELS[name]), name)
        self.designCombo.currentIndexChanged.connect(self.onDesignChosen)
        layout.addRow(design.section_title(_("Design")), self.designCombo)

        self._designHint = design.hint_label("")
        layout.addRow(self._designHint)

        layout.addRow(design.hint_label(_(
            "Reload a tool module, or restart Slicer, to repaint it: a widget "
            "is built with the treatment that was in force when it was made."
        )))

    def onDesignChosen(self, _index=None) -> None:
        if self._syncingDesign:
            return
        name = self.designCombo.itemData(self.designCombo.currentIndex)
        if not name or not design.set_variant(name):
            return
        save_design(name)
        self._designHint.setText(_(design.VARIANT_HINTS[name]))
        # Repaints what this stylesheet reaches -- the ground, the fields, the
        # boxes -- so the choice shows something at once. The buttons and chips
        # around it keep the treatment they were built with, which is what the
        # line under the chooser says.
        design.apply(self.uiWidget)
        logger.info("Design treatment set to %s", name)

    def _loadDesign(self) -> None:
        current = design.variant()
        self._syncingDesign = True
        try:
            for index in range(self.designCombo.count):
                if self.designCombo.itemData(index) == current:
                    self.designCombo.setCurrentIndex(index)
                    break
        finally:
            self._syncingDesign = False
        self._designHint.setText(_(design.VARIANT_HINTS[current]))

    def cleanup(self) -> None:
        if self._statusJob:
            self._statusJob.cancel()
            self._statusJob = None

    def enter(self) -> None:
        design.apply(self.uiWidget)
        self._refreshStatus()

    def _loadFromClient(self) -> None:
        """Reflect whatever is actually active right now: a saved override if
        one was applied at startup, otherwise config.py's defaults."""
        self.urlEdit.text = self.client.server_url
        self.tokenEdit.text = self.client.token
        self.verifyTlsCheck.checked = self.client.verify_tls
        self.timeoutSpin.value = self.client.timeout
        self._refreshStatus()

    def onSaveButton(self) -> None:
        server_url = self.urlEdit.text.strip()
        if not server_url:
            slicer.util.errorDisplay(_("Server URL cannot be empty."))
            return

        token = self.tokenEdit.text
        verify_tls = self.verifyTlsCheck.checked
        timeout = self.timeoutSpin.value

        save_overrides(server_url, token, verify_tls, timeout)
        self.client.configure(server_url=server_url, token=token, verify_tls=verify_tls, timeout=timeout)
        logger.info("Server settings saved: url=%s verify_tls=%s timeout=%s", server_url, verify_tls, timeout)
        slicer.util.showStatusMessage(_("Server settings saved."), 3000)
        self._refreshStatus()

    def onRestoreButton(self) -> None:
        clear_overrides()
        self.client.configure(
            server_url=config.SERVER_URL,
            token=config.API_TOKEN,
            verify_tls=config.VERIFY_TLS,
            timeout=config.TIMEOUT,
        )
        self._loadFromClient()
        slicer.util.showStatusMessage(_("Restored default server settings."), 3000)

    def _refreshStatus(self) -> None:
        """Owned by the widget, not a local - see ServerToolWidgetBase._refreshServerStatus()."""
        if self._statusJob:
            self._statusJob.cancel()

        def task(_progress_cb):
            return self.client.health()

        self._statusJob = BackgroundJob(
            task, on_success=self._onStatusChecked, on_error=lambda _exc: self._onStatusChecked(False)
        )
        self._statusJob.start()

    def _onStatusChecked(self, ok: bool) -> None:
        self._statusJob = None
        if self._statusBadge:
            design.update_status_badge(self._statusBadge, ok)

"""Generic Slicer widget for any tool exposed by the tool server.

A concrete module declares a handful of class attributes (TOOL_NAME,
FILE_INPUTS, RESULT_KIND) and optionally overrides a few hooks; everything
else — Slicer lifecycle, schema-driven GUI, theme, async call, error
handling, temp-file cleanup — is inherited from here.

See ARCHITECTURE.md, "How to add a new module in 5 minutes".
"""

import logging
import os

import ctk
import qt
import slicer
from slicer.i18n import tr as _
from slicer.ScriptedLoadableModule import ScriptedLoadableModuleWidget
from slicer.util import VTKObservationMixin

from . import design, formgen, is_file_type, slicer_io
from .errors import ServerToolError
from .worker import BackgroundJob

logger = logging.getLogger("ServerToolsCore.base_widget")

_FILE_INPUT_MODES = ("single_file", "volume_node", "folder_zip")
_RESULT_KINDS = ("text", "segmentation", "volume", "model", "save_as")


class ServerToolWidgetBase(ScriptedLoadableModuleWidget, VTKObservationMixin):
    # -- declared by subclasses --------------------------------------
    TOOL_NAME = None
    FILE_INPUTS = {}  # {schema_argument_name: "single_file" | "volume_node" | "folder_zip"}
    RESULT_KIND = "text"
    AUTO_UI = True

    def __init__(self, parent=None):
        ScriptedLoadableModuleWidget.__init__(self, parent)
        VTKObservationMixin.__init__(self)

        if not self.TOOL_NAME:
            raise ValueError(f"{type(self).__name__} must set TOOL_NAME.")
        for arg_name, mode in self.FILE_INPUTS.items():
            if mode not in _FILE_INPUT_MODES:
                raise ValueError(f"{type(self).__name__}: unknown file input mode '{mode}' for '{arg_name}'.")
        if self.RESULT_KIND not in _RESULT_KINDS:
            raise ValueError(f"{type(self).__name__}: unknown RESULT_KIND '{self.RESULT_KIND}'.")

        # Imported lazily to keep ServerToolsCoreLib importable outside Slicer for tests.
        from . import get_client

        self.client = get_client()
        self._argWidgets = {}
        self._schema = None
        self._job = None
        self._workspace = None
        self._inputWidgets = {}  # {schema_argument_name: widget}
        self._outputFolderWidget = None
        self._statusBadge = None
        self.uiWidget = None

    # ------------------------------------------------------------------
    # Slicer lifecycle
    # ------------------------------------------------------------------

    def setup(self) -> None:
        ScriptedLoadableModuleWidget.setup(self)

        self.uiWidget = qt.QWidget()
        self.layout.addWidget(self.uiWidget)
        rootLayout = qt.QVBoxLayout(self.uiWidget)

        self._statusBadge = design.status_badge()
        rootLayout.addWidget(self._statusBadge)

        try:
            if self.AUTO_UI:
                self._buildAutoUI(rootLayout)
            else:
                self.buildCustomUI(rootLayout)
        except Exception as exc:
            # Never leave the user with a silently blank/half-built panel: a bad
            # CTK/Qt call, a module misconfiguration, etc. must be visible right
            # here, not just in the Python console.
            logger.exception("Failed to build the UI for tool '%s'", self.TOOL_NAME)
            rootLayout.addWidget(
                design.warning_label(_("Could not build this module's UI: {error}").format(error=exc))
            )

        extraLayout = qt.QVBoxLayout()
        rootLayout.addLayout(extraLayout)
        self.addExtraWidgets(extraLayout)

        self.applyButton = design.primary_button(_("Apply"))
        self.cancelButton = design.danger_button(_("Cancel"))
        self.cancelButton.setVisible(False)
        rootLayout.addWidget(self.applyButton)
        rootLayout.addWidget(self.cancelButton)

        self.applyButton.clicked.connect(self.onApplyButton)
        self.cancelButton.clicked.connect(self.onCancelButton)

        # Without a trailing stretch, QVBoxLayout spreads its (Preferred-policy)
        # widgets across the whole module panel height instead of packing them
        # at the top — the same reason every hand-written .ui file in this repo
        # ends with a vertical spacer.
        rootLayout.addStretch(1)

        design.apply(self.uiWidget)

        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.StartCloseEvent, self.onSceneStartClose)
        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.EndCloseEvent, self.onSceneEndClose)

        self._checkCanApply()

    def cleanup(self) -> None:
        self.removeObservers()
        if self._job:
            self._job.cancel()
            self._job = None
        if self._workspace:
            self._workspace.__exit__(None, None, None)
            self._workspace = None

    def enter(self) -> None:
        if self.uiWidget:
            design.apply(self.uiWidget)
        self._refreshServerStatus()

    def exit(self) -> None:
        pass

    def onSceneStartClose(self, caller, event) -> None:
        pass

    def onSceneEndClose(self, caller, event) -> None:
        pass

    # ------------------------------------------------------------------
    # GUI construction
    # ------------------------------------------------------------------

    def _buildAutoUI(self, rootLayout) -> None:
        logger.info("Building AUTO_UI for TOOL_NAME='%s' (FILE_INPUTS=%s, RESULT_KIND=%s)",
                    self.TOOL_NAME, self.FILE_INPUTS, self.RESULT_KIND)

        inputsBox = ctk.ctkCollapsibleButton()
        inputsBox.text = _("Inputs")
        inputsLayout = qt.QFormLayout(inputsBox)
        rootLayout.addWidget(inputsBox)

        self._inputWidgets = self._buildInputWidgets(inputsLayout)

        try:
            self._schema = self.client.get_tool_schema(self.TOOL_NAME)
            logger.info(
                "Schema for '%s': output_kind=%s, argument keys=%s",
                self.TOOL_NAME,
                self._schema.get("output_kind"),
                sorted(self._schema.get("arguments", {}).keys()),
            )
            self._applyFileArgumentTooltips()
            self._warnAboutFileInputsMismatch(rootLayout)
        except ServerToolError as exc:
            logger.warning("Could not load schema for '%s': %s", self.TOOL_NAME, exc)
            self._schema = {"arguments": {}}
            rootLayout.addWidget(
                design.warning_label(
                    _("Could not load '{tool}' from the server: {error}").format(tool=self.TOOL_NAME, error=exc)
                )
            )

        self._argWidgets = formgen.build(self._schema.get("arguments", {}), inputsLayout)
        logger.info("AUTO_UI built %d scalar field(s) for '%s': %s",
                    len(self._argWidgets), self.TOOL_NAME, sorted(self._argWidgets.keys()))
        for widget in self._argWidgets.values():
            formgen.connect_changed(widget, self._checkCanApply)

        self._populateServerSelectables(rootLayout)

        if self.RESULT_KIND == "save_as":
            outputsBox = ctk.ctkCollapsibleButton()
            outputsBox.text = _("Outputs")
            outputsLayout = qt.QFormLayout(outputsBox)
            rootLayout.addWidget(outputsBox)

            self._outputFolderWidget = ctk.ctkPathLineEdit()
            self._outputFolderWidget.filters = ctk.ctkPathLineEdit.Dirs
            outputsLayout.addRow(design.required_label(_("Output folder")), self._outputFolderWidget)
            formgen.connect_changed(self._outputFolderWidget, self._checkCanApply)

    def _buildInputWidgets(self, layout) -> dict:
        return {arg_name: self._buildFileInputWidget(layout, arg_name, mode) for arg_name, mode in self.FILE_INPUTS.items()}

    def _buildFileInputWidget(self, layout, arg_name: str, mode: str):
        label = _(arg_name.replace("_", " ").capitalize())

        if mode == "volume_node":
            widget = slicer.qMRMLNodeComboBox()
            widget.nodeTypes = ["vtkMRMLScalarVolumeNode"]
            widget.noneEnabled = True
            widget.setMRMLScene(slicer.mrmlScene)
            layout.addRow(design.required_label(label), widget)
            widget.currentNodeChanged.connect(self._checkCanApply)
            return widget

        widget = ctk.ctkPathLineEdit()
        if mode == "folder_zip":
            widget.filters = ctk.ctkPathLineEdit.Dirs
        layout.addRow(design.required_label(label), widget)
        formgen.connect_changed(widget, self._checkCanApply)
        return widget

    def _populateServerSelectables(self, rootLayout) -> None:
        """Fill every server_selectable dropdown (see formgen._make_widget)
        with the file names hosted on the server for this tool, from
        GET /tools/{tool}/data — e.g. surg_mov_pred's "model" argument, which
        is picked among the server's models by name, never uploaded.

        Synchronous like the schema fetch just above, and for the same reason:
        the form needs its choices before the first paint, and the call is
        capped at the same short timeout. A failure (or an empty list) shows a
        visible warning instead of leaving a silently empty dropdown.
        """
        arguments = self._schema.get("arguments", {})
        # File-typed server_selectable arguments (e.g. an uploadable-or-server
        # testfile) are handled by FILE_INPUTS, never emitted by formgen.build
        # — so restricting to _argWidgets naturally keeps only the scalar ones.
        selectable = {
            name: spec["server_selectable"]
            for name, spec in arguments.items()
            if spec.get("server_selectable") and name in self._argWidgets
        }
        if not selectable:
            return

        try:
            data = self.client.list_tool_data(self.TOOL_NAME)
        except ServerToolError as exc:
            logger.warning("Could not list server-side data for '%s': %s", self.TOOL_NAME, exc)
            rootLayout.addWidget(
                design.warning_label(
                    _("Could not list the server-side files for '{tool}': {error}").format(
                        tool=self.TOOL_NAME, error=exc
                    )
                )
            )
            return

        for arg_name, kind in selectable.items():
            choices = data.get("models" if kind == "model" else "testfiles", [])
            widget = self._argWidgets[arg_name]
            widget.clear()
            widget.addItems(choices)
            logger.info("Populated '%s.%s' with %d server-side %s(s)",
                        self.TOOL_NAME, arg_name, len(choices), kind)
            if not choices:
                rootLayout.addWidget(
                    design.warning_label(
                        _("No {kind} available on the server for '{tool}' — ask the server maintainer to add one.").format(
                            kind=kind, tool=self.TOOL_NAME
                        )
                    )
                )

    def _applyFileArgumentTooltips(self) -> None:
        """Use the server's own description for each file input, once the
        schema is known (input widgets are built before the schema arrives)."""
        arguments = self._schema.get("arguments", {})
        for arg_name, widget in self._inputWidgets.items():
            description = arguments.get(arg_name, {}).get("description")
            if description:
                widget.setToolTip(description)

    def _warnAboutFileInputsMismatch(self, rootLayout) -> None:
        """Catch schema drift early: FILE_INPUTS is written by hand against a
        remembered schema, so if the server renames/drops a file argument this
        surfaces immediately instead of failing later with a confusing 422."""
        declared = {name for name, spec in self._schema.get("arguments", {}).items() if is_file_type(spec.get("type", ""))}
        missing = set(self.FILE_INPUTS) - declared
        if missing:
            message = _(
                "FILE_INPUTS declares {missing} but the server's '{tool}' schema doesn't have "
                "them as file arguments (it has: {declared})."
            ).format(missing=sorted(missing), tool=self.TOOL_NAME, declared=sorted(declared))
            logger.warning(message)
            rootLayout.addWidget(design.warning_label(message))

    def buildCustomUI(self, layout) -> None:
        """Override when AUTO_UI = False."""
        raise NotImplementedError(f"{type(self).__name__} must implement buildCustomUI() since AUTO_UI is False.")

    def addExtraWidgets(self, layout) -> None:
        """Override to add a custom button or field. Called after the auto-generated
        GUI, before Apply/Cancel — this is the supported way to extend a module
        without touching setup()."""

    # ------------------------------------------------------------------
    # Overridable data hooks
    # ------------------------------------------------------------------

    def collectArgs(self) -> dict:
        """Override to transform values before sending."""
        return formgen.collect(self._argWidgets)

    def prepareInputFiles(self, workspace: slicer_io.TempWorkspace) -> dict:
        """Override for exotic input cases. Default behavior covers all three
        file input modes for every entry declared in FILE_INPUTS. Returns
        {schema_argument_name: local_file_path}."""
        files = {}
        for arg_name, mode in self.FILE_INPUTS.items():
            path = self._prepareOneInputFile(workspace, arg_name, mode)
            if path is not None:
                files[arg_name] = path
        return files

    def _prepareOneInputFile(self, workspace: slicer_io.TempWorkspace, arg_name: str, mode: str):
        widget = self._inputWidgets.get(arg_name)
        if mode == "single_file":
            return widget.currentPath
        if mode == "folder_zip":
            return slicer_io.zip_folder(widget.currentPath, workspace.file(f"{self.TOOL_NAME}_{arg_name}.zip"))
        if mode == "volume_node":
            node = widget.currentNode()
            if node is None:
                return None
            return slicer_io.export_volume(node, workspace.file(f"{self.TOOL_NAME}_{arg_name}.nii.gz"))
        return None

    def handleResult(self, result) -> None:
        """Override for custom result display."""
        if self.RESULT_KIND == "text":
            slicer.util.infoDisplay(result.text or "")
        elif self.RESULT_KIND in ("segmentation", "volume", "model"):
            slicer_io.load_result(result.path, self.RESULT_KIND)
        elif self.RESULT_KIND == "save_as":
            self._handleSaveAsResult(result)

    def _handleSaveAsResult(self, result) -> None:
        """A "save_as" tool may return either one file as-is (e.g. SurgMovPred's
        single predictions_outputs.xlsx) or several files bundled into a .zip
        by the server-side wrapper (since one HTTP response can only carry one
        blob). Only unpack a genuine `.zip` — do NOT sniff the file's bytes for
        a zip signature: .xlsx/.docx/.ods are themselves zip containers
        (OOXML), so that would "extract" a result spreadsheet into raw XML
        parts instead of keeping it as the file it is."""
        if slicer_io.is_extractable_archive(result.path):
            resultDir = os.path.dirname(result.path)
            slicer_io.unzip_folder(result.path, resultDir)
            os.remove(result.path)
            slicer.util.infoDisplay(_("Results saved to {path}").format(path=resultDir))
        else:
            slicer.util.infoDisplay(_("Result saved to {path}").format(path=result.path))

    # ------------------------------------------------------------------
    # Apply / cancel
    # ------------------------------------------------------------------

    def _checkCanApply(self, *_args) -> None:
        arguments = (self._schema or {}).get("arguments", {})
        canApply = self._inputReady() and formgen.all_required_filled(self._argWidgets, arguments)
        if self.RESULT_KIND == "save_as":
            canApply = canApply and bool(self._outputFolderWidget and self._outputFolderWidget.currentPath)
        self.applyButton.enabled = canApply

    def _inputReady(self) -> bool:
        for arg_name, mode in self.FILE_INPUTS.items():
            widget = self._inputWidgets.get(arg_name)
            if mode == "volume_node":
                if widget is None or widget.currentNode() is None:
                    return False
            elif not (widget and widget.currentPath):
                return False
        return True

    def onApplyButton(self) -> None:
        self._workspace = slicer_io.TempWorkspace()
        self._workspace.__enter__()

        try:
            files = self.prepareInputFiles(self._workspace)
            args = self.collectArgs()
        except Exception as exc:
            self._workspace.__exit__(None, None, None)
            self._workspace = None
            slicer.util.errorDisplay(str(exc))
            return

        outputDir = self._outputFolderWidget.currentPath if self._outputFolderWidget else self._workspace.path

        self.applyButton.setVisible(False)
        self.cancelButton.setVisible(True)

        def task(progress_cb):
            return self.client.run(
                self.TOOL_NAME,
                args=args,
                files=files,
                output_dir=outputDir,
                progress_cb=progress_cb,
            )

        self._job = BackgroundJob(
            task, on_success=self._onJobSuccess, on_error=self._onJobError, on_progress=self._onJobProgress
        )
        self._job.start()

    def onCancelButton(self) -> None:
        if self._job:
            self._job.cancel()
        self._teardownJob()
        slicer.util.showStatusMessage(_("Cancelled."), 3000)

    def _onJobSuccess(self, result) -> None:
        self._teardownJob()
        with slicer.util.tryWithErrorDisplay(_("Failed to handle the tool result."), waitCursor=False):
            self.handleResult(result)

    def _onJobError(self, exc) -> None:
        self._teardownJob()
        slicer.util.errorDisplay(str(exc))

    def _onJobProgress(self, message) -> None:
        slicer.util.showStatusMessage(message)

    def _teardownJob(self) -> None:
        self.applyButton.setVisible(True)
        self.cancelButton.setVisible(False)
        self._job = None
        if self._workspace:
            self._workspace.__exit__(None, None, None)
            self._workspace = None
        self._checkCanApply()

    # ------------------------------------------------------------------
    # Server status banner
    # ------------------------------------------------------------------

    def _refreshServerStatus(self) -> None:
        def task(_progress_cb):
            return self.client.health()

        job = BackgroundJob(task, on_success=self._onStatusChecked, on_error=lambda _exc: self._onStatusChecked(False))
        job.start()

    def _onStatusChecked(self, ok: bool) -> None:
        if self._statusBadge:
            design.update_status_badge(self._statusBadge, ok)

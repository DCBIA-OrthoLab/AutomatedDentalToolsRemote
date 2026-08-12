"""BatchDentalSeg — teeth and jaw structures on dental CT/CBCT, computed on the
tool server.

Replaces the local `BATCHDENTALSEG` module (a 2940-line Qt widget driving
nnUNet inside Slicer's own interpreter, with a queue table, a RAM watchdog, a
process killer and a runtime model download from GitHub). None of that is here:
the queue is a folder argument, the memory is the server's, and the models are
staged server-side and picked by name. The old module is left in the tree but
is no longer wired into the build — see CMakeLists.txt and ARCHITECTURE.md.

Two halves make up the panel, and the split is the point:

* **The standard server panel**, generated from `GET /tools/BatchDentalSeg`:
  the input row (one scan, a whole folder, an open volume, or a cohort the
  server already hosts), the model dropdown filled from
  `GET /tools/BatchDentalSeg/data`, `separate_segments`, `prediction_ID`, the
  output folder, Apply/Cancel, the server status badge. Not one line of it is
  written here — a model added server-side, or a new argument, shows up with
  no client release.
* **What DentalSegmentator's own interface gave a clinician**, ported: the
  model-scope line under the dropdown, segments that come back *named and
  coloured* instead of as grey `Segment_1..n`, and a segment editor with the
  Show-3D surface smoothing slider to review and touch up the result without
  leaving the module.

**Naming the segments is the server's job, not this file's.** The returned
volume is a label map, and `BatchDentalSeg_report.json` publishes the `labels`
table of the model that actually ran — which is the only thing that says what
its integers mean, since the four models do not label the same things (
NasoMaxillaDentSeg separates the maxilla, which shifts every later value, and
UniversalLab labels 52 teeth individually). So no structure list lives in this
client; only the colours do. See BatchDentalSegLib/results.py.

**Not offered here, because the tool does not produce them**: the STL/OBJ/glTF
/VTK mesh exports of the local module. The server port returns segmentations
only; surfaces are the obvious next server-side addition, and the moment the
tool grows the argument, it appears in this panel by itself.
"""

import logging
import os

import ctk
import qt
import slicer
from slicer.i18n import tr as _
from slicer.ScriptedLoadableModule import ScriptedLoadableModule

from BatchDentalSegLib import results
from ServerToolsCoreLib import design, formgen, slicer_io
from ServerToolsCoreLib.base_widget import ServerToolWidgetBase

logger = logging.getLogger("BatchDentalSeg")

# Loading a segmentation node per scan is instant for a handful and minutes of
# frozen UI for a cohort. Past this count the user is asked rather than made to
# wait for something they may not have wanted.
_CONFIRM_LOAD_ABOVE = 12

# Building closed surfaces for every segment is what "Show 3D" costs, and a
# UniversalLab run has 55 of them. Switched on automatically only for a result
# small enough that it is quick; above it the button is right there, unpressed.
_AUTO_SHOW_3D_UP_TO = 8


class BatchDentalSeg(ScriptedLoadableModule):
    """Uses ScriptedLoadableModule base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = _("BatchDentalSeg")
        self.parent.categories = ["Automated Dental Tools"]
        self.parent.dependencies = ["ServerToolsCore"]
        self.parent.contributors = [
            "Enzo Tulissi (UoM)",
            "Gauthier DOT (AP-HP)",
            "Laurent GAJNY (ENSAM)",
            "Roman FENIOUX (KITWARE SAS)",
            "Thibault PELLETIER (KITWARE SAS)",
            "Lucia Cevidanes (UoM)",
            "Juan Carlos Prieto (UoNC)",
        ]
        self.parent.helpText = _("""
        Fully automatic segmentation of teeth and jaw structures on dental CT and CBCT scans,
        with the DentalSegmentator family of nnU-Net models, computed remotely by the Automated
        Dental Tools server. Give it one scan or a whole folder, pick a model, and the
        segmentations come back named and coloured, with a report saying what each label value
        means and which scans (if any) could not be read.
        See more information in <a href="https://github.com/DCBIA-OrthoLab/SlicerAutomatedDentalTools">documentation</a>.
        """)
        self.parent.acknowledgementText = _("""
        This module was originally developed for the
        <a href="https://orthodontie-ffo.org/">Fédération Française d'Orthodontie</a>
        (FFO) for the analysis of dento-maxillo-facial data.
        """)


class BatchDentalSegWidget(ServerToolWidgetBase):
    """Thin GUI: HTTP, async, form generation, styling and lifecycle all live in
    ServerToolsCoreLib. See ARCHITECTURE.md.

    No FILE_INPUTS override: the schema types `input` as
    ("volume_or_zip_file", "folder"), so the schema-driven rule already gives it
    one path field with a File and a Folder browse button — a single scan or a
    whole cohort, zipped before upload. No RESULT_KIND either: `output_kind` is
    "files", which can only mean "save the archive".
    """

    TOOL_NAME = "BatchDentalSeg"

    def __init__(self, parent=None):
        ServerToolWidgetBase.__init__(self, parent)
        self.loadResultsCheckBox = None
        self._modelScopeLabel = None
        self._reviewBox = None
        self._segmentationSelector = None
        self._segmentEditorWidget = None
        self._segmentEditorNode = None
        self._show3DButton = None
        self._smoothingSlider = None

    # ------------------------------------------------------------------
    # Panel
    # ------------------------------------------------------------------

    def configureFields(self) -> None:
        """Touch up the generated form, once per build.

        Runs on every rebuild (a server that was down at setup() time coming
        back rebuilds the whole schema-driven half), which is why the model
        scope row is added here and not in addExtraWidgets: a widget parented
        to the previous form would go with it.
        """
        field = self._argWidgets.get("prediction_ID")
        if field is not None:
            # A placeholder rather than a pre-filled value: an empty optional
            # field is dropped from the request (collectArgs), so the default
            # stays written down once, server-side.
            field.setPlaceholderText("Seg")

        self._addModelScopeRow()

    def _addModelScopeRow(self) -> None:
        """The local module's "Model Scope:" line, under the model dropdown.

        Its text is the server's own `description` for the `model` argument,
        shown on screen instead of only as a tooltip — which is what the row
        was for: knowing what a model labels *before* running it. It does not
        change with the selection, because the schema publishes one description
        for the argument and not one per hosted bundle; the exact table of the
        model that ran is in the run report, and the end-of-run summary shows
        it. Publishing a description per bundle would be a (small) server-side
        addition, and this row would then follow the dropdown with no change
        here beyond reading it.
        """
        spec = self._schemaArgument("model")
        description = (spec.get("description") or "").strip()
        layout = self._sectionLayouts.get(formgen.section_of(spec))
        if not description or layout is None:
            return
        # The label is this module's own chrome, so it is translated; the text
        # beside it is the server's and is not, being absent from this module's
        # translation catalog. Same rule as every other row (formgen.build).
        self._modelScopeLabel = design.hint_label(description)
        layout.addRow(design.section_title(_("Model scope")), self._modelScopeLabel)

    def addExtraWidgets(self, layout) -> None:
        self.loadResultsCheckBox = qt.QCheckBox(_("Load the segmentations into the scene when done"))
        self.loadResultsCheckBox.setChecked(True)
        layout.addWidget(self.loadResultsCheckBox)
        self._buildReviewSection(layout)

    def _buildReviewSection(self, layout) -> None:
        """The half of the local module's interface that is not a form: look at
        the segmentation that came back, and fix it if it needs fixing.

        Collapsed on open — before a run there is nothing in it — and expanded
        automatically once a result has been loaded. Built here rather than in
        the schema-driven half because nothing about it comes from the schema,
        and addExtraWidgets runs once, so a rebuild cannot lose the editor
        (with whatever the user was in the middle of doing to a segment).
        """
        self._reviewBox = ctk.ctkCollapsibleButton()
        self._reviewBox.text = _("Segmentation review")
        self._reviewBox.collapsed = True
        form = qt.QFormLayout(self._reviewBox)

        self._segmentationSelector = slicer.qMRMLNodeComboBox()
        self._segmentationSelector.nodeTypes = ["vtkMRMLSegmentationNode"]
        self._segmentationSelector.addEnabled = False
        self._segmentationSelector.removeEnabled = True
        self._segmentationSelector.renameEnabled = True
        self._segmentationSelector.noneEnabled = True
        self._segmentationSelector.showHidden = False
        self._segmentationSelector.setMRMLScene(slicer.mrmlScene)
        self._segmentationSelector.connect(
            "currentNodeChanged(vtkMRMLNode*)", self._onReviewNodeChanged
        )
        form.addRow(design.section_title(_("Segmentation")), self._segmentationSelector)

        self._segmentEditorWidget = slicer.qMRMLSegmentEditorWidget()
        self._segmentEditorWidget.setMRMLScene(slicer.mrmlScene)
        # Our own selector above drives it; the source volume selector stays
        # visible on purpose, unlike the local module's — the scan a remote run
        # was made from may not be in the scene at all, so the user has to be
        # able to say which volume to edit against.
        self._segmentEditorWidget.setSegmentationNodeSelectorVisible(False)
        form.addRow(self._segmentEditorWidget)

        self._wireSurfaceSmoothing(form)
        layout.addWidget(self._reviewBox)

    def _wireSurfaceSmoothing(self, form) -> None:
        """Mirror the smoothing slider buried inside the Show-3D button.

        The local module surfaced it as a top-level row, because the smoothing
        factor is what makes a voxelised jaw look like a jaw. Guarded: it lives
        in a child widget of Slicer's own segment editor, and a version that
        renames it must cost the slider, not the module.
        """
        try:
            self._show3DButton = slicer.util.findChild(self._segmentEditorWidget, "Show3DButton")
            inner = self._show3DButton.findChild("ctkSliderWidget")
        except Exception as exc:  # noqa: BLE001 - a missing child must not break the panel
            logger.warning("Surface smoothing slider unavailable: %s", exc)
            self._show3DButton = None
            return
        if inner is None:
            return

        self._smoothingSlider = ctk.ctkSliderWidget()
        self._smoothingSlider.decimals = 2
        self._smoothingSlider.maximum = 1
        self._smoothingSlider.singleStep = 0.1
        self._smoothingSlider.value = inner.value
        # Rebuilding every closed surface on each intermediate value of a drag
        # is seconds of work per step on a full-mouth segmentation.
        self._smoothingSlider.tracking = False
        self._smoothingSlider.valueChanged.connect(inner.setValue)
        form.addRow(design.section_title(_("Surface smoothing")), self._smoothingSlider)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def cleanup(self) -> None:
        self._removeSegmentEditorNode()
        ServerToolWidgetBase.cleanup(self)

    def onSceneEndClose(self, caller, event) -> None:
        ServerToolWidgetBase.onSceneEndClose(self, caller, event)
        # The closing scene took the editor's parameter node with it; a new one
        # is created on the next selection.
        self._segmentEditorNode = None

    def _removeSegmentEditorNode(self) -> None:
        if self._segmentEditorNode is not None and slicer.mrmlScene.IsNodePresent(
            self._segmentEditorNode
        ):
            slicer.mrmlScene.RemoveNode(self._segmentEditorNode)
        self._segmentEditorNode = None

    def _ensureSegmentEditorNode(self):
        """The editor's parameter node, created on demand and re-created after a
        scene close (which removes it) rather than at setup()."""
        if self._segmentEditorNode is None or not slicer.mrmlScene.IsNodePresent(
            self._segmentEditorNode
        ):
            self._segmentEditorNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentEditorNode")
            self._segmentEditorWidget.setMRMLSegmentEditorNode(self._segmentEditorNode)
        return self._segmentEditorNode

    # ------------------------------------------------------------------
    # Result
    # ------------------------------------------------------------------

    def handleResult(self, result) -> None:
        """Unpack the archive, load and name what came back, and report what did
        not.

        Overriding rather than extending the base "save_as" handling: its info
        dialog would pop before the report has been read, and the report is
        what turns a label volume into named anatomy — and a partial run into
        something other than scans that silently went missing.
        """
        resultDir = os.path.dirname(result.path)
        if slicer_io.is_extractable_archive(result.path):
            # Unpacking runs on the main thread and label volumes expand ~100x,
            # so say so before starting rather than looking frozen.
            self._showPhase(_("Extracting results..."))
            slicer.app.processEvents()
            try:
                slicer_io.unzip_folder(result.path, resultDir)
            finally:
                self._hideProgress()
            os.remove(result.path)

        report = results.read_report(resultDir)
        paths = results.find_segmentations(resultDir, (report or {}).get("prediction_ID") or "")
        loaded = self._loadSegmentations(paths, results.label_names(report))

        slicer.util.infoDisplay(self._summarize(resultDir, report, len(paths), loaded))

    def _loadSegmentations(self, paths: list, labelNames: dict) -> int:
        """Load the returned label volumes as segmentations; return how many
        made it. One unreadable file is logged and skipped rather than costing
        the user the other thirty-nine."""
        if not paths or not (self.loadResultsCheckBox and self.loadResultsCheckBox.isChecked()):
            return 0

        if len(paths) > _CONFIRM_LOAD_ABOVE and not slicer.util.confirmYesNoDisplay(
            _("This run produced {count} segmentations. Load them all into the scene?").format(
                count=len(paths)
            )
        ):
            return 0

        loaded = 0
        lastNode = None
        for path in paths:
            try:
                node = slicer.util.loadSegmentation(path)
            except Exception as exc:  # noqa: BLE001 - one bad file must not lose the rest
                logger.warning("Could not load %s: %s", path, exc)
                continue
            self._nameSegments(node, labelNames)
            lastNode = node
            loaded += 1

        if lastNode is not None:
            self._showInReview(lastNode)
        return loaded

    def _nameSegments(self, node, labelNames: dict) -> None:
        """Give each segment the name the model's own label table says it has,
        and a colour to match.

        Without this a returned segmentation opens as `Segment_1..n` in Slicer's
        default palette, and which structure is which is a lookup in a JSON
        file. The mapping goes through the label VALUE, never the segment's
        position: a structure absent from a scan leaves a gap, and everything
        after it would otherwise be named as the structure before it.
        """
        if not labelNames or node is None:
            return
        segmentation = node.GetSegmentation()
        if node.GetDisplayNode() is None:
            node.CreateDefaultDisplayNodes()
        displayNode = node.GetDisplayNode()

        for index in range(segmentation.GetNumberOfSegments()):
            segmentId = segmentation.GetNthSegmentID(index)
            segment = segmentation.GetSegment(segmentId)
            if segment is None:
                continue
            value = results.segment_label_value(segmentId, index, self._declaredLabel(segment))
            name = labelNames.get(value)
            if not name:
                # A value the report does not describe: leave Slicer's own name
                # rather than invent one. Visible as unnamed, which is honest.
                continue
            segment.SetName(name)
            segment.SetColor(*results.color_for(name, value))
            if displayNode is not None:
                displayNode.SetSegmentOpacity3D(segmentId, results.opacity_for(name))

    @staticmethod
    def _declaredLabel(segment):
        """What the segment says its label value is, when the Slicer version is
        recent enough to record it. None otherwise — results.segment_label_value
        then falls back to the id."""
        getter = getattr(segment, "GetLabelValue", None)
        if getter is None:
            return None
        try:
            return getter()
        except Exception:  # noqa: BLE001 - an older vtkSegment simply has no value
            return None

    def _showInReview(self, node) -> None:
        """Open the review box on the segmentation that was just loaded."""
        if self._segmentationSelector is None:
            return
        if self._reviewBox is not None:
            self._reviewBox.collapsed = False
        self._segmentationSelector.setCurrentNode(node)

    def _onReviewNodeChanged(self, node=None) -> None:
        if self._segmentEditorWidget is None:
            return
        if node is None or not slicer.mrmlScene.IsNodePresent(node):
            return

        self._ensureSegmentEditorNode()
        if node.GetDisplayNode() is None:
            node.CreateDefaultDisplayNodes()
        node.SetDisplayVisibility(True)
        self._segmentEditorWidget.setSegmentationNode(node)

        volumeNode = self._inputVolumeNode()
        if volumeNode is not None and slicer.mrmlScene.IsNodePresent(volumeNode):
            node.SetReferenceImageGeometryParameterFromVolumeNode(volumeNode)
            self._segmentEditorWidget.setSourceVolumeNode(volumeNode)

        segmentCount = node.GetSegmentation().GetNumberOfSegments()
        if self._show3DButton is not None and segmentCount <= _AUTO_SHOW_3D_UP_TO:
            self._show3DButton.setChecked(True)
            slicer.util.resetThreeDViews()

    def _inputVolumeNode(self):
        """The scan this run was made from, when it was picked from the scene.

        The only case where the client knows: a scan uploaded from disk or
        named on the server never enters the MRML scene, and the editor then
        works against whatever source volume the user selects in it.
        """
        widget = self._inputWidgets.get("input")
        reader = getattr(widget, "volume_name", None)
        name = reader() if reader else ""
        return self._sceneVolumes.get(name) if name else None

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def _summarize(self, resultDir: str, report, produced: int, loaded: int) -> str:
        """The end-of-run message, built around what did NOT work.

        The successes are in the scene and on disk; a scan the server could not
        read exists only in the report, and a patient silently missing from a
        cohort of forty reads as a bug in the tool.
        """
        lines = []

        if report:
            summary = report.get("summary") or _("finished")
            duration = report.get("duration_seconds")
            first = _("BatchDentalSeg: {summary}.").format(summary=summary)
            if duration:
                first += " " + _("Server time: {seconds}s.").format(seconds=duration)
            lines.append(first)

            model = report.get("model")
            if model:
                description = report.get("model_description")
                lines.append(
                    _("Model: {model}").format(model=model)
                    + (f" — {description}" if description else "")
                )

            names = list((report.get("labels") or {}).keys())
            if names:
                shown = ", ".join(names[:8]) + (", ..." if len(names) > 8 else "")
                lines.append(
                    _("{count} segment(s) labelled: {names}").format(count=len(names), names=shown)
                )

            failures = results.failed_scans(report)
            if failures:
                lines.append("")
                lines.append(_("Scans that failed (the data, not the model):"))
                lines.extend(f"  {name}: {error}" for name, error in failures)
        else:
            lines.append(
                _("BatchDentalSeg finished. {produced} segmentation(s) produced.").format(
                    produced=produced
                )
            )
            lines.append(_("No run report was found in the results."))

        lines.append("")
        if loaded:
            lines.append(
                _("{loaded} segmentation(s) loaded into the scene.").format(loaded=loaded)
            )
        lines.append(_("Results saved to {path}").format(path=resultDir))
        return "\n".join(lines)

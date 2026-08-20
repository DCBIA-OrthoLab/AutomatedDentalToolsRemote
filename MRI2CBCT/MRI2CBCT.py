"""MRI2CBCT - MRI-to-CBCT registration, computed on the tool server.

Replaces the former local module (a Slicer widget driving six CLI modules, an
nnUNet condyle model downloaded into Documents, and a pip install that pinned
pydicom 2.2.2 and dicom2nifti 2.3.0 into Slicer's own environment). Nothing is
computed in Slicer any more: the panel is generated from the server's
`GET /tools` entry. MRI2CBCT_utils/ is left in the tree but is no longer wired
to this module.

Two things about MRI2CBCT's schema are worth knowing when reading this file:

* **`step` is what the six tabs became, and one call runs one step.** That is
  the tool's contract, not a client decision: the pipeline is Orient, Resample,
  Approximate, a crop, then Register, and a clinician is meant to look at each
  result before starting the next. Twenty-two of the twenty-three arguments
  carry a `visible_when` naming the steps that read them, so the panel shows
  five fields or eight rather than all of them.
* **The normalisation table became eight numbers.** Upstream's panel has a
  2x4 grid of spin boxes packed into one string; the schema publishes eight
  labelled integers, and the server's own tool packs them back. There is
  nothing to build here.
"""

import glob
import json
import logging
import os

import qt
import slicer
from slicer.i18n import tr as _
from slicer.ScriptedLoadableModule import ScriptedLoadableModule

from ServerToolsCoreLib import slicer_io
from ServerToolsCoreLib.base_widget import ServerToolWidgetBase

logger = logging.getLogger("MRI2CBCT")


class MRI2CBCT(ScriptedLoadableModule):
    """Uses ScriptedLoadableModule base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = _("MRI2CBCT")
        self.parent.categories = ["Automated Dental Tools"]
        self.parent.dependencies = ["ServerToolsCore"]
        self.parent.contributors = [
            "Alexandre Buisson (UoM)",
            "Lucia Cevidanes (UoM)",
            "Juan Carlos Prieto (UoNC)",
        ]
        self.parent.helpText = _("""
        Brings a TMJ MRI into its CBCT's space, on the Automated Dental Tools server.
        The pipeline runs one step at a time - orient the MRI, resample both modalities,
        approximate, crop to the joint, then register - so that each result can be looked
        at before the next step starts.
        See more information in <a href="https://github.com/DCBIA-OrthoLab/SlicerAutomatedDentalTools">documentation</a>.
        """)
        self.parent.acknowledgementText = _("""
        This module was supported by NIDCR R01 024450.
        """)


class MRI2CBCTWidget(ServerToolWidgetBase):
    """Thin GUI: HTTP, async, form generation, styling and lifecycle all live
    in ServerToolsCoreLib. See ARCHITECTURE.md."""

    TOOL_NAME = "MRI2CBCT"

    # No FILE_INPUTS. Every input is a packaged tool's `path`, which the client
    # already gives a picker taking a file or a folder
    # (client.accepts_folder). Each step here works on folders and says so in
    # its description; a single file is taken with its folder rather than
    # refused, so naming a mode would only restate the schema.
    #
    # No RESULT_KIND: output_kind "files" is whatever the chosen step wrote,
    # bundled into one .zip and unpacked into the output folder the user picks.
    #
    # No TEST_DATA: upstream ships no test-file button for this module, and
    # there is no published MRI/CBCT pair to point at.

    # A resampled cohort legitimately returns two folders of volumes. Twelve is
    # the number AREG and GreedyReg use for the same kind of output.
    MAX_RESULTS_TO_LOAD = 12

    # Pattern -> how to load it. Every step here writes volumes; the elastix
    # transform (`*_reg_transform.tfm`) is deliberately absent, because loading
    # a transform into the scene applies nothing by itself and the registered
    # volume beside it is already the answer.
    _LOADABLE = (
        ("*.nii.gz", "volume"),
        ("*.nii", "volume"),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loadResultsCheckBox = None

    # ------------------------------------------------------------------
    # Panel
    # ------------------------------------------------------------------

    def addExtraWidgets(self, layout) -> None:
        self._loadResultsCheckBox = qt.QCheckBox(
            _("Load the resulting volumes into the scene when done"))
        layout.addWidget(self._loadResultsCheckBox)

    # ------------------------------------------------------------------
    # Result
    # ------------------------------------------------------------------

    def handleResult(self, result) -> None:
        """Unpack the archive (base class), then say what the step wrote.

        Which step ran is worth restating: the panel is a pipeline the user
        walks through several times, and "MRI2CBCT finished" says nothing about
        where they are in it.
        """
        super().handleResult(result)

        outputDir = self._outputFolderWidget.currentPath if self._outputFolderWidget else None
        if not outputDir:
            return

        report = self._readRunReport(outputDir)
        if report:
            slicer.util.showStatusMessage(self._summarize(report), 8000)

        if self._loadResultsCheckBox and self._loadResultsCheckBox.isChecked():
            self._loadResults(outputDir)

    @staticmethod
    def _readRunReport(outputDir: str):
        """The run report, or None when there isn't a readable one.

        Never fatal: the results are already on disk and are what the user
        asked for. A missing report costs them the summary, not the run.
        """
        found = glob.glob(os.path.join(outputDir, "**", "MRI2CBCT_report.json"), recursive=True)
        if not found:
            return None
        try:
            with open(found[0], encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, ValueError) as exc:
            logger.warning("Could not read %s: %s", found[0], exc)
            return None

    @staticmethod
    def _summarize(report: dict) -> str:
        written = report.get("written") or {}
        return _("MRI2CBCT finished step '{step}': {folders}.").format(
            step=report.get("step") or "?",
            folders=", ".join(sorted(written)) or _("no output folder"),
        )

    @classmethod
    def _findResults(cls, outputDir: str) -> list:
        """[(path, kind)] for every result with a loader."""
        return sorted(
            (path, kind)
            for pattern, kind in cls._LOADABLE
            for path in glob.glob(os.path.join(outputDir, "**", pattern), recursive=True)
        )

    def _loadResults(self, outputDir: str) -> None:
        found = self._findResults(outputDir)
        if not found:
            slicer.util.showStatusMessage(_("MRI2CBCT: no result file found to load."), 5000)
            return

        if len(found) > self.MAX_RESULTS_TO_LOAD:
            slicer.util.infoDisplay(
                _(
                    "{count} result files were produced - too many to load at once.\n"
                    "They are all saved in {path}."
                ).format(count=len(found), path=outputDir)
            )
            return

        failed = []
        for path, kind in found:
            try:
                slicer_io.load_result(path, kind)
            except Exception as exc:  # one bad file must not lose the others
                failed.append(f"{os.path.basename(path)}: {exc}")

        if failed:
            slicer.util.errorDisplay(
                _("Some results could not be loaded:\n{details}").format(
                    details="\n".join(failed))
            )

"""VISU -- look at what a tool produced, one case at a time.

Every other module in this extension asks the server to compute something.
This one computes nothing: it opens folders that are already on disk and puts
them on screen in the order a reader wants them, with the arrow keys to step
from one patient to the next.

**Why it is not "drag the folder into Slicer".** Dragging works and tells you
nothing about which file goes with which. A cohort of forty comes back as a
scan here, a mask two directories down under a name the tool invented, and a
landmark file whose stem matches nothing -- and the one arrangement that is
wrong renders exactly as well as the right one. `VISULib.index` decides the
pairing; this file is the panel over it.

**The one thing it must never do is lie about the frame.** ASO's landmarks
carry its recentring and its ICP rotation, so they belong to the scan ASO
WROTE; ALI writes no scan at all, so its landmarks belong to the one the
caller sent. Draw either on the other and the picture renders without an error
and is wrong by a rotation -- which is precisely the mistake a reviewer opened
this panel to catch. So a view names the scan its overlays are drawn on, and
says whether that was read off the folder or assumed.
"""

import logging
import os
import shutil
import tempfile
import threading

import ctk
import qt
import slicer
from slicer.i18n import tr as _
from slicer.ScriptedLoadableModule import ScriptedLoadableModule, ScriptedLoadableModuleWidget

from ServerToolsCoreLib import design, formgen, get_client, slicer_io, testfile_entries
from ServerToolsCoreLib.worker import BackgroundJob
from VISULib import index

logger = logging.getLogger("VISU")

_SETTINGS_GROUP = "VISU"
_KEY_FOLDER = f"{_SETTINGS_GROUP}/Folder"

# One folder in, and the index carries one source label for everything under
# it. Two fields were a worse question: a reader has one folder in front of
# them, and whether it holds the acquisition, a run's output or both is
# something the folder answers rather than something to be declared. An
# overlay with no anchor in its own directory falls back to a scan from this
# source, which is what puts ALI's landmarks on the scan beside them.
SOURCE = "folder"

# Read ahead by one, in a daemon thread, so pressing the arrow does not also
# pay for the disk. It warms the page cache and touches no MRML node: loading
# one is main-thread work whatever we do here, and a 130 MB CBCT that is
# already in memory loads in a fraction of the time it takes off a disk or a
# network share. Bounded, because a cohort folder can hold gigabytes.
_PREFETCH_BUDGET_MB = 400
_PREFETCH_CHUNK = 1 << 20


class VISU(ScriptedLoadableModule):
    """Uses ScriptedLoadableModule base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = _("VISU")
        self.parent.categories = ["Automated Dental Tools"]
        self.parent.dependencies = ["ServerToolsCore"]
        self.parent.contributors = ["Automated Dental Tools team"]
        self.parent.helpText = _("""
        Step through what a tool produced, one patient at a time. Point it at the folder the
        scans came from and, if you have one, the folder a run wrote, and it pairs them: the
        scan, the masks, the surfaces and the landmarks of one patient are shown together, and
        the arrow keys move to the next.
        <br><br>
        <b>Read the line that says what the landmarks are drawn on.</b> Some tools write their
        points against a scan they oriented rather than the one you sent; the two look alike and
        only one of them is right. The panel names the scan it used and whether it found it
        beside the points or had to assume.
        """)
        self.parent.acknowledgementText = ""


class SceneLoader:
    """Everything that touches the MRML scene, kept in one object.

    Two reasons it is not just three calls inline. The panel must own what it
    put in the scene and nothing else -- a clinician's own data is in there too
    -- so every node created here is remembered and only these are removed.
    And keeping it behind one small object is what lets the panel's navigation
    be exercised without a running Slicer.
    """

    def __init__(self):
        self._owned = []

    def clear(self) -> None:
        for node in self._owned:
            try:
                slicer.mrmlScene.RemoveNode(node)
            except Exception as exc:  # noqa: BLE001 - a stale node must not wedge the panel
                logger.warning("Could not remove a node VISU loaded: %s", exc)
        self._owned = []

    def load(self, artifact):
        """Open one artifact and keep the node, or None if it would not open."""
        try:
            node = slicer_io.load_result(artifact.path, artifact.kind)
        except Exception as exc:  # noqa: BLE001 - one unreadable file is not the case
            logger.warning("Could not open %s: %s", artifact.name, exc)
            return None
        if node is None:
            return None
        node.SetName(artifact.name)
        self._owned.append(node)
        if artifact.kind == index.MARKUPS:
            self._unlock(node)
        return node

    @staticmethod
    def _unlock(node) -> None:
        """Let the points be dragged.

        ALI writes every control point with `"locked": true` -- the node itself
        is unlocked, each point is not -- so a landmark loaded as it comes
        refuses to move and the view looks broken rather than read-only. The
        file keeps its own flags; only the node in this scene is changed.
        """
        try:
            node.SetLocked(False)
            for point in range(node.GetNumberOfControlPoints()):
                node.SetNthControlPointLocked(point, False)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not unlock the landmarks: %s", exc)

    @staticmethod
    def display(anchor_node, label_node) -> None:
        try:
            slicer.util.setSliceViewerLayers(
                background=anchor_node, label=label_node, fit=True
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not fit the slice views: %s", exc)


def prefetch(paths) -> None:
    """Warm the page cache for the next case, in the background."""
    def run():
        budget = _PREFETCH_BUDGET_MB * 1024 * 1024
        for path in paths:
            if budget <= 0 or not os.path.isfile(path):
                continue
            try:
                with open(path, "rb") as handle:
                    while budget > 0 and handle.read(_PREFETCH_CHUNK):
                        budget -= _PREFETCH_CHUNK
            except OSError:
                # A file that cannot be read now will report itself when the
                # reader steps onto it. Nothing here is worth a message.
                return

    threading.Thread(target=run, daemon=True).start()


def hosted_choices(found) -> tuple:
    """`(entries, {label: (tool, name, kind)})` for what the server hosts.

    One entry per distinct FILE, however many tool names offer it.
    `deployment.toml` points several tool names at one bundle folder -- ALI,
    ALI_CBCT and ALI_IOS share theirs, and the four AREG names share another
    -- so asking every tool returns the same file up to four times. Measured
    against this deployment: **61 entries for 34 distinct files**, and 8
    distinct files on disk behind those, the bundles being hardlinked.

    The tool is named in the label only when it has to be: two files that
    genuinely differ and happen to share a name. Otherwise the name is the
    name, which is what a reader is looking for.

    `found` is `[(tool, name, kind, size), ...]`, and files are the same when
    all three of name, kind and size match -- the most a listing can compare
    without fetching. Two different files agreeing on all three would merge;
    the one that would be lost is reachable under the other's tool.
    """
    groups = {}
    for tool, name, kind, size in found:
        groups.setdefault((name, kind, size), []).append(tool)
    times_named = {}
    for name, _kind, _size in groups:
        times_named[name] = times_named.get(name, 0) + 1

    entries, offered = [], {}
    for (name, kind, size), tools in groups.items():
        tool = sorted(tools)[0]
        label = name if times_named[name] == 1 else "{} / {}".format(tool, name)
        offered[label] = (tool, name, kind)
        entries.append({"name": label, "kind": kind, "size": size})
    return sorted(entries, key=lambda entry: entry["name"]), offered


class VISUWidget(ScriptedLoadableModuleWidget):

    def __init__(self, parent=None):
        ScriptedLoadableModuleWidget.__init__(self, parent)
        self.cases = []
        self.views = []
        self.position = 0
        self.scene = SceneLoader()
        # Filling a combo fires its own currentIndexChanged, which would
        # re-enter the refresh that is filling it. A flag rather than
        # `blockSignals`, because what has to be suppressed is this panel's
        # reaction and not the widget's signal.
        self._filling = False
        # True between opening the module and the reader's first action.
        # Opening a module must not put somebody's cohort in their scene, so a
        # remembered folder is INDEXED and not shown; the first press of an
        # arrow shows what is already selected rather than moving off it.
        self._waiting = False
        # Set only while `_restore` is driving the input, so `onIndex` can
        # tell a folder the reader just chose -- which is an action, and shows
        # at once -- from one the panel remembered, which must not.
        self._restoring = False
        # {what the dropdown shows: (tool, the server's own name, kind)}. The
        # entries are labelled with their tool because this panel is not one:
        # it borrows every tool's test data, and two tools may host a file of
        # the same name.
        self._hosted = {}
        # Where the last fetched test file was unpacked, removed when the next
        # one lands. A cohort is hundreds of megabytes and a viewer is opened
        # many times in a sitting.
        self._staging = ""

    # -- building the panel ------------------------------------------------

    def setup(self) -> None:
        ScriptedLoadableModuleWidget.setup(self)
        # A root of our own, and `design.apply` is the reason for it: the
        # stylesheet goes down a whole widget tree, and `self.parent` also
        # holds Slicer's own Reload & Test box. Styling that would repaint a
        # part of the application this module does not own.
        self.uiWidget = qt.QWidget()
        self.layout.addWidget(self.uiWidget)
        self.panel = qt.QVBoxLayout(self.uiWidget)
        self._buildInput()
        self._buildCase()
        self.panel.addStretch(1)
        self._buildNavigation()
        design.apply(self.uiWidget)
        self._restore()
        self._refresh()

    def _buildInput(self) -> None:
        box = ctk.ctkCollapsibleButton()
        box.text = _("Folder")
        self.panel.addWidget(box)
        form = qt.QFormLayout(box)

        # The same input row every tool panel uses, in folder-only mode: it
        # browses, it captions what was chosen, and it reports every change --
        # which a ctkPathLineEdit restricted to Dirs does not, its
        # currentPathChanged being swallowed for a folder.
        self.folderInput = formgen.FileOrFolderInput(modes=("folder",))
        self.folderInput.onPathChanged(self.onIndex)

        # The same composite every tool panel puts on a hosted argument: the
        # picker, plus a dropdown of the test data the server holds. Wrapping
        # it is all it takes -- picking an entry is an ACTION, the file is
        # fetched, and the row then holds an ordinary local path.
        self.sources = formgen.ServerFileInput(self.folderInput, hosted_downloads=True)
        # No scene dropdown: every other panel offers one so a volume already
        # open can be SENT to a tool. This panel has nothing to send, and it
        # is the thing that puts volumes in the scene in the first place.
        self.sources.setSceneSupported(False)
        self.sources.setHostedCallback(self.onTestFile)
        self.sources.container.toolTip = _(
            "A folder of scans, of results, or of both. Everything under it is "
            "indexed: a patient's scan, its masks, its surfaces and its landmarks "
            "are shown together."
        )
        form.addRow(_("Folder"), self.sources.container)

        self.countLabel = design.hint_label("")
        form.addRow("", self.countLabel)

    def _buildCase(self) -> None:
        box = ctk.ctkCollapsibleButton()
        box.text = _("Patient")
        self.panel.addWidget(box)
        outer = qt.QVBoxLayout(box)

        self.caseCombo = qt.QComboBox()
        self.caseCombo.toolTip = _("Jump to a patient")
        self.caseCombo.currentIndexChanged.connect(self.onPick)
        outer.addWidget(self.caseCombo)

        self.viewCombo = qt.QComboBox()
        self.viewCombo.toolTip = _(
            "A case can hold more than one picture: the scan you sent, and the one "
            "a tool oriented. They are not interchangeable."
        )
        self.viewCombo.currentIndexChanged.connect(self.onView)
        outer.addWidget(self.viewCombo)

        # The anti-lie line. Never folded into the combo above: what a reader
        # has to notice is not which view is selected but what the points are
        # being drawn against, and whether that was found or assumed.
        self.frameLabel = design.warning_label("")
        outer.addWidget(self.frameLabel)

        self.contentsLabel = design.hint_label("")
        self.contentsLabel.setWordWrap(True)
        outer.addWidget(self.contentsLabel)

    def _buildNavigation(self) -> None:
        """The two steppers, at the very bottom and with nothing between them.

        Below the stretch on purpose: this is the control a reader uses while
        looking at the SCAN, so it wants a fixed place at the edge of the
        panel rather than a position that moves with how much a case has to
        say about itself. Nothing between them either -- a target you reach
        for without looking must not have a drop-down beside it.
        """
        # Which of how many, beside the control that changes it. The panel
        # said it in the Folder box, three sections away from the arrows -- so
        # the one number a reader wants while stepping was the one furthest
        # from where they were looking.
        self.positionLabel = design.section_title("")
        self.panel.addWidget(self.positionLabel)

        row = qt.QHBoxLayout()
        row.setSpacing(design.SPACING_SM)

        self.previousButton = design.nav_button("◀")
        self.previousButton.setShortcut(qt.QKeySequence(qt.Qt.Key_Left))
        self.previousButton.toolTip = _("Previous case (Left arrow)")
        self.previousButton.connect("clicked()", self.onPrevious)
        row.addWidget(self.previousButton, 1)

        self.nextButton = design.nav_button("▶")
        self.nextButton.setShortcut(qt.QKeySequence(qt.Qt.Key_Right))
        self.nextButton.toolTip = _("Next case (Right arrow)")
        self.nextButton.connect("clicked()", self.onNext)
        row.addWidget(self.nextButton, 1)

        self.panel.addLayout(row)

    # -- settings ----------------------------------------------------------

    def _restore(self) -> None:
        remembered = qt.QSettings().value(_KEY_FOLDER, "") or ""
        if not remembered:
            return
        # Setting the path notifies, which indexes. `_waiting` is what keeps
        # that from also LOADING: the panel opens knowing what the folder
        # holds and with the scene untouched.
        self._restoring = True
        try:
            self.folderInput.setCurrentPath(remembered)
        finally:
            self._restoring = False

    def _remember(self) -> None:
        qt.QSettings().setValue(_KEY_FOLDER, self.folderInput.currentPath)

    # -- actions -----------------------------------------------------------

    def onIndex(self) -> None:
        self._remember()
        self._waiting = self._restoring
        folder = self.folderInput.currentPath
        self.cases = index.build([(SOURCE, folder)] if folder else [])
        self.position = 0

        self._filling = True
        self.caseCombo.clear()
        for case in self.cases:
            self.caseCombo.addItem(case.label)
        self._filling = False

        if not self.cases:
            self._waiting = False
            self.countLabel.text = _("Nothing to show in that folder.")
        elif self._waiting:
            self.countLabel.text = _(
                "{count} patient(s). Press an arrow to show the first."
            ).format(count=len(self.cases))
        else:
            self.countLabel.text = _("{count} patient(s).").format(count=len(self.cases))
        self._refresh()

    def onPrevious(self) -> None:
        self._step(-1)

    def onNext(self) -> None:
        self._step(1)

    def _step(self, by: int) -> None:
        if not self.cases:
            return
        if self._waiting:
            # The first press shows what is selected. Moving instead would
            # skip case one of a cohort nobody has seen yet.
            self._waiting = False
            self.countLabel.text = _("{count} patient(s).").format(count=len(self.cases))
            self._refresh()
            return
        # Clamped rather than wrapped: a reader stepping through a cohort wants
        # to be told they are at the end, not silently returned to the start.
        self.position = max(0, min(len(self.cases) - 1, self.position + by))
        self._refresh()

    def onPick(self, position: int) -> None:
        if self._filling:
            return
        if not (0 <= position < len(self.cases)):
            return
        if position != self.position or self._waiting:
            self._waiting = False
            self.position = position
            self._refresh()

    def onView(self, _position: int) -> None:
        if not self._filling and not self._waiting:
            self._show()

    def _refresh(self) -> None:
        has = bool(self.cases)
        self.previousButton.enabled = has and self.position > 0
        self.nextButton.enabled = has and self.position < len(self.cases) - 1
        self.positionLabel.text = (
            _("{at} of {total} - {patient}").format(
                at=self.position + 1, total=len(self.cases),
                patient=self.cases[self.position].label,
            ) if has else ""
        )
        if not has:
            self.views = []
            self._filling = True
            self.viewCombo.clear()
            self._filling = False
            self.frameLabel.text = ""
            self.contentsLabel.text = ""
            self.scene.clear()
            return

        self._filling = True
        if self.caseCombo.currentIndex != self.position:
            self.caseCombo.setCurrentIndex(self.position)

        self.views = self.cases[self.position].views(acquisition=SOURCE)
        self.viewCombo.clear()
        for view in self.views:
            self.viewCombo.addItem(view.label)
        # Open on a view that has something ON it. A case can offer the scan
        # as sent and the scan a tool oriented, and only one of them carries
        # the points a reader came to look at.
        carrying = next(
            (n for n, view in enumerate(self.views) if view.overlays), 0
        )
        self.viewCombo.setCurrentIndex(carrying)
        self._filling = False
        if self._waiting:
            # Controls filled, nothing opened. Reading ahead waits too: it is
            # a courtesy for a reader who is stepping, not for one who has not
            # arrived.
            return
        self._show()
        self._prefetchNeighbour()

    def _show(self) -> None:
        self.scene.clear()
        if not self.views:
            return
        position = max(0, self.viewCombo.currentIndex)
        view = self.views[min(position, len(self.views) - 1)]

        anchor_node = self.scene.load(view.anchor) if view.anchor is not None else None
        label_node = None
        for overlay in view.overlays:
            node = self.scene.load(overlay)
            if overlay.kind == index.LABELMAP and label_node is None:
                label_node = node
        self.scene.display(anchor_node, label_node)

        if view.overlays:
            self.frameLabel.text = _("Overlays drawn on {scan} - {basis}").format(
                scan=view.label, basis=view.basis
            )
        else:
            self.frameLabel.text = ""
        self.contentsLabel.text = "\n".join(
            f"{artifact.kind}: {artifact.name}"
            for artifact in [view.anchor] + view.overlays
            if artifact is not None
        )

    def _prefetchNeighbour(self) -> None:
        following = self.position + 1
        if following >= len(self.cases):
            return
        prefetch([artifact.path for artifact in self.cases[following].artifacts])

    # -- leaving -----------------------------------------------------------

    def enter(self) -> None:
        # Re-read on every visit rather than once at build: the server may
        # have been down when the module was first opened, or bundles may have
        # been fetched since.
        self._refreshTestFiles()

    def _refreshTestFiles(self) -> None:
        """Offer every tool's hosted test files, fetched off the main thread."""
        def work(_progress):
            client = get_client()
            found = []
            for tool in sorted(client.list_tools() or {}):
                try:
                    data = client.list_tool_data(tool)
                except Exception as exc:  # noqa: BLE001 - one tool is not the list
                    logger.info("No hosted data for %s: %s", tool, exc)
                    continue
                for entry in testfile_entries(data):
                    found.append((tool, entry.get("name", ""),
                                  entry.get("kind"), entry.get("size")))
            return hosted_choices(found)

        def done(result):
            entries, offered = result
            self._hosted = offered
            self.sources.setChoices(entries)

        def failed(exc):
            # A server that is away costs the dropdown, not the panel: every
            # local folder still opens.
            logger.warning("Could not list the hosted test files: %s", exc)

        BackgroundJob(work, on_success=done, on_error=failed).start()

    def onTestFile(self, label: str) -> None:
        """Fetch the hosted entry the reader picked, then point the panel at it."""
        found = self._hosted.get(label)
        if found is None:
            logger.warning("No hosted test file called %r", label)
            return
        tool, name, kind = found

        def work(progress):
            return self._fetch(tool, name, kind, progress)

        def done(path):
            # Writing the local path resets the dropdown to its prompt and
            # notifies, which indexes and shows. The row then holds a local
            # folder like any other.
            formgen.set_local_path(self.sources, path)

        def failed(exc):
            slicer.util.errorDisplay(
                _("Could not fetch {name}: {error}").format(name=name, error=exc)
            )

        BackgroundJob(work, on_success=done, on_error=failed).start()

    def _fetch(self, tool: str, name: str, kind, progress) -> str:
        """Download one hosted entry and hand back a FOLDER to index.

        A hosted folder arrives as a zip the server built and is unpacked. A
        hosted single file is left as it is and its staging directory is
        returned instead -- a lone scan is a cohort of one, and the index
        walks directories.
        """
        if self._staging:
            shutil.rmtree(self._staging, ignore_errors=True)
        self._staging = tempfile.mkdtemp(prefix="VISU_")
        payload = os.path.join(self._staging, os.path.basename(name) or "testfile")
        get_client().download_testfile(tool, name, payload, progress)
        if kind != "folder":
            return self._staging
        unpacked = os.path.join(self._staging, "unpacked")
        slicer_io.unzip_folder(payload, unpacked)
        os.remove(payload)
        return unpacked

    def exit(self) -> None:
        # What this panel loaded is this panel's, and a clinician switching to
        # another module should not find forty nodes of somebody else's cohort
        # waiting in their scene.
        self.scene.clear()

    def cleanup(self) -> None:
        self.scene.clear()
        if self._staging:
            shutil.rmtree(self._staging, ignore_errors=True)
            self._staging = ""

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
from VISULib import edits, index

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

# The hosted datasets worth opening a VIEWER on, named rather than discovered.
#
# Asking every tool for its test files answered 61 entries -- 28 once the
# facades were folded together, since `deployment.toml` points several tool
# names at one bundle. That list is not too long by accident: it is every
# tool's REGRESSION FIXTURE, and most of it is a second timepoint, a transform
# or a spreadsheet that a viewer has nothing to do with. Size does not separate
# them either: 13 entries sit under 250 MB and 9 under 100.
#
# The rule a sample has to pass: AT LEAST THREE subjects, each one carrying
# both a scan and the landmarks placed on it. Three because the arrows are the
# point and two of anything demonstrates nothing; matched because the panel
# exists to show what belongs to one scan together, and a subject that comes
# up bare teaches the reader that the panel lost something.
#
# Counted with this module's own index against the bundles on disk. **Exactly
# one hosted folder passes.** Four carry landmarks at all and the other three
# hold one or two subjects -- the server's test data is each tool's regression
# fixture, assembled to prove a tool still runs rather than to be looked at.
# A folder of one's own is where a richer set lives; `VISULib.index` walks any
# directory, so pointing the field at it needs nothing from here.
# Each entry is (tool, the server's own name, what to call it here). The third
# is not decoration: the server's names are each tool's fixture names --
# `IOSCBCT_RegTestFiles`, `CBCT_SemiAuto_DCM` -- and they say which REGRESSION
# TEST the folder belongs to, not what is inside it. Renaming them on the
# server would break the tools that name them; naming them here costs nothing
# and is the only place that knows a viewer is asking.
SAMPLE_DATA = (
    ("AREG", "IOSCBCT_RegTestFiles", "3 subjects - CBCT and IOS, with landmarks"),
    # Staged by hand under `DATA/`, which is gitignored: three CBCT and three
    # IOS with the landmarks ALI placed on them, filed `CBCT/` beside
    # `Landmarks/`. A deployment that has not staged them offers them not at
    # all, which is what makes naming them here safe.
    ("ASO", "VISU_CBCT_3", "3 subjects - CBCT, with landmarks"),
    ("ASO", "VISU_IOS_3", "3 subjects - IOS, with landmarks"),
)

# What a CBCT is rendered with in 3D, and it is the tools' own choice: AMASSS
# and ASO both name CT-AAA for the scans they return. `slicer_io` applies the
# shift it measured on a scan out of this pipeline over the top.
VOLUME_RENDERING = "CT-AAA"

# How a mask is opened when it cannot be the slice label layer. Not one of
# `index`'s kinds: what the file IS stays a labelmap, this is only how it is
# shown.
SEGMENTATION = "segmentation"

# How big a landmark is drawn, in millimetres of the patient rather than in
# percent of the view. Small on purpose: a point is a POSITION, and a glyph
# wide enough to cover the structure under it hides the very thing a reader
# opened the panel to judge. 1 mm is about three voxels of a 0.3 mm CBCT.
LANDMARK_SIZE_MM = 1.0

# What an adjustment is called on disk, beside the scan it moves. Never the
# scan's own name: this file is the reader's, and the tool's output has to
# stay recognisable as the tool's.
ADJUSTMENT_SUFFIX = "_VISU_adjust.tfm"

# What the check boxes offer, in the order they are drawn, and the kind each
# one governs. Words a reader uses, not the loader's vocabulary: nobody calls
# a mask a labelmap out loud.
#
# A TRANSFORM is on the list although there is nothing to draw: loaded, it is
# a node the Transforms module can apply, which is the only way to see what a
# registration did. Off by default for the same reason -- it shows nothing on
# its own.
SHOWABLE = (
    # NOT "Scan". An intraoral scan is a scan, and calling the volume chip
    # that made a reader on an IOS case read the greyed chip as "the scan
    # will not display" -- while the mesh was on screen under `Surfaces`,
    # 122 023 points of it. Two words that cannot both mean one file.
    ("CBCT", index.VOLUME, True),
    ("Surfaces", index.MODEL, True),
    ("Masks", index.LABELMAP, True),
    ("Landmarks", index.MARKUPS, True),
    ("Transforms", index.TRANSFORM, False),
)
_KIND_OF_OPTION = {label: kind for label, kind, _on in SHOWABLE}

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

    def load(self, artifact, opened_as: str = ""):
        """Open one artifact and keep the node, or None if it would not open.

        `opened_as` overrides what the file IS with how it should be SHOWN.
        One mask is a label layer; three masks cannot be, a volume having one
        label layer and no more -- so several masks on one scan are opened as
        segmentations, which stack as coloured outlines on the slices and as
        surfaces in 3D. It costs a closed-surface representation the tool did
        not produce, and it is the only way to see a mandible and a maxilla at
        the same time.
        """
        try:
            node = slicer_io.load_result(artifact.path, opened_as or artifact.kind)
        except Exception as exc:  # noqa: BLE001 - one unreadable file is not the case
            logger.warning("Could not open %s: %s", artifact.name, exc)
            return None
        if node is None:
            return None
        node.SetName(artifact.name)
        self._owned.append(node)
        if artifact.kind == index.MARKUPS:
            self._unlock(node)
            self._make_visible(node)
        return node

    @staticmethod
    def _make_visible(node) -> None:
        """Give the points a size a reader can find on a CBCT.

        Slicer sizes a glyph as a PERCENTAGE of the view, default 2. On a
        230 mm field that is a speck, and on a mesh 60 mm across it is a
        boulder -- the same number cannot serve both. An absolute millimetre
        size does, and it is also what a clinician judges a landmark by.
        """
        display = node.GetDisplayNode()
        if display is None:
            return
        try:
            display.SetUseGlyphScale(False)
            display.SetGlyphSize(LANDMARK_SIZE_MM)
            display.SetVisibility(True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not size the landmarks: %s", exc)

    @staticmethod
    def jump_to(node) -> None:
        """Bring the slices to the first point.

        Measured on the hosted CBCT: the volume spans 230 mm and opens on its
        centre, while its landmarks sit up to 60 mm away -- so every one of
        them is off-slice and the reader presses the chip and sees nothing.
        """
        try:
            logic = slicer.modules.markups.logic()
            if node.GetNumberOfControlPoints():
                logic.JumpSlicesToNthPointInMarkup(node.GetID(), 0, True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not jump to a landmark: %s", exc)

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
    def draw_on_slices(node) -> None:
        """Show a surface's intersection with the slice planes.

        A model loaded beside a volume is in 3D and NOWHERE on the slices,
        which is where a reader checks whether a mesh sits on the anatomy it
        was registered to. Off by default in Slicer, so it is switched on.
        """
        try:
            display = node.GetDisplayNode()
            if display is not None:
                display.SetVisibility2D(True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not draw a surface on the slices: %s", exc)

    @staticmethod
    def display(anchor, anchor_node, label_node, reframe: bool = True) -> None:
        """Put the case on screen the way it is meant to be read.

        Loading a node is not showing it. A volume lands in the slice views
        and leaves the 3D view EMPTY -- which a clinician reads as "it did not
        work", and which is why every tool panel that returns a scan turns
        volume rendering on. A mesh is the opposite: it is only ever in 3D,
        and the three slice panes around it are dead space.

        So the layout follows the anchor rather than being left where the last
        module put it, and that is the whole difference between a viewer and a
        file loader.
        """
        try:
            if anchor is not None and anchor.kind == index.MODEL:
                if reframe:
                    SceneLoader._layout("SlicerLayoutOneUp3DView")
            else:
                if reframe:
                    SceneLoader._layout("SlicerLayoutFourUpView")
                slicer.util.setSliceViewerLayers(
                    background=anchor_node, label=label_node, fit=reframe
                )
                if anchor_node is not None and anchor.kind == index.VOLUME:
                    # The same preset the CBCT panels use, with the shift
                    # `slicer_io` measured on a scan out of this pipeline.
                    slicer_io.show_volume_rendering(anchor_node, VOLUME_RENDERING)
            if reframe:
                SceneLoader._frame3D()
        except Exception as exc:  # noqa: BLE001 - a view is never worth a failure
            logger.warning("Could not set the views up: %s", exc)

    @staticmethod
    def _layout(name: str) -> None:
        manager = slicer.app.layoutManager()
        node = getattr(slicer, "vtkMRMLLayoutNode", None)
        if manager is None or node is None or not hasattr(node, name):
            return
        manager.setLayout(getattr(node, name))

    @staticmethod
    def _frame3D() -> None:
        """Point the 3D view at what was just loaded.

        Without it the camera stays where the previous case left it, so
        stepping onto a mesh recorded in another part of the world shows an
        empty view that looks exactly like a failed load.
        """
        manager = slicer.app.layoutManager()
        if manager is None:
            return
        for number in range(manager.threeDViewCount):
            view = manager.threeDWidget(number).threeDView()
            view.resetFocalPoint()
            view.resetCamera()


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

    `found` is `[(tool, name, kind, size, called), ...]`, and files are the same
    when all three of name, kind and size match -- the most a listing can
    compare without fetching. Two different files agreeing on all three would
    merge; the one that would be lost is reachable under the other's tool.

    `called` is what to show instead of the server's own name, which says
    which regression test a folder belongs to rather than what is in it.
    """
    groups = {}
    for tool, name, kind, size, called in found:
        groups.setdefault((name, kind, size, called), []).append(tool)
    times_named = {}
    for name, _kind, _size, _called in groups:
        times_named[name] = times_named.get(name, 0) + 1

    entries, offered = [], {}
    for (name, kind, size, called), tools in groups.items():
        tool = sorted(tools)[0]
        label = called or (name if times_named[name] == 1
                           else "{} / {}".format(tool, name))
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
        self._anchorNode = None
        # [(artifact, node)] for the markups on screen: a save has to know
        # which file a node came from, and a node does not carry its path.
        self._points = []
        # The transform "Adjust position" put the anchor under, if any.
        self._adjustment = None

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
        self._buildModify()
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

        # `chips`, so the word IS the control: five short labels, and what is
        # on reads as filled against outlined at a glance rather than as five
        # small ticks to squint at.
        self.showGroup = formgen.MultiChoiceGroup(
            {label: on for label, _kind, on in SHOWABLE}, layout="chips",
        )
        formgen.connect_changed(self.showGroup, self.onShowChanged)
        outer.addWidget(design.section_title(_("Show")))
        outer.addWidget(self.showGroup.container)

        self.contentsLabel = design.hint_label("")
        self.contentsLabel.setWordWrap(True)
        outer.addWidget(self.contentsLabel)

    def _buildModify(self) -> None:
        """Changing what a tool produced, and writing it back.

        Its own section, and collapsed: reading is what this panel is for and
        editing is the exception, so the controls that can overwrite a file
        are not the ones a reader meets first.
        """
        box = ctk.ctkCollapsibleButton()
        box.text = _("Modify")
        box.collapsed = True
        self.panel.addWidget(box)
        column = qt.QVBoxLayout(box)

        column.addWidget(design.hint_label(_(
            "Drag a point in a slice or in 3D, then save. Only the points that "
            "actually moved are written, and everything else in the file is left "
            "exactly as the tool wrote it."
        )))
        self.saveLandmarksButton = design.primary_button(_("Save landmarks"))
        self.saveLandmarksButton.connect("clicked()", self.onSaveLandmarks)
        column.addWidget(self.saveLandmarksButton)

        column.addWidget(design.hint_label(_(
            "Adjust position puts the scan under a transform you can drag. "
            "Saving writes that displacement beside it as a .tfm; the scan "
            "itself is never rewritten."
        )))
        self.adjustButton = design.toggle_button(_("Adjust position"))
        self.adjustButton.connect("clicked()", self.onAdjust)
        column.addWidget(self.adjustButton)

        self.savePositionButton = design.secondary_button(_("Save position"))
        self.savePositionButton.connect("clicked()", self.onSavePosition)
        column.addWidget(self.savePositionButton)

        self.revertButton = design.secondary_button(_("Revert to what is on disk"))
        self.revertButton.connect("clicked()", self.onRevert)
        column.addWidget(self.revertButton)

        self.modifyLabel = design.hint_label("")
        self.modifyLabel.setWordWrap(True)
        column.addWidget(self.modifyLabel)

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

    def _offerWhatIsThere(self, case) -> None:
        """Grey the chips for what this patient does not have.

        Greyed rather than removed: a row that changes shape under the reader
        as they step is a row they have to re-read every time, and a chip that
        is there but off tells them this patient has no landmarks -- which is
        worth knowing. Their ticked state is left alone, so it comes back on
        the next patient that does have one.
        """
        present = {artifact.kind for artifact in case.artifacts}
        for label, kind, _on in SHOWABLE:
            box = self.showGroup.boxes.get(label)
            if box is not None:
                box.setEnabled(kind in present)

    def onShowChanged(self, *_args) -> None:
        # `reframe=False`: ticking a chip changes WHAT is on screen, never
        # where the reader is looking. Relaying out the panel and recentring
        # the camera under someone who has just scrolled to the tooth they
        # were checking is the one thing a viewer must not do.
        if not self._filling and not self._waiting:
            self._show(reframe=False)

    def wanted_kinds(self) -> set:
        """The kinds the check boxes are letting through."""
        return {_KIND_OF_OPTION[label]
                for label, on in self.showGroup.value().items() if on}

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

        self._offerWhatIsThere(self.cases[self.position])
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

    def _show(self, reframe: bool = True) -> None:
        self.scene.clear()
        if not self.views:
            return
        position = max(0, self.viewCombo.currentIndex)
        view = self.views[min(position, len(self.views) - 1)]

        self._points = []
        self._adjustment = None
        wanted = self.wanted_kinds()
        anchor = view.anchor if (view.anchor is not None
                                 and view.anchor.kind in wanted) else None
        overlays = [o for o in view.overlays if o.kind in wanted]

        anchor_node = self.scene.load(anchor) if anchor is not None else None
        self._anchorNode = anchor_node
        on_a_scan = anchor is not None and anchor.kind == index.VOLUME
        masks = [o for o in overlays if o.kind == index.LABELMAP]
        # One mask can be the volume's label layer. Several cannot, so they
        # all become segmentations rather than one being shown and the rest
        # loaded invisibly -- which reads as a viewer that lost them.
        stack = on_a_scan and len(masks) > 1

        label_node = None
        points = []
        if index.TRANSFORM in wanted:
            # Not an overlay: a transform has no geometry, so no view holds
            # one. Taken from the case, which is where it sits.
            for artifact in self.cases[self.position].of_kind(index.TRANSFORM):
                self.scene.load(artifact)
        for overlay in overlays:
            node = self.scene.load(overlay, opened_as=SEGMENTATION if
                                   (stack and overlay.kind == index.LABELMAP) else "")
            if node is None:
                continue
            if overlay.kind == index.LABELMAP and not stack and label_node is None:
                label_node = node
            if overlay.kind == index.MODEL and on_a_scan:
                self.scene.draw_on_slices(node)
            if overlay.kind == index.MARKUPS:
                points.append(node)
                self._points.append((overlay, node))
        self.scene.display(anchor, anchor_node, label_node, reframe=reframe)
        if reframe and points:
            # The slices open on the volume's centre and the points are not
            # there. One of them has to be, or the chip looks broken.
            self.scene.jump_to(points[0])

        if overlays:
            self.frameLabel.text = _("Overlays drawn on {scan} - {basis}").format(
                scan=view.label, basis=view.basis
            )
        else:
            # Said outright. A blank line here reads as a panel that failed to
            # draw something, and the reader goes looking for the bug: the
            # hosted `cohort_6` is six scans and no landmarks at all, which is
            # what it is rather than what went wrong.
            self.frameLabel.text = _("No landmarks or masks for this patient here.")
        self.contentsLabel.text = "\n".join(
            f"{artifact.kind}: {artifact.name}"
            for artifact in [anchor] + overlays
            if artifact is not None
        )

    def _prefetchNeighbour(self) -> None:
        following = self.position + 1
        if following >= len(self.cases):
            return
        prefetch([artifact.path for artifact in self.cases[following].artifacts])

    # -- modifying -----------------------------------------------------------

    def onSaveLandmarks(self) -> None:
        """Write every point that moved back into the file it came from."""
        moved, files = 0, 0
        for artifact, node in self._points:
            positions = {}
            try:
                for point in range(node.GetNumberOfControlPoints()):
                    place = [0.0, 0.0, 0.0]
                    node.GetNthControlPointPosition(point, place)
                    positions[node.GetNthControlPointLabel(point)] = place
            except Exception as exc:  # noqa: BLE001 - one file is not the save
                logger.warning("Could not read %s back: %s", artifact.name, exc)
                continue
            try:
                count = edits.save_markups(artifact.path, positions)
            except OSError as exc:
                slicer.util.errorDisplay(
                    _("Could not write {name}: {error}").format(
                        name=artifact.name, error=exc))
                continue
            moved += count
            files += 1 if count else 0

        if not self._points:
            self.modifyLabel.text = _("No landmarks on screen to save.")
        elif moved:
            self.modifyLabel.text = _(
                "{moved} point(s) written, in {files} file(s)."
            ).format(moved=moved, files=files)
        else:
            # Said, rather than left silent. "Saved" over an unchanged file is
            # a claim the reader cannot check.
            self.modifyLabel.text = _("Nothing moved, so nothing was written.")

    def onAdjust(self) -> None:
        """Put the anchor under a transform the reader can drag, or take it out."""
        if self._anchorNode is None:
            self.modifyLabel.text = _("Nothing on screen to move.")
            self.adjustButton.setChecked(False)
            return
        if not self.adjustButton.isChecked():
            self._detachAdjustment()
            self.modifyLabel.text = _("Position left as it was.")
            return
        try:
            self._adjustment = slicer.mrmlScene.AddNewNodeByClass(
                "vtkMRMLLinearTransformNode", "VISU adjustment")
            self._anchorNode.SetAndObserveTransformNodeID(self._adjustment.GetID())
            self._adjustment.CreateDefaultDisplayNodes()
            display = self._adjustment.GetDisplayNode()
            if display is not None:
                display.SetEditorVisibility(True)
            self.modifyLabel.text = _("Drag the handles, then Save position.")
        except Exception as exc:  # noqa: BLE001
            # Half a transform is worse than none: the scan would be under a
            # node with no handles, which moves nothing and cannot be undone
            # by unticking. Taken back off before reporting.
            logger.warning("Could not offer an adjustment: %s", exc)
            self._detachAdjustment()
            self.modifyLabel.text = _("This scan cannot be moved here.")
            self.adjustButton.setChecked(False)

    def onSavePosition(self) -> None:
        """Write the displacement beside the scan, as its own transform.

        Its own file rather than folded into whatever transform the tool
        wrote: composing two matrices is a claim about which order they apply
        in, and getting that backwards is silent. A `.tfm` beside the scan is
        something a reader can load, look at and delete.
        """
        if self._adjustment is None:
            self.modifyLabel.text = _("Nothing has been moved.")
            return
        anchor = self._currentAnchor()
        if anchor is None:
            return
        stem, _extension = index.split_extension(anchor.name)
        destination = os.path.join(os.path.dirname(anchor.path),
                                   f"{stem}{ADJUSTMENT_SUFFIX}")
        try:
            slicer.util.saveNode(self._adjustment, destination)
        except Exception as exc:  # noqa: BLE001
            slicer.util.errorDisplay(
                _("Could not write the transform: {error}").format(error=exc))
            return
        self.modifyLabel.text = _("Written: {name}").format(
            name=os.path.basename(destination))

    def onRevert(self) -> None:
        """Throw away every unsaved change by reloading from disk."""
        self._detachAdjustment()
        self.adjustButton.setChecked(False)
        self._show(reframe=False)
        self.modifyLabel.text = _("Reloaded from disk.")

    def _currentAnchor(self):
        if not self.views:
            return None
        view = self.views[min(max(0, self.viewCombo.currentIndex),
                              len(self.views) - 1)]
        return view.anchor

    def _detachAdjustment(self) -> None:
        if self._adjustment is None:
            return
        try:
            if self._anchorNode is not None:
                self._anchorNode.SetAndObserveTransformNodeID(None)
            slicer.mrmlScene.RemoveNode(self._adjustment)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not take the adjustment off: %s", exc)
        self._adjustment = None

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
            called = {(tool, name): label for tool, name, label in SAMPLE_DATA}
            wanted = {}
            for tool, name, _label in SAMPLE_DATA:
                wanted.setdefault(tool, set()).add(name)
            found = []
            for tool in sorted(wanted):
                try:
                    data = client.list_tool_data(tool)
                except Exception as exc:  # noqa: BLE001 - one tool is not the list
                    logger.info("No hosted data for %s: %s", tool, exc)
                    continue
                for entry in testfile_entries(data):
                    name = entry.get("name", "")
                    if name in wanted[tool]:
                        found.append((tool, name, entry.get("kind"),
                                      entry.get("size"), called[(tool, name)]))
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

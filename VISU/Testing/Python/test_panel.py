"""What the VISU panel does as a reader steps through a cohort.

    python3 -m unittest test_panel

Driven against `qt_stubs`, so no Slicer is launched. What is asserted is the
navigation and -- the reason this file exists -- that the scene holds exactly
what the selected view says it holds, and nothing from the case before it.
"""

import json
import os
import sys
import tempfile
import types
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", ".."))                       # VISU/
sys.path.insert(0, os.path.join(_HERE, "..", "..", ".."))                 # the extension
sys.path.insert(0, os.path.join(_HERE, "..", "..", "..",
                                "ServerToolsCore", "Testing", "Python"))  # qt_stubs
sys.path.insert(0, os.path.join(_HERE, "..", "..", "..", "ServerToolsCore"))

import qt_stubs  # noqa: E402


def _extend_stubs():
    class QSettings:
        store = {}

        def value(self, key, default=None):
            return QSettings.store.get(key, default)

        def setValue(self, key, value):
            QSettings.store[key] = value

    class QKeySequence:
        def __init__(self, *args):
            self.args = args

    def setShortcut(self, sequence):
        self._shortcut = sequence

    qt_stubs.QSettings = QSettings
    qt_stubs.QKeySequence = QKeySequence
    qt_stubs.QPushButton.setShortcut = setShortcut
    qt_stubs.Qt.Key_Left = 0x01000012
    qt_stubs.Qt.Key_Right = 0x01000014


_extend_stubs()
qt, ctk = qt_stubs.install()
qt.QSettings = qt_stubs.QSettings
qt.QKeySequence = qt_stubs.QKeySequence

slicer = sys.modules["slicer"]
slicer.app = types.SimpleNamespace(palette=lambda: qt.QPalette(),
                                   layoutManager=lambda: _LayoutManager())

# The scene, observable. A node is whatever `load_result` returned; the panel
# is only allowed to remove the ones it put there.
SCENE = []


class _Node:
    def __init__(self, path):
        self.path = path
        self.name = ""
        self.locked = True
        self.points = [True, True]
        self.under = None
        # What the file below holds, already in Slicer's RAS.
        self.positions = [[-1.0, -2.0, 3.0], [-4.0, -5.0, 6.0]]

    def SetName(self, name):
        self.name = name

    def SetLocked(self, locked):
        self.locked = bool(locked)

    def GetNumberOfControlPoints(self):
        return len(self.points)

    def SetNthControlPointLocked(self, point, locked):
        self.points[point] = bool(locked)

    def GetDisplayNode(self):
        return self.display

    def GetID(self):
        return self.path

    # -- what a save reads back -------------------------------------------
    def GetNthControlPointPosition(self, index, place):
        place[:] = list(self.positions[index])

    def GetNthControlPointLabel(self, index):
        return ["Ba", "S"][index]

    def SetAndObserveTransformNodeID(self, node_id):
        self.under = node_id

    def CreateDefaultDisplayNodes(self):
        self.display = _Display()


slicer.mrmlScene = types.SimpleNamespace(
    RemoveNode=lambda node: SCENE.remove(node) if node in SCENE else None)

# Where the slices were sent, and by whom. A viewer that opens on a slice
# holding none of the points looks broken.
JUMPS = []
slicer.modules = types.SimpleNamespace(markups=types.SimpleNamespace(
    logic=lambda: types.SimpleNamespace(
        JumpSlicesToNthPointInMarkup=lambda node_id, n, centred: JUMPS.append(node_id))))

# The views, observable. Loading a node is not showing it, and which layout a
# case lands in is the difference between a viewer and a file loader.
VIEWS = {"layout": None, "framed": 0, "rendered": []}


class _ThreeDView:
    @staticmethod
    def resetFocalPoint():
        VIEWS["framed"] += 1

    @staticmethod
    def resetCamera():
        pass


class _LayoutManager:
    threeDViewCount = 1

    @staticmethod
    def setLayout(layout):
        VIEWS["layout"] = layout

    @staticmethod
    def threeDWidget(_number):
        return types.SimpleNamespace(threeDView=lambda: _ThreeDView())


SAVED = []
slicer.mrmlScene.AddNewNodeByClass = lambda cls, name: _Node("transform:" + name)

slicer.vtkMRMLLayoutNode = types.SimpleNamespace(
    SlicerLayoutFourUpView="four-up", SlicerLayoutOneUp3DView="3d",
)
LAYERS = {}
class _Composite:
    """A slice composite node: what really decides what a slice pane shows."""

    def __init__(self):
        self.background = None
        self.label = None

    def SetBackgroundVolumeID(self, node_id):
        self.background = node_id

    def SetLabelVolumeID(self, node_id):
        self.label = node_id


COMPOSITES = [_Composite(), _Composite(), _Composite()]


def _nodes_by_class(name):
    if name == "vtkMRMLSliceCompositeNode":
        return COMPOSITES
    return [n for n in SCENE if getattr(n, "kind_class", None) == name]


slicer.util = types.SimpleNamespace(
    getNodesByClass=_nodes_by_class,
    resetSliceViews=lambda: LAYERS.update(fit=True),
    setSliceViewerLayers=lambda **kwargs: LAYERS.update(kwargs),
    showStatusMessage=lambda *_a, **_k: None,
    saveNode=lambda node, path: SAVED.append(path),
)


class _ScriptedLoadableModule:
    def __init__(self, parent):
        self.parent = parent


class _ScriptedLoadableModuleWidget:
    def __init__(self, parent=None):
        self.parent = parent
        self.layout = qt.QVBoxLayout()

    def setup(self):
        pass


slicer.ScriptedLoadableModule = types.ModuleType("slicer.ScriptedLoadableModule")
slicer.ScriptedLoadableModule.ScriptedLoadableModule = _ScriptedLoadableModule
slicer.ScriptedLoadableModule.ScriptedLoadableModuleWidget = _ScriptedLoadableModuleWidget
sys.modules["slicer.ScriptedLoadableModule"] = slicer.ScriptedLoadableModule
slicer.i18n = types.ModuleType("slicer.i18n")
slicer.i18n.tr = lambda text: text
sys.modules["slicer.i18n"] = slicer.i18n

import VISU  # noqa: E402
from VISULib import index  # noqa: E402


OPENED = []


class _Display:
    def __init__(self):
        self.on_slices = False
        self.absolute = None
        self.size = None
        self.visible = None

    def SetVisibility2D(self, visible):
        self.on_slices = bool(visible)

    def SetUseGlyphScale(self, relative):
        self.absolute = not relative

    def SetGlyphSize(self, size):
        self.size = size

    def SetVisibility(self, visible):
        self.visible = bool(visible)

    def SetEditorVisibility(self, visible):
        self.handles = bool(visible)


def _loader(path, kind):
    node = _Node(path)
    node.display = _Display()
    OPENED.append((os.path.basename(path), kind))
    SCENE.append(node)
    return node


VISU.slicer_io = types.SimpleNamespace(
    load_result=_loader,
    show_volume_rendering=lambda node, preset: VIEWS["rendered"].append((node.path, preset)),
)
# Reading ahead touches the disk in a thread and asserts nothing; the files
# here are one byte each and the thread would race the temp directory's
# removal.
VISU.prefetch = lambda _paths: None


class _SyncJob:
    """BackgroundJob, run on the calling thread so a test can assert outcomes."""

    def __init__(self, target, on_success=None, on_error=None, **_kwargs):
        self._target, self._ok, self._bad = target, on_success, on_error

    def start(self):
        try:
            result = self._target(lambda *_a, **_k: None)
        except Exception as exc:  # noqa: BLE001 - the panel's own error path
            if self._bad:
                self._bad(exc)
            return
        if self._ok:
            self._ok(result)


VISU.BackgroundJob = _SyncJob

DOWNLOADS = []


# What the sample list names here, so the tests read against a fixed set
# rather than against whatever SAMPLE_DATA happens to hold.
VISU.SAMPLE_DATA = (("ASO", "CBCT_SemiAuto", "two subjects with landmarks"),
                    ("ASO", "MG_test_scan.nii.gz", "one CBCT"))

ASKED = []


class _FakeClient:
    """One tool, hosting a folder, a single scan, and a fixture nobody wants."""

    fail = False

    def list_tool_data(self, tool):
        ASKED.append(tool)
        if _FakeClient.fail:
            raise RuntimeError("the server is away")
        return {
            "testfiles": ["CBCT_SemiAuto", "MG_test_scan.nii.gz", "cohort_6"],
            "entries": {"testfiles": [
                {"name": "CBCT_SemiAuto", "kind": "folder", "size": 12},
                {"name": "MG_test_scan.nii.gz", "kind": "file", "size": 9},
                {"name": "cohort_6", "kind": "folder", "size": 591000000},
            ]},
        }


def _download(tool, name, destination, _progress=None):
    DOWNLOADS.append((tool, name))
    with open(destination, "w", encoding="utf-8") as handle:
        handle.write("x")
    return destination


_FakeClient.download_testfile = staticmethod(_download)
VISU.get_client = lambda: _FakeClient()


def _unzip(_archive, into):
    # What the server sends for a hosted FOLDER: a cohort, here two scans.
    os.makedirs(into, exist_ok=True)
    for name in ("p1_scan.nii.gz", "p2_scan.nii.gz"):
        with open(os.path.join(into, name), "w", encoding="utf-8") as handle:
            handle.write("x")


VISU.slicer_io.unzip_folder = _unzip
slicer.util.errorDisplay = lambda text, **_k: ERRORS.append(text)
ERRORS = []


def tree(root, paths):
    for relative in paths:
        full = os.path.join(root, relative)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as handle:
            handle.write("x")


class PanelTest(unittest.TestCase):

    def setUp(self):
        del SCENE[:]
        LAYERS.clear()
        for composite in COMPOSITES:
            composite.background = composite.label = None
        VIEWS.update(layout=None, framed=0)
        del VIEWS["rendered"][:]
        del OPENED[:]
        del JUMPS[:]
        qt_stubs.QSettings.store.clear()
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        self.widget = VISU.VISUWidget()
        self.widget.setup()

    def open(self, paths, folder="scans"):
        # One folder in. Setting the path is what indexes -- the input reports
        # every change and the panel listens, so there is no Open button.
        tree(self.root.name, paths)
        self.widget.folderInput.setCurrentPath(os.path.join(self.root.name, folder))

    def test_the_arrows_walk_the_cohort_and_stop_at_both_ends(self):
        self.open([f"scans/p{n}_scan.nii.gz" for n in range(1, 4)])
        self.assertEqual(len(self.widget.cases), 3)
        self.assertFalse(self.widget.previousButton.enabled)
        self.widget.onNext()
        self.widget.onNext()
        self.assertEqual(self.widget.position, 2)
        self.assertFalse(self.widget.nextButton.enabled)
        self.widget.onNext()
        self.assertEqual(self.widget.position, 2, "stepping past the end wrapped")
        self.widget.onPrevious()
        self.assertEqual(self.widget.position, 1)

    def test_the_panel_says_which_patient_of_how_many(self):
        self.open([f"scans/p{n}_scan.nii.gz" for n in range(1, 4)])
        self.assertEqual(self.widget.positionLabel.text, "1 of 3 - p1")
        self.widget.onNext()
        self.assertEqual(self.widget.positionLabel.text, "2 of 3 - p2")
        self.assertEqual(
            [self.widget.caseCombo.itemText(n)
             for n in range(self.widget.caseCombo.count)],
            ["p1", "p2", "p3"],
        )

    def test_moving_on_removes_the_case_before_it(self):
        self.open([f"scans/p{n}_scan.nii.gz" for n in range(1, 4)])
        self.assertEqual(len(SCENE), 1)
        first = SCENE[0]
        self.widget.onNext()
        self.assertEqual(len(SCENE), 1)
        self.assertNotIn(first, SCENE, "the previous case stayed in the scene")

    def test_a_scan_fills_the_slices_and_the_3d_view(self):
        # A volume loads into the slice views and leaves 3D EMPTY, which reads
        # as a failed load. Every tool panel returning a scan turns rendering
        # on; so does this one.
        self.open(["scans/p1_scan.nii.gz"])
        self.assertEqual(VIEWS["layout"], "four-up")
        self.assertEqual(VIEWS["rendered"], [(COMPOSITES[0].background, "CT-AAA")])
        self.assertGreaterEqual(VIEWS["framed"], 1)

    def test_a_mesh_gets_the_3d_view_to_itself(self):
        # Three slice panes around a surface are dead space.
        self.open(["scans/arch.vtk"])
        self.assertEqual(VIEWS["layout"], "3d")
        self.assertEqual(VIEWS["rendered"], [], "a mesh has nothing to render")
        self.assertGreaterEqual(VIEWS["framed"], 1)

    def test_several_masks_on_one_scan_are_all_shown(self):
        # A volume has ONE label layer. Three masks as label layers means two
        # loaded invisibly, which reads as a viewer that lost them.
        self.open(["scans/p1_scan.nii.gz",
                   "scans/p1_Pred_MAND.nii.gz",
                   "scans/p1_Pred_MAX.nii.gz",
                   "scans/p1_Pred_CB.nii.gz"])
        opened = dict(OPENED)
        self.assertEqual(opened["p1_scan.nii.gz"], "volume")
        for mask in ("p1_Pred_MAND.nii.gz", "p1_Pred_MAX.nii.gz", "p1_Pred_CB.nii.gz"):
            self.assertEqual(opened[mask], "segmentation", mask)
        self.assertTrue(all(c.label is None for c in COMPOSITES),
                        "one mask was made the label layer")

    def test_a_single_mask_stays_the_label_layer(self):
        self.open(["scans/p1_scan.nii.gz", "scans/p1_Pred_MAND.nii.gz"])
        self.assertEqual(dict(OPENED)["p1_Pred_MAND.nii.gz"], "labelmap")
        self.assertTrue(all(c.label is not None for c in COMPOSITES))

    def test_a_mesh_on_a_scan_is_drawn_on_the_slices_too(self):
        # Where a reader checks whether a mesh sits on the anatomy it was
        # registered to. Off by default in Slicer.
        self.open(["scans/p1_scan.nii.gz", "scans/p1_Seg.vtk"])
        mesh = [n for n in SCENE if n.path.endswith(".vtk")]
        self.assertEqual(len(mesh), 1)
        self.assertTrue(mesh[0].display.on_slices)

    def test_unticking_a_kind_takes_it_off_the_screen(self):
        self.open(["scans/p1_scan.nii.gz", "scans/p1_scan_lm_Pred.mrk.json"])
        self.assertEqual(len(SCENE), 2)

        self.widget.showGroup.boxes["Landmarks"].setChecked(False)
        self.assertEqual([os.path.basename(n.path) for n in SCENE],
                         ["p1_scan.nii.gz"])

        self.widget.showGroup.boxes["Landmarks"].setChecked(True)
        self.assertEqual(len(SCENE), 2)

    def test_unticking_the_scan_leaves_the_landmarks(self):
        # Points on their own are what a reader wants when the scan is in the
        # way -- and the panel must not then claim they are drawn on it.
        self.open(["scans/p1_scan.nii.gz", "scans/p1_scan_lm_Pred.mrk.json"])
        self.widget.showGroup.boxes["CBCT"].setChecked(False)
        self.assertEqual([os.path.basename(n.path) for n in SCENE],
                         ["p1_scan_lm_Pred.mrk.json"])

    def test_transforms_are_off_until_asked_for(self):
        # Nothing to draw, so nothing is loaded -- but ticked, the node is
        # there for the Transforms module to apply.
        self.open(["scans/p1_scan.nii.gz", "scans/p1_scan_Or_transform.tfm"])
        self.assertEqual([os.path.basename(n.path) for n in SCENE],
                         ["p1_scan.nii.gz"])
        self.widget.showGroup.boxes["Transforms"].setChecked(True)
        self.assertIn("p1_scan_Or_transform.tfm",
                      [os.path.basename(n.path) for n in SCENE])

    def test_the_slices_go_to_a_landmark_when_a_patient_opens(self):
        # Measured on the hosted CBCT: the volume spans 230 mm, opens on its
        # centre, and its points sit up to 60 mm away -- so every one of them
        # is off-slice and the chip looks broken.
        self.open(["scans/p1_scan.nii.gz", "scans/p1_scan_lm_Pred.mrk.json"])
        self.assertEqual(len(JUMPS), 1)

    def test_the_file_decides_how_a_landmark_looks(self):
        # Three fields say the size -- glyphScale, glyphSize, useGlyphScale --
        # and they are the tool's to set. A panel that overrides them shows
        # something no other reader of the same file sees.
        self.open(["scans/p1_scan.nii.gz", "scans/p1_scan_lm_Pred.mrk.json"])
        points = [n for n in SCENE if n.path.endswith(".mrk.json")][0]
        self.assertIsNone(points.display.absolute, "the panel resized the points")
        self.assertIsNone(points.display.size)

    def test_a_ticked_chip_means_visible_whatever_the_kind(self):
        # A ticked chip that shows nothing is worse than no chip: the reader
        # believes they are looking at the landmarks and they are looking at
        # their absence.
        self.open(["scans/p1_scan.nii.gz", "scans/p1_scan_lm_Pred.mrk.json",
                   "scans/p1_scan_Seg.vtk"])
        for node in SCENE:
            self.assertTrue(node.display.visible,
                            f"{os.path.basename(node.path)} was loaded invisible")

    def test_a_file_that_says_do_not_draw_is_drawn_anyway(self):
        # `"visibility": false` builds the node and draws nothing. Both
        # original ALI CLIs wrote it and every fixture from before the fix
        # still carries it -- all four landmark files of the first hosted
        # sample do. A viewer cannot honour "do not draw".
        self.open(["scans/p1_scan.nii.gz", "scans/p1_scan_lm_Pred.mrk.json"])
        points = [n for n in SCENE if n.path.endswith(".mrk.json")][0]
        self.assertTrue(points.display.visible)

    def test_ticking_a_chip_does_not_move_the_reader(self):
        # The one thing a viewer must not do: relay out the panel and recentre
        # the camera under someone who has just scrolled to what they were
        # checking.
        self.open(["scans/p1_scan.nii.gz", "scans/p1_scan_lm_Pred.mrk.json"])
        for composite in COMPOSITES:
            composite.background = composite.label = None
        VIEWS.update(layout=None, framed=0)
        del JUMPS[:]
        LAYERS.clear()

        self.widget.showGroup.boxes["Landmarks"].setChecked(False)
        self.widget.showGroup.boxes["Landmarks"].setChecked(True)

        self.assertIsNone(VIEWS["layout"], "the layout was reset")
        self.assertEqual(VIEWS["framed"], 0, "the camera was recentred")
        self.assertEqual(JUMPS, [], "the slices moved")
        self.assertFalse(LAYERS.get("fit"), "the slices were refitted")
        self.assertTrue(all(c.background is not None for c in COMPOSITES),
                        "the scan left the slice views")
        # and the points are back on screen
        self.assertIn("p1_scan_lm_Pred.mrk.json",
                      [os.path.basename(n.path) for n in SCENE])

    def test_a_mesh_is_a_surface_and_never_the_cbct_chip(self):
        # An intraoral scan IS a scan, so a chip called "Scan" that governs
        # volumes read, on an IOS case, as "the scan will not display" --
        # while the mesh was on screen under another chip.
        self.open(["scans/Upper_new_9.vtk", "scans/Upper_new_9_Upper_O_Pred.mrk.json"])
        boxes = self.widget.showGroup.boxes
        self.assertFalse(boxes["CBCT"].isEnabled(), "there is no volume here")
        self.assertTrue(boxes["Surfaces"].isEnabled())
        self.assertIn("Upper_new_9.vtk",
                      [os.path.basename(n.path) for n in SCENE])

    def test_a_kind_this_patient_has_not_got_is_greyed(self):
        # Greyed rather than removed: a row that changes shape as the reader
        # steps is a row they re-read every time, and a chip present but off
        # says this patient has no landmarks -- which is worth knowing.
        self.open(["scans/p1_scan.nii.gz", "scans/p1_scan_lm_Pred.mrk.json",
                   "scans/p2_scan.nii.gz"])
        boxes = self.widget.showGroup.boxes
        self.assertTrue(boxes["CBCT"].isEnabled())
        self.assertTrue(boxes["Landmarks"].isEnabled())
        self.assertFalse(boxes["Surfaces"].isEnabled(), "p1 has no mesh")

        self.widget.onNext()          # p2: a scan and nothing else
        self.assertTrue(boxes["CBCT"].isEnabled())
        self.assertFalse(boxes["Landmarks"].isEnabled())

        self.widget.onPrevious()      # and it comes back
        self.assertTrue(boxes["Landmarks"].isEnabled())
        self.assertTrue(boxes["Landmarks"].isChecked(), "the tick was lost")

    def test_every_kind_has_a_box_and_they_start_the_way_they_mean_to(self):
        boxes = self.widget.showGroup.value()
        self.assertEqual(sorted(boxes),
                         ["CBCT", "Landmarks", "Masks", "Surfaces", "Transforms"])
        self.assertFalse(boxes["Transforms"], "a transform draws nothing")
        self.assertTrue(all(on for name, on in boxes.items() if name != "Transforms"))

    def test_a_patient_with_nothing_on_it_says_so(self):
        # `cohort_6` is six scans and no landmarks. A blank line there sends
        # the reader looking for a bug that is not one.
        self.open(["scans/p1_scan.nii.gz"])
        self.assertIn("No landmarks", self.widget.frameLabel.text)

    def test_saving_writes_only_the_point_that_moved(self):
        landmarks = os.path.join(self.root.name, "scans", "p1_scan_lm_Pred.mrk.json")
        os.makedirs(os.path.dirname(landmarks), exist_ok=True)
        with open(landmarks, "w", encoding="utf-8") as handle:
            json.dump({"markups": [{"coordinateSystem": "LPS", "controlPoints": [
                {"label": "Ba", "position": [1.0, 2.0, 3.0], "description": "predicted"},
                {"label": "S", "position": [4.0, 5.0, 6.0]},
            ]}]}, handle)
        self.open(["scans/p1_scan.nii.gz"])

        node = [n for n in SCENE if n.path.endswith(".mrk.json")][0]
        node.positions[0] = [-1.0, -2.0, 8.0]          # Ba dragged 5 mm in z
        self.widget.onSaveLandmarks()

        self.assertIn("1 point", self.widget.modifyLabel.text)
        with open(landmarks, encoding="utf-8") as handle:
            after = json.load(handle)["markups"][0]["controlPoints"]
        self.assertEqual(after[0]["position"], [1.0, 2.0, 8.0])
        self.assertEqual(after[1]["position"], [4.0, 5.0, 6.0])
        self.assertEqual(after[0]["description"], "predicted")

    def test_saving_an_untouched_case_says_so_rather_than_claiming_a_write(self):
        landmarks = os.path.join(self.root.name, "scans", "p1_scan_lm_Pred.mrk.json")
        os.makedirs(os.path.dirname(landmarks), exist_ok=True)
        with open(landmarks, "w", encoding="utf-8") as handle:
            json.dump({"markups": [{"coordinateSystem": "LPS", "controlPoints": [
                {"label": "Ba", "position": [1.0, 2.0, 3.0]},
                {"label": "S", "position": [4.0, 5.0, 6.0]},
            ]}]}, handle)
        self.open(["scans/p1_scan.nii.gz"])
        self.widget.onSaveLandmarks()
        self.assertIn("Nothing moved", self.widget.modifyLabel.text)

    def test_adjusting_puts_the_scan_under_a_transform_and_saves_it_beside(self):
        del SAVED[:]
        self.open(["scans/p1_scan.nii.gz"])
        self.widget.adjustButton.setChecked(True)
        self.widget.onAdjust()
        self.assertIsNotNone(self.widget._adjustment)
        self.assertIsNotNone(self.widget._anchorNode.under, "the scan was not moved")
        self.assertTrue(self.widget._adjustment.display.handles, "no handles to drag")
        self.assertIn("Drag the handles", self.widget.modifyLabel.text)

        self.widget.onSavePosition()
        self.assertEqual([os.path.basename(p) for p in SAVED],
                         ["p1_scan_VISU_adjust.tfm"])

    def test_an_adjustment_that_cannot_be_offered_is_taken_back_off(self):
        # Half a transform is worse than none: the scan sits under a node with
        # no handles, which moves nothing and unticking cannot undo.
        self.open(["scans/p1_scan.nii.gz"])
        broken = self.widget._anchorNode
        broken.CreateDefaultDisplayNodes = None      # the call will raise
        self.widget._anchorNode = broken
        original = slicer.mrmlScene.AddNewNodeByClass
        slicer.mrmlScene.AddNewNodeByClass = lambda cls, name: types.SimpleNamespace(
            GetID=lambda: "x", CreateDefaultDisplayNodes=lambda: 1 / 0)
        try:
            self.widget.adjustButton.setChecked(True)
            self.widget.onAdjust()
        finally:
            slicer.mrmlScene.AddNewNodeByClass = original
        self.assertIsNone(self.widget._adjustment)
        self.assertIsNone(self.widget._anchorNode.under)
        self.assertFalse(self.widget.adjustButton.isChecked())

    def test_reverting_takes_the_adjustment_off(self):
        self.open(["scans/p1_scan.nii.gz"])
        self.widget.adjustButton.setChecked(True)
        self.widget.onAdjust()
        self.widget.onRevert()
        self.assertIsNone(self.widget._adjustment)
        self.assertIn("Reloaded", self.widget.modifyLabel.text)

    def test_leaving_the_module_leaves_the_scene_alone(self):
        # Models, Volume Rendering and Segment Editor are where a reader goes
        # to work on what VISU just showed them. Emptying the scene on the way
        # out wiped it at the moment it became useful.
        self.open(["scans/p1_scan.nii.gz", "scans/p1_scan_lm_Pred.mrk.json"])
        self.assertEqual(len(SCENE), 2)
        self.widget.exit()
        self.assertEqual(len(SCENE), 2, "switching module emptied the scene")

    def test_the_module_going_away_does_empty_it(self):
        self.open(["scans/p1_scan.nii.gz"])
        self.widget.cleanup()
        self.assertEqual(SCENE, [])

    def test_stepping_still_never_accumulates(self):
        # The bound that replaces clearing on exit.
        self.open([f"scans/p{n}_scan.nii.gz" for n in range(1, 4)])
        for _ in range(2):
            self.widget.onNext()
        self.assertEqual(len(SCENE), 1)

    def test_landmarks_start_locked_and_unlock_point_by_point(self):
        # Locked at rest: a point nudged by a stray drag while scrolling is a
        # correction nobody made and nobody sees. ALI locks each POINT and
        # leaves the node unlocked, so both levels have to be set or the
        # points go on refusing to move.
        self.open(["scans/p1_scan.nii.gz", "scans/p1_scan_lm_Pred.mrk.json"])
        points = [node for node in SCENE if node.path.endswith(".mrk.json")][0]
        self.assertTrue(points.locked)
        self.assertEqual(points.points, [True, True])

        self.widget.lockButton.setChecked(True)
        self.widget.onLockToggled()
        self.assertFalse(points.locked)
        self.assertEqual(points.points, [False, False])
        self.assertIn("Unlocked", self.widget.lockButton.text)

    def test_the_lock_survives_stepping_to_the_next_patient(self):
        # Freshly loaded nodes carry the file's own flags; unlocking once
        # must not be undone by the next arrow.
        self.open(["scans/p1_scan.nii.gz", "scans/p1_scan_lm_Pred.mrk.json",
                   "scans/p2_scan.nii.gz", "scans/p2_scan_lm_Pred.mrk.json"])
        self.widget.lockButton.setChecked(True)
        self.widget.onLockToggled()
        self.widget.onNext()
        points = [node for node in SCENE if node.path.endswith(".mrk.json")][0]
        self.assertFalse(points.locked, "the next patient came back locked")

    def test_the_button_says_the_state_it_is_in(self):
        # A button reading "Unlock" while the points are already unlocked is
        # the classic way to get this wrong.
        self.assertIn("Locked", self.widget.lockButton.text)
        self.assertNotIn("Unlocked", self.widget.lockButton.text)

    def test_the_panel_says_which_scan_the_points_are_drawn_on(self):
        # What ASO actually writes: the oriented scan, its landmarks and its
        # transform, side by side in one directory.
        self.open(["scans/p1_scan.nii.gz",
                   "scans/p1_Or.nii.gz",
                   "scans/p1_lm_Or.mrk.json"])
        labels = [self.widget.viewCombo.itemText(n)
                  for n in range(self.widget.viewCombo.count)]
        self.assertIn("p1_Or.nii.gz", labels)
        self.assertIn("p1_scan.nii.gz", labels)
        # The view carrying the points is the oriented scan, and the line says so.
        oriented = labels.index("p1_Or.nii.gz")
        self.widget.viewCombo.setCurrentIndex(oriented)
        self.assertIn("p1_Or.nii.gz", self.widget.frameLabel.text)
        self.assertIn(index.BASIS_COLOCATED, self.widget.frameLabel.text)

    def test_a_folder_with_nothing_in_it_says_so_rather_than_breaking(self):
        os.makedirs(os.path.join(self.root.name, "scans"))
        self.widget.folderInput.setCurrentPath(os.path.join(self.root.name, "scans"))
        self.assertEqual(self.widget.cases, [])
        self.assertIn("Nothing", self.widget.countLabel.text)
        self.assertFalse(self.widget.nextButton.enabled)

    def test_two_stages_in_two_subfolders_are_two_cases(self):
        """The cost of asking for one folder, stated rather than hidden.

        With two fields, `scans/p1` and `out/p1` were one patient because each
        root was its own origin. With one, the tree IS the grouping -- which
        is right for a run's output, where a tool mirrors the input tree, and
        splits a parent folder holding an acquisition beside a result.
        """
        self.open(["scans/acquired/p1_scan.nii.gz", "scans/oriented/p1_Or.nii.gz"])
        self.assertEqual([case.key for case in self.widget.cases],
                         [os.path.join("acquired", "p1"),
                          os.path.join("oriented", "p1")])

    def test_opening_the_module_indexes_but_loads_nothing(self):
        """A module that opens must not put somebody's cohort in their scene."""
        self.open([f"scans/p{n}_scan.nii.gz" for n in range(1, 4)])
        del SCENE[:]

        second = VISU.VISUWidget()
        second.setup()
        self.assertEqual(second.folderInput.currentPath,
                         os.path.join(self.root.name, "scans"))
        self.assertEqual(len(second.cases), 3, "the folder was not indexed")
        self.assertEqual(SCENE, [], "opening the module loaded a case")
        self.assertIn("arrow", second.countLabel.text)

        # The first press shows case one rather than stepping past it.
        second.onNext()
        self.assertEqual(second.position, 0)
        self.assertEqual(len(SCENE), 1)
        self.assertNotIn("arrow", second.countLabel.text)
        second.onNext()
        self.assertEqual(second.position, 1)

    def test_choosing_a_folder_shows_its_first_case_at_once(self):
        # Choosing IS the action. Only a folder the panel remembered by itself
        # waits for a press.
        self.open(["scans/p1_scan.nii.gz"])
        self.assertEqual(len(SCENE), 1)
        self.assertNotIn("arrow", self.widget.countLabel.text)

    def test_picking_a_case_on_a_freshly_opened_panel_shows_it(self):
        self.open([f"scans/p{n}_scan.nii.gz" for n in range(1, 4)])
        del SCENE[:]
        second = VISU.VISUWidget()
        second.setup()
        self.assertEqual(SCENE, [])
        second.caseCombo.setCurrentIndex(2)
        self.assertEqual(second.position, 2)
        self.assertEqual(len(SCENE), 1)


class HostedChoicesTest(unittest.TestCase):
    """Turning what every tool answers into what a reader should see."""

    def test_one_file_offered_by_four_tool_names_is_one_entry(self):
        found = [(tool, "FullyAuto.zip", "folder", 99, "")
                 for tool in ("AREG", "AREG_CBCT", "AREG_IOS", "AREG_IOSCBCT")]
        entries, offered = VISU.hosted_choices(found)
        self.assertEqual([entry["name"] for entry in entries], ["FullyAuto.zip"])
        # Downloadable from the first name alphabetically; they are the same file.
        self.assertEqual(offered["FullyAuto.zip"], ("AREG", "FullyAuto.zip", "folder"))

    def test_two_different_files_of_one_name_keep_their_tool(self):
        entries, offered = VISU.hosted_choices([
            ("AMASSS", "scan.nii.gz", "file", 10, ""),
            ("CLIC", "scan.nii.gz", "file", 20, ""),
        ])
        self.assertEqual([entry["name"] for entry in entries],
                         ["AMASSS / scan.nii.gz", "CLIC / scan.nii.gz"])

    def test_entries_are_ordered_and_keep_what_a_picker_shows(self):
        entries, _ = VISU.hosted_choices([
            ("B", "second.vtk", "file", 2, ""), ("A", "first.nii.gz", "folder", 1, ""),
        ])
        self.assertEqual([entry["name"] for entry in entries],
                         ["first.nii.gz", "second.vtk"])
        self.assertEqual(entries[0]["kind"], "folder")
        self.assertEqual(entries[0]["size"], 1)


class TestFileTest(unittest.TestCase):
    """The hosted dropdown: the same one every tool panel has."""

    def setUp(self):
        del SCENE[:]
        del DOWNLOADS[:]
        del ERRORS[:]
        _FakeClient.fail = False
        qt_stubs.QSettings.store.clear()
        self.widget = VISU.VISUWidget()
        self.widget.setup()
        self.addCleanup(self.widget.cleanup)

    def labels(self):
        combo = self.widget.sources.combo
        return [combo.itemText(n) for n in range(combo.count)]

    def test_only_the_named_sample_data_is_offered(self):
        # A viewer wants a scan to look at, not every tool's regression
        # fixture. `cohort_6` is hosted, 591 MB, and not on the list.
        self.widget.enter()
        offered = self.labels()
        self.assertTrue(any("two subjects" in text for text in offered), offered)
        self.assertTrue(any("one CBCT" in text for text in offered))
        self.assertFalse(any("cohort_6" in text for text in offered), offered)

    def test_only_the_tools_that_hold_it_are_asked(self):
        # Eighteen tool names answered the old listing; the sample names two.
        del ASKED[:]
        self.widget.enter()
        self.assertEqual(ASKED, ["ASO"])

    def test_picking_a_hosted_folder_fetches_it_and_opens_it(self):
        self.widget.enter()
        self.widget.onTestFile("two subjects with landmarks")
        self.assertEqual(DOWNLOADS, [("ASO", "CBCT_SemiAuto")])
        self.assertEqual([case.key for case in self.widget.cases], ["p1", "p2"])
        self.assertEqual(len(SCENE), 1, "the first case was not shown")

    def test_a_hosted_single_scan_is_a_cohort_of_one(self):
        self.widget.enter()
        self.widget.onTestFile("one CBCT")
        self.assertEqual(DOWNLOADS, [("ASO", "MG_test_scan.nii.gz")])
        self.assertEqual([case.key for case in self.widget.cases], ["MG_test"])

    def test_the_previous_download_is_removed_when_the_next_lands(self):
        self.widget.enter()
        self.widget.onTestFile("two subjects with landmarks")
        first = self.widget._staging
        self.widget.onTestFile("one CBCT")
        self.assertFalse(os.path.exists(first), "a cohort was left in the temp dir")

    def test_a_server_that_is_away_costs_the_dropdown_and_not_the_panel(self):
        _FakeClient.fail = True
        self.widget.enter()
        self.assertEqual(self.widget._hosted, {})
        # Every local folder still opens.
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        tree(root.name, ["scans/p1_scan.nii.gz"])
        self.widget.folderInput.setCurrentPath(os.path.join(root.name, "scans"))
        self.assertEqual(len(self.widget.cases), 1)

    def test_an_entry_the_panel_does_not_know_downloads_nothing(self):
        self.widget.enter()
        self.widget.onTestFile("Nope / nothing.nii.gz")
        self.assertEqual(DOWNLOADS, [])


if __name__ == "__main__":
    unittest.main()

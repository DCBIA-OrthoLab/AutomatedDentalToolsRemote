"""What the VISU panel does as a reader steps through a cohort.

    python3 -m unittest test_panel

Driven against `qt_stubs`, so no Slicer is launched. What is asserted is the
navigation and -- the reason this file exists -- that the scene holds exactly
what the selected view says it holds, and nothing from the case before it.
"""

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
slicer.app = types.SimpleNamespace(palette=lambda: qt.QPalette())

# The scene, observable. A node is whatever `load_result` returned; the panel
# is only allowed to remove the ones it put there.
SCENE = []


class _Node:
    def __init__(self, path):
        self.path = path
        self.name = ""
        self.locked = True
        self.points = [True, True]

    def SetName(self, name):
        self.name = name

    def SetLocked(self, locked):
        self.locked = bool(locked)

    def GetNumberOfControlPoints(self):
        return len(self.points)

    def SetNthControlPointLocked(self, point, locked):
        self.points[point] = bool(locked)


slicer.mrmlScene = types.SimpleNamespace(RemoveNode=lambda node: SCENE.remove(node))
LAYERS = {}
slicer.util = types.SimpleNamespace(
    setSliceViewerLayers=lambda **kwargs: LAYERS.update(kwargs),
    showStatusMessage=lambda *_a, **_k: None,
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


def _loader(path, _kind):
    node = _Node(path)
    SCENE.append(node)
    return node


VISU.slicer_io = types.SimpleNamespace(load_result=_loader)
# Reading ahead touches the disk in a thread and asserts nothing; the files
# here are one byte each and the thread would race the temp directory's
# removal.
VISU.prefetch = lambda _paths: None


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
        qt_stubs.QSettings.store.clear()
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        self.widget = VISU.VISUWidget()
        self.widget.setup()

    def open(self, paths, results=()):
        tree(self.root.name, paths)
        self.widget.scansEdit.currentPath = os.path.join(self.root.name, "scans")
        if results:
            self.widget.resultsEdit.currentPath = os.path.join(self.root.name, "out")
        self.widget.onIndex()

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

    def test_moving_on_removes_the_case_before_it(self):
        self.open([f"scans/p{n}_scan.nii.gz" for n in range(1, 4)])
        self.assertEqual(len(SCENE), 1)
        first = SCENE[0]
        self.widget.onNext()
        self.assertEqual(len(SCENE), 1)
        self.assertNotIn(first, SCENE, "the previous case stayed in the scene")

    def test_leaving_the_module_empties_what_it_loaded(self):
        self.open(["scans/p1_scan.nii.gz"])
        self.assertEqual(len(SCENE), 1)
        self.widget.exit()
        self.assertEqual(SCENE, [])

    def test_landmarks_are_unlocked_point_by_point(self):
        # ALI writes every control point locked, so a file loaded as it comes
        # refuses to move.
        self.open(["scans/p1_scan.nii.gz", "scans/p1_scan_lm_Pred.mrk.json"])
        markups = [node for node in SCENE if node.path.endswith(".mrk.json")]
        self.assertEqual(len(markups), 1)
        self.assertFalse(markups[0].locked)
        self.assertEqual(markups[0].points, [False, False])

    def test_the_panel_says_which_scan_the_points_are_drawn_on(self):
        self.open(
            ["scans/p1_scan.nii.gz", "out/p1_Or.nii.gz", "out/p1_lm_Or.mrk.json"],
            results=True,
        )
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
        self.widget.scansEdit.currentPath = os.path.join(self.root.name, "scans")
        self.widget.onIndex()
        self.assertEqual(self.widget.cases, [])
        self.assertIn("Nothing", self.widget.countLabel.text)
        self.assertFalse(self.widget.nextButton.enabled)

    def test_the_folders_are_remembered(self):
        self.open(["scans/p1_scan.nii.gz"])
        second = VISU.VISUWidget()
        second.setup()
        self.assertEqual(second.scansEdit.currentPath,
                         os.path.join(self.root.name, "scans"))


if __name__ == "__main__":
    unittest.main()

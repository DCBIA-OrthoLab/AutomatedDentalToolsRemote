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
VISU.SAMPLE_DATA = (("ASO", "CBCT_SemiAuto"), ("ASO", "MG_test_scan.nii.gz"))

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
        found = [(tool, "FullyAuto.zip", "folder", 99)
                 for tool in ("AREG", "AREG_CBCT", "AREG_IOS", "AREG_IOSCBCT")]
        entries, offered = VISU.hosted_choices(found)
        self.assertEqual([entry["name"] for entry in entries], ["FullyAuto.zip"])
        # Downloadable from the first name alphabetically; they are the same file.
        self.assertEqual(offered["FullyAuto.zip"], ("AREG", "FullyAuto.zip", "folder"))

    def test_two_different_files_of_one_name_keep_their_tool(self):
        entries, offered = VISU.hosted_choices([
            ("AMASSS", "scan.nii.gz", "file", 10),
            ("CLIC", "scan.nii.gz", "file", 20),
        ])
        self.assertEqual([entry["name"] for entry in entries],
                         ["AMASSS / scan.nii.gz", "CLIC / scan.nii.gz"])

    def test_entries_are_ordered_and_keep_what_a_picker_shows(self):
        entries, _ = VISU.hosted_choices([
            ("B", "second.vtk", "file", 2), ("A", "first.nii.gz", "folder", 1),
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
        self.assertTrue(any("CBCT_SemiAuto" in text for text in offered), offered)
        self.assertTrue(any("MG_test_scan.nii.gz" in text for text in offered))
        self.assertFalse(any("cohort_6" in text for text in offered), offered)

    def test_only_the_tools_that_hold_it_are_asked(self):
        # Eighteen tool names answered the old listing; the sample names two.
        del ASKED[:]
        self.widget.enter()
        self.assertEqual(ASKED, ["ASO"])

    def test_picking_a_hosted_folder_fetches_it_and_opens_it(self):
        self.widget.enter()
        self.widget.onTestFile("CBCT_SemiAuto")
        self.assertEqual(DOWNLOADS, [("ASO", "CBCT_SemiAuto")])
        self.assertEqual([case.key for case in self.widget.cases], ["p1", "p2"])
        self.assertEqual(len(SCENE), 1, "the first case was not shown")

    def test_a_hosted_single_scan_is_a_cohort_of_one(self):
        self.widget.enter()
        self.widget.onTestFile("MG_test_scan.nii.gz")
        self.assertEqual(DOWNLOADS, [("ASO", "MG_test_scan.nii.gz")])
        self.assertEqual([case.key for case in self.widget.cases], ["MG_test"])

    def test_the_previous_download_is_removed_when_the_next_lands(self):
        self.widget.enter()
        self.widget.onTestFile("CBCT_SemiAuto")
        first = self.widget._staging
        self.widget.onTestFile("MG_test_scan.nii.gz")
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

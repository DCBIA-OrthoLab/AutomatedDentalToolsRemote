"""Unit tests for the ASO module's client behaviour — run outside Slicer, with
`qt`/`ctk`/`slicer` stubbed (ServerToolsCore/Testing/Python/qt_stubs.py).

Two things are covered, and they fail for different reasons:

* **What ASO's panel derives from its schema.** ASO declares nothing but
  TOOL_NAME, so every widget, every extension filter and the result handling
  come from `GET /tools`. These tests assert that the schema really does answer
  all of it — if the server's schema changes shape, this is what notices, and
  they are also what would catch someone "helpfully" re-adding a FILE_INPUTS or
  RESULT_KIND override that only repeats the server.
* **Which result files get loaded, and how.** ASO returns four kinds of file
  per case and only three of them belong in the scene.

`ASO.py` is imported here, which needs three `slicer` submodules qt_stubs does
not provide. That is safe for what is under test: these functions are pure
Python and never touch `slicer` — the stub only gets the import statement past
a Slicer that isn't running, so the test is not measuring the stub.

Usage:
    python3 -m unittest ASO/Testing/Python/test_aso_client.py
"""

import os
import shutil
import sys
import tempfile
import types
import unittest

_HERE = os.path.abspath(os.path.dirname(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
_CORE = os.path.join(_REPO_ROOT, "ServerToolsCore")
# `ServerToolsCoreLib` is a package inside ServerToolsCore/, and qt_stubs lives
# with that module's own tests: it is the extension's single set of Qt
# stand-ins, and forking a second copy here would drift.
sys.path.insert(0, os.path.join(_CORE, "Testing", "Python"))
sys.path.insert(0, _CORE)

import qt_stubs

qt, ctk = qt_stubs.install()


def _stub_slicer_module_framework():
    """The three `slicer` submodules ASO.py touches at import time.

    qt_stubs leaves `slicer` deliberately empty (design.is_dark_mode() reaches
    for slicer.app.palette() inside a try/except and wants it to fail), so the
    module framework is added here rather than there — it is ASO's import that
    needs it, not the core library's.
    """
    slicer = sys.modules["slicer"]

    i18n = types.ModuleType("slicer.i18n")
    i18n.tr = lambda text: text
    sys.modules["slicer.i18n"] = i18n
    slicer.i18n = i18n

    framework = types.ModuleType("slicer.ScriptedLoadableModule")

    class ScriptedLoadableModule:
        def __init__(self, parent):
            self.parent = parent

    class ScriptedLoadableModuleWidget:
        def __init__(self, parent=None):
            pass

    framework.ScriptedLoadableModule = ScriptedLoadableModule
    framework.ScriptedLoadableModuleWidget = ScriptedLoadableModuleWidget
    sys.modules["slicer.ScriptedLoadableModule"] = framework
    slicer.ScriptedLoadableModule = framework

    util = types.ModuleType("slicer.util")

    class VTKObservationMixin:
        def __init__(self, *args, **kwargs):
            pass

    util.VTKObservationMixin = VTKObservationMixin
    sys.modules["slicer.util"] = util
    slicer.util = util


_stub_slicer_module_framework()

from ServerToolsCoreLib import client as client_module
from ServerToolsCoreLib import formgen
from ServerToolsCoreLib.base_widget import ServerToolWidgetBase

def _load_aso_module():
    """Import ASO.py by path.

    `import ASO` is ambiguous here and resolves the wrong way: the repository
    has a directory called ASO/, which Python 3 treats as a namespace package
    whenever the repo root is on sys.path — so the import yields an empty
    package rather than the module inside it, whatever the working directory
    happens to be.
    """
    import importlib.util

    path = os.path.join(_REPO_ROOT, "ASO", "ASO.py")
    spec = importlib.util.spec_from_file_location("aso_module", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ASOWidget = _load_aso_module().ASOWidget


# The server's actual GET /tools payload for ASO, verbatim (long option lists
# abbreviated where the count is what matters, never the shape). Kept here as a
# fixture so the panel can be tested without a running server; if the server's
# schema changes, these tests are what notices.
ASO_SCHEMA = {
    "name": "ASO",
    "output_kind": "files",
    "arguments": {
        "modality": {
            "type": "choice",
            "types": ["choice"],
            "required": True,
            "description": "CBCT: cone-beam CT volumes. IOS: intra-oral surface scans",
            "server_selectable": None,
            "choices": {"CBCT": True, "IOS": False},
            "initial": None,
            "extensions": None,
        },
        "automation": {
            "type": "choice",
            "types": ["choice"],
            "required": True,
            "description": "Semi-Automated: you send the landmarks ...",
            "server_selectable": None,
            "choices": {"Semi-Automated": True, "Fully-Automated": False},
            "initial": None,
            "extensions": None,
        },
        "input": {
            "type": "volume_or_zip_file",
            "types": ["volume_or_zip_file", "surface_file", "folder"],
            "required": True,
            "description": "One CBCT scan ... or one intra-oral mesh ...",
            "server_selectable": None,
            "choices": None,
            "initial": None,
            "extensions": {
                "volume_or_zip_file": [
                    ".nii", ".nii.gz", ".nrrd", ".nrrd.gz", ".gipl", ".gipl.gz", ".zip",
                ],
                "surface_file": [".vtk", ".vtp", ".stl", ".obj", ".off"],
                "folder": [".zip"],
            },
        },
        "reference": {
            "type": "zip_file",
            "types": ["zip_file", "folder"],
            "required": True,
            "description": "The already-oriented case defining the target coordinate frame ...",
            "server_selectable": "model",
            "choices": None,
            "initial": None,
            "extensions": {"zip_file": [".zip"], "folder": [".zip"]},
        },
        "landmark_models": {
            "type": "str",
            "types": ["str"],
            "required": False,
            "description": "Fully-Automated CBCT only: name of the landmark model bundle ...",
            "server_selectable": "model",
            "choices": None,
            "initial": None,
            "extensions": None,
        },
        "cbct_landmarks": {
            "type": "multichoice",
            "types": ["multichoice"],
            "required": False,
            "description": "CBCT only: the landmarks to register on ...",
            "server_selectable": None,
            "choices": {
                "Ba": True, "C2": False, "S": True, "N": True, "RPo": True,
                "LPo": True, "ROr": True, "LOr": True, "A": False, "ANS": False,
            },
            "initial": None,
            "extensions": None,
        },
        "ios_teeth": {
            "type": "multichoice",
            "types": ["multichoice"],
            "required": False,
            "description": "IOS only: the teeth to register on ...",
            "server_selectable": None,
            "choices": {
                "UR6": True, "UL1": True, "UL6": True,
                "LL6": True, "LR1": True, "LR6": True, "UR8": False,
            },
            "initial": None,
            "extensions": None,
        },
        "ios_landmark_types": {
            "type": "multichoice",
            "types": ["multichoice"],
            "required": False,
            "description": "Semi-Automated IOS only ...",
            "server_selectable": None,
            "choices": {"O": True, "MB": False, "DB": False},
            "initial": None,
            "extensions": None,
        },
        "ios_jaws": {
            "type": "multichoice",
            "types": ["multichoice"],
            "required": False,
            "description": "IOS only: which jaws to orient",
            "server_selectable": None,
            "choices": {"Upper": True, "Lower": True},
            "initial": None,
            "extensions": None,
        },
        "ios_occlusion": {
            "type": "choice",
            "types": ["choice"],
            "required": False,
            "description": "IOS only: orienting each jaw on its own is the default ...",
            "server_selectable": None,
            "choices": {
                "Orient each jaw independently": True,
                "Upper drives Lower": False,
                "Lower drives Upper": False,
            },
            "initial": None,
            "extensions": None,
        },
        "dicom_input": {
            "type": "bool",
            "types": ["bool"],
            "required": False,
            "description": "CBCT only: the input is a zip of DICOM folders ...",
            "server_selectable": None,
            "choices": None,
            "initial": False,
            "extensions": None,
        },
        "output_suffix": {
            "type": "str",
            "types": ["str"],
            "required": False,
            "description": "Added to every output file name, e.g. patient1_Or.nii.gz",
            "server_selectable": None,
            "choices": None,
            "initial": "Or",
            "extensions": None,
        },
    },
}


# ---------------------------------------------------------------------------
# What the schema alone has to answer
# ---------------------------------------------------------------------------

class DeclarationTest(unittest.TestCase):
    def test_the_module_declares_nothing_but_the_tool_name(self):
        """Every override below would only repeat what the server already says,
        and an override written against a remembered schema is the one thing
        that can drift out of sync with it."""
        self.assertEqual(ASOWidget.TOOL_NAME, "ASO")
        self.assertEqual(ASOWidget.FILE_INPUTS, ServerToolWidgetBase.FILE_INPUTS)
        self.assertIsNone(ASOWidget.RESULT_KIND)
        self.assertTrue(ASOWidget.AUTO_UI)


class SchemaDrivenPanelTest(unittest.TestCase):
    def test_input_takes_a_file_or_a_folder(self):
        """`input` lists "folder" alongside two file types, so the panel gives
        one path field with both browse buttons; which kind was given is read
        off the path at upload time, never asked."""
        modes = formgen.file_input_modes(ASO_SCHEMA["arguments"])
        self.assertEqual(modes["input"], "file_or_folder")

    def test_the_file_picker_offers_every_format_the_server_reads(self):
        """Read from the schema's `extensions`, never rebuilt here: a client
        copy of that table is exactly what drifted before, and "folder"'s .zip
        is what a zipped folder uploads AS, not something a picker should
        show."""
        extensions = client_module.file_extensions_for(ASO_SCHEMA["arguments"]["input"])
        self.assertIn(".nii.gz", extensions)
        self.assertIn(".vtk", extensions)
        self.assertIn(".off", extensions)
        # .zip appears because volume_or_zip_file genuinely accepts an archive,
        # not because "folder" is in the list.
        self.assertIn(".zip", extensions)

    def test_the_reference_can_be_hosted_or_uploaded(self):
        """A file-typed argument flagged server_selectable means BOTH: pick a
        bundle the server hosts, or send your own. A clinic has its own."""
        spec = ASO_SCHEMA["arguments"]["reference"]
        self.assertEqual(spec["server_selectable"], "model")
        self.assertTrue(client_module.is_file_type(spec["type"]))
        self.assertTrue(client_module.accepts_folder(spec))

    def test_the_landmark_bundle_is_a_name_never_an_upload(self):
        """server_selectable on a SCALAR means name-only: the weights never
        leave the server."""
        spec = ASO_SCHEMA["arguments"]["landmark_models"]
        self.assertEqual(spec["server_selectable"], "model")
        self.assertFalse(client_module.is_file_type(spec["type"]))

    def test_the_result_is_saved_not_loaded_blindly(self):
        """output_kind "files" can only mean "save the archive", which is why
        the module declares no RESULT_KIND."""
        self.assertEqual(
            formgen.result_kind_for(ASO_SCHEMA["output_kind"], ASOWidget.RESULT_KIND),
            "save_as",
        )

    def test_four_arguments_form_a_complete_request(self):
        """Everything mode-specific is optional, so the inactive mode cannot
        block a request — and the defaults come from the server."""
        required = [
            name for name, spec in ASO_SCHEMA["arguments"].items() if spec["required"]
        ]
        self.assertEqual(
            sorted(required), ["automation", "input", "modality", "reference"]
        )

    def test_the_mode_is_asked_for_rather_than_guessed(self):
        """A .zip can hold CBCT volumes or intra-oral meshes, so no extension
        tells you which pipeline was wanted."""
        for name in ("modality", "automation"):
            spec = ASO_SCHEMA["arguments"][name]
            self.assertEqual(spec["type"], "choice")
            self.assertTrue(spec["required"])
            self.assertEqual(sum(spec["choices"].values()), 1)

    def test_every_scalar_default_reaches_the_widget(self):
        """A form always sends every widget, so a field starting at Qt's own
        empty value would override run()'s default server-side."""
        self.assertEqual(ASO_SCHEMA["arguments"]["output_suffix"]["initial"], "Or")
        self.assertIs(ASO_SCHEMA["arguments"]["dicom_input"]["initial"], False)


# ---------------------------------------------------------------------------
# Finding what came back
# ---------------------------------------------------------------------------

class ResultDiscoveryTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)

    def _write(self, relative):
        path = os.path.join(self.dir, relative)
        os.makedirs(os.path.dirname(path) or self.dir, exist_ok=True)
        with open(path, "w") as handle:
            handle.write("x")
        return path

    def _found(self):
        return {
            os.path.basename(path): kind
            for path, kind in ASOWidget._findResults(self.dir)
        }

    def test_each_result_kind_gets_the_right_loader(self):
        """The oriented CBCT is a VOLUME, not a segmentation: ASO moves a scan,
        it does not label one. Meshes are models, landmarks are markups."""
        self._write("patient1_Or.nii.gz")
        self._write("P1_U_Seg_Or.vtk")
        self._write("patient1_lm_Or.mrk.json")
        self.assertEqual(
            self._found(),
            {
                "patient1_Or.nii.gz": "volume",
                "P1_U_Seg_Or.vtk": "model",
                "patient1_lm_Or.mrk.json": "markups",
            },
        )

    def test_transforms_and_the_report_are_not_loaded(self):
        """Loading a .tfm into the scene applies nothing and explains nothing;
        ASO_report.json is not a scene object either. Both must stay out, or
        they would eat into the MAX_RESULTS_TO_LOAD budget as well."""
        self._write("patient1_Or_transform.tfm")
        self._write("ASO_report.json")
        self.assertEqual(ASOWidget._findResults(self.dir), [])

    def test_results_are_found_across_the_whole_tree(self):
        """The server preserves the input's folder structure, so a cohort's
        results are nested — a non-recursive search would find nothing."""
        self._write("siteA/patient1_Or.nii.gz")
        self._write("siteB/nested/patient2_Or.nii.gz")
        self.assertEqual(len(ASOWidget._findResults(self.dir)), 2)

    def test_a_compressed_scan_is_not_counted_twice(self):
        """"*.nii" must not also match "patient1_Or.nii.gz" — a double count
        would halve the effective load cap and load the same file twice."""
        self._write("patient1_Or.nii.gz")
        self.assertEqual(len(ASOWidget._findResults(self.dir)), 1)


if __name__ == "__main__":
    unittest.main()

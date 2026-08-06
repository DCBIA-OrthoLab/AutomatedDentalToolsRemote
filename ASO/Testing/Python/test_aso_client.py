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
            "section": "Inputs", "visible_when": None, "ui": None, "groups": None,
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
            "section": "Inputs", "visible_when": None, "ui": None, "groups": None,
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
            "section": "Inputs", "visible_when": None, "ui": None, "groups": None,
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
            "section": "Inputs", "visible_when": None, "ui": None, "groups": None,
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
            "section": "Inputs",
            "visible_when": {"modality": "CBCT", "automation": "Fully-Automated"},
            "ui": None, "groups": None,
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
            "section": "Landmark Reference",
            "visible_when": {"modality": "CBCT"},
            "ui": "tabs",
            "groups": {"Cranial base": ["Ba", "C2", "S", "N", "RPo", "LPo"],
                       "Upper": ["ROr", "LOr", "A", "ANS"]},
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
            "section": "Teeth & Landmarks",
            "visible_when": {"modality": "IOS"},
            "ui": "grid",
            "groups": {"Upper": ["UR8", "UR6", "UL1", "UL6"],
                       "Lower": ["LL6", "LR1", "LR6"]},
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
            "section": "Teeth & Landmarks",
            "visible_when": {"modality": "IOS", "automation": "Semi-Automated"},
            "ui": "inline", "groups": None,
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
            "section": "Teeth & Landmarks",
            "visible_when": {"modality": "IOS"},
            "ui": "inline", "groups": None,
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
            "section": "Teeth & Landmarks",
            "visible_when": {"modality": "IOS"},
            "ui": None, "groups": None,
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
            "section": "Inputs",
            "visible_when": {"modality": "CBCT"},
            "ui": None, "groups": None,
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
            "section": "Outputs", "visible_when": None, "ui": None, "groups": None,
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


# ---------------------------------------------------------------------------
# The four modes, and what each one shows
# ---------------------------------------------------------------------------

_ARGUMENTS = ASO_SCHEMA["arguments"]


def _hidden_in(**mode) -> set:
    """The arguments whose `visible_when` is not satisfied — exactly what
    base_widget._applyVisibility computes and what collectArgs then drops."""
    return {
        name for name, spec in _ARGUMENTS.items() if not formgen.is_visible(spec, mode)
    }


class ModePanelTest(unittest.TestCase):
    """ASO's four modes share one schema, so a panel showing every argument
    shows the 130 CBCT landmarks next to the 32 teeth while a run uses one or
    the other. The old Slicer module solved this with a four-page
    QStackedWidget built by hand; the server states the same thing as
    `visible_when`, and these tests are what notices if it stops.
    """

    def test_a_cbct_run_is_not_asked_about_teeth(self):
        hidden = _hidden_in(modality="CBCT", automation="Semi-Automated")
        self.assertEqual(
            hidden,
            {"ios_teeth", "ios_landmark_types", "ios_jaws", "ios_occlusion",
             "landmark_models"},
        )
        self.assertNotIn("cbct_landmarks", hidden)
        self.assertNotIn("dicom_input", hidden)

    def test_an_ios_run_is_not_asked_about_cbct_landmarks(self):
        hidden = _hidden_in(modality="IOS", automation="Semi-Automated")
        self.assertIn("cbct_landmarks", hidden)
        # DICOM is a CBCT acquisition format; offering it for a mesh is how a
        # user comes to believe an .stl might be one.
        self.assertIn("dicom_input", hidden)
        self.assertNotIn("ios_teeth", hidden)
        self.assertNotIn("ios_jaws", hidden)

    def test_the_landmark_bundle_belongs_to_exactly_one_of_the_four_modes(self):
        """It is read only by Fully-Automated CBCT, and offering it elsewhere
        is what makes Semi-Automated look like it needs a model."""
        self.assertNotIn(
            "landmark_models", _hidden_in(modality="CBCT", automation="Fully-Automated")
        )
        for modality, automation in (("CBCT", "Semi-Automated"),
                                     ("IOS", "Fully-Automated"),
                                     ("IOS", "Semi-Automated")):
            self.assertIn("landmark_models", _hidden_in(modality=modality, automation=automation))

    def test_semi_automated_ios_is_the_only_mode_asking_for_landmark_types(self):
        """Fully-Automated IOS registers on tooth centroids and reads no
        landmark file at all, so the eight types have nothing to apply to."""
        self.assertNotIn(
            "ios_landmark_types", _hidden_in(modality="IOS", automation="Semi-Automated")
        )
        self.assertIn(
            "ios_landmark_types", _hidden_in(modality="IOS", automation="Fully-Automated")
        )

    def test_the_two_scans_and_the_reference_are_asked_for_in_every_mode(self):
        for modality in ("CBCT", "IOS"):
            for automation in ("Semi-Automated", "Fully-Automated"):
                hidden = _hidden_in(modality=modality, automation=automation)
                self.assertNotIn("input", hidden)
                self.assertNotIn("reference", hidden)
                self.assertNotIn("output_suffix", hidden)

    def test_the_two_selection_sections_are_mutually_exclusive(self):
        """Which is what makes them behave like the old module's stacked
        pages: a section whose every row is hidden is hidden too."""
        sections = {name: formgen.section_of(spec) for name, spec in _ARGUMENTS.items()}
        for modality, live, dead in (("CBCT", "Landmark Reference", "Teeth & Landmarks"),
                                     ("IOS", "Teeth & Landmarks", "Landmark Reference")):
            hidden = _hidden_in(modality=modality, automation="Semi-Automated")
            visible_sections = {
                section for name, section in sections.items() if name not in hidden
            }
            self.assertIn(live, visible_sections, modality)
            self.assertNotIn(dead, visible_sections, modality)

    def test_the_panel_is_laid_out_in_four_boxes_in_reading_order(self):
        self.assertEqual(
            formgen.sections_of(_ARGUMENTS),
            ["Inputs", "Landmark Reference", "Teeth & Landmarks", "Outputs"],
        )

    def test_every_condition_names_a_choice_argument_of_this_tool(self):
        """A visible_when naming an argument the tool doesn't publish would
        hide its field forever, and nothing on screen would say why. The
        server's check_schema rejects it at boot; this is the client-side half
        of the same guard, against a schema fetched from an older server."""
        for name in formgen.controlling_arguments(_ARGUMENTS):
            self.assertIn(name, _ARGUMENTS, name)
            self.assertEqual(_ARGUMENTS[name]["type"], "choice", name)
        for name, spec in _ARGUMENTS.items():
            for other, expected in (spec.get("visible_when") or {}).items():
                wanted = expected if isinstance(expected, (list, tuple)) else [expected]
                for value in wanted:
                    self.assertIn(value, _ARGUMENTS[other]["choices"], f"{name} -> {other}")


class HiddenArgumentsAreNotSentTest(unittest.TestCase):
    """collectArgs must DROP a hidden argument, not send whatever its invisible
    widget happens to hold.

    A multichoice is read back as the complete {option: checked} dict and the
    server reads what it receives AS the selection — so sending `ios_teeth`
    with a CBCT run states a selection the user was never shown, and freezes it
    at whatever the widget was built with even after the default changes
    server-side.
    """

    def setUp(self):
        self.panel = ServerToolWidgetBase.__new__(ServerToolWidgetBase)
        self.panel._schema = ASO_SCHEMA
        self.panel._inputWidgets = {}
        self.panel._argWidgets = formgen.build(_ARGUMENTS, qt.QFormLayout())

    def _collect(self, **mode):
        self.panel._argWidgets["modality"].setCurrentIndex(
            list(_ARGUMENTS["modality"]["choices"]).index(mode["modality"])
        )
        self.panel._argWidgets["automation"].setCurrentIndex(
            list(_ARGUMENTS["automation"]["choices"]).index(mode["automation"])
        )
        self.panel._hiddenArgs = _hidden_in(**mode)
        return ServerToolWidgetBase.collectArgs(self.panel)

    def test_a_cbct_request_carries_no_ios_argument(self):
        sent = self._collect(modality="CBCT", automation="Semi-Automated")
        self.assertEqual([name for name in sent if name.startswith("ios_")], [])
        self.assertIn("cbct_landmarks", sent)
        self.assertEqual(sent["modality"], "CBCT")

    def test_an_ios_request_carries_no_cbct_argument(self):
        sent = self._collect(modality="IOS", automation="Semi-Automated")
        self.assertNotIn("cbct_landmarks", sent)
        self.assertNotIn("dicom_input", sent)
        self.assertIn("ios_teeth", sent)

    def test_what_is_sent_is_still_the_complete_multichoice_state(self):
        """Dropping the hidden ones must not turn into dropping the unchecked
        options of a visible one: absent means "apply the default", and every
        box unchecked is a different, meaningful request."""
        sent = self._collect(modality="CBCT", automation="Semi-Automated")
        self.assertEqual(
            set(sent["cbct_landmarks"]), set(_ARGUMENTS["cbct_landmarks"]["choices"])
        )


class _FakeClient:
    """Answers the two calls _buildAutoUI makes, with no HTTP and no server."""

    def __init__(self, schema):
        self._schema = schema

    def get_tool_schema(self, _name, force_refresh=False):
        return self._schema

    def list_tool_data(self, _name):
        return {"models": ["Frankfurt_Horizontal_Midsagittal_Plane.zip"], "testfiles": []}


class BuiltPanelTest(unittest.TestCase):
    """Builds the real panel through ServerToolWidgetBase._buildAutoUI.

    The tests above check the schema states the right thing; this one checks
    the widget actually acts on it — the two used to be the same assertion only
    because there was nothing between them but a single form layout.
    """

    def setUp(self):
        self.panel = ServerToolWidgetBase.__new__(ASOWidget)
        # The parts of __init__ _buildAutoUI touches. Constructed by hand
        # rather than through __init__, which reaches for get_client() and a
        # live Slicer scene.
        self.panel.client = _FakeClient(ASO_SCHEMA)
        self.panel._argWidgets = {}
        self.panel._inputWidgets = {}
        self.panel._inputModes = {}
        self.panel._sectionBoxes = {}
        self.panel._sectionLayouts = {}
        self.panel._rows = {}
        self.panel._rowSections = {}
        self.panel._sectionsWithOwnRows = set()
        self.panel._hiddenArgs = set()
        self.panel._schema = None
        self.panel._schemaError = None
        self.panel._outputFolderWidget = None
        self.panel.applyButton = None
        self.panel._loadResultsCheckBox = None

        self.panel._buildAutoUI(qt.QVBoxLayout())

    def _boxes(self):
        return {name: box for name, box in self.panel._sectionBoxes.items()}

    def _visible_sections(self):
        return {name for name, box in self._boxes().items() if box.isVisible()}

    def _setMode(self, modality, automation):
        for arg, value in (("modality", modality), ("automation", automation)):
            widget = self.panel._argWidgets[arg]
            widget.setCurrentIndex(list(ASO_SCHEMA["arguments"][arg]["choices"]).index(value))

    def test_the_panel_is_built_in_four_titled_boxes(self):
        self.assertEqual(
            list(self.panel._sectionBoxes),
            ["Inputs", "Landmark Reference", "Teeth & Landmarks", "Outputs"],
        )

    def test_the_file_inputs_land_in_the_section_their_spec_names(self):
        self.assertEqual(self.panel._rowSections["input"], "Inputs")
        self.assertEqual(self.panel._rowSections["reference"], "Inputs")
        self.assertEqual(self.panel._rowSections["cbct_landmarks"], "Landmark Reference")
        self.assertEqual(self.panel._rowSections["output_suffix"], "Outputs")

    def test_it_opens_on_the_declared_defaults_already_filtered(self):
        # CBCT + Semi-Automated are the schema's own defaults, so the panel
        # must open showing the CBCT half only -- not everything until the
        # user touches a combo box.
        self.assertEqual(self._visible_sections(), {"Inputs", "Landmark Reference", "Outputs"})
        self.assertIn("ios_teeth", self.panel._hiddenArgs)
        self.assertNotIn("cbct_landmarks", self.panel._hiddenArgs)

    def test_switching_modality_swaps_the_two_selection_sections(self):
        self._setMode("IOS", "Semi-Automated")
        self.assertEqual(self._visible_sections(), {"Inputs", "Teeth & Landmarks", "Outputs"})
        self.assertIn("cbct_landmarks", self.panel._hiddenArgs)
        self.assertNotIn("ios_teeth", self.panel._hiddenArgs)

        self._setMode("CBCT", "Semi-Automated")
        self.assertEqual(self._visible_sections(), {"Inputs", "Landmark Reference", "Outputs"})

    def test_the_outputs_box_stays_even_though_no_argument_of_it_is_required(self):
        """It holds the output folder picker, which belongs to no schema
        argument — a section is only empty when nothing at all is in it."""
        self._setMode("IOS", "Fully-Automated")
        self.assertIn("Outputs", self._visible_sections())
        self.assertIsNotNone(self.panel._outputFolderWidget)

    def test_a_row_hidden_by_the_mode_hides_its_label_too(self):
        """Otherwise a stray "Ios teeth *" label sits above nothing."""
        self._setMode("CBCT", "Semi-Automated")
        for widget in self.panel._rows["ios_teeth"]:
            self.assertFalse(widget.isVisible())
        for widget in self.panel._rows["cbct_landmarks"]:
            self.assertTrue(widget.isVisible())

    def test_the_landmark_bundle_row_follows_both_combo_boxes(self):
        self._setMode("CBCT", "Fully-Automated")
        self.assertTrue(self.panel._rows["landmark_models"][0].isVisible())
        self._setMode("CBCT", "Semi-Automated")
        self.assertFalse(self.panel._rows["landmark_models"][0].isVisible())

    def test_the_landmark_catalog_is_rendered_as_the_servers_own_tabs(self):
        group = self.panel._argWidgets["cbct_landmarks"]
        tabs = [w for w in group.container.layout.widgets if isinstance(w, qt.QTabWidget)]
        self.assertEqual([title for title, _w in tabs[0].tabs], ["Cranial base", "Upper"])

    def test_the_reference_dropdown_is_filled_from_the_server(self):
        """The panel still does everything it did before it had sections."""
        self.assertIn(
            "Frankfurt_Horizontal_Midsagittal_Plane.zip",
            self.panel._inputWidgets["reference"].combo._items,
        )


if __name__ == "__main__":
    unittest.main()

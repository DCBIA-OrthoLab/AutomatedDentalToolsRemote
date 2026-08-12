"""Unit tests for the BatchDentalSeg module's client behaviour — run outside
Slicer, with `qt`/`ctk`/`slicer` stubbed
(ServerToolsCore/Testing/Python/qt_stubs.py).

Two things are covered, and they are the two that can actually be wrong here:

* what BatchDentalSeg's own schema produces in the panel (one path field taking
  a scan *or* a cohort folder, a model dropdown with no local picker, the
  Inputs/Outputs split, and that `input` + `model` alone form a valid request);
* `BatchDentalSegLib/results.py`, the Slicer-free half of the result handling.
  This is where a mistake is silent rather than loud: a segment mapped to the
  wrong label value does not fail, it renames anatomy — and the four models
  deliberately do not number the same structures the same way.

`BatchDentalSeg.py` itself is deliberately NOT imported: it subclasses
ScriptedLoadableModule and ServerToolWidgetBase, which need a real Slicer.
Its declarations are asserted instead, against the same functions it delegates
to — same rule as ALI/Testing/Python/test_ali_client.py.

Usage:
    python3 -m unittest BatchDentalSeg/Testing/Python/test_batchdentalseg_client.py
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

_HERE = os.path.abspath(os.path.dirname(__file__))
_MODULE_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
_REPO_ROOT = os.path.abspath(os.path.join(_MODULE_ROOT, ".."))
_CORE = os.path.join(_REPO_ROOT, "ServerToolsCore")
# `ServerToolsCoreLib` is a package inside ServerToolsCore/, and qt_stubs lives
# with that module's own tests: it is the extension's single set of Qt
# stand-ins, and forking a second copy here would drift.
sys.path.insert(0, os.path.join(_CORE, "Testing", "Python"))
sys.path.insert(0, _CORE)
sys.path.insert(0, _MODULE_ROOT)

import qt_stubs

qt, ctk = qt_stubs.install()

from BatchDentalSegLib import results
from ServerToolsCoreLib import formgen
from ServerToolsCoreLib.client import ToolServerClient
from ServerToolsCoreLib.errors import ServerToolError

# The server's actual GET /tools payload for BatchDentalSeg, verbatim. Kept
# here as a fixture so the panel can be tested without a running server; if the
# server's schema changes, these tests are what notices.
BATCHDENTALSEG_SCHEMA = {
    "name": "BatchDentalSeg",
    "output_kind": "files",
    "arguments": {
        "input": {
            "label": "Scan or Folder", "section": "Inputs",
            "visible_when": None, "ui": None, "groups": None,
            "type": "volume_or_zip_file",
            "types": ["volume_or_zip_file", "folder"],
            "required": True,
            "server_selectable": "testfile",
            "choices": None, "initial": None,
            "extensions": {
                "volume_or_zip_file": [
                    ".nii", ".nii.gz", ".nrrd", ".nrrd.gz", ".gipl", ".gipl.gz", ".zip",
                ],
                "folder": [".zip"],
            },
            "description": (
                "A dental CT/CBCT scan (.nii/.nii.gz/.nrrd/.nrrd.gz/.gipl/.gipl.gz), or a "
                "folder of scans for batch segmentation (sent as a .zip archive)"
            ),
        },
        "model": {
            "label": "Model", "section": "Inputs",
            "visible_when": None, "ui": None, "groups": None,
            "type": "str", "types": ["str"], "required": True,
            "server_selectable": "model",
            "choices": None, "initial": None, "extensions": None,
            "description": (
                "Name of a model hosted on the server (see "
                "GET /tools/BatchDentalSeg/data). DentalSegmentator and "
                "PediatricDentalSeg label 5 segments (the maxilla is inside Upper "
                "Skull); NasoMaxillaDentSeg separates the maxilla; UniversalLab labels "
                "every tooth individually. The run report says what the values mean"
            ),
        },
        "separate_segments": {
            "label": "Also write one file per segment", "section": "Outputs",
            "visible_when": None, "ui": None, "groups": None,
            "type": "bool", "types": ["bool"], "required": False,
            "server_selectable": None, "choices": None, "initial": False,
            "extensions": None,
            "description": (
                "In addition to the multi-label volume, write a binary mask per segment "
                "the model actually found. Empty segments are not written"
            ),
        },
        "prediction_ID": {
            "label": "Prediction ID", "section": "Outputs",
            "visible_when": None, "ui": None, "groups": None,
            "type": "str", "types": ["str"], "required": False,
            "server_selectable": None, "choices": None, "initial": "Seg",
            "extensions": None,
            "description": "Suffix used in output file names, e.g. scan_Seg.nii.gz",
        },
    },
}

# The five-segment table DentalSegmentator and PediatricDentalSeg share, and
# the six-segment one NasoMaxillaDentSeg emits. Copied from the server's
# catalogs.py because the whole point of the tests below is that the client
# must follow whichever of them the report carries.
FIVE_LABELS = {
    "Upper Skull": 1, "Mandible": 2, "Upper Teeth": 3, "Lower Teeth": 4,
    "Mandibular canal": 5,
}
NASO_LABELS = {
    "Upper Skull": 1, "Mandible": 2, "Maxilla": 3, "Upper Teeth": 4,
    "Lower Teeth": 5, "Mandibular canal": 6,
}


def _argument(name: str) -> dict:
    return BATCHDENTALSEG_SCHEMA["arguments"][name]


def _report(**overrides) -> dict:
    report = {
        "tool": "BatchDentalSeg",
        "model": "DentalSegmentator",
        "model_description": "Adult dental CT/CBCT. Upper Skull (maxilla included), ...",
        "labels": dict(FIVE_LABELS),
        "device": "cuda",
        "prediction_ID": "Seg",
        "separate_segments": False,
        "scans": [{"case_id": "case_0000", "input": "scan.nii.gz", "status": "ok"}],
        "summary": "1/1 scan(s) segmented",
        "duration_seconds": 42.0,
    }
    report.update(overrides)
    return report


class TestInputPicker(unittest.TestCase):
    """The `input` row: one scan or a whole cohort, with no module-side type
    knowledge."""

    def test_the_schema_alone_gives_a_file_and_folder_row(self):
        # "folder" is among the declared types, so the schema-driven rule
        # already produces the two-button row. This is why BatchDentalSeg.py
        # declares no FILE_INPUTS override at all — and this test is what fails
        # if someone adds one back believing it is needed.
        self.assertEqual(formgen.auto_file_mode(_argument("input")), "file_or_folder")
        self.assertEqual(
            formgen.file_input_modes(BATCHDENTALSEG_SCHEMA["arguments"], {}),
            {"input": "file_or_folder"},
        )

    def test_the_picker_offers_every_volume_extension_the_server_accepts(self):
        extensions = formgen.file_extensions_for(_argument("input"))
        # ".zip" belongs to the "folder" type only: it says what a zipped
        # folder may be uploaded as, not what a file picker should show. It is
        # nonetheless offered here because the *file* type accepts it too.
        self.assertEqual(
            set(extensions),
            {".nii", ".nii.gz", ".nrrd", ".nrrd.gz", ".gipl", ".gipl.gz", ".zip"},
        )
        self.assertEqual(len(extensions), len(set(extensions)))

    def test_an_open_volume_can_satisfy_the_input(self):
        # A CBCT already loaded in the scene is exported and uploaded like any
        # local file. Derived from the schema, not declared by the module.
        self.assertTrue(formgen.accepts_volume(_argument("input")))

    def test_a_folder_selection_is_recognised_as_one(self):
        directory = tempfile.mkdtemp(prefix="bds_pick_")
        self.addCleanup(shutil.rmtree, directory, True)

        widget = formgen.file_widget(_argument("input"), "file_or_folder")
        qt.QFileDialog.next_directory = directory
        widget.local._onBrowseFolder()

        self.assertEqual(widget.currentPath, directory)
        # The upload path branches on this, never on something the user had to
        # set correctly beforehand.
        self.assertTrue(widget.is_folder())


class TestModelSelection(unittest.TestCase):
    """`model` is server_selectable on a SCALAR type: a name travels, never
    weights."""

    def test_the_model_argument_gets_no_local_picker(self):
        self.assertFalse(formgen.is_file_type(_argument("model")["type"]))

    def test_the_model_travels_as_a_name(self):
        self.assertEqual(
            ToolServerClient._stringify({"model": "DentalSegmentator"}),
            {"model": "DentalSegmentator"},
        )

    def test_the_model_is_required_so_the_dropdown_has_no_automatic_entry(self):
        # ALI's model is optional and its dropdown leads with "(automatic)";
        # here the bundle name IS the model (it selects the weights and their
        # label table together), so there is nothing for the server to infer.
        self.assertTrue(_argument("model")["required"])

    def test_the_model_scope_row_has_something_to_show(self):
        # BatchDentalSeg.py puts this description on screen under the dropdown
        # rather than only in a tooltip (the local module's "Model Scope:"
        # row). An empty description would silently produce no row.
        self.assertTrue(_argument("model")["description"].strip())
        self.assertEqual(formgen.section_of(_argument("model")), "Inputs")


class TestOneRequest(unittest.TestCase):
    """`input` + `model` alone is a complete, valid request."""

    def test_input_and_model_alone_satisfy_the_schema(self):
        ToolServerClient._validate_against_schema(
            BATCHDENTALSEG_SCHEMA, {"model": "DentalSegmentator"}, {"input": "/tmp/cohort.zip"}
        )

    def test_a_hosted_cohort_satisfies_the_required_file_argument(self):
        # `input` is server_selectable "testfile": naming one uploads nothing.
        ToolServerClient._validate_against_schema(
            BATCHDENTALSEG_SCHEMA,
            {"model": "DentalSegmentator", "input": "MG_test_scan.nii.gz"},
            {},
        )

    def test_a_missing_model_is_caught_before_the_round_trip(self):
        with self.assertRaises(ServerToolError):
            ToolServerClient._validate_against_schema(
                BATCHDENTALSEG_SCHEMA, {}, {"input": "/tmp/cohort.zip"}
            )

    def test_separate_segments_travels_as_a_lowercase_boolean(self):
        self.assertEqual(
            ToolServerClient._stringify({"separate_segments": True}),
            {"separate_segments": "true"},
        )

    def test_the_result_is_saved_not_loaded_as_one_node(self):
        # output_kind "files": one segmentation per scan plus the report, in a
        # zip. Only "save_as" can express that, and it is derived, not declared.
        self.assertEqual(formgen.result_kind_for(BATCHDENTALSEG_SCHEMA["output_kind"]), "save_as")


class TestPanelLayout(unittest.TestCase):
    """Which box each row lands in comes from the schema."""

    def test_sections_are_inputs_then_outputs(self):
        # "Outputs" is also where base_widget puts the output-folder picker for
        # a "save_as" tool, so the two merge into one box rather than stacking.
        self.assertEqual(
            formgen.sections_of(BATCHDENTALSEG_SCHEMA["arguments"], ["Inputs", "Outputs"]),
            ["Inputs", "Outputs"],
        )

    def test_only_the_scalar_arguments_become_form_fields(self):
        layout = qt.QFormLayout()
        widgets = formgen.build(BATCHDENTALSEG_SCHEMA["arguments"], layout)
        # `input` is a file argument: base_widget gives it its own input row.
        self.assertEqual(sorted(widgets), ["model", "prediction_ID", "separate_segments"])

    def test_the_declared_defaults_reach_the_widgets(self):
        layout = qt.QFormLayout()
        widgets = formgen.build(BATCHDENTALSEG_SCHEMA["arguments"], layout)
        # `initial` is the server's, so a checkbox does not start at Qt's own
        # default while the tool's reads False (or, later, True).
        self.assertFalse(widgets["separate_segments"].isChecked())


class TestFindSegmentations(unittest.TestCase):
    """Which of the returned volumes get loaded into the scene."""

    def setUp(self):
        self.resultDir = tempfile.mkdtemp(prefix="bds_results_")
        self.addCleanup(shutil.rmtree, self.resultDir, True)

    def _write(self, *relative):
        for name in relative:
            path = os.path.join(self.resultDir, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "wb").close()

    def test_per_segment_masks_are_not_loaded_alongside_the_label_volume(self):
        # `separate_segments` writes one binary mask per structure BESIDE the
        # multi-label volume. Loading both would put every structure in the
        # scene twice, once named and once not.
        self._write(
            "scan_Seg.nii.gz",
            "scan_Seg_Mandible.nii.gz",
            "scan_Seg_Upper-Teeth.nii.gz",
        )
        found = results.find_segmentations(self.resultDir, "Seg")
        self.assertEqual([os.path.basename(path) for path in found], ["scan_Seg.nii.gz"])

    def test_the_output_tree_is_walked_recursively(self):
        # The server mirrors the input's own folder tree, so two patients whose
        # scans share a file name stay apart.
        self._write("patient1/scan_Seg.nii.gz", "patient2/scan_Seg.nii.gz")
        found = results.find_segmentations(self.resultDir, "Seg")
        self.assertEqual(len(found), 2)
        self.assertNotEqual(found[0], found[1])

    def test_a_custom_prediction_id_is_followed(self):
        self._write("scan_MyRun.nii.gz", "scan_MyRun_Mandible.nii.gz")
        found = results.find_segmentations(self.resultDir, "MyRun")
        self.assertEqual([os.path.basename(path) for path in found], ["scan_MyRun.nii.gz"])

    def test_the_report_json_is_never_mistaken_for_a_volume(self):
        self._write("scan_Seg.nii.gz", results.REPORT_NAME)
        found = results.find_segmentations(self.resultDir, "Seg")
        self.assertEqual([os.path.basename(path) for path in found], ["scan_Seg.nii.gz"])

    def test_an_unmatched_suffix_falls_back_to_everything_found(self):
        # An unreadable report costs the user the segment names, not the load.
        self._write("scan_Seg.nii.gz")
        self.assertEqual(len(results.find_segmentations(self.resultDir, "")), 1)
        self.assertEqual(len(results.find_segmentations(self.resultDir, "Other")), 1)

    def test_the_input_container_is_preserved_by_the_server(self):
        # A .nrrd scan comes back as .nrrd.gz, so the discovery cannot assume
        # NIfTI just because that is what nnUNet produced internally.
        self._write("scan_Seg.nrrd.gz", "other_Seg.gipl.gz")
        found = results.find_segmentations(self.resultDir, "Seg")
        self.assertEqual(len(found), 2)


class TestReport(unittest.TestCase):
    """Reading BatchDentalSeg_report.json."""

    def setUp(self):
        self.resultDir = tempfile.mkdtemp(prefix="bds_report_")
        self.addCleanup(shutil.rmtree, self.resultDir, True)

    def _write(self, payload):
        path = os.path.join(self.resultDir, results.REPORT_NAME)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(payload if isinstance(payload, str) else json.dumps(payload))
        return path

    def test_a_missing_report_is_not_fatal(self):
        self.assertIsNone(results.read_report(self.resultDir))
        self.assertEqual(results.label_names(None), {})

    def test_a_malformed_report_is_not_fatal(self):
        # The segmentations are already on disk and are what the user asked
        # for; a broken report costs the summary, not the run.
        self._write("{not json")
        self.assertIsNone(results.read_report(self.resultDir))

    def test_the_label_table_is_read_back_by_value(self):
        self._write(_report())
        report = results.read_report(self.resultDir)
        self.assertEqual(
            results.label_names(report),
            {1: "Upper Skull", 2: "Mandible", 3: "Upper Teeth", 4: "Lower Teeth",
             5: "Mandibular canal"},
        )

    def test_a_non_integer_label_value_is_dropped_not_raised(self):
        self._write(_report(labels={"Mandible": 2, "Broken": "two"}))
        self.assertEqual(results.label_names(results.read_report(self.resultDir)), {2: "Mandible"})

    def test_failed_scans_are_listed_with_their_reason(self):
        report = _report(
            summary="1/2 scan(s) segmented",
            scans=[
                {"case_id": "case_0000", "input": "p1/scan.nii.gz", "status": "ok"},
                {"case_id": "case_0001", "input": "p2/scan.nii.gz", "status": "failed",
                 "error": "could not be read (RuntimeError: unknown format)"},
            ],
        )
        self.assertEqual(
            results.failed_scans(report),
            [("p2/scan.nii.gz", "could not be read (RuntimeError: unknown format)")],
        )

    def test_a_complete_run_reports_no_failure(self):
        self.assertEqual(results.failed_scans(_report()), [])


class TestSegmentLabelling(unittest.TestCase):
    """Turning a label value into a name and a colour.

    This is where a mistake is silent: a wrong mapping does not fail, it
    renames anatomy.
    """

    def test_the_value_the_segment_declares_wins(self):
        self.assertEqual(results.segment_label_value("Segment_1", 0, 5), 5)

    def test_the_id_is_parsed_when_the_segment_declares_nothing(self):
        # Slicer names a segment imported from a labelmap after the integer it
        # came from.
        self.assertEqual(results.segment_label_value("Segment_4", 0, None), 4)
        self.assertEqual(results.segment_label_value("Segment_52", 3, 0), 52)

    def test_position_is_the_last_resort_and_that_matters(self):
        # A structure absent from a scan leaves a gap in the values, and
        # everything after it shifts by one. Position is therefore only used
        # when neither the segment nor its id says anything.
        self.assertEqual(results.segment_label_value("weird-id", 2, None), 3)

    def test_a_gap_in_the_present_labels_does_not_shift_the_names(self):
        # The scan has no maxillary teeth: the segments are 1, 2, 4, 5. Naming
        # them by position would call label 4 "Upper Teeth".
        names = results.label_names(_report())
        present = ["Segment_1", "Segment_2", "Segment_4", "Segment_5"]
        named = [names[results.segment_label_value(sid, i, None)] for i, sid in enumerate(present)]
        self.assertEqual(named, ["Upper Skull", "Mandible", "Lower Teeth", "Mandibular canal"])

    def test_the_same_structure_keeps_its_colour_across_models(self):
        # NasoMaxillaDentSeg separates the maxilla, which shifts every later
        # value: the mandible is 2 in both tables but the upper teeth are 3
        # under one model and 4 under the other. A palette indexed by VALUE
        # would recolour the teeth on that one model alone.
        five = results.label_names(_report(labels=dict(FIVE_LABELS)))
        naso = results.label_names(_report(labels=dict(NASO_LABELS)))
        self.assertEqual(five[3], "Upper Teeth")
        self.assertEqual(naso[3], "Maxilla")
        self.assertEqual(
            results.color_for(five[3], 3), results.color_for(naso[4], 4)
        )

    def test_an_unknown_structure_still_gets_a_stable_colour(self):
        # Every UniversalLab tooth, and anything a future model adds: no
        # anatomy list lives in this client, so these are generated.
        first = results.color_for("Upper-left first molar", 12)
        self.assertEqual(first, results.color_for("Upper-left first molar", 12))
        self.assertEqual(len(first), 3)
        self.assertTrue(all(0.0 <= channel <= 1.0 for channel in first))

    def test_consecutive_generated_colours_are_distinguishable(self):
        # Adjacent teeth are what a clinician has to tell apart.
        for value in range(1, 33):
            here = results.color_for(f"tooth {value}", value)
            nxt = results.color_for(f"tooth {value + 1}", value + 1)
            self.assertGreater(sum(abs(a - b) for a, b in zip(here, nxt)), 0.2)

    def test_the_bone_shells_are_translucent_and_the_teeth_are_not(self):
        # Otherwise the enclosing bone is all one sees of the result in 3D.
        self.assertLess(results.opacity_for("Upper Skull"), 1.0)
        self.assertLess(results.opacity_for("Mandible"), 1.0)
        self.assertLess(results.opacity_for("Maxilla"), 1.0)
        self.assertEqual(results.opacity_for("Upper Teeth"), 1.0)
        self.assertEqual(results.opacity_for("Upper-left first molar"), 1.0)

    def test_the_named_palette_is_matched_case_insensitively(self):
        self.assertEqual(results.color_for("mandible", 2), results.color_for("Mandible", 2))


class TestStem(unittest.TestCase):
    """Compound medical extensions, which os.path.splitext gets wrong."""

    def test_compound_extensions_are_stripped_whole(self):
        self.assertEqual(results.stem("scan_Seg.nii.gz"), "scan_Seg")
        self.assertEqual(results.stem("scan_Seg.nrrd.gz"), "scan_Seg")
        self.assertEqual(results.stem("scan_Seg.gipl.gz"), "scan_Seg")

    def test_a_plain_extension_still_works(self):
        self.assertEqual(results.stem("scan_Seg.nrrd"), "scan_Seg")

    def test_a_dotted_patient_name_keeps_its_dots(self):
        self.assertEqual(results.stem("patient.1.2.3_Seg.nii.gz"), "patient.1.2.3_Seg")


if __name__ == "__main__":
    unittest.main()

"""Unit tests for the MRI2CBCT module's client behaviour - run outside Slicer,
with `qt`/`ctk`/`slicer` stubbed (ServerToolsCore/Testing/Python/qt_stubs.py).

What is tested here is what the generic ServerToolsCore tests cannot cover,
because it depends on MRI2CBCT's own schema: that a panel of twenty-two
arguments collapses to the handful the chosen step actually reads, that the
eight normalisation numbers are all present and all scoped to Register, and
that a step with nothing but its inputs is a complete request.

`MRI2CBCT.py` itself is deliberately NOT imported: it subclasses
ScriptedLoadableModule and ServerToolWidgetBase, which need a real Slicer.
Its declarations are read out of the source with `ast` instead.

Usage:
    python3 -m unittest MRI2CBCT/Testing/Python/test_mri2cbct_client.py
"""

import ast
import os
import sys
import unittest

_HERE = os.path.abspath(os.path.dirname(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
_CORE = os.path.join(_REPO_ROOT, "ServerToolsCore")
sys.path.insert(0, os.path.join(_CORE, "Testing", "Python"))
sys.path.insert(0, _CORE)

import qt_stubs

qt, ctk = qt_stubs.install()

from ServerToolsCoreLib import client as client_module
from ServerToolsCoreLib import formgen
from ServerToolsCoreLib.client import ToolServerClient

# The server's GET /tools payload for MRI2CBCT, generated from the tool's own
# `scripts/describe.py` output and put through the same reduction
# `registry/schema_tool.py` applies. If the tool's signature changes, these
# tests are what notices.
MRI2CBCT_SCHEMA = {
    "name": "MRI2CBCT",
    "arguments": {
        "step": {
            "type": "choice",
            "types": [
                "choice"
            ],
            "required": False,
            "description": "Which operation to run. The pipeline is Orient MRI, Resample, Approximate, a crop, then Register, and it is one call per step on purpose: a badly oriented MRI is worth catching before an hour of registration, which is why the module puts them on separate tabs.",
            "server_selectable": None,
            "choices": {
                "Orient MRI": False,
                "Resample": False,
                "Approximate": False,
                "LR crop": False,
                "TMJ crop": False,
                "Register": True
            },
            "initial": None,
            "extensions": None,
            "label": "Step",
            "section": "Inputs",
            "visible_when": None,
            "options_when": None,
            "hidden": False,
            "ui": None,
            "groups": None
        },
        "mri": {
            "type": "path",
            "types": [
                "path"
            ],
            "required": False,
            "description": "The MRI scans, as a folder (a single file is taken with its folder). Read by every step.",
            "server_selectable": None,
            "choices": None,
            "initial": None,
            "extensions": None,
            "label": "MRI",
            "section": "Inputs",
            "visible_when": None,
            "options_when": None,
            "hidden": False,
            "ui": None,
            "groups": None
        },
        "cbct": {
            "type": "path",
            "types": [
                "path"
            ],
            "required": False,
            "description": "The CBCT scans, paired to the MRI by patient key.",
            "server_selectable": None,
            "choices": None,
            "initial": None,
            "extensions": None,
            "label": "CBCT",
            "section": "Inputs",
            "visible_when": {
                "step": [
                    "Resample",
                    "Approximate",
                    "LR crop",
                    "TMJ crop",
                    "Register"
                ]
            },
            "options_when": None,
            "hidden": False,
            "ui": None,
            "groups": None
        },
        "segmentation": {
            "type": "path",
            "types": [
                "path"
            ],
            "required": False,
            "description": "The CBCT segmentations. Register uses them as the mask it normalises and registers through; TMJ crop needs them to find the joint; LR crop splits them like a CBCT, being in CBCT space.",
            "server_selectable": None,
            "choices": None,
            "initial": None,
            "extensions": None,
            "label": "CBCT segmentation",
            "section": "Inputs",
            "visible_when": {
                "step": [
                    "Resample",
                    "LR crop",
                    "TMJ crop",
                    "Register"
                ]
            },
            "options_when": None,
            "hidden": False,
            "ui": None,
            "groups": None
        },
        "mri_t2": {
            "type": "path",
            "types": [
                "path"
            ],
            "required": False,
            "description": "A second MRI timepoint, resampled alongside the first. Resample only.",
            "server_selectable": None,
            "choices": None,
            "initial": None,
            "extensions": None,
            "label": "MRI (T2)",
            "section": "Inputs",
            "visible_when": {
                "step": "Resample"
            },
            "options_when": None,
            "hidden": False,
            "ui": None,
            "groups": None
        },
        "cbct_t2": {
            "type": "path",
            "types": [
                "path"
            ],
            "required": False,
            "description": "A second CBCT timepoint. Resample only.",
            "server_selectable": None,
            "choices": None,
            "initial": None,
            "extensions": None,
            "label": "CBCT (T2)",
            "section": "Inputs",
            "visible_when": {
                "step": "Resample"
            },
            "options_when": None,
            "hidden": False,
            "ui": None,
            "groups": None
        },
        "segmentation_t2": {
            "type": "path",
            "types": [
                "path"
            ],
            "required": False,
            "description": "The second timepoint's segmentations. Resample only.",
            "server_selectable": None,
            "choices": None,
            "initial": None,
            "extensions": None,
            "label": "Segmentation (T2)",
            "section": "Inputs",
            "visible_when": {
                "step": "Resample"
            },
            "options_when": None,
            "hidden": False,
            "ui": None,
            "groups": None
        },
        "condyle_model": {
            "type": "path",
            "types": [
                "path"
            ],
            "required": False,
            "description": "The nnUNet condyle segmentation model folder, used by Approximate and TMJ crop to locate the joint. Named rather than resolved here: a tool does not go looking for weights on the server's disk.",
            "server_selectable": None,
            "choices": None,
            "initial": None,
            "extensions": None,
            "label": "nnUNet condyle model",
            "section": "Condyle model",
            "visible_when": {
                "step": [
                    "Approximate",
                    "TMJ crop"
                ]
            },
            "options_when": None,
            "hidden": False,
            "ui": None,
            "groups": None
        },
        "direction": {
            "type": "str",
            "types": [
                "str"
            ],
            "required": False,
            "description": "The MRI's new direction, nine comma-separated numbers read as a 3x3 matrix row by row. Orient MRI only. The default is the orientation upstream documents for MRI; a CBCT is \"1.0,0.0,0.0,0.0,1.0,0.0,0.0,0.0,1.0\".",
            "server_selectable": None,
            "choices": None,
            "initial": "0.0,0.0,-1.0,1.0,0.0,0.0,0.0,-1.0,0.0",
            "extensions": None,
            "label": "Direction matrix",
            "section": "Orientation",
            "visible_when": {
                "step": "Orient MRI"
            },
            "options_when": None,
            "hidden": False,
            "ui": None,
            "groups": None
        },
        "acquisition_z_spacing": {
            "type": "float",
            "types": [
                "float"
            ],
            "required": False,
            "description": "The slice spacing to write into the MRI header, in mm. 0 leaves the acquisition's own spacing alone. Orient MRI only.",
            "server_selectable": None,
            "choices": None,
            "initial": 0.0,
            "extensions": None,
            "label": "Slice spacing (mm)",
            "section": "Orientation",
            "visible_when": {
                "step": "Orient MRI"
            },
            "options_when": None,
            "hidden": False,
            "ui": None,
            "groups": None
        },
        "resample_size": {
            "type": "list[int]",
            "types": [
                "list[int]"
            ],
            "required": False,
            "description": "Target size in voxels, as three numbers. Empty keeps each scan's own size. Resample only.",
            "server_selectable": None,
            "choices": None,
            "initial": [],
            "extensions": None,
            "label": "Size (voxels)",
            "section": "Resampling",
            "visible_when": {
                "step": "Resample"
            },
            "options_when": None,
            "hidden": False,
            "ui": None,
            "groups": None
        },
        "spacing": {
            "type": "list[float]",
            "types": [
                "list[float]"
            ],
            "required": False,
            "description": "Target spacing in mm, as three numbers. Empty keeps each scan's own spacing. Resample only.",
            "server_selectable": None,
            "choices": None,
            "initial": [],
            "extensions": None,
            "label": "Spacing (mm)",
            "section": "Resampling",
            "visible_when": {
                "step": "Resample"
            },
            "options_when": None,
            "hidden": False,
            "ui": None,
            "groups": None
        },
        "center": {
            "type": "bool",
            "types": [
                "bool"
            ],
            "required": False,
            "description": "Centre each resampled volume on its own image centre. Resample only.",
            "server_selectable": None,
            "choices": None,
            "initial": True,
            "extensions": None,
            "label": "Centre each volume",
            "section": "Resampling",
            "visible_when": {
                "step": "Resample"
            },
            "options_when": None,
            "hidden": False,
            "ui": None,
            "groups": None
        },
        "mri_min_norm": {
            "type": "int",
            "types": [
                "int"
            ],
            "required": False,
            "description": "Lower bound of the MRI intensity range after normalisation. Register only.",
            "server_selectable": None,
            "choices": None,
            "initial": 0,
            "extensions": None,
            "label": "MRI min",
            "section": "Normalisation",
            "visible_when": {
                "step": "Register"
            },
            "options_when": None,
            "hidden": False,
            "ui": None,
            "groups": None
        },
        "mri_max_norm": {
            "type": "int",
            "types": [
                "int"
            ],
            "required": False,
            "description": "Upper bound of the MRI intensity range. Register only.",
            "server_selectable": None,
            "choices": None,
            "initial": 100,
            "extensions": None,
            "label": "MRI max",
            "section": "Normalisation",
            "visible_when": {
                "step": "Register"
            },
            "options_when": None,
            "hidden": False,
            "ui": None,
            "groups": None
        },
        "mri_lower_percentile": {
            "type": "int",
            "types": [
                "int"
            ],
            "required": False,
            "description": "Intensity percentile mapped to the lower bound; everything below it is clipped. Register only.",
            "server_selectable": None,
            "choices": None,
            "initial": 10,
            "extensions": None,
            "label": "MRI lower percentile",
            "section": "Normalisation",
            "visible_when": {
                "step": "Register"
            },
            "options_when": None,
            "hidden": False,
            "ui": None,
            "groups": None
        },
        "mri_upper_percentile": {
            "type": "int",
            "types": [
                "int"
            ],
            "required": False,
            "description": "Intensity percentile mapped to the upper bound. Register only.",
            "server_selectable": None,
            "choices": None,
            "initial": 95,
            "extensions": None,
            "label": "MRI upper percentile",
            "section": "Normalisation",
            "visible_when": {
                "step": "Register"
            },
            "options_when": None,
            "hidden": False,
            "ui": None,
            "groups": None
        },
        "cbct_min_norm": {
            "type": "int",
            "types": [
                "int"
            ],
            "required": False,
            "description": "Lower bound of the CBCT intensity range. Register only.",
            "server_selectable": None,
            "choices": None,
            "initial": 0,
            "extensions": None,
            "label": "CBCT min",
            "section": "Normalisation",
            "visible_when": {
                "step": "Register"
            },
            "options_when": None,
            "hidden": False,
            "ui": None,
            "groups": None
        },
        "cbct_max_norm": {
            "type": "int",
            "types": [
                "int"
            ],
            "required": False,
            "description": "Upper bound of the CBCT intensity range. Register only.",
            "server_selectable": None,
            "choices": None,
            "initial": 100,
            "extensions": None,
            "label": "CBCT max",
            "section": "Normalisation",
            "visible_when": {
                "step": "Register"
            },
            "options_when": None,
            "hidden": False,
            "ui": None,
            "groups": None
        },
        "cbct_lower_percentile": {
            "type": "int",
            "types": [
                "int"
            ],
            "required": False,
            "description": "The CBCT's lower percentile. Register only.",
            "server_selectable": None,
            "choices": None,
            "initial": 10,
            "extensions": None,
            "label": "CBCT lower percentile",
            "section": "Normalisation",
            "visible_when": {
                "step": "Register"
            },
            "options_when": None,
            "hidden": False,
            "ui": None,
            "groups": None
        },
        "cbct_upper_percentile": {
            "type": "int",
            "types": [
                "int"
            ],
            "required": False,
            "description": "The CBCT's upper percentile. Register only.",
            "server_selectable": None,
            "choices": None,
            "initial": 95,
            "extensions": None,
            "label": "CBCT upper percentile",
            "section": "Normalisation",
            "visible_when": {
                "step": "Register"
            },
            "options_when": None,
            "hidden": False,
            "ui": None,
            "groups": None
        },
        "keep_temporary": {
            "type": "bool",
            "types": [
                "bool"
            ],
            "required": False,
            "description": "Keep the inverted, normalised and masked volumes the registration built on its way. They are what tells you WHICH stage went wrong when a registration comes out badly. Register only.",
            "server_selectable": None,
            "choices": None,
            "initial": False,
            "extensions": None,
            "label": "Keep intermediate volumes",
            "section": "Normalisation",
            "visible_when": {
                "step": "Register"
            },
            "options_when": None,
            "hidden": False,
            "ui": None,
            "groups": None
        }
    },
    "output_kind": "files",
    "calls": []
}


STEPS = list(MRI2CBCT_SCHEMA["arguments"]["step"]["choices"])


def _module_source() -> str:
    with open(os.path.join(_REPO_ROOT, "MRI2CBCT", "MRI2CBCT.py"), encoding="utf-8") as handle:
        return handle.read()


def _class_attribute(name: str):
    """A literal class attribute of MRI2CBCTWidget, read without importing."""
    tree = ast.parse(_module_source())
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "MRI2CBCTWidget":
            for statement in node.body:
                if isinstance(statement, ast.Assign):
                    for target in statement.targets:
                        if isinstance(target, ast.Name) and target.id == name:
                            return ast.literal_eval(statement.value)
    raise AssertionError(f"MRI2CBCTWidget declares no {name}")


def _visible(step: str) -> set:
    values = {"step": step}
    return {
        name for name, spec in MRI2CBCT_SCHEMA["arguments"].items()
        if formgen.is_visible(spec, values)
    }


class TestToolName(unittest.TestCase):
    def test_it_names_the_tool_the_server_serves(self):
        self.assertEqual(_class_attribute("TOOL_NAME"), MRI2CBCT_SCHEMA["name"])


class TestStepScoping(unittest.TestCase):
    """Twenty-two arguments, and no step reads more than a third of them."""

    def test_the_six_steps_are_the_ones_upstream_had_tabs_for(self):
        self.assertEqual(
            STEPS,
            ["Orient MRI", "Resample", "Approximate", "LR crop", "TMJ crop", "Register"],
        )

    def test_orienting_shows_only_the_mri_and_its_orientation(self):
        self.assertEqual(
            _visible("Orient MRI"),
            {"step", "mri", "direction", "acquisition_z_spacing"},
        )

    def test_registering_shows_the_eight_normalisation_numbers(self):
        visible = _visible("Register")
        for name in ("mri_min_norm", "mri_max_norm", "mri_lower_percentile",
                     "mri_upper_percentile", "cbct_min_norm", "cbct_max_norm",
                     "cbct_lower_percentile", "cbct_upper_percentile"):
            self.assertIn(name, visible, name)
        self.assertIn("keep_temporary", visible)
        # And none of the other steps' arguments.
        for name in ("direction", "resample_size", "condyle_model", "mri_t2"):
            self.assertNotIn(name, visible, name)

    def test_the_condyle_model_is_shown_exactly_where_it_is_read(self):
        for step in STEPS:
            shown = "condyle_model" in _visible(step)
            self.assertEqual(shown, step in ("Approximate", "TMJ crop"), step)

    def test_the_second_timepoint_belongs_to_resampling_alone(self):
        for step in STEPS:
            shown = "mri_t2" in _visible(step)
            self.assertEqual(shown, step == "Resample", step)

    def test_no_step_ever_shows_the_whole_panel(self):
        """The point of the conditions: a usable panel, not twenty-two rows.

        Register is deliberately the widest at thirteen -- three folders, the
        eight normalisation numbers, the temporaries flag and `step` itself --
        and every other step is under half that. The counts are pinned rather
        than bounded loosely: a condition dropped by accident shows up here as
        a number that grew, which a "fewer than all" assertion would miss.
        """
        total = len(MRI2CBCT_SCHEMA["arguments"])
        widths = {step: len(_visible(step)) for step in STEPS}
        self.assertEqual(widths, {
            "Orient MRI": 4,
            "Resample": 10,
            "Approximate": 4,
            "LR crop": 4,
            "TMJ crop": 5,
            "Register": 13,
        })
        for step, width in widths.items():
            self.assertLess(width, total, step)

    def test_every_condition_names_a_real_step(self):
        for name, spec in MRI2CBCT_SCHEMA["arguments"].items():
            condition = spec.get("visible_when")
            if not condition:
                continue
            for controlling, expected in condition.items():
                self.assertEqual(controlling, "step", name)
                expected = expected if isinstance(expected, list) else [expected]
                self.assertLessEqual(set(expected), set(STEPS), name)

    def test_step_is_recognised_as_the_controlling_argument(self):
        self.assertEqual(
            formgen.controlling_arguments(MRI2CBCT_SCHEMA["arguments"]), {"step"})


class TestInputPickers(unittest.TestCase):
    def test_every_input_takes_a_folder_without_any_override(self):
        modes = formgen.file_input_modes(MRI2CBCT_SCHEMA["arguments"])
        for name in ("mri", "cbct", "segmentation", "condyle_model"):
            self.assertEqual(modes[name], "file_or_folder", name)

    def test_the_module_declares_no_file_inputs(self):
        self.assertNotIn("FILE_INPUTS = ", _module_source())

    def test_a_size_is_a_list_of_numbers_not_a_text_field(self):
        self.assertEqual(MRI2CBCT_SCHEMA["arguments"]["resample_size"]["type"], "list[int]")
        self.assertEqual(MRI2CBCT_SCHEMA["arguments"]["spacing"]["type"], "list[float]")


class TestOneRequest(unittest.TestCase):
    def test_an_orient_run_needs_only_the_mri(self):
        ToolServerClient._validate_against_schema(
            MRI2CBCT_SCHEMA, {"step": "Orient MRI"}, {"mri": "/tmp/MRI.zip"})

    def test_a_register_run_carries_its_three_folders(self):
        ToolServerClient._validate_against_schema(
            MRI2CBCT_SCHEMA,
            {"step": "Register"},
            {"mri": "/tmp/MRI.zip", "cbct": "/tmp/CBCT.zip", "segmentation": "/tmp/Seg.zip"},
        )

    def test_the_result_is_an_archive_to_unpack(self):
        self.assertEqual(formgen.result_kind_for(MRI2CBCT_SCHEMA["output_kind"]), "save_as")

    def test_the_module_lets_the_schema_decide_the_result_kind(self):
        self.assertNotIn("RESULT_KIND = ", _module_source())


class TestResultLoading(unittest.TestCase):
    def test_results_load_as_volumes(self):
        loadable = dict(_class_attribute("_LOADABLE"))
        self.assertEqual(set(loadable.values()), {"volume"})

    def test_the_elastix_transform_is_not_loaded(self):
        patterns = [pattern for pattern, _kind in _class_attribute("_LOADABLE")]
        self.assertNotIn("*.tfm", patterns)
        self.assertNotIn("*_reg_transform.tfm", patterns)


class TestNoSupervisedCall(unittest.TestCase):
    def test_this_tool_asks_for_no_other(self):
        """Unlike GreedyReg: MRI2CBCT segments the condyle itself."""
        self.assertEqual(MRI2CBCT_SCHEMA["calls"], [])


if __name__ == "__main__":
    unittest.main()

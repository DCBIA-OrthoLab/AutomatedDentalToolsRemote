"""Unit tests for ServerToolsCoreLib.formgen — run outside Slicer, `qt`/`ctk`/
`slicer` stubbed (see qt_stubs.py).

Everything here is driven by EXAMPLE_TOOL_SCHEMA, the real `GET /tools` entry
for `example_tool`: it is the one tool exercising every argument shape the
panel has to render — free text, int, float, a single-choice dropdown, a
multi-choice checkbox group, and a file argument that also accepts a folder.

Usage:
    python3 -m unittest ServerToolsCore/Testing/Python/test_formgen.py
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import qt_stubs

qt, ctk = qt_stubs.install()

from ServerToolsCoreLib import formgen
from ServerToolsCoreLib.client import ToolServerClient

# The server's actual GET /tools payload for example_tool, verbatim.
EXAMPLE_TOOL_SCHEMA = {
    "name": "example_tool",
    "output_kind": "files",
    "arguments": {
        "label": {
            "type": "str", "types": ["str"], "required": True,
            "description": "Free-text label for this run",
            "server_selectable": None, "choices": None,
        },
        "input": {
            "type": "csv_file", "types": ["csv_file", "folder"], "required": True,
            "description": "A single .csv file, or a folder of .csv/.xlsx/.ods files sent as a .zip archive",
            "server_selectable": None, "choices": None,
        },
        "threshold": {
            "type": "float", "types": ["float"], "required": True,
            "description": "Numeric threshold parameter",
            "server_selectable": None, "choices": None,
        },
        "iterations": {
            "type": "int", "types": ["int"], "required": False,
            "description": "Optional number of iterations",
            "server_selectable": None, "choices": None,
        },
        "outputs": {
            "type": "multichoice", "types": ["multichoice"], "required": False,
            "description": "Which result files to produce",
            "server_selectable": None,
            "choices": {"summary": True, "preview": True, "columns": False},
        },
        "preview_format": {
            "type": "choice", "types": ["choice"], "required": False,
            "description": "Format of the preview file",
            "server_selectable": None,
            "choices": {"csv": True, "json": False},
        },
    },
}


def _build():
    layout = qt.QFormLayout()
    return formgen.build(EXAMPLE_TOOL_SCHEMA["arguments"], layout), layout


class ChoiceWidgetTest(unittest.TestCase):
    """`"choice"`: one QComboBox, items in declaration order, the single true
    entry preselected."""

    def setUp(self):
        self.widgets, self.layout = _build()
        self.combo = self.widgets["preview_format"]

    def test_is_a_combobox(self):
        self.assertIsInstance(self.combo, qt.QComboBox)

    def test_items_are_the_choice_keys_in_declaration_order(self):
        self.assertEqual([self.combo.itemText(i) for i in range(self.combo.count())], ["csv", "json"])

    def test_initial_selection_is_the_true_entry(self):
        self.assertEqual(self.combo.currentText, "csv")
        self.assertEqual(formgen.collect(self.widgets)["preview_format"], "csv")

    def test_reads_back_the_selected_option_name(self):
        self.combo.setCurrentText("json")

        self.assertEqual(formgen.collect(self.widgets)["preview_format"], "json")

    def test_selection_is_sent_in_clear(self):
        self.combo.setCurrentText("json")
        data = ToolServerClient._stringify(formgen.collect(self.widgets))

        self.assertEqual(data["preview_format"], "json")

    def test_true_entry_is_preselected_wherever_it_sits(self):
        # Nothing may assume the default is the first option.
        spec = {"type": "choice", "choices": {"a": False, "b": False, "c": True}}
        widget = formgen._make_widget("k", spec)

        self.assertEqual(widget.currentText, "c")

    def test_description_becomes_the_tooltip(self):
        self.assertEqual(self.combo.toolTip(), "Format of the preview file")


class MultiChoiceWidgetTest(unittest.TestCase):
    """`"multichoice"`: one QCheckBox per option, in declaration order, each
    starting at its declared boolean."""

    def setUp(self):
        self.widgets, self.layout = _build()
        self.group = self.widgets["outputs"]

    def test_is_a_multichoice_group(self):
        self.assertIsInstance(self.group, formgen.MultiChoiceGroup)

    def test_one_checkbox_per_option_in_declaration_order(self):
        self.assertEqual(list(self.group.boxes), ["summary", "preview", "columns"])
        for box in self.group.boxes.values():
            self.assertIsInstance(box, qt.QCheckBox)

    def test_checkboxes_are_laid_out_in_declaration_order(self):
        laid_out = self.group.container.layout.widgets
        self.assertEqual([box.text for box in laid_out], ["summary", "preview", "columns"])

    def test_initial_state_matches_the_declared_booleans(self):
        self.assertEqual(
            [self.group.boxes[option].isChecked() for option in ("summary", "preview", "columns")],
            [True, True, False],
        )

    def test_reads_back_the_full_state_after_toggling(self):
        self.group.boxes["preview"].setChecked(False)
        self.group.boxes["columns"].setChecked(True)

        self.assertEqual(
            formgen.collect(self.widgets)["outputs"],
            {"summary": True, "preview": False, "columns": True},
        )

    def test_every_option_is_reported_even_when_none_is_checked(self):
        # Server-side, what is sent *is* the selection: an option left out of
        # the payload counts as unchecked whatever its declared default, and
        # omitting the argument entirely is what applies the defaults. So
        # "everything unchecked" has to be spelled out in full, not dropped.
        for box in self.group.boxes.values():
            box.setChecked(False)

        self.assertEqual(
            formgen.collect(self.widgets)["outputs"],
            {"summary": False, "preview": False, "columns": False},
        )

    def test_description_becomes_the_tooltip(self):
        self.assertEqual(self.group.container.toolTip(), "Which result files to produce")


class MultiChoiceEncodingTest(unittest.TestCase):
    """How the checkbox state reaches the wire (client._stringify)."""

    def setUp(self):
        self.widgets, _ = _build()
        self.group = self.widgets["outputs"]

    def test_sent_as_json(self):
        self.group.boxes["preview"].setChecked(False)
        self.group.boxes["columns"].setChecked(True)

        data = ToolServerClient._stringify(formgen.collect(self.widgets))

        self.assertEqual(
            json.loads(data["outputs"]),
            {"summary": True, "preview": False, "columns": True},
        )

    def test_json_uses_lowercase_booleans_not_python_repr(self):
        data = ToolServerClient._stringify(formgen.collect(self.widgets))

        self.assertIn('"summary": true', data["outputs"])
        self.assertNotIn("True", data["outputs"])

    def test_all_unchecked_is_not_an_empty_field(self):
        for box in self.group.boxes.values():
            box.setChecked(False)

        data = ToolServerClient._stringify(formgen.collect(self.widgets))

        self.assertEqual(json.loads(data["outputs"]), {"summary": False, "preview": False, "columns": False})

    def test_option_name_containing_a_comma_survives(self):
        # Why JSON and not the server's `a,b` shortcut: that spelling is for
        # curl and cannot represent an option name with a comma in it.
        group = formgen.MultiChoiceGroup({"a,b": True, "c": False})

        payload = ToolServerClient._stringify({"outputs": group.value()})["outputs"]

        self.assertEqual(json.loads(payload), {"a,b": True, "c": False})


class OtherArgumentTypesTest(unittest.TestCase):
    """`choices: null` arguments must produce neither of the two new widgets."""

    def setUp(self):
        self.widgets, self.layout = _build()

    def test_str_int_float_are_unchanged(self):
        self.assertIsInstance(self.widgets["label"], qt.QLineEdit)
        self.assertIsInstance(self.widgets["threshold"], qt.QDoubleSpinBox)
        self.assertIsInstance(self.widgets["iterations"], qt.QSpinBox)

    def test_no_choice_widget_for_a_null_choices_argument(self):
        for name in ("label", "threshold", "iterations"):
            widget = self.widgets[name]
            self.assertNotIsInstance(widget, qt.QComboBox, name)
            self.assertNotIsInstance(widget, qt.QCheckBox, name)
            self.assertNotIsInstance(widget, formgen.MultiChoiceGroup, name)

    def test_file_argument_is_not_a_generated_field(self):
        # "input" is provided by base_widget from FILE_INPUTS, not by build().
        self.assertNotIn("input", self.widgets)

    def test_every_other_argument_gets_exactly_one_row(self):
        self.assertEqual(
            [name for name, _spec in EXAMPLE_TOOL_SCHEMA["arguments"].items() if name != "input"],
            list(self.widgets),
        )
        self.assertEqual(len(self.layout.rows), len(self.widgets))

    def test_collect_returns_one_entry_per_generated_field(self):
        collected = formgen.collect(self.widgets)

        self.assertEqual(set(collected), set(self.widgets))
        self.assertEqual(collected["label"], "")
        self.assertEqual(collected["threshold"], 0.0)

    def test_required_flag_drives_the_apply_button(self):
        arguments = EXAMPLE_TOOL_SCHEMA["arguments"]
        self.assertFalse(formgen.all_required_filled(self.widgets, arguments))  # "label" still empty

        self.widgets["label"].setText("run-1")

        self.assertTrue(formgen.all_required_filled(self.widgets, arguments))


class MultiChoiceRequiredTest(unittest.TestCase):
    def test_an_all_unchecked_required_multichoice_still_counts_as_filled(self):
        schema = {"outputs": {"type": "multichoice", "required": True, "choices": {"a": False, "b": False}}}
        layout = qt.QFormLayout()
        widgets = formgen.build(schema, layout)

        self.assertTrue(formgen.all_required_filled(widgets, schema))


class ChangeSignalTest(unittest.TestCase):
    def setUp(self):
        self.widgets, _ = _build()
        self.calls = []

    def test_toggling_any_checkbox_notifies(self):
        formgen.connect_changed(self.widgets["outputs"], lambda *_a: self.calls.append(1))

        self.widgets["outputs"].boxes["columns"].setChecked(True)

        self.assertEqual(len(self.calls), 1)

    def test_changing_the_choice_notifies(self):
        formgen.connect_changed(self.widgets["preview_format"], lambda *_a: self.calls.append(1))

        self.widgets["preview_format"].setCurrentText("json")

        self.assertEqual(len(self.calls), 1)


class AutoFileModeTest(unittest.TestCase):
    """The one rule deciding what a file argument's picker looks like — and,
    downstream, whether base_widget zips the selection before uploading."""

    def test_folder_plus_a_file_type_offers_both(self):
        self.assertEqual(formgen.auto_file_mode(EXAMPLE_TOOL_SCHEMA["arguments"]["input"]), "file_or_folder")

    def test_no_folder_means_a_single_file(self):
        self.assertEqual(formgen.auto_file_mode({"types": ["nifti_file"]}), "single_file")

    def test_folder_only_means_a_zipped_folder(self):
        self.assertEqual(formgen.auto_file_mode({"types": ["folder"]}), "folder_zip")

    def test_an_unknown_argument_falls_back_to_a_single_file(self):
        # What base_widget resolves against when the schema could not be loaded.
        self.assertEqual(formgen.auto_file_mode({}), "single_file")


class FileOrFolderInputTest(unittest.TestCase):
    """The `input` argument: `types` = ["csv_file", "folder"] — one path field
    taking either, with the client working out which it got."""

    def setUp(self):
        self.spec = EXAMPLE_TOOL_SCHEMA["arguments"]["input"]
        self.field = formgen.file_widget(self.spec)
        self.work = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.work, True)
        self.csv = os.path.join(self.work, "measurements.csv")
        with open(self.csv, "w") as fh:
            fh.write("a,b\n1,2\n")
        self.folder = os.path.join(self.work, "cohort")
        os.makedirs(self.folder)

    def test_folder_in_types_gives_a_single_field_accepting_both(self):
        self.assertIsInstance(self.field, formgen.FileOrFolderInput)
        self.assertIsInstance(self.field.pathEdit, qt.QLineEdit)

    def test_the_file_dialog_is_restricted_to_the_declared_extensions(self):
        # The extensions still come from `types` — that is the whole point of
        # driving the dialog here rather than letting ctkPathLineEdit do it.
        self.field.fileButton.clicked.emit()

        self.assertIn("*.csv", qt.QFileDialog.last_open_file_args[3])

    def test_nothing_selected_is_not_a_folder(self):
        self.assertEqual(self.field.currentPath, "")
        self.assertFalse(self.field.is_folder())

    def test_a_file_is_detected_as_a_file(self):
        self.field.pathEdit.setText(self.csv)

        self.assertEqual(self.field.currentPath, self.csv)
        self.assertFalse(self.field.is_folder())

    def test_a_folder_is_detected_as_a_folder(self):
        # The user says nothing: picking the path *is* saying which it is.
        self.field.pathEdit.setText(self.folder)

        self.assertTrue(self.field.is_folder())

    def test_a_folder_pasted_into_the_field_is_still_detected(self):
        # A kind selector made this a wrong request: a folder left under
        # "File" was uploaded as a file and failed at open().
        self.field.pathEdit.setText(self.csv)
        self.assertFalse(self.field.is_folder())

        self.field.pathEdit.setText(self.folder)

        self.assertTrue(self.field.is_folder())

    def test_surrounding_whitespace_is_ignored(self):
        # A pasted path often carries a trailing newline or space.
        self.field.pathEdit.setText(f"  {self.folder}\n")

        self.assertEqual(self.field.currentPath, self.folder)
        self.assertTrue(self.field.is_folder())

    def test_a_nonexistent_path_is_not_taken_for_a_folder(self):
        self.field.pathEdit.setText(os.path.join(self.work, "gone"))

        self.assertFalse(self.field.is_folder())

    def test_each_browse_button_fills_the_same_field(self):
        qt.QFileDialog.next_directory = self.folder
        qt.QFileDialog.next_file = self.csv
        self.addCleanup(setattr, qt.QFileDialog, "next_directory", "")
        self.addCleanup(setattr, qt.QFileDialog, "next_file", "")

        self.field.folderButton.clicked.emit()
        self.assertEqual(self.field.currentPath, self.folder)
        self.assertTrue(self.field.is_folder())

        self.field.fileButton.clicked.emit()
        self.assertEqual(self.field.currentPath, self.csv)
        self.assertFalse(self.field.is_folder())

    def test_a_cancelled_dialog_keeps_the_current_selection(self):
        self.field.pathEdit.setText(self.csv)
        qt.QFileDialog.next_directory = ""  # what Qt returns when cancelled
        qt.QFileDialog.next_file = ""

        self.field.folderButton.clicked.emit()
        self.field.fileButton.clicked.emit()

        self.assertEqual(self.field.currentPath, self.csv)

    def test_every_selection_notifies_whatever_its_kind(self):
        # Regression: on a ctkPathLineEdit, a *.csv name filter silences
        # currentPathChanged for every folder (and every non-matching file),
        # so the Apply button would never enable after choosing a folder.
        calls = []
        formgen.connect_changed(self.field, lambda *_a: calls.append(1))
        qt.QFileDialog.next_directory = self.folder
        self.addCleanup(setattr, qt.QFileDialog, "next_directory", "")

        self.field.pathEdit.setText(self.csv)
        self.field.folderButton.clicked.emit()
        self.field.pathEdit.setText(os.path.join(self.work, "other.xlsx"))

        self.assertEqual(len(calls), 3)

    def test_an_explicit_mode_overrides_the_schema_rule(self):
        # SurgMovPred's "input" is typed zip_file and the module still wants a
        # folder picker (it zips it): a declared mode wins over the derived one.
        field = formgen.file_widget({"type": "zip_file", "types": ["zip_file"]}, "folder_zip")

        self.assertIsInstance(field, ctk.ctkPathLineEdit)
        self.assertEqual(field.filters, ctk.ctkPathLineEdit.Dirs)

    def test_a_file_only_argument_gets_a_plain_file_picker(self):
        field = formgen.file_widget({"type": "nifti_file", "types": ["nifti_file"]})

        self.assertIsInstance(field, ctk.ctkPathLineEdit)
        self.assertEqual(field.filters, ctk.ctkPathLineEdit.Files)
        self.assertIn("Supported files (*.nii *.nii.gz)", field.nameFilters)

    def test_a_generic_file_argument_is_left_unrestricted(self):
        field = formgen.file_widget({"type": "file", "types": ["file"]})

        self.assertEqual(field.nameFilters, [])
        self.assertEqual(field.nameFilterAssignments, 0)

    def test_single_kind_pickers_are_configured_once_and_never_touched(self):
        # Regression: re-assigning nameFilters on a live ctkPathLineEdit
        # corrupts it and crashes Slicer, either on the next filters
        # assignment or later at teardown. Every ctkPathLineEdit this module
        # hands out must come fully configured and stay that way.
        for spec, mode in (
            ({"types": ["csv_file"]}, "single_file"),
            ({"types": ["zip_file"]}, "folder_zip"),
            ({"types": ["file"]}, "single_file"),
        ):
            picker = formgen.file_widget(spec, mode)
            self.assertEqual(picker.filterAssignments, 1, mode)
            self.assertLessEqual(picker.nameFilterAssignments, 1, mode)


if __name__ == "__main__":
    unittest.main()

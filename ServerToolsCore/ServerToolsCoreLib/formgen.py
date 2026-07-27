"""Builds Qt widgets from a server tool's argument schema, and reads them back.

Imports neither `requests` nor anything HTTP — see ARCHITECTURE.md dependency
rule. The server is the single source of truth for the schema: adding a field
to a tool server-side makes it appear here without touching any module code.

File-type arguments (any type accepted by `is_file_type` — "file", "zip_file",
"nifti_file", ...) are skipped by build()/collect(): they are not generic
scalar fields, they are produced by base_widget according to the module's
FILE_INPUTS (see base_widget.py).

Escape hatch: a hand-written .ui can still be used by giving its widgets a Qt
dynamic property named "serverArgName" matching the schema argument name —
collect() will pick them up as if they had been generated. Not used by
SurgMovPred; documented for future modules that need custom layout.
"""

import logging

import ctk
import qt

from . import design, is_file_type

logger = logging.getLogger("ServerToolsCore.formgen")

ARG_NAME_PROPERTY = "serverArgName"


def build(arguments_schema: dict, layout) -> dict:
    """Add one row per non-file argument to `layout` (a qt.QFormLayout). Returns
    {arg_name: widget}."""
    widgets = {}
    for name, spec in arguments_schema.items():
        if is_file_type(spec.get("type", "")):
            continue

        widget = _make_widget(name, spec)
        widget.setProperty(ARG_NAME_PROPERTY, name)
        description = spec.get("description")
        if description:
            widget.setToolTip(description)

        label = design.required_label(name) if spec.get("required") else design.section_title(name)
        layout.addRow(label, widget)
        widgets[name] = widget
    return widgets


def _make_widget(name: str, spec: dict):
    arg_type = spec.get("type", "str")

    # A scalar argument flagged server_selectable (e.g. surg_mov_pred's
    # "model": the *name* of a model hosted on the server) is a choice among
    # server-side files, not free text: render a dropdown. base_widget
    # populates it from GET /tools/{tool}/data once the schema is known —
    # formgen itself never talks HTTP (dependency rule, see ARCHITECTURE.md).
    if spec.get("server_selectable"):
        return qt.QComboBox()

    if arg_type == "str":
        return qt.QLineEdit()
    if arg_type == "int":
        widget = qt.QSpinBox()
        widget.setRange(-2147483648, 2147483647)
        return widget
    if arg_type == "float":
        widget = qt.QDoubleSpinBox()
        widget.setRange(-1e12, 1e12)
        widget.setDecimals(6)
        return widget
    if arg_type == "bool":
        return qt.QCheckBox()
    if is_file_type(arg_type):
        return ctk.ctkPathLineEdit()

    logger.warning("Unknown argument type '%s' for '%s', falling back to QLineEdit", arg_type, name)
    return qt.QLineEdit()


def collect(arg_widgets: dict) -> dict:
    return {name: _read_widget(widget) for name, widget in arg_widgets.items()}


def _read_widget(widget):
    if isinstance(widget, qt.QCheckBox):
        return widget.isChecked()
    if isinstance(widget, qt.QComboBox):
        # "" while the server-side list hasn't been loaded (or is empty) —
        # which keeps all_required_filled() False and the Apply button disabled.
        return widget.currentText
    if isinstance(widget, (qt.QSpinBox, qt.QDoubleSpinBox)):
        return widget.value
    if isinstance(widget, ctk.ctkPathLineEdit):
        return widget.currentPath
    if isinstance(widget, qt.QLineEdit):
        return widget.text
    raise TypeError(f"Don't know how to read value from widget {widget!r}")


def all_required_filled(arg_widgets: dict, arguments_schema: dict) -> bool:
    for name, spec in arguments_schema.items():
        if is_file_type(spec.get("type", "")) or not spec.get("required"):
            continue
        widget = arg_widgets.get(name)
        if widget is None:
            return False
        value = _read_widget(widget)
        if value in ("", None):
            return False
    return True


def connect_changed(widget, callback) -> None:
    if isinstance(widget, qt.QCheckBox):
        widget.toggled.connect(callback)
    elif isinstance(widget, qt.QComboBox):
        widget.currentTextChanged.connect(callback)
    elif isinstance(widget, (qt.QSpinBox, qt.QDoubleSpinBox)):
        widget.valueChanged.connect(callback)
    elif isinstance(widget, ctk.ctkPathLineEdit):
        widget.currentPathChanged.connect(callback)
    elif isinstance(widget, qt.QLineEdit):
        widget.textChanged.connect(callback)
    else:
        logger.warning("Don't know how to connect change signal for widget %r", widget)

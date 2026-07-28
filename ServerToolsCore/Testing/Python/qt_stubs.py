"""Minimal stand-ins for `qt`, `ctk` and `slicer`, so the GUI-facing parts of
ServerToolsCoreLib can be unit-tested outside Slicer.

Only what `formgen` (and the `design` module it pulls in) actually touches is
implemented — enough to assert *which* widgets a schema produces, in which
order, with which initial state, and what they read back as. This obviously
tests the schema-to-widget logic, not Qt itself; the Qt calls it makes are the
same ones the previously shipped widgets already used.

Call `install()` before importing ServerToolsCoreLib.formgen.
"""

import sys
import types


class Signal:
    def __init__(self):
        self._slots = []

    def connect(self, slot):
        self._slots.append(slot)

    def emit(self, *args):
        for slot in list(self._slots):
            slot(*args)


class QObject:
    def __init__(self, *_args, **_kwargs):
        self._properties = {}
        self._tooltip = ""
        self._stylesheet = ""
        self._visible = True

    def setVisible(self, visible):
        self._visible = bool(visible)

    def isVisible(self):
        return self._visible

    def setProperty(self, name, value):
        self._properties[name] = value

    def property(self, name):
        return self._properties.get(name)

    def setToolTip(self, text):
        self._tooltip = text

    def toolTip(self):
        return self._tooltip

    def setStyleSheet(self, sheet):
        self._stylesheet = sheet


class QWidget(QObject):
    def __init__(self, parent=None):
        QObject.__init__(self)
        self.parent = parent
        self.layout = None


class QLayout(QObject):
    def __init__(self, parent=None):
        QObject.__init__(self)
        self.widgets = []
        if parent is not None:
            parent.layout = self

    def setContentsMargins(self, *_margins):
        pass

    def setSpacing(self, _spacing):
        pass

    def addWidget(self, widget, stretch=0):
        self.widgets.append(widget)


class QVBoxLayout(QLayout):
    pass


class QHBoxLayout(QLayout):
    pass


class QFileDialog:
    """Test seam: `next_file`/`next_directory` are what the static helpers
    return, so a test can drive the browse buttons without a real (modal)
    dialog, and inspect the arguments they were called with — the file
    dialog's filter string among them."""

    next_file = ""
    next_directory = ""
    last_open_file_args = None
    last_existing_directory_args = None

    @staticmethod
    def getOpenFileName(*args, **_kwargs):
        QFileDialog.last_open_file_args = args
        return QFileDialog.next_file

    @staticmethod
    def getExistingDirectory(*args, **_kwargs):
        QFileDialog.last_existing_directory_args = args
        return QFileDialog.next_directory


class QFormLayout(QLayout):
    def __init__(self, parent=None):
        QLayout.__init__(self, parent)
        self.rows = []  # [(label, widget)]

    def addRow(self, label, widget):
        self.rows.append((label, widget))
        self.widgets.append(widget)


class QLabel(QObject):
    def __init__(self, text=""):
        QObject.__init__(self)
        self.text = text

    def setText(self, text):
        self.text = text

    def setWordWrap(self, _wrap):
        pass


class QPushButton(QObject):
    def __init__(self, text=""):
        QObject.__init__(self)
        self.text = text
        self.clicked = Signal()


class QLineEdit(QObject):
    def __init__(self, text=""):
        QObject.__init__(self)
        self._text = text
        self.placeholderText = ""
        self.textChanged = Signal()

    def setPlaceholderText(self, text):
        self.placeholderText = text

    @property
    def text(self):
        return self._text

    @text.setter
    def text(self, value):
        self._text = value
        self.textChanged.emit(value)

    def setText(self, value):
        self.text = value


class QCheckBox(QObject):
    def __init__(self, text=""):
        QObject.__init__(self)
        self.text = text
        self._checked = False
        self.toggled = Signal()

    def setChecked(self, checked):
        self._checked = bool(checked)
        self.toggled.emit(self._checked)

    def isChecked(self):
        return self._checked


class QComboBox(QObject):
    def __init__(self):
        QObject.__init__(self)
        self._items = []
        self._index = -1
        self.currentTextChanged = Signal()

    def addItems(self, items):
        self._items.extend(items)
        if self._index < 0 and self._items:
            self.setCurrentIndex(0)

    def addItem(self, item):
        self.addItems([item])

    def clear(self):
        self._items = []
        self._index = -1

    @property
    def count(self):
        # A property, not a method: PythonQt exposes a Qt property whose getter
        # shares its name as an attribute, and it shadows the method — real
        # Slicer raises "'int' object is not callable" on `combo.count()`.
        return len(self._items)

    def itemText(self, index):
        return self._items[index]

    @property
    def currentIndex(self):
        return self._index

    def setCurrentIndex(self, index):
        self._index = index
        self.currentTextChanged.emit(self.currentText)

    @property
    def currentText(self):
        if 0 <= self._index < len(self._items):
            return self._items[self._index]
        return ""

    def setCurrentText(self, text):
        self.setCurrentIndex(self._items.index(text))


class QSpinBox(QObject):
    def __init__(self):
        QObject.__init__(self)
        self.value = 0
        self.minimum = 0
        self.maximum = 99
        self.valueChanged = Signal()

    def setRange(self, minimum, maximum):
        self.minimum, self.maximum = minimum, maximum

    def setValue(self, value):
        self.value = value
        self.valueChanged.emit(value)


class QDoubleSpinBox(QSpinBox):
    def __init__(self):
        QSpinBox.__init__(self)
        self.value = 0.0
        self.decimals = 2

    def setDecimals(self, decimals):
        self.decimals = decimals


class QPalette:
    Window = 0


class ctkPathLineEdit(QObject):
    """Counts assignments to `filters`/`nameFilters`.

    Reconfiguring a real, live ctkPathLineEdit corrupts it and crashes Slicer
    (see formgen.path_widget); the counters let a test assert each picker is
    configured exactly once, at construction, and never again.
    """

    Files = 1
    Dirs = 2

    def __init__(self):
        QObject.__init__(self)
        self._path = ""
        self._filters = ctkPathLineEdit.Files
        self._name_filters = []
        self.filterAssignments = 0
        self.nameFilterAssignments = 0
        self.currentPathChanged = Signal()

    @property
    def filters(self):
        return self._filters

    @filters.setter
    def filters(self, value):
        self._filters = value
        self.filterAssignments += 1

    @property
    def nameFilters(self):
        return self._name_filters

    @nameFilters.setter
    def nameFilters(self, value):
        self._name_filters = value
        self.nameFilterAssignments += 1

    @property
    def currentPath(self):
        return self._path

    @currentPath.setter
    def currentPath(self, value):
        self._path = value
        self.currentPathChanged.emit(value)


class ctkCollapsibleButton(QWidget):
    def __init__(self):
        QWidget.__init__(self)
        self.text = ""


def install():
    """Register the fake `qt`, `ctk` and `slicer` modules in sys.modules.

    `slicer` is deliberately empty: `design.is_dark_mode()` reaches for
    `slicer.app.palette()` inside a try/except, so the missing attribute makes
    it fall back to the light palette — which is all these tests need.
    """
    qt = types.ModuleType("qt")
    for name, value in globals().items():
        if name.startswith("Q") or name == "Signal":
            setattr(qt, name, value)

    ctk = types.ModuleType("ctk")
    ctk.ctkPathLineEdit = ctkPathLineEdit
    ctk.ctkCollapsibleButton = ctkCollapsibleButton

    sys.modules.setdefault("qt", qt)
    sys.modules.setdefault("ctk", ctk)
    sys.modules.setdefault("slicer", types.ModuleType("slicer"))
    return qt, ctk

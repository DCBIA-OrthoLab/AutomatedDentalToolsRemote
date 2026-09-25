"""An argument that draws from one subfolder, not from the tool's whole catalogue.

A tool can serve several modalities -- AREG registers CBCT volumes, intraoral
surfaces, and one onto the other -- and the hosted-file list is published per
TOOL. Flat, every argument was offered every cohort: the CBCT baseline picker
listed the intraoral meshes, and picking one sends a folder of `.vtk` where a
volume is expected.

The server now publishes a subfolder on the argument and a list per subfolder
beside the flat one. What this pins is the client half: the scoped argument
reads its own list, an unscoped one reads the flat list exactly as before, and
a scope the server did not send falls back rather than emptying the picker.
"""

import os
import sys
import unittest

_HERE = os.path.abspath(os.path.dirname(__file__))
_CORE = os.path.abspath(os.path.join(_HERE, "..", ".."))
sys.path.insert(0, _HERE)
sys.path.insert(0, _CORE)

import test_hosted_test_files as fixtures  # noqa: E402,F401 - installs the stubs

from ServerToolsCoreLib.base_widget import ServerToolWidgetBase  # noqa: E402

DATA = {
    "testfiles": ["CBCT", "IOS"],
    "scoped": {
        "CBCT": {"testfiles": ["CBCT_FullyAuto", "CBCT_SemiAuto"], "models": []},
        "IOS": {"testfiles": ["IOS_test_scans"], "models": []},
    },
}


class _Combo:
    def __init__(self):
        self.items = []
        self.currentText = ""

    def clear(self):
        self.items = []

    def addItems(self, items):
        self.items.extend(items)

    def setCurrentIndex(self, index):
        self.currentText = self.items[index]


class ScopedHostedFilesTest(unittest.TestCase):
    def _panel(self, spec):
        panel = ServerToolWidgetBase.__new__(ServerToolWidgetBase)
        panel._schema = {"arguments": {"t1": dict(spec, required=False)}}
        panel._inputWidgets = {}
        panel._argWidgets = {"t1": _Combo()}
        return panel

    def test_a_scoped_argument_is_offered_only_its_own_folder(self):
        panel = self._panel({"server_selectable": "testfile", "selectable_scope": "CBCT"})

        panel._fillServerSelectable("t1", "testfile", DATA)

        assert "IOS_test_scans" not in panel._argWidgets["t1"].items
        assert "CBCT_FullyAuto" in panel._argWidgets["t1"].items

    def test_an_unscoped_argument_reads_the_flat_list(self):
        """Every deployment that scopes nothing, which is all of them until one
        says otherwise."""
        panel = self._panel({"server_selectable": "testfile"})

        panel._fillServerSelectable("t1", "testfile", DATA)

        assert "CBCT" in panel._argWidgets["t1"].items

    def test_a_scope_the_server_did_not_send_falls_back(self):
        """A panel built against a newer schema than the server it is talking
        to must not show an empty picker with no explanation."""
        panel = self._panel({"server_selectable": "testfile", "selectable_scope": "MRI"})

        panel._fillServerSelectable("t1", "testfile", DATA)

        assert "CBCT" in panel._argWidgets["t1"].items


if __name__ == "__main__":
    unittest.main()

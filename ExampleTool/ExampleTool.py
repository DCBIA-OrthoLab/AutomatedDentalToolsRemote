from slicer.i18n import tr as _
from slicer.ScriptedLoadableModule import ScriptedLoadableModule

from ServerToolsCoreLib.base_widget import ServerToolWidgetBase


class ExampleTool(ScriptedLoadableModule):
    """Uses ScriptedLoadableModule base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = _("Example Tool")
        self.parent.categories = ["Automated Dental Tools.Advanced"]
        self.parent.dependencies = ["ServerToolsCore"]
        self.parent.contributors = ["Jules Grivot Pelisson, University of North Carolina, Chapel Hill"]
        self.parent.helpText = _("""
        Reference client for the tool server's <code>example_tool</code>: it exercises every
        argument shape the schema-driven UI supports (free text, int, float, a single-choice
        dropdown, a multi-choice checkbox group, and an input accepting either a .csv file or a
        whole folder), and returns several result files as one archive.
        Useful to check a server connection end to end without running a real analysis.
        See more information in <a href="https://github.com/DCBIA-OrthoLab/SlicerAutomatedDentalTools">documentation</a>.
        """)
        self.parent.acknowledgementText = ""


class ExampleToolWidget(ServerToolWidgetBase):
    """Thin GUI: everything else (HTTP, async, form generation, styling, lifecycle)
    lives in ServerToolsCoreLib. See ARCHITECTURE.md."""

    TOOL_NAME = "example_tool"
    # "auto": the schema says `input` accepts ["csv_file", "folder"], so the
    # panel takes either — one path field with a File and a Folder browse
    # button — and works out which it was given, zipping a folder before
    # uploading. Nothing here names a type, an extension, or a mode.
    FILE_INPUTS = {"input": "auto"}
    # output_kind "files": several result files arrive as one .zip, unpacked
    # into the output folder the user picks (see _handleSaveAsResult).
    RESULT_KIND = "save_as"
    AUTO_UI = True

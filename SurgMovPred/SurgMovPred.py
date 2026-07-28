from slicer.i18n import tr as _
from slicer.ScriptedLoadableModule import ScriptedLoadableModule

from ServerToolsCoreLib.base_widget import ServerToolWidgetBase


class SurgMovPred(ScriptedLoadableModule):
    """Uses ScriptedLoadableModule base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = _("SurgMovPred")
        self.parent.categories = ["Automated Dental Tools"]
        self.parent.dependencies = ["ServerToolsCore"]
        self.parent.contributors = ["Paul Dumont, University of North Carolina, Chapel Hill"]
        self.parent.helpText = _("""
        Predicts surgical movement outcomes from cephalometric measurements, computed by a
        model served remotely by the Automated Dental Tools server.
        See more information in <a href="https://github.com/DCBIA-OrthoLab/SlicerAutomatedDentalTools">documentation</a>.
        """)
        self.parent.acknowledgementText = _("""
        This file was originally developed by Jean-Christophe Fillion-Robin, Kitware Inc., Andras Lasso, PerkLab,
        and Steve Pieper, Isomics, Inc. and was partially funded by NIH grant 3P41RR013218-12S1.
        """)


class SurgMovPredWidget(ServerToolWidgetBase):
    """Thin GUI: everything else (HTTP, async, form generation, styling, lifecycle)
    lives in ServerToolsCoreLib. See ARCHITECTURE.md."""

    TOOL_NAME = "SurgMovPred"
    # Both attributes below are overrides — the two things this tool's schema
    # cannot state. Everything else is derived from it: "model" is declared as
    # a server_selectable str, so the auto-UI renders it as a dropdown filled
    # from GET /tools/SurgMovPred/data and sends the chosen model's *name* —
    # no model file ever leaves or reaches this machine.
    #
    # The server types "input" as a plain zip_file, so it would get a file
    # picker; what the user actually has is a folder of measurement files, and
    # zipping it is the client's job.
    FILE_INPUTS = {"input": "folder_zip"}
    # output_kind is "file", which says a file comes back but not what to do
    # with it: save it, rather than load it into the scene.
    RESULT_KIND = "save_as"
    AUTO_UI = True

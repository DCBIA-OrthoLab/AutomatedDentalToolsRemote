from slicer.i18n import tr as _
from slicer.ScriptedLoadableModule import ScriptedLoadableModule


class ServerToolsCore(ScriptedLoadableModule):
    """Hidden module. Its only purpose is to make ServerToolsCoreLib importable
    as `from ServerToolsCoreLib import ...` by every other scripted module in
    this extension — see ARCHITECTURE.md.
    """

    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = _("Server Tools Core")
        self.parent.categories = ["Automated Dental Tools.Advanced"]
        self.parent.dependencies = []
        self.parent.contributors = ["Automated Dental Tools team"]
        self.parent.hidden = True
        self.parent.helpText = _(
            "Shared infrastructure for remote-server-backed tools: HTTP client, async "
            "execution, schema-driven GUI generation and shared styling. Not user-facing "
            "— see ARCHITECTURE.md at the repository root."
        )
        self.parent.acknowledgementText = ""

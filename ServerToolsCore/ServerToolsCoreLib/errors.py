"""Error types for the tool server client.

Imports neither `slicer` nor `qt` — see ARCHITECTURE.md dependency rule.
"""


class ServerToolError(Exception):
    """A presentable failure while talking to the tool server."""

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def error_for_status(status_code, server_message=None):
    """Map an HTTP status code to a ServerToolError with a user-facing message.

    The server's own `detail` is shown verbatim whenever it sends one — it is
    consistently the more specific message, and for the argument errors it is
    the only one that can be: 422 names the offending argument and, for an
    option outside a `choice`/`multichoice` list, spells out what was expected
    ("Argument 'preview_format': unknown option 'xml'. Expected one of: csv,
    json"). Nothing here second-guesses or rewrites it. The strings below are
    fallbacks for a response with no usable body.

    500 is the exception: a crash inside a tool is not a message meant for the
    user, and its detail may leak server-side internals.
    """
    if status_code == 401:
        return ServerToolError(server_message or "Authentication failed.", status_code)
    if status_code == 404:
        return ServerToolError("Unknown tool. Refresh the tool list and check the name.", status_code)
    if status_code == 422:
        return ServerToolError(server_message or "Invalid arguments.", status_code)
    if status_code == 400:
        return ServerToolError(server_message or "Disallowed file type.", status_code)
    if status_code == 413:
        return ServerToolError(server_message or "File too large for the server.", status_code)
    if status_code == 500:
        return ServerToolError("The tool failed on the server.", status_code)
    return ServerToolError(server_message or f"Server error ({status_code}).", status_code)

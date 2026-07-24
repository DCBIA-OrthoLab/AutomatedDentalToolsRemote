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

    For 400/422 the server message is already explicit and is propagated verbatim,
    per the API contract. Other codes get a generic application-level message.
    """
    if status_code == 401:
        return ServerToolError("Authentication failed.", status_code)
    if status_code == 404:
        return ServerToolError("Unknown tool. Refresh the tool list and check the name.", status_code)
    if status_code == 422:
        return ServerToolError(server_message or "Invalid arguments.", status_code)
    if status_code == 400:
        return ServerToolError(server_message or "Disallowed file type.", status_code)
    if status_code == 413:
        return ServerToolError("File too large for the server.", status_code)
    if status_code == 500:
        return ServerToolError("The tool failed on the server.", status_code)
    return ServerToolError(server_message or f"Server error ({status_code}).", status_code)

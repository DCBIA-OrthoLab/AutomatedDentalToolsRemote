"""Static configuration for the tool server client.

Token and URL are constants here on purpose: this project settled on hard-coded
config over environment variables (see ARCHITECTURE.md). Do not commit a real
production token — override these locally, or replace them at build time.
"""

SERVER_URL = "http://localhost:8000"
API_TOKEN = "dev-token"
VERIFY_TLS = False
TIMEOUT = 600

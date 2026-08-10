"""Static configuration for the tool server client.

Token and URL are constants here on purpose: this project settled on hard-coded
config over environment variables (see ARCHITECTURE.md). Do not commit a real
production token — override these locally, or replace them at build time.
"""

SERVER_URL = "http://localhost:8000"
API_TOKEN = "dev-token"
VERIFY_TLS = False
TIMEOUT = 600

# How many connections a single file's transfer uses at once (see transfer.py).
# This is what makes a remote server usable: one TCP stream over a long-haul
# link plateaus at a fraction of the available bandwidth because of its
# congestion window, and four streams multiply that by roughly four. On a LAN
# it changes little and costs nothing. Set to 1 to go back to one stream.
TRANSFER_PARALLELISM = 4

# Size of one part, in megabytes. The server clamps this to [1, 64] and answers
# with what it actually used. Smaller parts recover faster from a dropped
# connection; larger ones amortise the per-request overhead.
TRANSFER_CHUNK_MB = 8

# Whether to gzip parts of files that are not already compressed (an
# uncompressed .nii, a .vtk mesh) on the way up. Roughly a third of the bytes,
# so roughly a third of the time on a remote link, for cheap level-1
# compression spread across the transfer threads. Already-compressed inputs
# (.nii.gz, .zip, ...) are never touched. Turn off on a fast LAN with a slow
# client machine, where the CPU is the scarcer resource.
TRANSFER_COMPRESS = True

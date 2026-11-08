"""The web interface of the coding agent: FastAPI, SSE and a browser UI.

Nothing here imports FastAPI at module level, so that the web interface stays an
optional extra: `coderagent.web.__init__` is safe to import without it.
"""

"""Constants used throughout the Agentic Inquiry library.

This module contains system-wide constants to avoid magic strings
and improve code maintainability.
"""

# Project ID Constants
# ---------------------
# Special value indicating to use the current/configured project_id
# from the component's context (e.g., LanceDBManager._project_id)
CURRENT_PROJECT_ID = "current"

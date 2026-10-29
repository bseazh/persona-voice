# Voice worker

This directory is reserved for the real LiveKit worker. The currently deployed web/API service is mock-only. Before adding dispatch, validate the installed LiveKit SDK against upstream commit `608f4c7055c3e3307a98187cfdf74b77eeac8600`, configure providers locally in `.env.local`, and complete `MANUAL_SETUP.md`.

The upstream source is intentionally referenced rather than copied and silently modified. Its current `EnglishModel()` is not appropriate evidence of Chinese turn detection support.


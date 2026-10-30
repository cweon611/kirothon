"""Static seed data as Python modules, each exposing ``DATA``.

These are .py (not .json) because scripts/deploy.ps1 and ops/deploy.py ship only
.py files under backend/app; JSON files there never reach the server.
"""

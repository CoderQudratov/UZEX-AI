"""Offline CLI: invoke with the installed project Python; no user request input."""

from app.db.build import main

if __name__ == "__main__":
    raise SystemExit(main())

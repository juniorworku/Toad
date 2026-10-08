# Regression coverage

Run `.venv/bin/python -m pytest server/tests -q` from the repository root. The first batch has 33 passing cases across device integration, coordinator lifecycle/audio/camera, persistent state and explicit memory permission. Services and clocks are injected; no API credentials or paid services are used. These are initial cases, not a complete replacement of all 42 Desku server test declarations.

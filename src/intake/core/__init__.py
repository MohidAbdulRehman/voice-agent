"""Framework-free domain layer: models, validation, spoken forms, persistence and services.

Both the REST API and the voice agent go through this package for every read and
write. It must never import FastAPI or LiveKit (enforced by tests/unit/test_layering.py).
"""

"""Signing and submission layer — interface plus a mock, and nothing else.

No real backend exists in this repository. See ``interface.py`` for what one
would require and why it is deliberately absent.
"""

from .interface import (
    AcceptanceMessageType,
    SubmissionBackend,
    SubmissionReceipt,
    SubmissionState,
)
from .mock import MockSubmissionBackend

__all__ = [
    "AcceptanceMessageType",
    "SubmissionBackend",
    "SubmissionReceipt",
    "SubmissionState",
    "MockSubmissionBackend",
]

#: Every backend registered here must be a mock. The test suite asserts this.
AVAILABLE_BACKENDS: dict[str, type[SubmissionBackend]] = {
    "mock": MockSubmissionBackend,
}


def get_backend(name: str = "mock") -> SubmissionBackend:
    """Return a submission backend by name. Only ``"mock"`` exists."""
    if name not in AVAILABLE_BACKENDS:
        raise ValueError(
            f"Unknown backend '{name}'. This repository ships mock backends only: "
            f"{sorted(AVAILABLE_BACKENDS)}"
        )
    backend = AVAILABLE_BACKENDS[name]()
    if not backend.is_mock:
        raise RuntimeError(
            "A non-mock submission backend was registered. This repository must "
            "not contain one."
        )
    return backend

"""Submission interface — DEFINITION ONLY. NOTHING HERE TALKS TO ANYTHING.

===========================================================================
THIS MODULE IS INTENTIONALLY NON-FUNCTIONAL. THAT IS THE FEATURE.
===========================================================================
This file declares the *shape* of a signing-and-submission layer. It declares no
implementation of one. The only concrete implementation in this repository is
``mock.py``, which returns canned responses from a dictionary.

Specifically, this repository contains:

  * no cryptographic key, of any kind, in any format
  * no code that loads, parses, decrypts or uses a key file
  * no HTTP client, no socket, no URL for any Hacienda endpoint
  * no XML signing implementation
  * no credentials, no PIN, no certificate path, no environment variable that
    would supply any of the above

Those absences are load-bearing. A repository that demonstrates deadline
tracking over synthetic data has no business being one dependency away from
transmitting a document to a tax authority, and this one is not: there is no
network call to redirect and no key to point at a real certificate. Making it
capable of real submission would mean writing the signing and transport layers
from scratch, not flipping a flag.

WHAT A REAL IMPLEMENTATION WOULD NEED
=====================================
Documented so the gap is explicit, not so it can be closed here.

1. **A cryptographic key issued by Hacienda.** Costa Rica issues each taxpayer a
   *llave criptográfica* through the tax administration's own channel, protected
   by a PIN. Every electronic document must be signed with it (XAdES) before it
   is accepted. Obtaining one requires being the registered taxpayer or their
   authorised representative. It is not something a project acquires; it is
   something a business is issued.

2. **XML construction to the v4.4 schema.** Not the flattened model in
   ``models.py`` — the real, namespaced, element-ordered XML the schema
   requires, including the acceptance-message schema (``MensajeReceptor``) which
   is a different document from an invoice.

3. **XAdES-EPES signing.** Enveloped signature with the policy identifier
   Hacienda's resolution specifies. Signature placement and canonicalisation are
   both strict; an otherwise-valid document with a signature in the wrong place
   is rejected.

4. **API connection details.** Authentication and the reception endpoints, per
   the technical annex governing the API (the annex covering API connection is
   the operative reference). Environments are separated into sandbox and
   production and the credentials differ.

5. **An asynchronous result model.** Submission is accepted for processing and
   answered later; the caller has to poll for the definitive state rather than
   trusting the acknowledgement. Any real implementation needs durable storage
   of in-flight submissions and a retry policy that cannot double-submit.

6. **A rejection-handling path.** ``rechazado`` is a normal outcome, not an
   error condition, and it has to feed back into the deadline engine: a rejected
   document does not stop the clock.

None of that is implemented here, and this file exists so that fact is written
down rather than inferred.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class SubmissionState(str, Enum):
    """States a submitted document can be in."""

    BUILT = "BUILT"
    SIGNED = "SIGNED"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACEPTADO"
    PARTIALLY_ACCEPTED = "ACEPTADO_PARCIAL"
    REJECTED = "RECHAZADO"
    ERROR = "ERROR"


class AcceptanceMessageType(str, Enum):
    """The three confirmation messages a receiver can send.

    These are the actual decision a receiver makes inside the eight-business-day
    window. The deadline engine tracks *whether* one was sent in time; which one
    was sent determines how much credit is claimable, not whether the window was
    met.
    """

    FULL_ACCEPTANCE = "1"  # aceptación
    PARTIAL_ACCEPTANCE = "2"  # aceptación parcial
    REJECTION = "3"  # rechazo


@dataclass(frozen=True)
class SubmissionReceipt:
    clave: str
    state: SubmissionState
    submitted_at: datetime | None
    message: str
    is_mock: bool = True
    detail: dict[str, Any] = field(default_factory=dict)


class SubmissionBackend(ABC):
    """The interface a real signing/submission layer would have to satisfy.

    Four steps, in order. Split this way because each has a different failure
    mode and a different owner: building is a schema problem, signing is a key
    custody problem, submitting is a network problem, polling is a state
    problem. Collapsing them into one ``send()`` hides which one broke.
    """

    #: Implementations MUST declare whether they can reach a real tax authority.
    #: Nothing in this repository may set this to ``False``.
    is_mock: bool = True

    @abstractmethod
    def build_xml(self, document: Any, message_type: AcceptanceMessageType) -> bytes:
        """Render an acceptance message to XML bytes."""

    @abstractmethod
    def sign(self, xml_bytes: bytes) -> bytes:
        """Apply the taxpayer's cryptographic signature.

        A real implementation needs a Hacienda-issued key and its PIN. This
        repository has neither, and no implementation here does anything of the
        sort.
        """

    @abstractmethod
    def submit(self, signed_xml: bytes, *, clave: str) -> SubmissionReceipt:
        """Transmit the signed message. Returns an acknowledgement, not a verdict."""

    @abstractmethod
    def poll_status(self, clave: str) -> SubmissionReceipt:
        """Ask for the definitive state of a previously submitted message."""

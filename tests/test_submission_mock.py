"""The submission layer, and the safety properties it exists to guarantee.

These tests are the enforcement mechanism behind the README's "no keys, no live
calls" claim. Several of them read like paranoia — grepping the source tree for
HTTP clients, asserting no backend reports itself as real. That is intentional.
The claim is the reason the repository is publishable, so it should fail loudly
if someone ever weakens it.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from lxml import etree

from fractal_desk.submission import (
    AVAILABLE_BACKENDS,
    AcceptanceMessageType,
    MockSubmissionBackend,
    SubmissionState,
    get_backend,
)
from fractal_desk.submission.mock import MOCK_MARKER, MOCK_SIGNATURE_PREFIX

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"


class FakeDocument:
    clave = "50615072699900001000010000010000000001100012345678"
    issuer_id = "9990000100"
    receiver_id = "9990000001"
    issue_datetime = datetime(2026, 7, 15, 10, 0)
    total_tax = Decimal("26000")
    total_document = Decimal("226000")


@pytest.fixture
def backend():
    return MockSubmissionBackend()


class TestSafetyProperties:
    """The guarantees the README makes, asserted rather than trusted."""

    def test_only_mock_backends_are_registered(self):
        assert set(AVAILABLE_BACKENDS) == {"mock"}

    def test_every_backend_declares_itself_a_mock(self):
        for backend_class in AVAILABLE_BACKENDS.values():
            assert backend_class.is_mock is True

    def test_get_backend_rejects_unknown_names(self):
        with pytest.raises(ValueError):
            get_backend("hacienda")

    def test_package_declares_it_cannot_submit(self):
        import fractal_desk

        assert fractal_desk.CAN_SUBMIT_REAL_DOCUMENTS is False
        assert fractal_desk.ALL_DATA_IS_SYNTHETIC is True

    def test_no_http_client_is_imported_anywhere_in_the_package(self):
        """No transport means no live call is one edit away."""
        forbidden = ("requests", "httpx", "urllib.request", "http.client", "aiohttp", "socket")
        offenders = []
        for path in SRC_ROOT.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            for line in source.splitlines():
                stripped = line.strip()
                if not (stripped.startswith("import ") or stripped.startswith("from ")):
                    continue
                if any(module in stripped for module in forbidden):
                    offenders.append(f"{path.name}: {stripped}")
        assert not offenders, f"transport library imported: {offenders}"

    def test_no_signing_library_is_imported_anywhere_in_the_package(self):
        forbidden = ("cryptography", "OpenSSL", "signxml", "xmlsec", "Crypto")
        offenders = []
        for path in SRC_ROOT.rglob("*.py"):
            for line in path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not (stripped.startswith("import ") or stripped.startswith("from ")):
                    continue
                if any(module in stripped for module in forbidden):
                    offenders.append(f"{path.name}: {stripped}")
        assert not offenders, f"crypto library imported: {offenders}"

    def test_no_key_or_certificate_files_in_the_repository(self):
        repo = Path(__file__).resolve().parents[1]
        patterns = ("*.p12", "*.pfx", "*.pem", "*.key", "*.crt", "*.cer", "*.jks")
        found = [
            path
            for pattern in patterns
            for path in repo.rglob(pattern)
            if ".venv" not in path.parts and "build" not in path.parts
        ]
        assert not found, f"credential-shaped files present: {found}"


class TestBuildXml:
    def test_produces_parseable_xml(self, backend):
        payload = backend.build_xml(FakeDocument(), AcceptanceMessageType.FULL_ACCEPTANCE)
        body = payload.replace(MOCK_MARKER, b"").strip()
        root = etree.fromstring(body)
        assert root.tag == "MensajeReceptor"

    def test_every_artefact_is_labelled_synthetic(self, backend):
        payload = backend.build_xml(FakeDocument(), AcceptanceMessageType.FULL_ACCEPTANCE)
        assert MOCK_MARKER in payload
        assert b"SYNTHETIC" in payload

    def test_carries_the_message_type(self, backend):
        for message_type in AcceptanceMessageType:
            payload = backend.build_xml(FakeDocument(), message_type)
            body = payload.replace(MOCK_MARKER, b"").strip()
            root = etree.fromstring(body)
            assert root.findtext("Mensaje") == message_type.value

    def test_three_message_types_exist(self):
        assert {m.value for m in AcceptanceMessageType} == {"1", "2", "3"}


class TestSign:
    def test_sign_performs_no_cryptography(self, backend):
        original = b"<MensajeReceptor/>"
        signed = backend.sign(original)
        assert signed == MOCK_SIGNATURE_PREFIX + original
        assert original in signed, "input must pass through unmodified"

    def test_signing_is_reversible_which_a_real_signature_is_not(self, backend):
        """The clearest possible demonstration that nothing cryptographic happened."""
        original = b"<MensajeReceptor/>"
        assert backend.sign(original).removeprefix(MOCK_SIGNATURE_PREFIX) == original


class TestSubmit:
    def test_refuses_payloads_it_did_not_sign(self, backend):
        with pytest.raises(ValueError, match="Refusing to submit"):
            backend.submit(b"<MensajeReceptor/>", clave=FakeDocument.clave)

    def test_accepts_its_own_artefacts(self, backend):
        document = FakeDocument()
        signed = backend.sign(
            backend.build_xml(document, AcceptanceMessageType.FULL_ACCEPTANCE)
        )
        receipt = backend.submit(signed, clave=document.clave)
        assert receipt.state is SubmissionState.SUBMITTED
        assert receipt.is_mock is True
        assert receipt.detail["transport"] == "none"

    def test_submission_time_is_fixed_not_read_from_the_clock(self, backend):
        document = FakeDocument()
        signed = backend.sign(
            backend.build_xml(document, AcceptanceMessageType.FULL_ACCEPTANCE)
        )
        first = backend.submit(signed, clave=document.clave)
        second = backend.submit(signed, clave=document.clave)
        assert first.submitted_at == second.submitted_at


class TestPollStatus:
    def test_unknown_clave_returns_an_error_state(self, backend):
        receipt = backend.poll_status("nonexistent")
        assert receipt.state is SubmissionState.ERROR

    def test_verdict_is_deterministic_per_clave(self, backend):
        document = FakeDocument()
        signed = backend.sign(
            backend.build_xml(document, AcceptanceMessageType.FULL_ACCEPTANCE)
        )
        backend.submit(signed, clave=document.clave)
        assert backend.poll_status(document.clave).state == (
            backend.poll_status(document.clave).state
        )

    def test_every_verdict_says_it_is_canned(self, backend):
        document = FakeDocument()
        signed = backend.sign(
            backend.build_xml(document, AcceptanceMessageType.FULL_ACCEPTANCE)
        )
        backend.submit(signed, clave=document.clave)
        receipt = backend.poll_status(document.clave)
        assert "no tax authority was contacted" in receipt.message

    def test_all_three_verdicts_are_reachable(self, backend):
        """The mock covers rejection and partial acceptance, not just the happy path.

        The sample needs to span at least 20 distinct values of the mock's
        bucket function. Because the bucket is a digit-sum modulo 20, and a
        four-digit suffix over 0..199 produces digit sums 0..19, that range is
        the smallest one guaranteed to hit every bucket.
        """
        states = set()
        signed = backend.sign(
            backend.build_xml(FakeDocument(), AcceptanceMessageType.FULL_ACCEPTANCE)
        )
        for i in range(200):
            clave = f"5061507269990000100001000001000000000{i:04d}0012"
            backend.submit(signed, clave=clave)
            states.add(backend.poll_status(clave).state)
        assert states == {
            SubmissionState.ACCEPTED,
            SubmissionState.PARTIALLY_ACCEPTED,
            SubmissionState.REJECTED,
        }


class TestInterfaceContract:
    def test_abstract_backend_cannot_be_instantiated(self):
        from fractal_desk.submission.interface import SubmissionBackend

        with pytest.raises(TypeError):
            SubmissionBackend()  # type: ignore[abstract]

    def test_full_lifecycle_is_logged(self, backend):
        document = FakeDocument()
        xml = backend.build_xml(document, AcceptanceMessageType.FULL_ACCEPTANCE)
        backend.submit(backend.sign(xml), clave=document.clave)
        backend.poll_status(document.clave)
        assert [step for step, _ in backend.call_log] == [
            "build_xml", "sign", "submit", "poll_status",
        ]

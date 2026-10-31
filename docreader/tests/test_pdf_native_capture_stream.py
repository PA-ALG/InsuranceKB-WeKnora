"""PDF native structure capture over the streaming read (ReadStream).

The platform requests native character capture for the first parse of a managed RAW PDF and reads
it through ReadStream. The streaming path must honour the capture request exactly like the unary
path: the same evidence document, no image rendering, and failures that surface instead of falling
back to the scanned route. Project test for docreader/parser/pdf_parser.py; it lives in its own
file so the upstream test files stay byte-identical (U-2b).
"""

import unittest
from unittest import mock

from docreader.models.document import Document
from docreader.parser.parser import Parser
from docreader.parser.pdf_parser import PDFParser

MODE = "builtin-pdfium-charbox-v1"
KEY = "native_structure_artifact_v1"


class _Probe(PDFParser):
    """Records which route ran; the native route returns a document carrying the artifact."""

    routes: list = []

    def _route_native_capture(self, _content):
        self.routes.append("native")
        return Document(content="native text", metadata={KEY: "{}"})

    def _route_locked(self, _content, include_scanned_images=True):
        self.routes.append("legacy")
        return Document(content="legacy text"), []


class _FailingNative(_Probe):
    def _route_native_capture(self, _content):
        self.routes.append("native")
        raise ValueError("page 2 is scanned")


class NativeCaptureStreamTest(unittest.TestCase):
    def setUp(self):
        _Probe.routes = []

    def test_capture_request_takes_the_native_route_when_streamed(self):
        parser = _Probe(file_name="source.pdf", file_type="pdf", pdf_native_structure_capture=MODE)
        stream = parser.parse_stream(b"%PDF-probe")
        try:
            self.assertEqual(stream.document.content, "native text")
            self.assertEqual(stream.document.metadata[KEY], "{}")
            self.assertEqual(stream.image_count, 0)
            self.assertEqual(list(stream.images), [])
        finally:
            stream.close()
        self.assertEqual(_Probe.routes, ["native"])

    def test_streamed_and_unary_capture_return_the_same_document(self):
        unary = _Probe(file_name="source.pdf", file_type="pdf", pdf_native_structure_capture=MODE)
        streamed = _Probe(file_name="source.pdf", file_type="pdf", pdf_native_structure_capture=MODE)
        document = unary.parse(b"%PDF-probe")
        stream = streamed.parse_stream(b"%PDF-probe")
        try:
            self.assertEqual(stream.document.content, document.content)
            self.assertEqual(stream.document.metadata, document.metadata)
        finally:
            stream.close()

    def test_capture_failure_surfaces_when_streamed(self):
        parser = _FailingNative(
            file_name="source.pdf", file_type="pdf", pdf_native_structure_capture=MODE
        )
        with self.assertRaisesRegex(ValueError, "page 2 is scanned"):
            parser.parse_stream(b"%PDF-probe")
        self.assertEqual(_Probe.routes, ["native"])  # no scanned fallback, no legacy route

    def test_without_a_capture_request_the_stream_keeps_the_legacy_route(self):
        stream = _Probe(file_name="source.pdf", file_type="pdf").parse_stream(b"%PDF-probe")
        try:
            self.assertEqual(stream.document.content, "legacy text")
            self.assertNotIn(KEY, stream.document.metadata)
        finally:
            stream.close()
        self.assertEqual(_Probe.routes, ["legacy"])

    def test_the_override_reaches_the_parser_through_parse_file_stream(self):
        parser = Parser()
        # The registry is shared by every Parser; patch it only for this call.
        with mock.patch.object(parser.registry, "get_parser_class", return_value=_Probe):
            stream = parser.parse_file_stream(
                "source.pdf",
                "pdf",
                b"%PDF-probe",
                engine_overrides={"pdf_native_structure_capture": MODE},
            )
        try:
            self.assertEqual(stream.document.metadata[KEY], "{}")
        finally:
            stream.close()
        self.assertEqual(_Probe.routes, ["native"])


if __name__ == "__main__":
    unittest.main()

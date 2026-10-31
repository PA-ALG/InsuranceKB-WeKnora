"""Tests for our PDF parser patches (native structure capture, numeric-table sanitising).

These cover project changes to docreader/parser/pdf_parser.py; they live in their own file so the
upstream test_pdf_router.py stays byte-identical to WeKnora (U-2b).
"""

import hashlib
import json
import sys
import types
import unittest
from unittest import mock

from docreader.parser.pdf_parser import PDFParser


class PdfNumericTableSanitizeTest(unittest.TestCase):
    def test_preserves_numeric_table_without_figure_boundary(self):
        from docreader.parser.pdf_parser import _postprocess_pdf_text

        rows = "2 2 6350 12700 0 27600 2950\n3 3 6350 19050 0 41400 4800\n20 20 6350 127000 0 500000 67050"
        raw = rows + "\nImportant: values are at policy year end."
        self.assertEqual(_postprocess_pdf_text(raw), raw)

    def test_unrelated_figure_does_not_authorize_numeric_table_removal(self):
        from docreader.parser.pdf_parser import _postprocess_pdf_text

        rows = "2 2 6350 12700 0 27600 2950\n3 3 6350 19050 0 41400 4800\n20 20 6350 127000 0 500000 67050"
        raw = "Figure 1. An unrelated diagram.\n" + rows + "\nImportant: table assumptions."
        self.assertEqual(_postprocess_pdf_text(raw), raw)


class NativeStructureCaptureTest(unittest.TestCase):
    class _TextPage:
        def __init__(self, text, boxes):
            self.text = text
            self.boxes = boxes

        def count_chars(self):
            return len(self.text)

        def get_text_range(self, index=0, count=-1):
            if count < 0:
                return self.text[index:]
            return self.text[index : index + count]

        def get_charbox(self, index):
            box = self.boxes[index]
            if isinstance(box, Exception):
                raise box
            return box

        def close(self):
            pass

    class _Page:
        def __init__(self, text, boxes, size=(100.0, 200.0), objects=(), rotation=0):
            self.textpage = NativeStructureCaptureTest._TextPage(text, boxes)
            self.size = size
            self.objects = list(objects)
            self.rotation = rotation

        def get_textpage(self):
            return self.textpage

        def get_size(self):
            return self.size

        def get_objects(self):
            return self.objects

        def get_rotation(self):
            return self.rotation

        def close(self):
            pass

    class _Document:
        def __init__(self, pages):
            self.pages = pages

        def __len__(self):
            return len(self.pages)

        def __getitem__(self, index):
            return self.pages[index]

        def close(self):
            pass

    def _capture(self, pages, source=b"%PDF-native"):
        pdfium = types.ModuleType("pypdfium2")
        pdfium.PdfDocument = lambda _content: self._Document(pages)
        versions = types.ModuleType("pypdfium2.version")
        versions.PYPDFIUM_INFO = "5.8.0"
        versions.PDFIUM_INFO = "7543"
        raw = types.ModuleType("pypdfium2.raw")
        raw.FPDF_PAGEOBJ_IMAGE = 3
        with mock.patch.dict(
            sys.modules,
            {
                "pypdfium2": pdfium,
                "pypdfium2.version": versions,
                "pypdfium2.raw": raw,
            },
        ):
            return PDFParser(
                file_name="source.pdf",
                file_type="pdf",
                pdf_native_structure_capture="builtin-pdfium-charbox-v1",
            ).parse_into_text(source)

    def test_unknown_capture_mode_is_rejected(self):
        for mode in ("", "client-defined-mode"):
            with self.subTest(mode=mode):
                with self.assertRaisesRegex(ValueError, "unsupported PDF native capture mode"):
                    PDFParser(
                        file_name="source.pdf",
                        file_type="pdf",
                        pdf_native_structure_capture=mode,
                    )

    def test_explicit_capture_uses_native_route(self):
        from docreader.models.document import Document

        class RoutingProbe(PDFParser):
            def _route(self, _content):
                return Document(content="legacy")

            def _route_native_capture(self, _content):
                return Document(content="native")

        parser = RoutingProbe(
            file_name="source.pdf",
            file_type="pdf",
            pdf_native_structure_capture="builtin-pdfium-charbox-v1",
        )
        self.assertEqual(parser.parse_into_text(b"%PDF-probe").content, "native")

    def test_capture_failure_does_not_fallback_to_scanned_route(self):
        from docreader.models.document import Document

        class FailingCaptureProbe(PDFParser):
            def _route(self, _content):
                return Document(content="legacy")

            def _route_native_capture(self, _content):
                raise ValueError("native coordinates unavailable")

        parser = FailingCaptureProbe(
            file_name="source.pdf",
            file_type="pdf",
            pdf_native_structure_capture="builtin-pdfium-charbox-v1",
        )
        with self.assertRaisesRegex(ValueError, "coordinates unavailable"):
            parser.parse_into_text(b"%PDF-probe")

    def test_unicode_pages_emit_codepoint_ranges_hashes_and_top_left_bboxes(self):
        pages = [
            self._Page("A😀", [(10, 20, 20, 40), (20, 20, 40, 40)]),
            self._Page("中", [(25, 50, 50, 100)]),
        ]
        source = b"%PDF-unicode-source"
        doc = self._capture(pages, source)

        self.assertEqual(doc.content, "A😀\n\n中")
        envelope = json.loads(doc.metadata["native_structure_artifact_v1"])
        sanitized = envelope["sanitized_json"]
        self.assertEqual(envelope["schema_version"], "builtin-pdfium-native-locators.v1")
        self.assertEqual(envelope["source_sha256"], hashlib.sha256(source).hexdigest())
        self.assertEqual(envelope["raw_sha256"], envelope["sanitized_sha256"])
        self.assertEqual(
            envelope["sanitized_sha256"],
            hashlib.sha256(
                json.dumps(
                    sanitized,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
        )
        self.assertEqual(sanitized["markdown_sha256"], hashlib.sha256(doc.content.encode()).hexdigest())
        self.assertEqual(
            sanitized["parser_identity"],
            {
                "capture_mode": "builtin-pdfium-charbox-v1",
                "pdfium_version": "7543",
                "producer_contract": "weknora.docreader.builtin-pdfium-charbox.v1",
                "pypdfium2_version": "5.8.0",
            },
        )
        identity_bytes = json.dumps(
            sanitized["parser_identity"],
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        self.assertEqual(
            sanitized["parser_identity_sha256"], hashlib.sha256(identity_bytes).hexdigest()
        )
        self.assertEqual(
            [(p["global_codepoint_start"], p["global_codepoint_end"]) for p in sanitized["pages"]],
            [(0, 2), (4, 5)],
        )
        self.assertEqual(sanitized["pages"][0]["width_points"], "100")
        self.assertEqual(sanitized["pages"][0]["height_points"], "200")
        self.assertEqual(
            sanitized["pages"][0]["bboxes"][0],
            {
                "bbox": [100000, 800000, 200000, 900000],
                "global_codepoint_end": 1,
                "global_codepoint_start": 0,
            },
        )
        self.assertEqual(sanitized["coordinate_space"], "normalized_0_1e6_top_left")
        serialized = json.dumps(sanitized, ensure_ascii=False)
        self.assertNotIn("A😀", serialized)
        self.assertNotIn("中", serialized)

    def test_scanned_page_is_rejected_without_image_fallback(self):
        class ImageObject:
            type = 3

            @staticmethod
            def get_bounds():
                return (0, 0, 100, 200)

        page = self._Page("hidden", [(1, 1, 2, 2)] * 6, objects=[ImageObject()])
        with self.assertRaisesRegex(ValueError, "page 1 is scanned"):
            self._capture([page])

    def test_image_classification_failure_is_rejected(self):
        class BrokenImageObject:
            type = 3

            @staticmethod
            def get_bounds():
                raise RuntimeError("missing image bounds")

        page = self._Page("X", [(1, 1, 2, 2)], objects=[BrokenImageObject()])
        with self.assertRaisesRegex(ValueError, "page 1 image geometry"):
            self._capture([page])

    def test_rotated_page_keeps_text_without_mislabeling_coordinates(self):
        page = self._Page("X", [(1, 1, 2, 2)], rotation=90)
        doc = self._capture([page])
        self.assertEqual(doc.content, "X")
        native = json.loads(doc.metadata["native_structure_artifact_v1"])["sanitized_json"]
        self.assertEqual(native["pages"][0]["bboxes"], [])
        self.assertEqual(native["pages"][0]["unavailable_ranges"][0]["reason"], "page_rotation_unsupported")

    def test_missing_or_invalid_character_bbox_preserves_text_and_good_locations(self):
        cases = [
            RuntimeError("no charbox"),
            (10, 20, 10, 40),
            (10, 20, 10.000000001, 40),
            (-1, 20, 10, 40),
            (10, 20, float("nan"), 40),
        ]
        for box in cases:
            with self.subTest(box=box):
                doc = self._capture([self._Page("XY", [box, (1, 1, 2, 2)]), self._Page("Z", [(1, 1, 2, 2)])])
                self.assertEqual(doc.content, "XY\n\nZ")
                native = json.loads(doc.metadata["native_structure_artifact_v1"])["sanitized_json"]
                self.assertEqual(native["contract"], "builtin-pdfium-native-locators.v2")
                self.assertEqual(native["pages"][0]["unavailable_ranges"], [{"global_codepoint_start": 0, "global_codepoint_end": 1, "reason": "bbox_unavailable" if isinstance(box, Exception) else "bbox_invalid"}])
                self.assertEqual(len(native["pages"][0]["bboxes"]), 1)
                self.assertEqual(native["pages"][0]["bboxes"][0]["global_codepoint_start"], 1)
                self.assertEqual(len(native["pages"][1]["bboxes"]), 1)

    def test_ambiguous_character_mapping_keeps_original_page_and_next_page(self):
        page = self._Page("AB", [(1, 1, 2, 2)] * 2)
        page.textpage.count_chars = lambda: 3
        doc = self._capture([page, self._Page("C", [(1, 1, 2, 2)])])
        self.assertEqual(doc.content, "AB\n\nC")
        native = json.loads(doc.metadata["native_structure_artifact_v1"])["sanitized_json"]
        self.assertEqual(native["pages"][0]["bboxes"], [])
        self.assertEqual(native["pages"][0]["unavailable_ranges"][0]["reason"], "character_mapping_unavailable")
        self.assertEqual(len(native["pages"][1]["bboxes"]), 1)


if __name__ == "__main__":
    unittest.main()

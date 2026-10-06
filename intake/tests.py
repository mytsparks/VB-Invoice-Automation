import tempfile
from pathlib import Path

from django.test import TestCase

from intake.models import Document
from intake.services import estimate_pages, ingest_folder


class IngestTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)

    def test_ingest_is_repeatable_and_skips_duplicates(self):
        (self.folder / "a.pdf").write_bytes(b"%PDF one")
        (self.folder / "copy_of_a.pdf").write_bytes(b"%PDF one")
        (self.folder / "notes.txt").write_bytes(b"hello")
        first = ingest_folder(self.folder)
        self.assertEqual((first.added, first.duplicates, first.unsupported), (1, 1, 1))
        second = ingest_folder(self.folder)
        self.assertEqual((second.added, second.duplicates), (0, 3))
        self.assertEqual(Document.objects.count(), 2)
        self.assertEqual(Document.objects.get(file_name="notes.txt").status, "unsupported")

    def test_original_files_are_untouched(self):
        path = self.folder / "a.pdf"
        path.write_bytes(b"%PDF one")
        ingest_folder(self.folder)
        self.assertEqual(path.read_bytes(), b"%PDF one")

    def test_files_outside_synthetic_are_real(self):
        (self.folder / "a.pdf").write_bytes(b"%PDF one")
        ingest_folder(self.folder)
        self.assertEqual(Document.objects.get().source, "real")

    def test_page_estimate(self):
        self.assertEqual(estimate_pages(b"/Type /Pages /Type /Page /Type/Page", "application/pdf"), 2)
        self.assertEqual(estimate_pages(b"", "image/png"), 1)

import io
from pathlib import Path
import sys
import tarfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import fetch_sources


def archive(payload=b"source", timestamp=1, mode=0o644, name="source.c", duplicate=False, link=False):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as target:
        entry = tarfile.TarInfo(name)
        entry.mtime, entry.mode = timestamp, mode
        if link:
            entry.type, entry.linkname = tarfile.SYMTYPE, "/outside"
            target.addfile(entry)
        else:
            entry.size = len(payload)
            target.addfile(entry, io.BytesIO(payload))
            if duplicate:
                target.addfile(entry, io.BytesIO(payload))
    return output.getvalue()


class SourceIdentityTests(unittest.TestCase):
    def test_fec_identity_ignores_only_archive_transport_metadata(self):
        first, second = archive(timestamp=1), archive(timestamp=2)
        self.assertNotEqual(first, second)
        checksum = fetch_sources.archive_tree_digest(first)
        self.assertEqual(fetch_sources.archive_tree_digest(second), checksum)
        with mock.patch.object(fetch_sources, "FEC_TREE_SHA256", checksum):
            fetch_sources.verify_source("fec.tar.gz", first)
            fetch_sources.verify_source("fec.tar.gz", second)
            for changed in (archive(b"changed"), archive(mode=0o755), archive(name="other.c")):
                with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                    fetch_sources.verify_source("fec.tar.gz", changed)
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            fetch_sources.verify_source("picosha2.h", first)

    def test_archive_rejects_duplicate_links_and_escaping_paths(self):
        for content in (archive(duplicate=True), archive(link=True),
                        archive(name="../source.c"), archive(name="/source.c")):
            with self.assertRaisesRegex(ValueError, "Unsafe or duplicate"):
                fetch_sources.archive_tree_digest(content)

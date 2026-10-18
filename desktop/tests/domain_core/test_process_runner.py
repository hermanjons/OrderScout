from __future__ import annotations

import unittest

from Core.process.process_runner import GenericProcessRunner


class TestProcessRunner(unittest.TestCase):
    def test_append_capped_bytes_keeps_tail_within_limit(self) -> None:
        first = b"a" * (200 * 1024)
        second = b"b" * (200 * 1024)

        merged = GenericProcessRunner._append_capped_bytes(first, second)

        self.assertLessEqual(len(merged), 256 * 1024)
        self.assertTrue(merged.endswith(b"b" * 1024))
        self.assertLess(merged.count(b"a"), len(first))


if __name__ == "__main__":
    unittest.main()

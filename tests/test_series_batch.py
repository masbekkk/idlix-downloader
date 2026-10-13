import unittest
from src.idlixHelper import IdlixHelper

class TestSeriesBatchHelper(unittest.TestCase):
    def test_parse_episode_selection_ranges_and_lists(self):
        # Range
        self.assertEqual(IdlixHelper.parse_episode_selection("1-5"), [1, 2, 3, 4, 5])
        # Comma separated
        self.assertEqual(IdlixHelper.parse_episode_selection("1, 3, 5"), [1, 3, 5])
        # Mixed
        self.assertEqual(IdlixHelper.parse_episode_selection("1-3, 5, 8-10"), [1, 2, 3, 5, 8, 9, 10])
        # Overlapping and duplicates
        self.assertEqual(IdlixHelper.parse_episode_selection("1-3, 2, 3-4"), [1, 2, 3, 4])
        # Reverse range 5-3
        self.assertEqual(IdlixHelper.parse_episode_selection("5-3"), [3, 4, 5])

    def test_parse_episode_selection_with_available(self):
        available = [{"episodeNumber": 1}, {"episodeNumber": 2}, {"episodeNumber": 3}]
        # All keyword
        self.assertEqual(IdlixHelper.parse_episode_selection("all", available), [1, 2, 3])
        # Filtered to available only
        self.assertEqual(IdlixHelper.parse_episode_selection("1-5", available), [1, 2, 3])

    def test_parse_episode_selection_invalid(self):
        with self.assertRaises(ValueError):
            IdlixHelper.parse_episode_selection("1-abc")
        with self.assertRaises(ValueError):
            IdlixHelper.parse_episode_selection("xyz")

    def test_select_best_variant_exact(self):
        variants = [
            {"id": "0", "resolution": "1920x1080", "bandwidth": 5000000, "uri": "http://1080.m3u8"},
            {"id": "1", "resolution": "1280x720", "bandwidth": 2500000, "uri": "http://720.m3u8"},
            {"id": "2", "resolution": "854x480", "bandwidth": 1000000, "uri": "http://480.m3u8"},
        ]
        # Target 1080p
        var, exact = IdlixHelper.select_best_variant(variants, "1080p")
        self.assertTrue(exact)
        self.assertEqual(var["resolution"], "1920x1080")

        # Target 720
        var, exact = IdlixHelper.select_best_variant(variants, "720")
        self.assertTrue(exact)
        self.assertEqual(var["resolution"], "1280x720")

        # Best / Auto
        var, exact = IdlixHelper.select_best_variant(variants, "best")
        self.assertTrue(exact)
        self.assertEqual(var["resolution"], "1920x1080")

    def test_select_best_variant_fallback_next_highest(self):
        # Episode only has 720p and 480p, user wanted 1080p (Option A)
        variants = [
            {"id": "0", "resolution": "1280x720", "bandwidth": 2500000, "uri": "http://720.m3u8"},
            {"id": "1", "resolution": "854x480", "bandwidth": 1000000, "uri": "http://480.m3u8"},
        ]
        var, exact = IdlixHelper.select_best_variant(variants, "1080p")
        self.assertFalse(exact)
        # Should fallback to next highest available: 720p
        self.assertEqual(var["resolution"], "1280x720")

    def test_select_best_variant_fallback_when_target_lower(self):
        # Episode only has 1080p, user wanted 720p
        variants = [
            {"id": "0", "resolution": "1920x1080", "bandwidth": 5000000, "uri": "http://1080.m3u8"},
        ]
        var, exact = IdlixHelper.select_best_variant(variants, "720p")
        self.assertFalse(exact)
        self.assertEqual(var["resolution"], "1920x1080")

    def test_select_best_variant_empty_and_auto(self):
        self.assertEqual(IdlixHelper.select_best_variant([], "1080p"), (None, False))
        variants = [{"id": "0", "resolution": "1920x1080", "uri": "http://1080.m3u8"}]
        var, exact = IdlixHelper.select_best_variant(variants, "")
        self.assertTrue(exact)
        self.assertEqual(var["resolution"], "1920x1080")
        var, exact = IdlixHelper.select_best_variant(variants, "auto")
        self.assertTrue(exact)
        self.assertEqual(var["resolution"], "1920x1080")

    def test_parse_episode_selection_whitespace_and_empty(self):
        self.assertEqual(IdlixHelper.parse_episode_selection(""), [])
        self.assertEqual(IdlixHelper.parse_episode_selection("  1 - 3 , 5  "), [1, 2, 3, 5])
        self.assertEqual(IdlixHelper.parse_episode_selection(" * ", [1, 2, 3]), [1, 2, 3])

if __name__ == "__main__":
    unittest.main()


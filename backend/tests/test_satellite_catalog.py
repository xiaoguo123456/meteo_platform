import unittest

from app.satellite_catalog import categories, get_satellite, list_satellites, track


class SatelliteCatalogTests(unittest.TestCase):
    def test_catalog_covers_multiple_types_and_is_expandable(self):
        value = list_satellites(limit=200)
        self.assertGreaterEqual(value["total"], 15)
        self.assertGreaterEqual(len({item["category"] for item in value["items"]}), 8)
        self.assertTrue(any(item["track"] for item in value["items"]))
        self.assertGreaterEqual(len(categories()), 12)

    def test_detail_contains_orbit_mission_and_sources(self):
        value = get_satellite("fy-4a")
        self.assertIsNotNone(value)
        self.assertEqual(value["orbit"]["orbit_class"], "GEO")
        self.assertTrue(value["mission_summary"])
        self.assertTrue(value["sources"])
        self.assertIn("ai", value)

    def test_track_is_time_ordered_and_has_position_fields(self):
        value = track("iss", hours=1, step_minutes=15)
        self.assertEqual(value["id"], "iss")
        self.assertGreater(len(value["points"]), 5)
        self.assertLess(value["points"][0]["time"], value["points"][-1]["time"])
        self.assertIn("altitude_km", value["points"][0])


if __name__ == "__main__":
    unittest.main()

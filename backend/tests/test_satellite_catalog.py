import unittest

from app.satellite_catalog import categories, constellation_members, get_satellite, list_satellites, track


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

    def test_geostationary_track_stays_fixed_relative_to_earth(self):
        expected = {"fy-4a": 104.7, "fy-4b": 133.0, "himawari-9": 140.7, "goes-16": -75.2}
        for satellite_id, longitude in expected.items():
            points = track(satellite_id, hours=2, step_minutes=2)["points"]
            self.assertEqual(len(points), 1, satellite_id)
            self.assertAlmostEqual(points[0]["longitude"], longitude, places=2, msg=satellite_id)
            self.assertEqual(points[0]["latitude"], 0.0, satellite_id)
            detail = get_satellite(satellite_id, at="2026-10-15T08:30:00Z", orbits=3)
            self.assertEqual(len(detail["track"]), 1, satellite_id)
            self.assertAlmostEqual(detail["position"]["longitude"], longitude, places=2, msg=satellite_id)

    def test_constellation_exposes_selectable_members(self):
        value = constellation_members("starlink-group", limit=3)
        self.assertEqual(value["total"], 24)
        self.assertEqual(len(value["items"]), 3)
        member_id = value["items"][0]["id"]
        self.assertTrue(get_satellite(member_id)["track"])

    def test_detail_supports_time_position_and_multiple_orbits(self):
        value = get_satellite("iss", at="2026-10-15T08:30:00Z", orbits=3)
        self.assertIsNotNone(value)
        self.assertGreater(len(value["track"]), 100)
        self.assertEqual(value["track"][len(value["track"]) // 2]["time"], "2026-10-15T08:30:00+00:00")


if __name__ == "__main__":
    unittest.main()

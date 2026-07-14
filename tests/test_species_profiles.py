from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from common import db
from journal import queries


class SpeciesProfileTests(unittest.TestCase):
    def test_species_profile_schema_is_repeatable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "feeder.sqlite"
            db.initialize(path)
            conn = db.connect(path)
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(species_profiles)")
            }
            self.assertLessEqual(
                {
                    "species_key",
                    "inat_taxon_id",
                    "introduction",
                    "reference_image",
                    "image_creator",
                    "image_license",
                    "fetched_at",
                    "error_category",
                },
                columns,
            )
            conn.close()

            db.initialize(path)

    def test_species_key_normalizes_whitespace_and_case(self) -> None:
        self.assertEqual(
            queries.species_key("Blue Jay", "  Cyanocitta   CRISTATA "),
            "sci:cyanocitta cristata",
        )
        self.assertEqual(
            queries.species_key("  Blue   Jay ", None),
            "common:blue jay",
        )


if __name__ == "__main__":
    unittest.main()

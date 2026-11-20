"""Validate the proposed read-only session inventory against an in-memory fixture."""

import sqlite3
import unittest


class SessionInventoryTests(unittest.TestCase):
    def test_inventory_does_not_infer_home_provenance(self):
        db = sqlite3.connect(":memory:")
        try:
            db.executescript("""
                CREATE TABLE sessioni (impronta TEXT PRIMARY KEY, tipo TEXT, da TEXT);
                CREATE TABLE everid_sessioni (impronta TEXT PRIMARY KEY);
                CREATE TABLE stato (utente INTEGER PRIMARY KEY, json TEXT);
                INSERT INTO sessioni VALUES ('oidc', 'cookie', NULL), ('form-or-legacy', 'cookie', NULL),
                    ('home', 'casa', NULL), ('home-cookie', 'cookie', 'home'), ('steps', 'passi', NULL);
                INSERT INTO everid_sessioni VALUES ('oidc');
                INSERT INTO stato VALUES (1, '{"fixture":true}');
            """)
            counts = dict(db.execute("""
                SELECT CASE
                    WHEN s.tipo = 'cookie' AND EXISTS (SELECT 1 FROM everid_sessioni e WHERE e.impronta = s.impronta)
                        THEN 'oidc-cookie'
                    WHEN s.tipo = 'cookie' THEN 'unknown-cookie'
                    WHEN s.tipo = 'casa' THEN 'home'
                    ELSE 'other'
                END AS category, COUNT(*) FROM sessioni s GROUP BY category
            """))
            self.assertEqual(counts, {"oidc-cookie": 1, "unknown-cookie": 2, "home": 1, "other": 1})
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sessioni WHERE da IS NOT NULL").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sessioni").fetchone()[0], 5)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM stato").fetchone()[0], 1)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()

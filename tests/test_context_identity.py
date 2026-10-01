# -*- coding: utf-8 -*-
from __future__ import print_function

import os
import sys
import tempfile
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)


class TestContextIdentity(unittest.TestCase):
    def test_paths_are_casefolded_without_collapsing_parent_directory(self):
        from core.context_identity import canonical_file_path

        with tempfile.TemporaryDirectory(dir=ROOT) as work:
            first = os.path.join(work, "Uno", "Modelo.MDB")
            second = os.path.join(work, "Dos", "modelo.mdb")
            self.assertEqual(
                canonical_file_path(first),
                canonical_file_path(first.upper()),
            )
            self.assertNotEqual(
                canonical_file_path(first),
                canonical_file_path(second),
            )

    def test_fingerprint_changes_for_same_basename_in_other_folder(self):
        from core.context_identity import build_context_identity, context_fingerprint

        with tempfile.TemporaryDirectory(dir=ROOT) as work:
            common = {
                "study_path": os.path.join(work, "estudios", "multi.zxst"),
                "feeder_id": "PE104",
                "network_id": "NET_2030_184_PE104",
            }
            first = dict(common, database_mdb=os.path.join(work, "A", "redes.mdb"))
            second = dict(common, database_mdb=os.path.join(work, "B", "redes.mdb"))

            first_fp = context_fingerprint(build_context_identity(first, require_complete=True))
            second_fp = context_fingerprint(build_context_identity(second, require_complete=True))

            self.assertRegex(first_fp, r"^[0-9a-f]{16}$")
            self.assertRegex(second_fp, r"^[0-9a-f]{16}$")
            self.assertNotEqual(first_fp, second_fp)

    def test_fingerprint_supports_arbitrary_mdb_and_feeder_identities(self):
        from core.context_identity import build_context_identity, context_fingerprint

        cases = [
            (r"D:\modelos\base norte.mdb", r"D:\estudios\TM105.zxst", "TM105", "NET_2030_174_TM105"),
            (r"E:\redes\base sur.mdb", r"E:\casos\PA217.zxst", "PA217", "NET_2030_179_PA217"),
            (r"F:\modelos\otra base.mdb", r"F:\proyectos\XX999.zxst", "XX999", "NET_CUSTOM_999"),
        ]
        fingerprints = set()
        for database, study, feeder, network in cases:
            identity = build_context_identity(
                {
                    "database_mdb": database,
                    "study_path": study,
                    "feeder_id": feeder,
                    "network_id": network,
                },
                require_complete=True,
            )
            fingerprints.add(context_fingerprint(identity))

        self.assertEqual(len(fingerprints), len(cases))

    def test_complete_identity_requires_four_fields(self):
        from core.context_identity import ContextIdentityError, build_context_identity

        payload = {
            "database_mdb": r"D:\bases\redes.mdb",
            "ui_study_path": r"D:\estudios\multi.zxst",
            "feeder_id": "PE104",
        }
        with self.assertRaises(ContextIdentityError) as caught:
            build_context_identity(payload, require_complete=True)

        self.assertEqual(caught.exception.code, "CONTEXT_INCOMPLETE")
        self.assertEqual(caught.exception.missing_fields, ["network_id"])

    def test_identity_mismatch_names_the_different_fields(self):
        from core.context_identity import (
            ContextIdentityError,
            assert_same_context,
            build_context_identity,
        )

        base = {
            "database_mdb": r"D:\bases\redes.mdb",
            "study_path": r"D:\estudios\multi.zxst",
            "feeder_id": "PE104",
            "network_id": "NET_2030_184_PE104",
        }
        other = dict(base, feeder_id="CA101", network_id="NET_2030_131_CA101")
        with self.assertRaises(ContextIdentityError) as caught:
            assert_same_context(
                build_context_identity(base, require_complete=True),
                build_context_identity(other, require_complete=True),
            )

        self.assertEqual(caught.exception.code, "CONTEXT_IDENTITY_MISMATCH")
        self.assertEqual(
            caught.exception.different_fields,
            ["feeder_id", "network_id"],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)

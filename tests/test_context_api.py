# -*- coding: utf-8 -*-
from __future__ import print_function

import os
import sys
import tempfile
import unittest
from unittest import mock


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)


class TestQuickContextCatalog(unittest.TestCase):
    def test_external_paths_are_added_deduplicated_and_disambiguated(self):
        from core.feeder_context import quick_context_catalog

        with tempfile.TemporaryDirectory(dir=ROOT) as work:
            db_a = os.path.join(work, "A", "redes.mdb")
            db_b = os.path.join(work, "B", "redes.mdb")
            study = os.path.join(work, "externo", "multi.zxst")
            for path, contents in ((db_a, b"a"), (db_b, b"b"), (study, b"s" * 2048)):
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as handle:
                    handle.write(contents)
            settings = {
                "database_dir": os.path.dirname(db_a),
                "projects_dir": os.path.dirname(study),
                "database_mdb": db_b,
                "ui_study_path": study,
            }
            with mock.patch(
                "pipeline.model_quality_gate.list_bd_networks",
                side_effect=AssertionError("quick catalog must not call CymPy"),
            ):
                result = quick_context_catalog(
                    settings,
                    selected_database=db_b,
                    selected_study=study,
                )

        db_paths = [row["path"] for row in result["databases"]]
        self.assertEqual(len(db_paths), 2)
        self.assertEqual(len(set(row["canonical_path"] for row in result["databases"])), 2)
        self.assertTrue(all("redes.mdb — " in row["label"] for row in result["databases"]))
        self.assertEqual(len(result["studies"]), 1)
        self.assertEqual(result["current_database"], os.path.realpath(db_b))

    def test_selected_database_only_accepts_matching_discovery(self):
        from core.feeder_context import quick_context_catalog

        selected = r"D:\A\redes.mdb"
        result = quick_context_catalog(
            {},
            selected_database=selected,
            discovery={
                "database_mdb": r"D:\B\redes.mdb",
                "feeders": [{"feeder_id": "CA101", "network_id": "NET_CA101"}],
            },
        )
        self.assertEqual(result["feeders"], [])

    def test_persisted_identity_is_returned_only_for_its_database(self):
        from core.feeder_context import quick_context_catalog

        with tempfile.TemporaryDirectory(dir=ROOT) as work:
            selected = os.path.join(work, "redes.mdb")
            other = os.path.join(work, "otra.mdb")
            for path in (selected, other):
                with open(path, "wb") as handle:
                    handle.write(b"mdb")
            settings = {
                "database_mdb": selected,
                "active_feeder": "PE104",
                "active_network_id": "NET_2030_184_PE104",
            }
            same = quick_context_catalog(settings, selected_database=selected)
            different = quick_context_catalog(settings, selected_database=other)

        self.assertEqual(same["current_feeder"], "PE104")
        self.assertEqual(same["current_network"], "NET_2030_184_PE104")
        self.assertEqual(different["current_feeder"], "")
        self.assertEqual(different["current_network"], "")


class TestStrictContextApplication(unittest.TestCase):
    def _files(self, work, study_name="CA101V2.sxst"):
        mdb = os.path.join(work, "redes.mdb")
        study = os.path.join(work, study_name)
        with open(mdb, "wb") as handle:
            handle.write(b"mdb")
        with open(study, "wb") as handle:
            handle.write(b"study" * 300)
        return mdb, study

    def test_pair_absent_from_discovered_mdb_is_rejected(self):
        from core.context_identity import ContextIdentityError
        from core.feeder_context import apply_context_selection

        with tempfile.TemporaryDirectory(dir=ROOT) as work:
            mdb, study = self._files(work)
            with self.assertRaises(ContextIdentityError) as caught:
                apply_context_selection(
                    database_mdb=mdb,
                    study_path=study,
                    feeder_id="PE104",
                    network_id="NET_2030_184_PE104",
                    allowed_networks=[
                        {"feeder_id": "CA101", "network_id": "NET_2030_131_CA101"}
                    ],
                    strict=True,
                    persist=False,
                )
        self.assertEqual(caught.exception.code, "CONTEXT_IDENTITY_MISMATCH")
        self.assertEqual(caught.exception.different_fields, ["feeder_id", "network_id"])

    def test_explicit_fields_are_returned_without_filename_or_family_fallback(self):
        from core.context_identity import context_fingerprint
        from core.feeder_context import apply_context_selection

        with tempfile.TemporaryDirectory(dir=ROOT) as work:
            mdb, study = self._files(work)
            result = apply_context_selection(
                database_mdb=mdb,
                study_path=study,
                feeder_id="PE104",
                network_id="NET_2030_184_PE104",
                allowed_networks=[
                    {"feeder_id": "PE104", "network_id": "NET_2030_184_PE104"}
                ],
                strict=True,
                persist=False,
            )

        self.assertEqual(result["database_mdb"], os.path.realpath(mdb))
        self.assertEqual(result["ui_study_path"], os.path.realpath(study))
        self.assertEqual(result["study_path"], os.path.realpath(study))
        self.assertEqual(result["feeder_id"], "PE104")
        self.assertEqual(result["network_id"], "NET_2030_184_PE104")
        self.assertEqual(result["context_fingerprint"], context_fingerprint(result))

    def test_changing_one_explicit_field_never_changes_the_other_three(self):
        from core.feeder_context import apply_context_selection

        with tempfile.TemporaryDirectory(dir=ROOT) as work:
            first_db, first_study = self._files(work, "CA101V2.sxst")
            second_study = os.path.join(work, "otro.xst")
            with open(second_study, "wb") as handle:
                handle.write(b"study" * 300)
            allowed = [{"feeder_id": "PE104", "network_id": "NET_2030_184_PE104"}]
            first = apply_context_selection(
                first_db, first_study, "PE104", "NET_2030_184_PE104",
                allowed_networks=allowed, strict=True, persist=False,
            )
            second = apply_context_selection(
                first_db, second_study, "PE104", "NET_2030_184_PE104",
                allowed_networks=allowed, strict=True, persist=False,
            )
        self.assertEqual(first["database_mdb"], second["database_mdb"])
        self.assertEqual(first["feeder_id"], second["feeder_id"])
        self.assertEqual(first["network_id"], second["network_id"])
        self.assertNotEqual(first["study_path"], second["study_path"])


class TestContextApplyCreatesStudy(unittest.TestCase):
    def test_create_study_saves_selected_network_without_applying_context(self):
        from api_app.routers.context import ContextStudyCreateRequest, context_create_study

        body = ContextStudyCreateRequest(
            database_mdb=r"D:\bases\260924.mdb",
            feeder_id="AL209",
            network_id="NET_2030_861579_AL209",
        )
        ensured = {
            "ok": True,
            "created": True,
            "reused": False,
            "study_path": r"D:\projects\AL209.zxst",
            "loaded_networks": [body.network_id],
        }

        with mock.patch(
            "core.feeder_context.load_settings",
            return_value={"projects_dir": r"D:\projects"},
        ), mock.patch(
            "core.cymdist_com.ensure_feeder_study_com",
            return_value=ensured,
        ) as ensure, mock.patch(
            "api_app.routers.context.apply_context_selection"
        ) as apply_context:
            result = context_create_study(body)

        self.assertTrue(result["ok"])
        self.assertTrue(result["created"])
        self.assertEqual(result["study_path"], ensured["study_path"])
        self.assertEqual(result["loaded_networks"], [body.network_id])
        ensure.assert_called_once_with(
            mock.ANY,
            selected_study="",
        )
        apply_context.assert_not_called()

    def test_empty_study_is_created_with_selected_network_before_context_persists(self):
        from api_app.routers.context import ContextApplyRequest, context_apply

        created_path = r"D:\projects\AL209.zxst"
        body = ContextApplyRequest(
            database_mdb=r"D:\bases\260924.mdb",
            study_path="",
            feeder_id="AL209",
            network_id="NET_2030_861579_AL209",
            allowed_networks=[
                {
                    "feeder_id": "AL209",
                    "network_id": "NET_2030_861579_AL209",
                }
            ],
        )
        ensured = {
            "ok": True,
            "created": True,
            "reused": False,
            "study_path": created_path,
            "ui_study_path": created_path,
            "database_mdb": body.database_mdb,
            "feeder_id": body.feeder_id,
            "network_id": body.network_id,
            "loaded_networks": [body.network_id],
            "cymdist_open": True,
        }
        applied = dict(ensured)
        applied["context_fingerprint"] = "abc123"

        with mock.patch(
            "core.feeder_context.load_settings",
            return_value={"projects_dir": r"D:\projects"},
        ), mock.patch(
            "core.cymdist_com.ensure_feeder_study_com",
            return_value=ensured,
        ), mock.patch(
            "api_app.routers.context.apply_context_selection",
            return_value=applied,
        ):
            result = context_apply(body)

        self.assertTrue(result["ok"])
        self.assertTrue(result["study_created"])
        self.assertEqual(result["study_path"], created_path)
        self.assertEqual(result["cymdist_sync"]["loaded_networks"], [body.network_id])


if __name__ == "__main__":
    unittest.main(verbosity=2)

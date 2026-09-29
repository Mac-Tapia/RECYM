import os
import sys
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from pipeline import transfer_tie_safety as ties
from pipeline.transfer_tie_safety import inspect_transfer_tie_gate


class Obj:
    def __init__(self, object_id, **values):
        self.ID = object_id
        self.DeviceNumber = object_id
        self.values = values

    def GetValue(self, field):
        return self.values.get(field)

    def SetValue(self, value, field):
        self.values[field] = value

    def ListDevices(self):
        return list(self.values.get("devices") or [])


class DeviceType:
    Sectionalizer = "Sectionalizer"
    Switch = "Switch"
    Breaker = "Breaker"
    Recloser = "Recloser"
    Fuse = "Fuse"


class Study:
    def __init__(self, shared=False, phase="None", coordinate_tie=False, ambiguous=False, interior_tie=False):
        pe_to = "TIE_NODE" if shared else "PE_END"
        ca_from = "TIE_NODE" if shared else "CA_END"
        tie = Obj("PE_CA_TIE", ClosedPhase=phase, NormalStatus="Open" if phase == "None" else "Closed")
        pe_sections = [
            Obj("PE_TRUNK", FromNodeID="PE_SOURCE", ToNodeID="PE_BRANCH"),
            Obj("PE_SEC", FromNodeID="PE_BRANCH", ToNodeID=pe_to, devices=[tie]),
            Obj("PE_LATERAL", FromNodeID="PE_BRANCH", ToNodeID="PE_LOAD"),
        ]
        ca_sections = [
            Obj("CA_SEC", FromNodeID=ca_from, ToNodeID="CA_BRANCH"),
            Obj("CA_TRUNK", FromNodeID="CA_BRANCH", ToNodeID="CA_SOURCE"),
        ]
        if ambiguous:
            tie_2 = Obj("PE_CA_TIE_2", ClosedPhase="None", NormalStatus="Open")
            pe_sections.append(Obj(
                "PE_SEC_2", FromNodeID="PE_BRANCH", ToNodeID="PE_END_2",
                devices=[tie_2],
            ))
            ca_sections.append(Obj("CA_SEC_2", FromNodeID="CA_END_2", ToNodeID="CA_BRANCH"))
        self.sections = {
            "NET_1_PE104": pe_sections,
            "NET_2_CA101": ca_sections,
        }
        self.devices = {
            "NET_1_PE104": [tie] + ([tie_2] if ambiguous else []),
            "NET_2_CA101": [],
        }
        coords = {
            "PE_SOURCE": (0.0, 0.0), "PE_BRANCH": (5.0, 0.0),
            "PE_END": (10.0, 0.0), "PE_LOAD": (5.0, 5.0),
            "CA_END": (30.0, 0.0), "CA_BRANCH": (35.0, 0.0),
            "CA_SOURCE": (40.0, 0.0), "TIE_NODE": (10.0, 0.0),
            "PE_END_2": (20.0, 0.0), "CA_END_2": (20.4, 0.0),
        }
        if coordinate_tie:
            coords["CA_END"] = (10.4, 0.0)
        if interior_tie:
            coords["CA_BRANCH"] = (10.4, 0.0)
        self.nodes = [Obj(node_id, X=x, Y=y) for node_id, (x, y) in coords.items()]

    def ListNetworks(self):
        return list(self.sections)

    def ListSections(self, network):
        return self.sections[network]

    def ListDevices(self, _dtype, network):
        return self.devices[network]

    def ListNodes(self):
        return self.nodes


class Cympy:
    def __init__(self, shared=False, phase="None", coordinate_tie=False, ambiguous=False, interior_tie=False):
        self.study = Study(
            shared=shared, phase=phase,
            coordinate_tie=coordinate_tie, ambiguous=ambiguous,
            interior_tie=interior_tie,
        )
        self.enums = type("Enums", (), {"DeviceType": DeviceType})()


def settings(device_ids=None):
    return {
        "transfer_pair": ["PE104", "CA101"],
        "require_open_transfer_tie_for_diagnostic": True,
        "transfer_tie_devices": list(device_ids or []),
        "transfer_tie_max_distance_m": 1.0,
    }


class TestTransferTieSafety(unittest.TestCase):
    def test_missing_physical_point_fails_closed(self):
        result = inspect_transfer_tie_gate(Cympy(shared=False), settings())
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "TRANSFER_POINT_NOT_MODELED")
        self.assertEqual(result["discovery"]["nearest_rejected"]["distance"], 20.0)

    def test_identified_open_tie_passes(self):
        result = inspect_transfer_tie_gate(
            Cympy(shared=True, phase="None"), settings(["PE_CA_TIE"])
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["verified_open"])

    def test_identified_closed_tie_blocks_diagnostic(self):
        result = inspect_transfer_tie_gate(
            Cympy(shared=True, phase="ABC"), settings(["PE_CA_TIE"])
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "TRANSFER_TIE_CLOSED")

    def test_branch_trace_discovers_coordinate_tie_without_fixed_device_id(self):
        result = inspect_transfer_tie_gate(
            Cympy(coordinate_tie=True, phase="None"), settings()
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["verified_open"])
        self.assertEqual(result["discovery"]["candidate_count"], 1)
        self.assertEqual(result["configured_devices"][0]["device_id"], "PE_CA_TIE")
        self.assertEqual(result["trace"]["PE104"]["section_count"], 3)
        self.assertEqual(result["trace"]["PE104"]["visited_section_count"], 3)

    def test_branch_trace_rejects_ambiguous_transfer_points(self):
        result = inspect_transfer_tie_gate(
            Cympy(coordinate_tie=True, phase="None", ambiguous=True), settings()
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "TRANSFER_POINT_AMBIGUOUS")
        self.assertEqual(result["discovery"]["candidate_count"], 2)

    def test_terminal_can_match_an_interior_node_of_the_other_feeder(self):
        result = inspect_transfer_tie_gate(
            Cympy(interior_tie=True, phase="None"), settings()
        )
        self.assertTrue(result["ok"])
        candidate = result["discovery"]["candidates"][0]
        self.assertEqual(candidate["nodes"], {"PE104": "PE_END", "CA101": "CA_BRANCH"})

    def test_ensure_open_changes_only_the_discovered_tie(self):
        ensure = getattr(ties, "ensure_transfer_ties_open", None)
        self.assertTrue(callable(ensure))
        cympy = Cympy(coordinate_tie=True, phase="ABC")
        result = ensure(cympy, settings())
        self.assertTrue(result["ok"])
        self.assertEqual(result["opened_device_ids"], ["PE_CA_TIE"])
        self.assertEqual(cympy.study.devices["NET_1_PE104"][0].GetValue("ClosedPhase"), "None")

    def test_required_gate_auto_opens_and_requires_verified_commit(self):
        cympy = Cympy(coordinate_tie=True, phase="ABC")

        def commit_ok(request, mutate):
            mutation = mutate()
            return {
                "ok": True,
                "reopen_verified": True,
                "mutation": mutation,
                "manifest_path": "commit.json",
            }

        with mock.patch.object(ties, "commit_cymdist_action", side_effect=commit_ok):
            result = ties.require_transfer_tie_gate(
                cympy, settings(), adapter=object(), auto_open=True
            )

        self.assertTrue(result["ok"])
        self.assertTrue(result["verified_open"])
        self.assertEqual(result["opened_device_ids"], ["PE_CA_TIE"])
        self.assertTrue(result["commit"]["reopen_verified"])


if __name__ == "__main__":
    unittest.main()

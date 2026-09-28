import { describe, expect, it } from "vitest";
import {
  acceptDiscoveryResult,
  applyPickerResult,
  beginDatabaseSelection,
  selectFeeder,
  selectStudy,
  type SelectionState,
} from "./selection";

const initial: SelectionState = {
  databaseMdb: "D:\\bases\\a.mdb",
  canonicalDatabaseMdb: "d:\\bases\\a.mdb",
  studyPath: "D:\\studies\\multi.zxst",
  feederId: "PE104",
  networkId: "NET_2030_184_PE104",
  databaseRequestId: 4,
  feeders: [{ feeder_id: "PE104", network_id: "NET_2030_184_PE104" }],
};

describe("independent CYMDIST selection", () => {
  it("changing_database_keeps_study_and_clears_feeder", () => {
    const next = beginDatabaseSelection(
      initial,
      "D:\\other\\a.mdb",
      "d:\\other\\a.mdb"
    );
    expect(next.studyPath).toBe(initial.studyPath);
    expect(next.feederId).toBe("");
    expect(next.networkId).toBe("");
    expect(next.feeders).toEqual([]);
    expect(next.databaseRequestId).toBe(5);
  });

  it("changing_study_keeps_database_and_feeder", () => {
    const next = selectStudy(initial, "D:\\studies\\other.xst");
    expect(next.databaseMdb).toBe(initial.databaseMdb);
    expect(next.feederId).toBe(initial.feederId);
    expect(next.networkId).toBe(initial.networkId);
  });

  it("changing_feeder_keeps_database_and_study", () => {
    const next = selectFeeder(initial, "CA101", "NET_2030_131_CA101");
    expect(next.databaseMdb).toBe(initial.databaseMdb);
    expect(next.studyPath).toBe(initial.studyPath);
    expect(next.feederId).toBe("CA101");
    expect(next.networkId).toBe("NET_2030_131_CA101");
  });

  it("cancelled_picker_preserves_context", () => {
    expect(applyPickerResult(initial, { ok: true, cancelled: true, kind: "database" })).toBe(
      initial
    );
    expect(applyPickerResult(initial, { ok: true, cancelled: true, kind: "study" })).toBe(
      initial
    );
  });

  it("ignores_out_of_order_discovery_result", () => {
    const stale = acceptDiscoveryResult(initial, 3, {
      database_mdb: initial.databaseMdb,
      canonical_database_mdb: initial.canonicalDatabaseMdb,
      feeders: [{ feeder_id: "CA101", network_id: "NET_2030_131_CA101" }],
    });
    expect(stale).toBe(initial);

    const wrongDatabase = acceptDiscoveryResult(initial, 4, {
      database_mdb: "D:\\bases\\other.mdb",
      canonical_database_mdb: "d:\\bases\\other.mdb",
      feeders: [{ feeder_id: "CA101", network_id: "NET_2030_131_CA101" }],
    });
    expect(wrongDatabase).toBe(initial);
  });
});

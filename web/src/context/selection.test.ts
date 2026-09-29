import { describe, expect, it } from "vitest";
import {
  acceptDiscoveryResult,
  applyPickerResult,
  beginDatabaseSelection,
  chooseStudyForFeeder,
  resolveAppliedStudy,
  selectFeeder,
  selectStudy,
  type SelectionState,
} from "./selection";
import * as selectionModule from "./selection";

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

  it("accepts_every_feeder_from_the_selected_mdb_with_windows_path_variants", () => {
    const selected = beginDatabaseSelection(
      initial,
      "D:\\BaseDatos\\260924.mdb",
      "D:\\BaseDatos\\260924.mdb"
    );
    const feeders = Array.from({ length: 101 }, (_, index) => ({
      feeder_id: `F${String(index + 1).padStart(3, "0")}`,
      network_id: `NET_${index + 1}`,
    }));

    const accepted = acceptDiscoveryResult(selected, selected.databaseRequestId, {
      database_mdb: "d:/basedatos/260924.mdb",
      canonical_database_mdb: "d:/basedatos/260924.mdb",
      feeders,
    });

    expect(accepted).not.toBe(selected);
    expect(accepted.feeders).toHaveLength(101);
    expect(accepted.feeders).toEqual(feeders);
  });
});

describe("feeder readiness presentation", () => {
  it("does_not_report_missing_readiness_metadata_as_blocked_after_1_1", () => {
    const derive = (
      selectionModule as typeof selectionModule & {
        deriveFeederReadiness?: (
          feeder: { operational?: boolean; inputs_ready?: boolean } | undefined,
          cymdistReady: boolean
        ) => { contextLabel: string; inputsLabel: string; tone: string };
      }
    ).deriveFeederReadiness;

    expect(typeof derive).toBe("function");
    if (!derive) return;
    expect(derive({}, true)).toEqual({
      contextLabel: "listo",
      inputsLabel: "por validar",
      tone: "ok",
    });
  });
});

describe("study resolution for selected feeder", () => {
  it("selects_the_exact_feeder_study_with_engine_extension_priority", () => {
    const studies = [
      { path: "D:\\projects\\ELD.zxst", feeder_id: "ELD", ext: ".zxst" },
      { path: "D:\\projects\\AL209.sxst", feeder_id: "AL209", ext: ".sxst" },
      { path: "D:\\projects\\AL209.zxst", feeder_id: "AL209", ext: ".zxst" },
    ];

    expect(chooseStudyForFeeder(studies, "al209")).toBe(
      "D:\\projects\\AL209.zxst"
    );
  });

  it("returns_empty_when_no_study_exists_for_the_feeder", () => {
    expect(
      chooseStudyForFeeder(
        [{ path: "D:\\projects\\ELD.zxst", feeder_id: "ELD", ext: ".zxst" }],
        "AL209"
      )
    ).toBe("");
  });
});

describe("study returned by 1.1", () => {
  it("accepts_the_new_saved_study_when_backend_created_it", () => {
    expect(
      resolveAppliedStudy(
        "D:\\studies\\ELD.zxst",
        "D:\\studies\\AL209.zxst",
        true
      )
    ).toBe("D:\\studies\\AL209.zxst");
  });

  it("keeps_strict_identity_when_existing_study_was_reused", () => {
    expect(() =>
      resolveAppliedStudy(
        "D:\\studies\\ELD.zxst",
        "D:\\studies\\OTRO.zxst",
        false
      )
    ).toThrow(/STUDY_IDENTITY_MISMATCH/);
  });
});

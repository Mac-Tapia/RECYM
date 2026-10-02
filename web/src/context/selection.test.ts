import { describe, expect, it } from "vitest";
import {
  acceptDiscoveryResult,
  applyPickerResult,
  beginDatabaseSelection,
  canHydratePersistedContext,
  chooseStudyForFeeder,
  resolveAppliedStudy,
  selectFeeder,
  selectStudy,
  studiesForFeeder,
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
  it("does_not_replace_a_pending_local_feeder_with_a_different_persisted_context", () => {
    expect(
      canHydratePersistedContext(
        {
          feeder: "CA101",
          network: "NET_2030_131_CA101",
          studyPath: "D:\\projects\\CA101.sxst",
          databaseMdb: "D:\\bases\\selected.mdb",
        },
        {
          feeder: "TM104",
          network: "NET_2030_173_TM104",
          studyPath: "D:\\projects\\TM104.zxst",
          databaseMdb: "D:\\bases\\selected.mdb",
        }
      )
    ).toBe(false);
  });

  it("hydrates_an_empty_client_context_and_accepts_case_or_slash_variants", () => {
    const persisted = {
      feeder: "CA101",
      network: "NET_2030_131_CA101",
      studyPath: "D:\\projects\\CA101.sxst",
      databaseMdb: "D:\\bases\\selected.mdb",
    };
    expect(canHydratePersistedContext({}, persisted)).toBe(true);
    expect(
      canHydratePersistedContext(
        {
          feeder: "ca101",
          network: "net_2030_131_ca101",
          studyPath: "d:/PROJECTS/ca101.sxst",
          databaseMdb: "d:/BASES/selected.mdb",
        },
        persisted
      )
    ).toBe(true);
  });

  it("rejects_same_feeder_from_a_different_mdb", () => {
    expect(
      canHydratePersistedContext(
        {
          feeder: "CA101",
          network: "NET_2030_131_CA101",
          studyPath: "D:\\projects\\CA101.sxst",
          databaseMdb: "D:\\bases\\first.mdb",
        },
        {
          feeder: "CA101",
          network: "NET_2030_131_CA101",
          studyPath: "D:\\projects\\CA101.sxst",
          databaseMdb: "D:\\other\\first.mdb",
        }
      )
    ).toBe(false);
  });

  it("changing_database_clears_study_and_feeder", () => {
    const next = beginDatabaseSelection(
      initial,
      "D:\\other\\a.mdb",
      "d:\\other\\a.mdb"
    );
    expect(next.studyPath).toBe("");
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

  it("changing_feeder_keeps_database_and_clears_study", () => {
    const next = selectFeeder(initial, "CA101", "NET_2030_131_CA101");
    expect(next.databaseMdb).toBe(initial.databaseMdb);
    expect(next.studyPath).toBe("");
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
  it("only_offers_studies_for_the_selected_feeder_family_or_shared_eld", () => {
    const studies = [
      { path: "D:\\projects\\TM104.xst", feeder_id: "TM104", ext: ".xst" },
      { path: "D:\\projects\\TM105.zxst", feeder_id: "TM105", ext: ".zxst" },
      { path: "D:\\projects\\TM105V2.sxst", feeder_id: "TM105V2", ext: ".sxst" },
      { path: "D:\\projects\\ELD.zxst", feeder_id: "ELD", ext: ".zxst" },
    ];

    expect(
      studiesForFeeder(studies, "TM105").map((study) =>
        typeof study === "string" ? study : study.path
      )
    ).toEqual([
      "D:\\projects\\TM105.zxst",
      "D:\\projects\\TM105V2.sxst",
      "D:\\projects\\ELD.zxst",
    ]);
    expect(studiesForFeeder(studies, "")).toEqual([]);
  });

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

describe("transfer study pair", () => {
  it("offers the studies of both feeders (PE104 lives in CA101.sxst)", () => {
    const studies = [
      { path: "D:\p\CA101.sxst", feeder_id: "CA101", ext: ".sxst" },
      { path: "D:\p\TM105.zxst", feeder_id: "TM105", ext: ".zxst" },
      { path: "D:\p\ELD.zxst", feeder_id: "ELD", ext: ".zxst" },
    ];
    const paths = selectionModule
      .studiesForPair(studies, "PE104", "CA101")
      .map((s) => (typeof s === "string" ? s : s.path));
    expect(paths).toEqual(["D:\p\ELD.zxst", "D:\p\CA101.sxst"]);
    expect(selectionModule.studiesForFeeder(studies, "PE104").length).toBe(1);
  });
});

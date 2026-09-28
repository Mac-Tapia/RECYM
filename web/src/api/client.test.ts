import { describe, expect, it } from "vitest";
import { buildDetachedJobEnvelope, setActiveContext } from "./client";

describe("detached jobs", () => {
  it("uses_exact_payload_without_active_context", () => {
    setActiveContext({
      feeder: "OLD",
      network: "NET_OLD",
      studyPath: "D:\\old\\old.zxst",
      databaseMdb: "D:\\old\\old.mdb",
    });
    const envelope = buildDetachedJobEnvelope("contexto_descubrir_redes", {
      database_mdb: "D:\\new\\new.mdb",
    });
    expect(envelope).toEqual({
      action: "contexto_descubrir_redes",
      payload: { database_mdb: "D:\\new\\new.mdb" },
    });
    expect(envelope).not.toHaveProperty("feeder");
    expect(envelope.payload).not.toHaveProperty("study_path");
    expect(envelope.payload).not.toHaveProperty("network_id");
  });
});

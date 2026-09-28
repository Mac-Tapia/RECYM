import { describe, expect, it } from "vitest";
import {
  buildDetachedJobEnvelope,
  setActiveContext,
  verifyProtectedJobContext,
} from "./client";

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

describe("protected CYMDIST jobs", () => {
  it("accepts only the fingerprint selected in section 1", () => {
    expect(
      verifyProtectedJobContext(
        "flujo",
        { ok: true, context_fingerprint: "abc123" },
        "abc123"
      )
    ).toMatchObject({ ok: true });
    expect(() =>
      verifyProtectedJobContext(
        "flujo",
        { ok: true, context_fingerprint: "other" },
        "abc123"
      )
    ).toThrow(/contexto distinto/i);
    expect(() => verifyProtectedJobContext("flujo", { ok: true }, "abc123")).toThrow(
      /sin huella/i
    );
  });

  it("does not impose CYMDIST identity on detached discovery", () => {
    expect(
      verifyProtectedJobContext("contexto_descubrir_redes", { ok: true }, "abc123")
    ).toMatchObject({ ok: true });
  });
});

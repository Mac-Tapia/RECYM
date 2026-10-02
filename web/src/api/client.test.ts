import { describe, expect, it } from "vitest";
import {
  buildDetachedJobEnvelope,
  getActiveContext,
  pollJobUntilDone,
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

describe("job polling after SSE drop", () => {
  const noSleep = () => Promise.resolve();

  it("keeps waiting while the job is still running", async () => {
    const states = [{ status: "running" }, { status: "running" }, { status: "ok", result: { ok: true, n: 7 } }];
    let i = 0;
    const result = await pollJobUntilDone(() => Promise.resolve(states[i++]), undefined, { sleep: noSleep });
    expect(result).toEqual({ ok: true, n: 7 });
    expect(i).toBe(3);
  });

  it("tolerates transient network failures", async () => {
    let calls = 0;
    const result = await pollJobUntilDone(
      () => {
        calls += 1;
        if (calls < 3) return Promise.reject(new Error("Failed to fetch"));
        return Promise.resolve({ status: "ok", result: { ok: true } });
      },
      undefined,
      { sleep: noSleep }
    );
    expect(result).toEqual({ ok: true });
  });

  it("surfaces the job's own error immediately", async () => {
    await expect(
      pollJobUntilDone(
        () => Promise.resolve({ status: "error", result: { error: "LF no convergió" } }),
        undefined,
        { sleep: noSleep }
      )
    ).rejects.toThrow("LF no convergió");
  });

  it("gives up after repeated connection failures", async () => {
    await expect(
      pollJobUntilDone(() => Promise.reject(new Error("Failed to fetch")), undefined, {
        sleep: noSleep,
        maxFailures: 3,
      })
    ).rejects.toThrow("Failed to fetch");
  });
});

describe("transfer scenario context", () => {
  it("exposes scenario and peer for jobs", () => {
    setActiveContext({
      scenarioId: "transfer_PA217_PA218",
      transferPeer: "PA218",
      transferPeerNetwork: "ELD_PA218",
    });
    expect(getActiveContext()).toMatchObject({
      scenarioId: "transfer_PA217_PA218",
      transferPeer: "PA218",
      transferPeerNetwork: "ELD_PA218",
    });
    setActiveContext({ scenarioId: "", transferPeer: "", transferPeerNetwork: "" });
  });
});

import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import { setActiveFeeder } from "../api/client";

type Ctx = {
  feeder: string;
  network: string;
  setFeeder: (f: string, network?: string) => void;
};

const FeederCtx = createContext<Ctx | null>(null);

export function FeederProvider({ children }: { children: ReactNode }) {
  const [feeder, setF] = useState("");
  const [network, setN] = useState("");
  const value = useMemo<Ctx>(
    () => ({
      feeder,
      network,
      setFeeder: (f, n) => {
        setF(f || "");
        if (n !== undefined) setN(n || "");
        setActiveFeeder(f || "");
      },
    }),
    [feeder, network]
  );
  return <FeederCtx.Provider value={value}>{children}</FeederCtx.Provider>;
}

export function useFeeder() {
  const c = useContext(FeederCtx);
  if (!c) throw new Error("useFeeder fuera de provider");
  return c;
}

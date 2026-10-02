import { describe, expect, it } from "vitest";
import { filePeriodKey, sortByPeriodDesc } from "./periodFiles";

describe("archivos por periodo MMAA", () => {
  it("elige el clientesimportantes más reciente", () => {
    const files = [
      "0126clientesImportantes.xlsb",
      "0726clientesImportantes.xlsx",
      "1225clientesImportantes.xlsb",
      "0526clientesImportantes.xlsx",
    ];
    expect(sortByPeriodDesc(files)[0]).toBe("0726clientesImportantes.xlsx");
    expect(sortByPeriodDesc(files).at(-1)).toBe("1225clientesImportantes.xlsb");
  });

  it("lee el periodo de suministrocliente ML_MMAA", () => {
    expect(filePeriodKey("ML_1225.xlsx")).toBe(202512);
    expect(sortByPeriodDesc(["ML_1225.xlsx", "ML_0326.xlsx"])[0]).toBe("ML_0326.xlsx");
  });
});

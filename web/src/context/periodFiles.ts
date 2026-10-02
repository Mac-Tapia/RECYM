/** Periodo MMAA embebido en el nombre: 0726clientesImportantes, ML_1225… */
export function filePeriodKey(name: string): number {
  const base = String(name || "").split(/[/\\]/).pop() || "";
  const m = base.match(/(?:^|[^0-9])(\d{2})(\d{2})(?=[^0-9]|$)/) || base.match(/^(\d{2})(\d{2})/);
  if (!m) return -1;
  const month = Number(m[1]);
  const year = Number(m[2]);
  if (month < 1 || month > 12) return -1;
  return (2000 + year) * 100 + month;
}

/** Más reciente primero; empates o sin periodo: orden alfabético inverso. */
export function sortByPeriodDesc(names: string[]): string[] {
  return [...(names || [])].sort((a, b) => {
    const diff = filePeriodKey(b) - filePeriodKey(a);
    return diff !== 0 ? diff : b.localeCompare(a);
  });
}

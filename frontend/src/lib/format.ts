export function fmtPct(v: number | null | undefined): string {
  return v === null || v === undefined ? "UNKNOWN" : `${(v * 100).toFixed(1)}%`;
}

export function fmtNum(v: number | null | undefined): string {
  return v === null || v === undefined ? "UNKNOWN" : v.toFixed(2);
}

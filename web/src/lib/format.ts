export function mmss(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

export function fixed(value: number, places = 1): string {
  return value.toFixed(places);
}

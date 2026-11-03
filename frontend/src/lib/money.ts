// Money arrives from the API as integer paise and is formatted once, here, at the UI edge.
const rupees = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const wholeRupees = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 0,
});

/** 1234567 -> "₹12,345.67". Integer arithmetic until the very last step. */
export function formatPaise(paise: number, opts: { whole?: boolean } = {}): string {
  if (!Number.isInteger(paise)) throw new Error(`paise must be an integer, got ${paise}`);
  if (opts.whole) return wholeRupees.format(Math.round(paise / 100));
  const sign = paise < 0 ? "-" : "";
  const abs = Math.abs(paise);
  const whole = Math.trunc(abs / 100);
  const rest = abs % 100;
  return sign + rupees.format(whole).replace(/\.00$/, "") + "." + String(rest).padStart(2, "0");
}

export function formatMonth(isoDate: string): string {
  return new Date(`${isoDate}T00:00:00`).toLocaleDateString("en-IN", { month: "short", year: "numeric" });
}

export function formatDate(isoDate: string): string {
  return new Date(`${isoDate}T00:00:00`).toLocaleDateString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

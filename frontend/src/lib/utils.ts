import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Backend timestamps are UTC; SQLite-backed dev servers may omit the zone suffix. */
export function parseDate(value: string): Date {
  return new Date(/[zZ]|[+-]\d{2}:?\d{2}$/.test(value) ? value : `${value}Z`);
}

const dateFormatter = new Intl.DateTimeFormat(undefined, { year: "numeric", month: "short", day: "numeric" });
const dateTimeFormatter = new Intl.DateTimeFormat(undefined, { year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

export const formatDate = (value: string | null | undefined) => (value ? dateFormatter.format(parseDate(value)) : "—");
export const formatDateTime = (value: string | null | undefined) => (value ? dateTimeFormatter.format(parseDate(value)) : "—");

export function formatRelative(value: string, now: Date = new Date()): string {
  const seconds = Math.round((now.getTime() - parseDate(value).getTime()) / 1000);
  const units: [number, Intl.RelativeTimeFormatUnit][] = [
    [60, "second"],
    [60, "minute"],
    [24, "hour"],
    [7, "day"],
    [4.345, "week"],
    [12, "month"],
    [Number.POSITIVE_INFINITY, "year"],
  ];
  const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  let amount = seconds;
  for (const [size, unit] of units) {
    if (Math.abs(amount) < size) return formatter.format(-Math.round(amount), unit);
    amount /= size;
  }
  return formatDate(value);
}

export function toNumber(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

/** Scores keep up to two decimals but drop trailing zeros ("50.00" -> "50", "71.30" -> "71.3"). */
export function formatScore(value: string | number | null | undefined): string {
  const parsed = toNumber(value);
  if (parsed === null) return "—";
  return String(Number(parsed.toFixed(2)));
}

export function formatYears(value: string | number | null | undefined): string {
  const parsed = toNumber(value);
  if (parsed === null) return "Not recorded";
  return `${formatScore(parsed)} ${parsed === 1 ? "year" : "years"}`;
}

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]!.toUpperCase())
    .join("");
}

export function pluralize(count: number, singular: string, plural = `${singular}s`) {
  return `${count.toLocaleString()} ${count === 1 ? singular : plural}`;
}

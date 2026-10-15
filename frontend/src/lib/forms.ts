import type { FieldValues, Path, UseFormSetError } from "react-hook-form";
import { toast } from "sonner";
import { isApiError } from "@/lib/api/client";

/**
 * Apply server validation errors to form fields. Returns a message for errors that do not map
 * to a field (shown above the form), or null when everything was attached to fields.
 */
export function applyServerErrors<T extends FieldValues>(error: unknown, setError: UseFormSetError<T>, fields: readonly string[]): string | null {
  if (!isApiError(error)) return "Something went wrong. Please try again.";
  if (error.status !== 422 || error.details.length === 0) return error.message;
  const unmatched: string[] = [];
  for (const [path, message] of Object.entries(error.fieldErrors())) {
    const root = path.split(".")[0]!;
    if (fields.includes(root)) setError(path as Path<T>, { type: "server", message });
    else unmatched.push(message);
  }
  return unmatched.length ? unmatched.join(" ") : null;
}

export function toastError(error: unknown, fallback = "The action could not be completed.") {
  toast.error(isApiError(error) ? error.message : fallback);
}

/** Convert an optional numeric text input into number | null for the API. */
export const optionalNumber = (value: string | number | null | undefined): number | null => {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

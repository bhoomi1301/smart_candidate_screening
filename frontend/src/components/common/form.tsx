import { X } from "lucide-react";
import * as React from "react";
import { inputClasses } from "@/components/ui/input";
import { Label } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";

interface FieldProps {
  id: string;
  label: string;
  error?: string;
  hint?: React.ReactNode;
  required?: boolean;
  className?: string;
  children: (props: { id: string; "aria-invalid": boolean; "aria-describedby"?: string; "aria-required"?: boolean }) => React.ReactNode;
}

/** Label + control + hint + error, with ids wired for screen readers. */
export function Field({ id, label, error, hint, required, className, children }: FieldProps) {
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <Label htmlFor={id}>
        {label}
        {required && (
          <span className="ml-0.5 text-destructive" aria-hidden="true">
            *
          </span>
        )}
      </Label>
      {children({ id, "aria-invalid": Boolean(error), "aria-describedby": [hintId, errorId].filter(Boolean).join(" ") || undefined, "aria-required": required || undefined })}
      {hint && !error && (
        <p id={hintId} className="text-xs text-muted-foreground">
          {hint}
        </p>
      )}
      {error && (
        <p id={errorId} className="text-xs font-medium text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}

/** Chip input for skill lists: Enter or comma adds, Backspace on an empty input removes the last chip. */
export function TagInput({
  id,
  value,
  onChange,
  placeholder,
  invalid,
  describedBy,
  maxLength = 100,
}: {
  id: string;
  value: string[];
  onChange: (value: string[]) => void;
  placeholder?: string;
  invalid?: boolean;
  describedBy?: string;
  maxLength?: number;
}) {
  const [draft, setDraft] = React.useState("");
  const add = (raw: string) => {
    const parts = raw
      .split(",")
      .map((part) => part.trim().replace(/\s+/g, " "))
      .filter(Boolean);
    const next = [...value];
    for (const part of parts) {
      if (!next.some((existing) => existing.toLowerCase() === part.toLowerCase())) next.push(part.slice(0, maxLength));
    }
    if (next.length !== value.length) onChange(next);
    setDraft("");
  };
  return (
    <div className={cn(inputClasses, "h-auto min-h-9 flex-wrap items-center gap-1.5 py-1.5")} aria-invalid={invalid || undefined}>
      {value.map((tag) => (
        <span key={tag} className="inline-flex items-center gap-1 rounded bg-secondary py-0.5 pl-2 pr-1 text-xs font-medium">
          {tag}
          <button type="button" className="rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground" onClick={() => onChange(value.filter((item) => item !== tag))} aria-label={`Remove ${tag}`}>
            <X className="size-3" aria-hidden="true" />
          </button>
        </span>
      ))}
      <input
        id={id}
        value={draft}
        aria-describedby={describedBy}
        aria-invalid={invalid || undefined}
        className="min-w-[8rem] flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
        placeholder={value.length ? "Add another…" : placeholder}
        onChange={(event) => {
          if (event.target.value.includes(",")) add(event.target.value);
          else setDraft(event.target.value);
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            if (draft.trim()) add(draft);
          } else if (event.key === "Backspace" && !draft && value.length) {
            onChange(value.slice(0, -1));
          }
        }}
        onBlur={() => draft.trim() && add(draft)}
      />
    </div>
  );
}

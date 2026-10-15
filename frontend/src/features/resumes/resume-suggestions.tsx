import { AlertTriangle, FileSearch, Quote } from "lucide-react";
import * as React from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/overlays";
import { Badge } from "@/components/ui/primitives";
import type { CandidateFormValues } from "@/features/candidates/candidate-form-page";
import type { ResumeExtraction, ResumeSuggestions } from "@/lib/api/types";
import { cn, formatScore } from "@/lib/utils";

// Must not exceed the API limit (RESUME_MAX_BYTES). Production sets 4 MB to fit the Vercel proxy body limit.
export const RESUME_MAX_MB = Number(import.meta.env.VITE_RESUME_MAX_MB) || 5;
export const RESUME_MAX_BYTES = RESUME_MAX_MB * 1024 * 1024;

/** Quick client-side checks for usability. The server re-validates the actual file content. */
export function resumeFileProblem(file: File): string | null {
  if (!file.name.toLowerCase().endsWith(".pdf") || (file.type && !["application/pdf", "application/x-pdf"].includes(file.type))) return "Choose a PDF file.";
  if (file.size === 0) return "The file is empty.";
  if (file.size > RESUME_MAX_BYTES) return `The PDF must be ${RESUME_MAX_MB} MB or smaller.`;
  return null;
}

type EducationRow = CandidateFormValues["education"][number];

export interface SuggestionSelection {
  fullName: { use: boolean; value: string };
  email: string | null; // null keeps the current value
  phone: string | null;
  experience: { use: boolean; value: string };
  skills: string[];
  education: (EducationRow & { use: boolean })[];
}

const normalise = (value: string) => value.trim().toLowerCase().replace(/\s+/g, " ");

export function defaultSelection(current: CandidateFormValues, suggestions: ResumeSuggestions): SuggestionSelection {
  const currentSkills = new Set(current.technical_skills.map(normalise));
  const currentEducation = new Set(current.education.map((item) => `${normalise(item.degree)}|${normalise(item.field_of_study)}`));
  const placeholderName = !current.full_name.trim();
  return {
    fullName: { use: Boolean(suggestions.full_name) && placeholderName, value: suggestions.full_name?.value ?? "" },
    email: !current.email.trim() && suggestions.emails[0] ? suggestions.emails[0].value : null,
    phone: !current.phone.trim() && suggestions.phones[0] ? suggestions.phones[0].value : null,
    experience: { use: Boolean(suggestions.total_experience) && !current.total_experience.trim(), value: suggestions.total_experience ? formatScore(suggestions.total_experience.value) : "" },
    skills: suggestions.skills.map((item) => item.value).filter((skill) => !currentSkills.has(normalise(skill))),
    education: suggestions.education.map((item) => ({
      degree: item.degree,
      field_of_study: item.field_of_study ?? "",
      institution: item.institution ?? "",
      graduation_year: item.graduation_year?.toString() ?? "",
      use: !currentEducation.has(`${normalise(item.degree)}|${normalise(item.field_of_study ?? "")}`),
    })),
  };
}

/** Merge the reviewed selection into form values. Never removes what HR already entered. */
export function applySuggestions(current: CandidateFormValues, selection: SuggestionSelection): CandidateFormValues {
  const skills = [...current.technical_skills];
  for (const skill of selection.skills) if (!skills.some((existing) => normalise(existing) === normalise(skill))) skills.push(skill);
  return {
    ...current,
    full_name: selection.fullName.use && selection.fullName.value.trim() ? selection.fullName.value.trim() : current.full_name,
    email: selection.email ?? current.email,
    phone: selection.phone ?? current.phone,
    total_experience: selection.experience.use && selection.experience.value.trim() ? selection.experience.value.trim() : current.total_experience,
    technical_skills: skills,
    education: [...current.education, ...selection.education.filter((item) => item.use && item.degree.trim()).map(({ use: _use, ...item }) => item)],
  };
}

export function ExtractionStatus({ extraction }: { extraction: ResumeExtraction }) {
  if (extraction.status === "ok") return null;
  return (
    <div role="status" className="flex items-start gap-2 rounded-md border border-warning/30 bg-warning-soft px-3 py-2 text-sm">
      <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden="true" />
      <span>{extraction.message}</span>
    </div>
  );
}

function Evidence({ text }: { text: string }) {
  return (
    <p className="mt-1 flex items-start gap-1 text-xs text-muted-foreground">
      <Quote className="mt-0.5 size-3 shrink-0" aria-hidden="true" />
      <span className="break-words">{text}</span>
    </p>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <fieldset className="space-y-2 border-t pt-3 first:border-t-0 first:pt-0">
      <legend className="mb-1 text-sm font-semibold">{title}</legend>
      {children}
    </fieldset>
  );
}

function ChoiceGroup({ name, label, current, options, value, onChange }: { name: string; label: string; current: string; options: { value: string; evidence: string }[]; value: string | null; onChange: (value: string | null) => void }) {
  if (!options.length) return null;
  return (
    <Section title={label}>
      <label className="flex items-center gap-2 text-sm">
        <input type="radio" name={name} className="accent-[hsl(var(--primary))]" checked={value === null} onChange={() => onChange(null)} />
        Keep current: <span className="font-medium">{current || <span className="text-muted-foreground">empty</span>}</span>
      </label>
      {options.map((option) => (
        <div key={option.value}>
          <label className="flex items-center gap-2 text-sm">
            <input type="radio" name={name} className="accent-[hsl(var(--primary))]" checked={value === option.value} onChange={() => onChange(option.value)} />
            Use <span className="font-medium break-all">{option.value}</span>
          </label>
          <div className="pl-6">
            <Evidence text={option.evidence} />
          </div>
        </div>
      ))}
    </Section>
  );
}

export function SuggestionsDialog({
  open,
  onOpenChange,
  extraction,
  current,
  onApply,
  applyLabel,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  extraction: ResumeExtraction | null;
  current: CandidateFormValues;
  onApply: (values: CandidateFormValues) => void;
  applyLabel: string;
}) {
  const [selection, setSelection] = React.useState<SuggestionSelection | null>(null);
  React.useEffect(() => {
    if (open && extraction) setSelection(defaultSelection(current, extraction.suggestions));
    // Recompute only when the dialog opens with new results, not on every keystroke in the form behind it.
  }, [open, extraction]);
  if (!extraction || !selection) return null;
  const { suggestions } = extraction;
  const currentSkills = new Set(current.technical_skills.map(normalise));
  const update = (patch: Partial<SuggestionSelection>) => setSelection({ ...selection, ...patch });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileSearch className="size-4 text-muted-foreground" aria-hidden="true" /> Review details found in the resume
          </DialogTitle>
          <DialogDescription>{extraction.notice} Nothing is saved until you submit the candidate form.</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <ExtractionStatus extraction={extraction} />
          {suggestions.full_name && (
            <Section title="Name">
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" className="accent-[hsl(var(--primary))]" checked={selection.fullName.use} onChange={(event) => update({ fullName: { ...selection.fullName, use: event.target.checked } })} />
                Replace “{current.full_name || "empty"}” with
                <Badge variant="warning">low confidence</Badge>
              </label>
              <Input aria-label="Suggested name" value={selection.fullName.value} disabled={!selection.fullName.use} onChange={(event) => update({ fullName: { ...selection.fullName, value: event.target.value } })} />
              <Evidence text={suggestions.full_name.evidence} />
            </Section>
          )}
          <ChoiceGroup name="resume-email" label="Email" current={current.email} options={suggestions.emails} value={selection.email} onChange={(email) => update({ email })} />
          <ChoiceGroup name="resume-phone" label="Phone" current={current.phone} options={suggestions.phones} value={selection.phone} onChange={(phone) => update({ phone })} />
          {suggestions.total_experience && (
            <Section title="Experience">
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" className="accent-[hsl(var(--primary))]" checked={selection.experience.use} onChange={(event) => update({ experience: { ...selection.experience, use: event.target.checked } })} />
                Set total experience (currently {current.total_experience || "not recorded"}) to
              </label>
              <div className="flex items-center gap-2">
                <Input aria-label="Suggested years of experience" type="number" min={0} max={80} step="0.5" className="w-28" value={selection.experience.value} disabled={!selection.experience.use} onChange={(event) => update({ experience: { ...selection.experience, value: event.target.value } })} />
                <span className="text-sm text-muted-foreground">years · {suggestions.total_experience.method === "stated" ? "stated in the resume" : "estimated from date ranges"}</span>
              </div>
              <Evidence text={suggestions.total_experience.evidence} />
            </Section>
          )}
          {suggestions.skills.length > 0 && (
            <Section title={`Skills (${suggestions.skills.length} found)`}>
              <ul className="grid gap-1.5 sm:grid-cols-2">
                {suggestions.skills.map((skill) => {
                  const already = currentSkills.has(normalise(skill.value));
                  const checked = already || selection.skills.includes(skill.value);
                  return (
                    <li key={skill.value}>
                      <label className={cn("flex items-start gap-2 rounded-md border px-2.5 py-1.5 text-sm", already && "opacity-60")} title={skill.evidence}>
                        <input
                          type="checkbox"
                          className="mt-0.5 accent-[hsl(var(--primary))]"
                          checked={checked}
                          disabled={already}
                          onChange={(event) => update({ skills: event.target.checked ? [...selection.skills, skill.value] : selection.skills.filter((item) => item !== skill.value) })}
                        />
                        <span>
                          <span className="font-medium">{skill.value}</span>
                          {already && <span className="text-muted-foreground"> · already listed</span>}
                        </span>
                      </label>
                    </li>
                  );
                })}
              </ul>
            </Section>
          )}
          {selection.education.length > 0 && (
            <Section title="Education">
              {selection.education.map((item, index) => (
                <div key={index} className="rounded-md border p-2.5">
                  <label className="flex items-center gap-2 text-sm font-medium">
                    <input
                      type="checkbox"
                      className="accent-[hsl(var(--primary))]"
                      checked={item.use}
                      onChange={(event) => update({ education: selection.education.map((row, i) => (i === index ? { ...row, use: event.target.checked } : row)) })}
                    />
                    Add this education entry
                  </label>
                  <div className="mt-2 grid gap-2 sm:grid-cols-[1fr_1.5fr_1.5fr_5rem]">
                    {(["degree", "field_of_study", "institution", "graduation_year"] as const).map((key) => (
                      <Input
                        key={key}
                        aria-label={{ degree: "Degree", field_of_study: "Field of study", institution: "Institution", graduation_year: "Year" }[key]}
                        placeholder={{ degree: "Degree", field_of_study: "Field", institution: "Institution", graduation_year: "Year" }[key]}
                        value={item[key]}
                        disabled={!item.use}
                        onChange={(event) => update({ education: selection.education.map((row, i) => (i === index ? { ...row, [key]: event.target.value } : row)) })}
                      />
                    ))}
                  </div>
                  <Evidence text={suggestions.education[index]!.evidence} />
                </div>
              ))}
            </Section>
          )}
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            type="button"
            disabled={extraction.status !== "ok"}
            onClick={() => {
              onApply(applySuggestions(current, selection));
              onOpenChange(false);
            }}
          >
            {applyLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

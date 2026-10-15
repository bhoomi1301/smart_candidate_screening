import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { GraduationCap, Plus, Trash2 } from "lucide-react";
import * as React from "react";
import { Controller, useFieldArray, useForm } from "react-hook-form";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { z } from "zod";
import { ErrorState, InlineError, PageHeader, PageSkeleton } from "@/components/common/feedback";
import { Field, TagInput } from "@/components/common/form";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/primitives";
import { isApiError } from "@/lib/api/client";
import { candidatesApi } from "@/lib/api/endpoints";
import type { CandidateDetail, CandidateInput } from "@/lib/api/types";
import { applyServerErrors, optionalNumber } from "@/lib/forms";
import { ResumeStarter } from "@/features/resumes/resume-starter";
import { FileText } from "lucide-react";

// Mirrors backend/app/schemas/candidate.py so most mistakes are caught before a round trip.
const optionalNumberText = (check: (value: number) => string | null) =>
  z.string().superRefine((value, context) => {
    if (value.trim() === "") return;
    const parsed = Number(value);
    const message = Number.isFinite(parsed) ? check(parsed) : "Enter a number";
    if (message) context.addIssue({ code: z.ZodIssueCode.custom, message });
  });

export const candidateSchema = z.object({
  full_name: z.string().trim().min(2, "Use at least 2 characters").max(160, "Use at most 160 characters"),
  email: z.string().trim().min(1, "Email is required").email("Enter a valid email address").max(320),
  phone: z
    .string()
    .trim()
    .max(40)
    .refine((value) => value === "" || (/^\+?[0-9][0-9 ()./-]{5,38}$/.test(value) && (value.match(/\d/g)?.length ?? 0) >= 6 && (value.match(/\d/g)?.length ?? 0) <= 20), {
      message: "Use 6–20 digits; only +, spaces, parentheses, dots, or dashes",
    }),
  total_experience: optionalNumberText((value) => (value < 0 || value > 80 ? "Must be between 0 and 80" : Math.round(value * 100) !== value * 100 ? "Use at most 2 decimals" : null)),
  technical_skills: z.array(z.string().max(100, "Each skill must be 100 characters or fewer")).max(100, "Add at most 100 skills"),
  education: z
    .array(
      z.object({
        degree: z.string().trim().min(1, "Degree is required").max(160),
        field_of_study: z.string().trim().max(160),
        institution: z.string().trim().max(180),
        graduation_year: optionalNumberText((value) => (!Number.isInteger(value) || value < 1900 || value > 2100 ? "Use a year between 1900 and 2100" : null)),
      }),
    )
    .max(30),
});
export type CandidateFormValues = z.infer<typeof candidateSchema>;
const FIELDS = ["full_name", "email", "phone", "total_experience", "technical_skills", "education"] as const;

export function toCandidateFormValues(candidate?: CandidateDetail): CandidateFormValues {
  return {
    full_name: candidate?.full_name ?? "",
    email: candidate?.email ?? "",
    phone: candidate?.phone ?? "",
    total_experience: candidate?.total_experience ?? "",
    technical_skills: candidate?.technical_skills ?? [],
    education: (candidate?.education ?? []).map((item) => ({
      degree: item.degree,
      field_of_study: item.field_of_study ?? "",
      institution: item.institution ?? "",
      graduation_year: item.graduation_year?.toString() ?? "",
    })),
  };
}

export function toCandidateInput(values: CandidateFormValues): CandidateInput {
  return {
    full_name: values.full_name.trim(),
    email: values.email.trim(),
    phone: values.phone.trim() || null,
    total_experience: optionalNumber(values.total_experience),
    technical_skills: values.technical_skills,
    education: values.education.map((item) => ({
      degree: item.degree.trim(),
      field_of_study: item.field_of_study.trim() || null,
      institution: item.institution.trim() || null,
      graduation_year: optionalNumber(item.graduation_year),
    })),
  };
}

export function CandidateFormPage() {
  const { candidateId } = useParams();
  const id = candidateId ? Number(candidateId) : null;
  const existing = useQuery({ queryKey: ["candidates", id], queryFn: () => candidatesApi.get(id!), enabled: id !== null });
  if (id !== null && existing.isPending) return <PageSkeleton />;
  if (id !== null && existing.isError) return <ErrorState error={existing.error} onRetry={() => existing.refetch()} />;
  return <CandidateForm candidate={existing.data} />;
}

function CandidateForm({ candidate }: { candidate?: CandidateDetail }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [formError, setFormError] = React.useState<string | null>(null);
  const location = useLocation();
  const prefill = (location.state as { resumePrefill?: CandidateFormValues } | null)?.resumePrefill;
  const [fromResume, setFromResume] = React.useState(Boolean(prefill));
  const [resumeFile, setResumeFile] = React.useState<File | null>(null);
  const form = useForm<CandidateFormValues>({ resolver: zodResolver(candidateSchema), defaultValues: toCandidateFormValues(candidate) });
  const education = useFieldArray({ control: form.control, name: "education" });
  const { errors, isDirty } = form.formState;

  // Values reviewed in the resume dialog on the profile page arrive as router state; they stay unsaved until submit.
  React.useEffect(() => {
    if (prefill) form.reset(prefill, { keepDefaultValues: true });
  }, [prefill, form]);

  const save = useMutation({
    mutationFn: (input: CandidateInput) => (candidate ? candidatesApi.update(candidate.id, input) : candidatesApi.create(input)),
    onSuccess: async (saved) => {
      queryClient.invalidateQueries({ queryKey: ["analytics"] });
      queryClient.invalidateQueries({ queryKey: ["applications"] });
      toast.success(candidate ? "Candidate updated. Screening scores were recalculated." : "Candidate added");
      if (!candidate && resumeFile) {
        try {
          await candidatesApi.uploadResume(saved.id, resumeFile);
          toast.success("Resume attached");
        } catch (error) {
          toast.error(`The candidate was saved, but the resume could not be attached: ${isApiError(error) ? error.message : "try again from the profile"}`);
        }
      }
      queryClient.invalidateQueries({ queryKey: ["candidates"] });
      navigate(`/candidates/${saved.id}`);
    },
    onError: (error) => {
      if (isApiError(error) && error.status === 409) {
        form.setError("email", { type: "server", message: error.message });
        return;
      }
      setFormError(applyServerErrors(error, form.setError, FIELDS));
    },
  });

  const onSubmit = form.handleSubmit((values) => {
    setFormError(null);
    save.mutate(toCandidateInput(values));
  });

  const backTo = candidate ? `/candidates/${candidate.id}` : "/candidates";
  return (
    <>
      <PageHeader title={candidate ? `Edit ${candidate.full_name}` : "Add candidate"} description="Required fields are marked with *." back={{ to: backTo, label: candidate ? "Back to profile" : "Back to candidates" }} />
      <form onSubmit={onSubmit} noValidate className="space-y-4">
        <InlineError message={formError} />
        {!candidate && (
          <ResumeStarter
            file={resumeFile}
            getValues={() => form.getValues()}
            onApply={(values) => {
              form.reset(values, { keepDefaultValues: true });
              setFromResume(true);
            }}
            onFileChange={setResumeFile}
          />
        )}
        {fromResume && (
          <p role="status" className="flex items-start gap-2 rounded-md border border-warning/30 bg-warning-soft px-3 py-2 text-sm">
            <FileText className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden="true" />
            Some fields were filled from the resume. They are unverified: check every field before saving.
          </p>
        )}
        <Card>
          <CardHeader>
            <CardTitle>Contact details</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <Field id="full_name" label="Full name" error={errors.full_name?.message} required>
              {(props) => <Input autoComplete="off" {...props} {...form.register("full_name")} />}
            </Field>
            <Field id="email" label="Email" error={errors.email?.message} hint="Must be unique in your workspace." required>
              {(props) => <Input type="email" autoComplete="off" {...props} {...form.register("email")} />}
            </Field>
            <Field id="phone" label="Phone" error={errors.phone?.message}>
              {(props) => <Input type="tel" autoComplete="off" placeholder="+1 555 0100" {...props} {...form.register("phone")} />}
            </Field>
            <Field id="total_experience" label="Total experience (years)" error={errors.total_experience?.message} hint="Leave blank if unknown; screening will mark experience as missing data.">
              {(props) => <Input type="number" inputMode="decimal" min={0} max={80} step="0.5" {...props} {...form.register("total_experience")} />}
            </Field>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Technical skills</CardTitle>
            <CardDescription>Press Enter or comma after each skill. Synonyms such as “JS” or “Postgres” are matched automatically.</CardDescription>
          </CardHeader>
          <CardContent>
            <Controller
              control={form.control}
              name="technical_skills"
              render={({ field }) => (
                <Field id="technical_skills" label="Skills" error={errors.technical_skills?.message ?? errors.technical_skills?.find?.((item) => item)?.message}>
                  {(props) => <TagInput id={props.id} value={field.value} onChange={field.onChange} placeholder="e.g. Python, SQL, Docker" invalid={props["aria-invalid"]} describedBy={props["aria-describedby"]} />}
                </Field>
              )}
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row items-center justify-between gap-3 space-y-0">
            <div>
              <CardTitle>Education and qualifications</CardTitle>
              <CardDescription>Used to match job qualification criteria. Nothing is inferred beyond what you enter.</CardDescription>
            </div>
            <Button type="button" variant="outline" size="sm" onClick={() => education.append({ degree: "", field_of_study: "", institution: "", graduation_year: "" })} disabled={education.fields.length >= 30}>
              <Plus aria-hidden="true" /> Add
            </Button>
          </CardHeader>
          <CardContent className="space-y-3">
            {education.fields.length === 0 && (
              <p className="flex items-center gap-2 text-sm text-muted-foreground">
                <GraduationCap className="size-4" aria-hidden="true" /> No education recorded.
              </p>
            )}
            {education.fields.map((item, index) => {
              const itemErrors = errors.education?.[index];
              return (
                <fieldset key={item.id} className="grid gap-3 rounded-md border p-3 sm:grid-cols-[2fr_2fr_2fr_1fr_auto] sm:items-start">
                  <legend className="sr-only">Education {index + 1}</legend>
                  <Field id={`education.${index}.degree`} label="Degree or certificate" error={itemErrors?.degree?.message} required>
                    {(props) => <Input placeholder="BSc" {...props} {...form.register(`education.${index}.degree`)} />}
                  </Field>
                  <Field id={`education.${index}.field_of_study`} label="Field of study" error={itemErrors?.field_of_study?.message}>
                    {(props) => <Input placeholder="Computer Science" {...props} {...form.register(`education.${index}.field_of_study`)} />}
                  </Field>
                  <Field id={`education.${index}.institution`} label="Institution" error={itemErrors?.institution?.message}>
                    {(props) => <Input {...props} {...form.register(`education.${index}.institution`)} />}
                  </Field>
                  <Field id={`education.${index}.graduation_year`} label="Year" error={itemErrors?.graduation_year?.message}>
                    {(props) => <Input type="number" inputMode="numeric" min={1900} max={2100} {...props} {...form.register(`education.${index}.graduation_year`)} />}
                  </Field>
                  <Button type="button" variant="ghost" size="icon" className="sm:mt-6" onClick={() => education.remove(index)} aria-label={`Remove education ${index + 1}`}>
                    <Trash2 aria-hidden="true" />
                  </Button>
                </fieldset>
              );
            })}
          </CardContent>
        </Card>

        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button type="button" variant="outline" onClick={() => navigate(backTo)}>
            Cancel
          </Button>
          <Button type="submit" loading={save.isPending} disabled={Boolean(candidate) && !isDirty}>
            {candidate ? "Save changes" : "Add candidate"}
          </Button>
        </div>
      </form>
    </>
  );
}

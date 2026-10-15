import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Lock, Plus, RotateCcw, Trash2, X } from "lucide-react";
import * as React from "react";
import { Controller, useFieldArray, useForm, useWatch, type Control } from "react-hook-form";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { z } from "zod";
import { EmptyState, ErrorState, InlineError, PageHeader, PageSkeleton } from "@/components/common/feedback";
import { Field, TagInput } from "@/components/common/form";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/primitives";
import { COMPONENT_LABELS, COMPONENT_ORDER } from "@/features/screening/screening-components";
import { jobsApi } from "@/lib/api/endpoints";
import type { ComponentName, Job, JobInput } from "@/lib/api/types";
import { applyServerErrors, optionalNumber } from "@/lib/forms";
import { cn, formatScore, toNumber } from "@/lib/utils";

export const DEFAULT_WEIGHTS: Record<ComponentName, string> = { required_skills: "50", preferred_skills: "20", experience: "20", qualifications: "10" };
const WEIGHT_HINTS: Record<ComponentName, string> = {
  required_skills: "Share of required skills the candidate has",
  preferred_skills: "Share of preferred skills the candidate has",
  experience: "Years vs. the minimum, capped at 100%",
  qualifications: "Qualification criteria found in the candidate’s education",
};

const num = (value: string) => (value.trim() === "" ? NaN : Number(value));
const twoDecimals = (value: number) => Math.round(value * 100) === value * 100;
const sum = (values: string[]) => Math.round(values.reduce((total, value) => total + (toNumber(value) ?? 0), 0) * 100) / 100;
const weightText = z.string().refine((value) => {
  const parsed = num(value);
  return Number.isFinite(parsed) && parsed >= 0 && parsed <= 100 && twoDecimals(parsed);
}, "0–100, up to 2 decimals");

// Mirrors backend/app/schemas/job.py; the server re-validates everything (including skill aliases).
export const jobSchema = z
  .object({
    title: z.string().trim().min(2, "Use at least 2 characters").max(180),
    department: z.string().trim().max(120),
    description: z.string().max(20000),
    required_skills: z.array(z.string().max(100)).min(1, "Add at least one required skill").max(100),
    preferred_skills: z.array(z.string().max(100)).max(100),
    minimum_experience: z.string().refine((value) => {
      if (value.trim() === "") return true;
      const parsed = num(value);
      return Number.isFinite(parsed) && parsed >= 0 && parsed <= 80 && twoDecimals(parsed);
    }, "Use 0–80 years, up to 2 decimals"),
    qualifications: z.array(z.object({ name: z.string().trim().min(1, "Name is required").max(180), is_mandatory: z.boolean(), weight: z.string() })).max(50),
    criterion_weights: z.object({ required_skills: weightText, preferred_skills: weightText, experience: weightText, qualifications: weightText }),
    use_skill_weights: z.boolean(),
    required_skill_weights: z.record(z.string()),
    preferred_skill_weights: z.record(z.string()),
  })
  .superRefine((values, context) => {
    const issue = (path: (string | number)[], message: string) => context.addIssue({ code: z.ZodIssueCode.custom, path, message });
    const total = sum(Object.values(values.criterion_weights));
    if (total !== 100) issue(["criterion_weights", "_total"], `Weights must total 100 (currently ${formatScore(total)})`);
    if ((toNumber(values.criterion_weights.required_skills) ?? 0) <= 0) issue(["criterion_weights", "required_skills"], "Must be greater than 0");
    const required = new Set(values.required_skills.map((skill) => skill.toLowerCase()));
    const overlap = values.preferred_skills.filter((skill) => required.has(skill.toLowerCase()));
    if (overlap.length) issue(["preferred_skills"], `Already required: ${overlap.join(", ")}`);
    const names = values.qualifications.map((item) => item.name.trim().toLowerCase());
    values.qualifications.forEach((item, index) => {
      if (names.indexOf(item.name.trim().toLowerCase()) !== index) issue(["qualifications", index, "name"], "Duplicate qualification");
    });
    const weighted = values.qualifications.filter((item) => item.weight.trim() !== "");
    if (weighted.length && weighted.length !== values.qualifications.length) issue(["qualifications", "_weights"], "Set a weight for every qualification, or for none");
    else if (weighted.length) {
      values.qualifications.forEach((item, index) => {
        const parsed = num(item.weight);
        if (!(Number.isFinite(parsed) && parsed >= 0 && parsed <= 100)) issue(["qualifications", index, "weight"], "0–100");
      });
      const qualificationTotal = sum(weighted.map((item) => item.weight));
      if (qualificationTotal !== 100) issue(["qualifications", "_weights"], `Qualification weights must total 100 (currently ${formatScore(qualificationTotal)})`);
    }
    if (values.use_skill_weights) {
      for (const [category, skills] of [
        ["required_skill_weights", values.required_skills],
        ["preferred_skill_weights", values.preferred_skills],
      ] as const) {
        if (!skills.length) continue;
        const entries = skills.map((skill) => values[category][skill] ?? "");
        // Skill names may contain dots ("node.js"), so problems are reported on the list total, not per path.
        const invalid = entries.some((entry) => {
          const parsed = num(entry);
          return !(Number.isFinite(parsed) && parsed >= 0 && parsed <= 100);
        });
        const categoryTotal = sum(entries);
        if (invalid) issue([category, "_total"], "Give every skill a weight from 0 to 100");
        else if (categoryTotal !== 100) issue([category, "_total"], `Must total 100 (currently ${formatScore(categoryTotal)})`);
      }
    }
  });
export type JobFormValues = z.infer<typeof jobSchema>;
const FIELDS = ["title", "department", "description", "required_skills", "preferred_skills", "minimum_experience", "qualifications", "criterion_weights", "required_skill_weights", "preferred_skill_weights"] as const;

function toValues(job?: Job): JobFormValues {
  const weights = (record: Record<string, string> | undefined) => Object.fromEntries(Object.entries(record ?? {}).map(([key, value]) => [key, formatScore(value)]));
  return {
    title: job?.title ?? "",
    department: job?.department ?? "",
    description: job?.description ?? "",
    required_skills: job?.required_skills ?? [],
    preferred_skills: job?.preferred_skills ?? [],
    minimum_experience: job ? formatScore(job.minimum_experience) : "0",
    qualifications: (job?.qualifications ?? []).map((item) => ({ name: item.name, is_mandatory: item.is_mandatory, weight: item.weight === null ? "" : formatScore(item.weight) })),
    criterion_weights: job
      ? (Object.fromEntries(COMPONENT_ORDER.map((name) => [name, formatScore(job.criterion_weights[name])])) as Record<ComponentName, string>)
      : { ...DEFAULT_WEIGHTS },
    use_skill_weights: Boolean(job && Object.keys(job.required_skill_weights).length),
    required_skill_weights: weights(job?.required_skill_weights),
    preferred_skill_weights: weights(job?.preferred_skill_weights),
  };
}

export function toJobInput(values: JobFormValues): JobInput {
  const pick = (skills: string[], record: Record<string, string>) =>
    values.use_skill_weights && skills.length ? Object.fromEntries(skills.map((skill) => [skill, Number(record[skill])])) : {};
  return {
    title: values.title.trim(),
    department: values.department.trim() || null,
    description: values.description,
    required_skills: values.required_skills,
    preferred_skills: values.preferred_skills,
    required_skill_weights: pick(values.required_skills, values.required_skill_weights),
    preferred_skill_weights: pick(values.preferred_skills, values.preferred_skill_weights),
    minimum_experience: optionalNumber(values.minimum_experience) ?? 0,
    qualifications: values.qualifications.map((item) => ({ name: item.name.trim(), is_mandatory: item.is_mandatory, weight: optionalNumber(item.weight) })),
    criterion_weights: {
      required_skills: Number(values.criterion_weights.required_skills),
      preferred_skills: Number(values.criterion_weights.preferred_skills),
      experience: Number(values.criterion_weights.experience),
      qualifications: Number(values.criterion_weights.qualifications),
    },
  };
}

export function JobFormPage() {
  const { jobId } = useParams();
  const id = jobId ? Number(jobId) : null;
  const existing = useQuery({ queryKey: ["jobs", id], queryFn: () => jobsApi.get(id!), enabled: id !== null });
  if (id !== null && existing.isPending) return <PageSkeleton />;
  if (id !== null && existing.isError) return <ErrorState error={existing.error} onRetry={() => existing.refetch()} />;
  if (existing.data?.status === "closed") {
    return (
      <>
        <PageHeader title={`Edit ${existing.data.title}`} back={{ to: `/jobs/${existing.data.id}`, label: "Back to job" }} />
        <Card>
          <EmptyState
            icon={Lock}
            title="This job is closed"
            description="Closed jobs keep the criteria their applicants were screened against. Reopen the job to change its criteria."
            action={
              <Button asChild>
                <Link to={`/jobs/${existing.data.id}`}>Go to job</Link>
              </Button>
            }
          />
        </Card>
      </>
    );
  }
  return <JobForm job={existing.data} />;
}

function JobForm({ job }: { job?: Job }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [formError, setFormError] = React.useState<string | null>(null);
  const form = useForm<JobFormValues>({ resolver: zodResolver(jobSchema), defaultValues: toValues(job), mode: "onTouched" });
  const qualifications = useFieldArray({ control: form.control, name: "qualifications" });
  const errors = form.formState.errors as typeof form.formState.errors & Record<string, Record<string, { message?: string }> | undefined>;

  const save = useMutation({
    mutationFn: (input: JobInput) => (job ? jobsApi.update(job.id, input) : jobsApi.create(input)),
    onSuccess: (saved) => {
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      queryClient.invalidateQueries({ queryKey: ["analytics"] });
      queryClient.invalidateQueries({ queryKey: ["applications"] });
      queryClient.invalidateQueries({ queryKey: ["candidates"] });
      toast.success(job ? "Job updated. Active applications were re-screened." : "Job created");
      navigate(`/jobs/${saved.id}`);
    },
    onError: (error) => setFormError(applyServerErrors(error, form.setError, FIELDS)),
  });
  const onSubmit = form.handleSubmit(
    (values) => {
      setFormError(null);
      save.mutate(toJobInput(values));
    },
    () => setFormError("Please fix the highlighted fields."),
  );

  const backTo = job ? `/jobs/${job.id}` : "/jobs";
  return (
    <>
      <PageHeader
        title={job ? `Edit ${job.title}` : "Create job"}
        description={job ? "Saving re-screens Pending, Under Review, and Shortlisted applications. Rejected applications keep their decision-time score." : "Define what this role needs. Candidates are scored against these criteria."}
        back={{ to: backTo, label: job ? "Back to job" : "Back to jobs" }}
      />
      <form onSubmit={onSubmit} noValidate className="space-y-4">
        <InlineError message={formError} />
        <Card>
          <CardHeader>
            <CardTitle>Role</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <Field id="title" label="Job title" error={errors.title?.message} required>
              {(props) => <Input placeholder="Backend Engineer" {...props} {...form.register("title")} />}
            </Field>
            <Field id="department" label="Department" error={errors.department?.message}>
              {(props) => <Input placeholder="Engineering" {...props} {...form.register("department")} />}
            </Field>
            <Field id="description" label="Description" error={errors.description?.message} className="sm:col-span-2">
              {(props) => <Textarea rows={4} placeholder="What the role involves" {...props} {...form.register("description")} />}
            </Field>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Skills and experience</CardTitle>
            <CardDescription>Press Enter or comma after each skill. Required skills are mandatory for eligibility.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4">
            <Controller
              control={form.control}
              name="required_skills"
              render={({ field }) => (
                <Field id="required_skills" label="Required skills" error={errors.required_skills?.message} required>
                  {(props) => <TagInput id={props.id} value={field.value} onChange={field.onChange} placeholder="e.g. Python, SQL" invalid={props["aria-invalid"]} describedBy={props["aria-describedby"]} />}
                </Field>
              )}
            />
            <Controller
              control={form.control}
              name="preferred_skills"
              render={({ field }) => (
                <Field id="preferred_skills" label="Preferred skills" error={errors.preferred_skills?.message} hint="Nice to have. Leave empty if none; its weight is then shared with the other components.">
                  {(props) => <TagInput id={props.id} value={field.value} onChange={field.onChange} placeholder="e.g. Docker" invalid={props["aria-invalid"]} describedBy={props["aria-describedby"]} />}
                </Field>
              )}
            />
            <Field id="minimum_experience" label="Minimum experience (years)" error={errors.minimum_experience?.message} hint="0 means no experience requirement." className="sm:max-w-xs">
              {(props) => <Input type="number" inputMode="decimal" min={0} max={80} step="0.5" {...props} {...form.register("minimum_experience")} />}
            </Field>
            <SkillWeights control={form.control} register={form.register} errors={errors} setValue={form.setValue} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row items-center justify-between gap-3 space-y-0">
            <div>
              <CardTitle>Qualifications</CardTitle>
              <CardDescription>Matched against candidates’ education. Mandatory ones affect eligibility.</CardDescription>
            </div>
            <Button type="button" variant="outline" size="sm" onClick={() => qualifications.append({ name: "", is_mandatory: true, weight: "" })} disabled={qualifications.fields.length >= 50}>
              <Plus aria-hidden="true" /> Add
            </Button>
          </CardHeader>
          <CardContent className="space-y-3">
            {qualifications.fields.length === 0 && <p className="text-sm text-muted-foreground">No qualifications. The qualifications weight is shared with the other components.</p>}
            {qualifications.fields.map((item, index) => {
              const itemErrors = errors.qualifications?.[index];
              return (
                <fieldset key={item.id} className="grid gap-3 rounded-md border p-3 sm:grid-cols-[1fr_auto_8rem_auto] sm:items-start">
                  <legend className="sr-only">Qualification {index + 1}</legend>
                  <Field id={`qualifications.${index}.name`} label="Qualification" error={itemErrors?.name?.message} required>
                    {(props) => <Input placeholder="BSc Computer Science" {...props} {...form.register(`qualifications.${index}.name`)} />}
                  </Field>
                  <label className="flex items-center gap-2 text-sm sm:mt-7">
                    <input type="checkbox" className="size-4 rounded border-input accent-[hsl(var(--primary))]" {...form.register(`qualifications.${index}.is_mandatory`)} />
                    Mandatory
                  </label>
                  <Field id={`qualifications.${index}.weight`} label="Weight" error={itemErrors?.weight?.message}>
                    {(props) => <Input type="number" inputMode="decimal" min={0} max={100} placeholder="Optional" {...props} {...form.register(`qualifications.${index}.weight`)} />}
                  </Field>
                  <Button type="button" variant="ghost" size="icon" className="sm:mt-6" onClick={() => qualifications.remove(index)} aria-label={`Remove qualification ${index + 1}`}>
                    <Trash2 aria-hidden="true" />
                  </Button>
                </fieldset>
              );
            })}
            {(errors.qualifications as unknown as Record<string, { message?: string }> | undefined)?._weights?.message && (
              <p className="text-xs font-medium text-destructive" role="alert">
                {(errors.qualifications as unknown as Record<string, { message?: string }>)._weights!.message}
              </p>
            )}
            {qualifications.fields.length > 1 && <p className="text-xs text-muted-foreground">Leave weights empty to count qualifications equally, or give every one a weight totalling 100.</p>}
          </CardContent>
        </Card>

        <CriterionWeights control={form.control} register={form.register} setValue={form.setValue} errors={errors} />

        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button type="button" variant="outline" onClick={() => navigate(backTo)}>
            Cancel
          </Button>
          <Button type="submit" loading={save.isPending}>
            {job ? "Save and re-screen" : "Create job"}
          </Button>
        </div>
      </form>
    </>
  );
}

type FormBits = {
  control: Control<JobFormValues>;
  register: ReturnType<typeof useForm<JobFormValues>>["register"];
  setValue: ReturnType<typeof useForm<JobFormValues>>["setValue"];
  errors: Record<string, unknown>;
};

function CriterionWeights({ control, register, setValue, errors }: FormBits) {
  const weights = useWatch({ control, name: "criterion_weights" });
  const total = sum(Object.values(weights));
  const weightErrors = (errors.criterion_weights ?? {}) as Record<string, { message?: string } | undefined>;
  const valid = total === 100;
  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-start justify-between gap-3 space-y-0">
        <div>
          <CardTitle>Scoring weights</CardTitle>
          <CardDescription>How much each component counts toward the 0–100 score. Must total 100.</CardDescription>
        </div>
        <Button type="button" variant="ghost" size="sm" onClick={() => setValue("criterion_weights", { ...DEFAULT_WEIGHTS }, { shouldValidate: true, shouldDirty: true })}>
          <RotateCcw aria-hidden="true" /> Reset to 50 / 20 / 20 / 10
        </Button>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {COMPONENT_ORDER.map((name) => (
            <Field key={name} id={`criterion_weights.${name}`} label={`${COMPONENT_LABELS[name]} (%)`} error={weightErrors[name]?.message} hint={WEIGHT_HINTS[name]}>
              {(props) => <Input type="number" inputMode="decimal" min={0} max={100} step="1" {...props} {...register(`criterion_weights.${name}`)} />}
            </Field>
          ))}
        </div>
        <div className="flex h-2.5 overflow-hidden rounded-full bg-muted" aria-hidden="true">
          {COMPONENT_ORDER.map((name, index) => (
            <div key={name} className={["bg-indigo-600", "bg-sky-500", "bg-teal-600", "bg-amber-500"][index]} style={{ width: `${Math.min(100, toNumber(weights[name]) ?? 0)}%` }} />
          ))}
        </div>
        <p className={cn("flex items-center gap-1.5 text-sm font-medium", valid ? "text-success" : "text-destructive")} role="status" aria-live="polite">
          {valid ? <Check className="size-4" aria-hidden="true" /> : <X className="size-4" aria-hidden="true" />}
          Total {formatScore(total)} / 100{!valid && " — adjust the weights so they total exactly 100"}
        </p>
      </CardContent>
    </Card>
  );
}

function SkillWeights({ control, register, setValue, errors }: FormBits) {
  const enabled = useWatch({ control, name: "use_skill_weights" });
  const required = useWatch({ control, name: "required_skills" });
  const preferred = useWatch({ control, name: "preferred_skills" });
  const requiredWeights = useWatch({ control, name: "required_skill_weights" });
  const preferredWeights = useWatch({ control, name: "preferred_skill_weights" });
  return (
    <div className="rounded-md border p-3">
      <label className="flex items-start gap-2 text-sm">
        <input type="checkbox" className="mt-0.5 size-4 rounded border-input accent-[hsl(var(--primary))]" {...register("use_skill_weights")} />
        <span>
          <span className="font-medium">Weight individual skills</span>
          <span className="block text-xs text-muted-foreground">By default every skill in a list counts equally. Turn on to make some skills matter more (each list must total 100).</span>
        </span>
      </label>
      {enabled && (
        <div className="mt-3 grid gap-4 md:grid-cols-2">
          {(
            [
              ["required_skill_weights", "Required skill weights", required, requiredWeights],
              ["preferred_skill_weights", "Preferred skill weights", preferred, preferredWeights],
            ] as const
          ).map(([category, label, skills, values]) => {
            const categoryErrors = (errors[category] ?? {}) as Record<string, { message?: string } | undefined>;
            return (
              <fieldset key={category} className="space-y-2">
                <legend className="text-sm font-medium">{label}</legend>
                {skills.length === 0 ? (
                  <p className="text-xs text-muted-foreground">Add skills above first.</p>
                ) : (
                  <>
                    {skills.map((skill) => (
                      <div key={skill} className="flex items-center gap-2">
                        <label htmlFor={`${category}-${skill}`} className="flex-1 truncate text-sm">
                          {skill}
                        </label>
                        <Input
                          id={`${category}-${skill}`}
                          type="number"
                          inputMode="decimal"
                          min={0}
                          max={100}
                          className="w-24"
                          aria-invalid={Boolean(categoryErrors._total)}
                          value={values?.[skill] ?? ""}
                          onChange={(event) => setValue(category, { ...values, [skill]: event.target.value }, { shouldDirty: true })}
                        />
                      </div>
                    ))}
                    <p className={cn("text-xs", categoryErrors._total ? "font-medium text-destructive" : "text-muted-foreground")}>
                      {categoryErrors._total?.message ?? `Total ${formatScore(sum(skills.map((skill) => values?.[skill] ?? "")))} / 100`}
                    </p>
                  </>
                )}
              </fieldset>
            );
          })}
        </div>
      )}
    </div>
  );
}

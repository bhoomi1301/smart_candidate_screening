import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Equal, Lock, LockOpen, Pencil, Plus, RefreshCw, Search, Trash2, Trophy, UserPlus } from "lucide-react";
import * as React from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { AssessmentBadge, EligibilityBadge, JobStatusBadge, StaleBadge, StatusBadge } from "@/components/common/badges";
import { ConfirmDialog, EmptyState, ErrorState, InlineError, PageHeader, PageSkeleton, Pagination, TableSkeleton, errorMessage } from "@/components/common/feedback";
import { Button } from "@/components/ui/button";
import { Input, NativeSelect } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/overlays";
import { Badge, Card, CardContent, CardDescription, CardHeader, CardTitle, Skeleton } from "@/components/ui/primitives";
import { COMPONENT_LABELS, COMPONENT_ORDER, ComponentBreakdown, EligibilityPanel, PointsBar } from "@/features/screening/screening-components";
import { applicationsApi, candidatesApi, jobsApi } from "@/lib/api/endpoints";
import type { Eligibility, Job, RankedApplication } from "@/lib/api/types";
import { toastError } from "@/lib/forms";
import { cn, formatDate, formatScore, formatYears, pluralize, toNumber } from "@/lib/utils";

const PAGE_SIZE = 20;

export function JobDetailPage() {
  const id = Number(useParams().jobId);
  const job = useQuery({ queryKey: ["jobs", id], queryFn: () => jobsApi.get(id) });
  if (job.isPending) return <PageSkeleton />;
  if (job.isError)
    return (
      <>
        <PageHeader title="Job" back={{ to: "/jobs", label: "Back to jobs" }} />
        <Card>
          <ErrorState error={job.error} onRetry={() => job.refetch()} />
        </Card>
      </>
    );
  return <JobDetail job={job.data} />;
}

function JobDetail({ job }: { job: Job }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [dialog, setDialog] = React.useState<"close" | "delete" | "add" | null>(null);
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["jobs"] });
    queryClient.invalidateQueries({ queryKey: ["analytics"] });
  };
  const setStatus = useMutation({
    mutationFn: (status: Job["status"]) => jobsApi.setStatus(job.id, status),
    onSuccess: (updated) => {
      invalidate();
      setDialog(null);
      toast.success(updated.status === "closed" ? "Job closed. Its applications and history are kept." : "Job reopened");
    },
    onError: (error) => toastError(error),
  });
  const remove = useMutation({
    mutationFn: () => jobsApi.remove(job.id),
    onSuccess: () => {
      invalidate();
      toast.success("Job deleted");
      navigate("/jobs", { replace: true });
    },
    onError: (error) => {
      setDialog(null);
      toastError(error);
    },
  });
  const open = job.status === "open";

  return (
    <>
      <PageHeader
        back={{ to: "/jobs", label: "Back to jobs" }}
        title={job.title}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <JobStatusBadge status={job.status} />
            <span>
              {job.department ?? "No department"} · Created {formatDate(job.created_at)} · {pluralize(job.application_count, "applicant")}
            </span>
          </span>
        }
        actions={
          <>
            {job.application_count === 0 && (
              <Button variant="outline" onClick={() => setDialog("delete")}>
                <Trash2 aria-hidden="true" /> Delete
              </Button>
            )}
            {open ? (
              <>
                <Button variant="outline" onClick={() => setDialog("close")}>
                  <Lock aria-hidden="true" /> Close job
                </Button>
                <Button variant="outline" asChild>
                  <Link to={`/jobs/${job.id}/edit`}>
                    <Pencil aria-hidden="true" /> Edit
                  </Link>
                </Button>
                <Button onClick={() => setDialog("add")}>
                  <UserPlus aria-hidden="true" /> Add applicant
                </Button>
              </>
            ) : (
              <Button variant="outline" loading={setStatus.isPending} onClick={() => setStatus.mutate("open")}>
                <LockOpen aria-hidden="true" /> Reopen job
              </Button>
            )}
          </>
        }
      />
      {!open && (
        <div className="mb-4 flex items-start gap-2 rounded-md border bg-muted/50 px-3 py-2 text-sm">
          <Lock className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
          <span>This job is closed: no new applicants, and its criteria are locked so existing scores stay comparable. Reopen it to edit or add applicants.</span>
        </div>
      )}
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <Rankings job={job} onAdd={() => setDialog("add")} />
        <Requirements job={job} />
      </div>

      <AddApplicantDialog job={job} open={dialog === "add"} onOpenChange={(value) => setDialog(value ? "add" : null)} />
      <ConfirmDialog
        open={dialog === "close"}
        onOpenChange={(value) => setDialog(value ? "close" : null)}
        title="Close this job?"
        description="Closed jobs stop accepting applicants and lock their criteria. Applications, scores, and history are kept, and you can reopen the job later."
        confirmLabel="Close job"
        destructive={false}
        loading={setStatus.isPending}
        onConfirm={() => setStatus.mutate("closed")}
      />
      <ConfirmDialog
        open={dialog === "delete"}
        onOpenChange={(value) => setDialog(value ? "delete" : null)}
        title={`Delete “${job.title}”?`}
        description="This job has no applicants, so it can be deleted permanently. This cannot be undone."
        confirmLabel="Delete job"
        loading={remove.isPending}
        onConfirm={() => remove.mutate()}
      />
    </>
  );
}

function Requirements({ job }: { job: Job }) {
  const weighted = (skills: string[], weights: Record<string, string>) => (
    <ul className="flex flex-wrap gap-1.5">
      {skills.map((skill) => (
        <li key={skill} className="rounded-md border bg-secondary px-2 py-0.5 text-xs">
          {skill}
          {weights[skill] !== undefined && <span className="text-muted-foreground"> · {formatScore(weights[skill])}%</span>}
        </li>
      ))}
    </ul>
  );
  return (
    <Card className="self-start">
      <CardHeader>
        <CardTitle>Requirements</CardTitle>
        {job.description && <CardDescription className="whitespace-pre-line">{job.description}</CardDescription>}
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        <section>
          <h3 className="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">Required skills</h3>
          {weighted(job.required_skills, job.required_skill_weights)}
        </section>
        <section>
          <h3 className="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">Preferred skills</h3>
          {job.preferred_skills.length ? weighted(job.preferred_skills, job.preferred_skill_weights) : <p className="text-muted-foreground">None</p>}
        </section>
        <section>
          <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">Minimum experience</h3>
          <p>{toNumber(job.minimum_experience) ? formatYears(job.minimum_experience) : "No minimum"}</p>
        </section>
        <section>
          <h3 className="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">Qualifications</h3>
          {job.qualifications.length === 0 ? (
            <p className="text-muted-foreground">None</p>
          ) : (
            <ul className="space-y-1">
              {job.qualifications.map((item) => (
                <li key={item.id} className="flex flex-wrap items-center gap-1.5">
                  {item.name}
                  <Badge variant={item.is_mandatory ? "primary" : "neutral"}>{item.is_mandatory ? "Mandatory" : "Optional"}</Badge>
                  {item.weight !== null && <span className="text-xs text-muted-foreground">{formatScore(item.weight)}%</span>}
                </li>
              ))}
            </ul>
          )}
        </section>
        <section>
          <h3 className="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">Scoring weights</h3>
          <dl className="space-y-1.5">
            {COMPONENT_ORDER.map((name) => (
              <div key={name} className="flex items-center gap-2">
                <dt className="flex-1 text-muted-foreground">{COMPONENT_LABELS[name]}</dt>
                <dd className="font-medium tabular">{formatScore(job.criterion_weights[name])}%</dd>
              </div>
            ))}
          </dl>
        </section>
      </CardContent>
    </Card>
  );
}

function Rankings({ job, onAdd }: { job: Job; onAdd: () => void }) {
  const queryClient = useQueryClient();
  const [eligibility, setEligibility] = React.useState<Eligibility | "">("");
  const [skip, setSkip] = React.useState(0);
  const [expanded, setExpanded] = React.useState<number | null>(null);
  const rankings = useQuery({
    queryKey: ["jobs", job.id, "rankings", { eligibility, skip }],
    queryFn: () => jobsApi.rankings(job.id, { eligibility: eligibility || undefined, skip, limit: PAGE_SIZE }),
    placeholderData: keepPreviousData,
  });
  const refresh = useMutation({
    mutationFn: () => jobsApi.refreshScreening(job.id),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["jobs", job.id] });
      queryClient.invalidateQueries({ queryKey: ["applications"] });
      queryClient.invalidateQueries({ queryKey: ["analytics"] });
      toast.success(`Re-screened ${pluralize(result.refreshed, "active application")}`);
    },
    onError: (error) => toastError(error),
  });

  return (
    <Card className="min-w-0 self-start">
      <CardHeader className="flex-row flex-wrap items-start justify-between gap-3 space-y-0">
        <div>
          <CardTitle>Ranked applicants</CardTitle>
          <CardDescription>Highest score first; ties go to the earlier application. Rankings support decisions; they never make them.</CardDescription>
        </div>
        <div className="flex w-full flex-wrap gap-2 sm:w-auto">
          <NativeSelect
            aria-label="Filter by eligibility"
            className="flex-1 sm:w-44 sm:flex-none"
            value={eligibility}
            onChange={(event) => {
              setEligibility(event.target.value as Eligibility | "");
              setSkip(0);
            }}
          >
            <option value="">All eligibility</option>
            <option value="eligible">Eligible</option>
            <option value="not_eligible">Not eligible</option>
            <option value="undetermined">Undetermined</option>
          </NativeSelect>
          {job.application_count > 0 && (
            <Button variant="outline" size="icon" loading={refresh.isPending} onClick={() => refresh.mutate()} aria-label="Re-screen active applications" title="Re-screen active applications">
              {!refresh.isPending && <RefreshCw aria-hidden="true" />}
            </Button>
          )}
        </div>
      </CardHeader>
      {rankings.isPending ? (
        <TableSkeleton rows={4} columns={4} />
      ) : rankings.isError ? (
        <ErrorState error={rankings.error} onRetry={() => rankings.refetch()} />
      ) : rankings.data.items.length === 0 ? (
        eligibility ? (
          <EmptyState icon={Search} title="No applicants with this eligibility" />
        ) : (
          <EmptyState
            icon={Trophy}
            title="No applicants yet"
            description={job.status === "open" ? "Add candidates to this job to screen and rank them." : "This job was closed before anyone applied."}
            action={
              job.status === "open" ? (
                <Button onClick={onAdd}>
                  <Plus aria-hidden="true" /> Add applicant
                </Button>
              ) : undefined
            }
          />
        )
      ) : (
        <>
          <ol className={cn("divide-y border-t", rankings.isPlaceholderData && "opacity-60")}>
            {rankings.data.items.map((item) => (
              <RankingRow key={item.application_id} item={item} expanded={expanded === item.application_id} onToggle={() => setExpanded(expanded === item.application_id ? null : item.application_id)} />
            ))}
          </ol>
          <Pagination skip={skip} limit={PAGE_SIZE} total={rankings.data.total} onChange={setSkip} label="applicants" />
        </>
      )}
    </Card>
  );
}

function RankingRow({ item, expanded, onToggle }: { item: RankedApplication; expanded: boolean; onToggle: () => void }) {
  const panelId = `breakdown-${item.application_id}`;
  return (
    <li>
      <div className="flex items-center gap-3 px-4 py-3 sm:px-5">
        <span className="w-7 shrink-0 text-center text-sm font-semibold text-muted-foreground tabular">
          <span className="sr-only">Rank </span>
          {item.rank}
        </span>
        <div className="min-w-0 flex-1">
          <Link to={`/applications/${item.application_id}`} className="block truncate font-medium hover:underline">
            {item.candidate.full_name}
          </Link>
          <div className="mt-1 flex flex-wrap items-center gap-1">
            <StatusBadge status={item.application_status} />
            <EligibilityBadge eligibility={item.eligibility} />
            <AssessmentBadge status={item.assessment_status} />
            <StaleBadge stale={item.is_stale && item.evaluated_at !== null} />
            {item.score_tied && (
              <Badge variant="outline" title="Same score as another applicant; the earlier application ranks first">
                <Equal aria-hidden="true" /> Tied
              </Badge>
            )}
          </div>
          {item.missing_mandatory_skills.length > 0 && <p className="mt-1 truncate text-xs text-destructive">Missing: {item.missing_mandatory_skills.join(", ")}</p>}
        </div>
        <div className="text-right">
          <p className="text-lg font-semibold tabular">{formatScore(item.score)}</p>
          <p className="text-xs text-muted-foreground">score</p>
        </div>
        <Button variant="ghost" size="icon" onClick={onToggle} aria-expanded={expanded} aria-controls={panelId} aria-label={`${expanded ? "Hide" : "Show"} score breakdown for ${item.candidate.full_name}`}>
          {expanded ? <ChevronDown aria-hidden="true" /> : <ChevronRight aria-hidden="true" />}
        </Button>
      </div>
      {expanded && (
        <div id={panelId} className="border-t bg-muted/30 px-4 py-4 sm:px-5">
          <InlineBreakdown applicationId={item.application_id} />
        </div>
      )}
    </li>
  );
}

function InlineBreakdown({ applicationId }: { applicationId: number }) {
  const screening = useQuery({ queryKey: ["applications", applicationId, "screening"], queryFn: () => applicationsApi.screening(applicationId) });
  if (screening.isPending) return <Skeleton className="h-40" />;
  if (screening.isError) return <ErrorState error={screening.error} onRetry={() => screening.refetch()} className="py-4" />;
  const breakdown = screening.data.score_breakdown;
  return (
    <div className="space-y-4">
      <PointsBar breakdown={breakdown} />
      <EligibilityPanel breakdown={breakdown} />
      <ComponentBreakdown breakdown={breakdown} />
      <Link to={`/applications/${applicationId}`} className="inline-block text-sm font-medium text-primary hover:underline">
        Open application to review and decide →
      </Link>
    </div>
  );
}

function AddApplicantDialog({ job, open, onOpenChange }: { job: Job; open: boolean; onOpenChange: (open: boolean) => void }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [search, setSearch] = React.useState("");
  const [term, setTerm] = React.useState("");
  const [selected, setSelected] = React.useState<number | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  React.useEffect(() => {
    const timer = window.setTimeout(() => setTerm(search.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [search]);
  React.useEffect(() => {
    if (open) {
      setSearch("");
      setSelected(null);
      setError(null);
    }
  }, [open]);
  const candidates = useQuery({ queryKey: ["candidates", "list", { q: term, limit: 8 }], queryFn: () => candidatesApi.list({ q: term || undefined, limit: 8 }), enabled: open });
  const applied = useQuery({ queryKey: ["candidates", "list", { job_id: job.id, limit: 100 }], queryFn: () => candidatesApi.list({ job_id: job.id, limit: 100 }), enabled: open });
  const appliedIds = new Set(applied.data?.items.map((candidate) => candidate.id));
  const add = useMutation({
    mutationFn: () => applicationsApi.create(job.id, selected!),
    onSuccess: (application) => {
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      queryClient.invalidateQueries({ queryKey: ["candidates"] });
      queryClient.invalidateQueries({ queryKey: ["analytics"] });
      toast.success(`${application.candidate.full_name} added and screened: score ${formatScore(application.current_screening_score)}`);
      onOpenChange(false);
      navigate(`/applications/${application.id}`);
    },
    onError: (err) => setError(errorMessage(err)),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add applicant to {job.title}</DialogTitle>
          <DialogDescription>The candidate is screened immediately against this job’s criteria.</DialogDescription>
        </DialogHeader>
        <form
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            if (selected === null) {
              setError("Choose a candidate.");
              return;
            }
            setError(null);
            add.mutate();
          }}
        >
          <InlineError message={error} className="mb-3" />
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
            <Input type="search" autoFocus aria-label="Search candidates" placeholder="Search by name, email, or skill" className="pl-8" value={search} onChange={(event) => setSearch(event.target.value)} />
          </div>
          <fieldset className="mt-3">
            <legend className="sr-only">Candidates</legend>
            {candidates.isPending ? (
              <div className="space-y-2">
                <Skeleton className="h-11" />
                <Skeleton className="h-11" />
              </div>
            ) : candidates.isError ? (
              <ErrorState error={candidates.error} onRetry={() => candidates.refetch()} className="py-4" />
            ) : candidates.data.items.length === 0 ? (
              <EmptyState
                title={term ? "No candidates match" : "No candidates yet"}
                action={
                  <Button variant="outline" asChild>
                    <Link to="/candidates/new">Add a candidate</Link>
                  </Button>
                }
                className="py-6"
              />
            ) : (
              <ul className="max-h-72 space-y-1 overflow-y-auto">
                {candidates.data.items.map((candidate) => {
                  const already = appliedIds.has(candidate.id);
                  return (
                    <li key={candidate.id}>
                      <label className={cn("flex cursor-pointer items-center gap-3 rounded-md border px-3 py-2 text-sm hover:bg-muted/50 has-[:checked]:border-primary has-[:checked]:bg-primary-soft", already && "cursor-not-allowed opacity-60")}>
                        <input type="radio" name="candidate" className="accent-[hsl(var(--primary))]" disabled={already} checked={selected === candidate.id} onChange={() => setSelected(candidate.id)} />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate font-medium">{candidate.full_name}</span>
                          <span className="block truncate text-xs text-muted-foreground">{candidate.technical_skills.join(", ") || "No skills recorded"}</span>
                        </span>
                        {already && <Badge variant="neutral">Already applied</Badge>}
                      </label>
                    </li>
                  );
                })}
              </ul>
            )}
          </fieldset>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={add.isPending}>
              Add and screen
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

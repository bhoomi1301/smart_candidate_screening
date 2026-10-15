import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, Briefcase, History, Lock, MessageSquare, RefreshCw, User } from "lucide-react";
import * as React from "react";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";
import { AssessmentBadge, JobStatusBadge, StatusBadge } from "@/components/common/badges";
import { ErrorState, InlineError, PageHeader, PageSkeleton } from "@/components/common/feedback";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/input";
import { Card, CardContent, CardDescription, CardHeader, CardTitle, Label, Skeleton } from "@/components/ui/primitives";
import { ComponentBreakdown, EligibilityPanel, PointsBar, ScoreExplanation, ScoreRing } from "@/features/screening/screening-components";
import { isApiError } from "@/lib/api/client";
import { applicationsApi, jobsApi } from "@/lib/api/endpoints";
import type { Application, ApplicationStatus, Screening } from "@/lib/api/types";
import { toastError } from "@/lib/forms";
import { cn, formatDate, formatDateTime, formatRelative, toNumber } from "@/lib/utils";

export const REJECTION_NOTE_MIN = 10;

export function ApplicationPage() {
  const id = Number(useParams().applicationId);
  const application = useQuery({ queryKey: ["applications", id], queryFn: () => applicationsApi.get(id) });
  const job = useQuery({ queryKey: ["jobs", application.data?.job_id], queryFn: () => jobsApi.get(application.data!.job_id), enabled: Boolean(application.data) });
  if (application.isPending) return <PageSkeleton />;
  if (application.isError)
    return (
      <>
        <PageHeader title="Application" back={{ to: "/jobs", label: "Back to jobs" }} />
        <Card>
          <ErrorState error={application.error} onRetry={() => application.refetch()} />
        </Card>
      </>
    );
  const data = application.data;
  return (
    <>
      <PageHeader
        back={{ to: `/jobs/${data.job_id}`, label: job.data ? `Back to ${job.data.title}` : "Back to job" }}
        title={data.candidate.full_name}
        description={
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <StatusBadge status={data.status} />
            <Link to={`/jobs/${data.job_id}`} className="inline-flex items-center gap-1 hover:underline">
              <Briefcase className="size-3.5" aria-hidden="true" />
              {job.data?.title ?? "Job"}
            </Link>
            {job.data?.status === "closed" && <JobStatusBadge status="closed" />}
            <Link to={`/candidates/${data.candidate_id}`} className="inline-flex items-center gap-1 hover:underline">
              <User className="size-3.5" aria-hidden="true" />
              Candidate profile
            </Link>
            <span>Applied {formatDate(data.created_at)}</span>
          </span>
        }
      />
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <ScreeningSection application={data} />
        <div className="space-y-4">
          <DecisionPanel application={data} />
          <HistoryTimeline applicationId={data.id} />
        </div>
      </div>
    </>
  );
}

function ScreeningSection({ application }: { application: Application }) {
  const queryClient = useQueryClient();
  const screening = useQuery({ queryKey: ["applications", application.id, "screening"], queryFn: () => applicationsApi.screening(application.id) });
  const refresh = useMutation({
    mutationFn: () => applicationsApi.refreshScreening(application.id),
    onSuccess: (result) => {
      queryClient.setQueryData(["applications", application.id, "screening"], result);
      queryClient.invalidateQueries({ queryKey: ["applications", application.id] });
      queryClient.invalidateQueries({ queryKey: ["jobs", application.job_id] });
      queryClient.invalidateQueries({ queryKey: ["analytics"] });
      toast.success("Screening recalculated with current candidate and job data");
    },
    onError: (error) => toastError(error),
  });

  if (screening.isPending) return <Skeleton className="h-[32rem]" />;
  if (screening.isError)
    return (
      <Card>
        <ErrorState error={screening.error} onRetry={() => screening.refetch()} />
      </Card>
    );
  const result: Screening = screening.data;
  const breakdown = result.score_breakdown;
  return (
    <div className="min-w-0 space-y-4">
      {result.is_stale && (
        <div className="flex flex-col gap-2 rounded-md border border-warning/30 bg-warning-soft px-3 py-2 text-sm sm:flex-row sm:items-center">
          <AlertTriangle className="size-4 shrink-0 text-warning" aria-hidden="true" />
          <p className="flex-1">
            <span className="font-medium">This score is out of date</span> ({(result.stale_reason ?? "data changed").replace(/_/g, " ")}).{" "}
            {application.status === "Rejected" ? "It is the score the rejection was based on." : "Refresh to score against current data."}
          </p>
          <Button size="sm" variant="outline" loading={refresh.isPending} onClick={() => refresh.mutate()}>
            <RefreshCw aria-hidden="true" /> Refresh score
          </Button>
        </div>
      )}
      <Card>
        <CardHeader className="flex-row flex-wrap items-start justify-between gap-2 space-y-0">
          <div>
            <CardTitle>Screening result</CardTitle>
            <CardDescription>Evaluated {formatRelative(result.evaluated_at)} · {formatDateTime(result.evaluated_at)}</CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <AssessmentBadge status={result.assessment_status} />
            {!result.is_stale && (
              <Button size="sm" variant="ghost" loading={refresh.isPending} onClick={() => refresh.mutate()}>
                {!refresh.isPending && <RefreshCw aria-hidden="true" />} Re-screen
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="flex flex-col items-center gap-6 sm:flex-row sm:items-start">
            <ScoreRing score={toNumber(result.score)} upperBound={breakdown.assessment_status === "incomplete" ? breakdown.score_upper_bound : null} />
            <div className="w-full min-w-0 flex-1 space-y-4">
              <EligibilityPanel breakdown={breakdown} />
              <div>
                <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">Points by component</h3>
                <PointsBar breakdown={breakdown} />
              </div>
            </div>
          </div>
          <ComponentBreakdown breakdown={breakdown} />
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>How this score was calculated</CardTitle>
        </CardHeader>
        <CardContent>
          <ScoreExplanation breakdown={breakdown} />
        </CardContent>
      </Card>
    </div>
  );
}

export function DecisionPanel({ application }: { application: Application }) {
  const queryClient = useQueryClient();
  const workflow = useQuery({ queryKey: ["applications", "workflow"], queryFn: applicationsApi.workflow, staleTime: Infinity });
  const allowed = workflow.data?.transitions.find((item) => item.from_status === application.status)?.allowed ?? [];
  const [target, setTarget] = React.useState<ApplicationStatus | "note" | null>(null);
  const [notes, setNotes] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [touched, setTouched] = React.useState(false);

  // When the status changes (here or by another reviewer) the allowed actions change, so the chosen
  // action is cleared. The typed note and any conflict explanation are kept so nothing is lost.
  React.useEffect(() => {
    setTarget(null);
    setTouched(false);
  }, [application.status]);

  const decide = useMutation({
    mutationFn: () => applicationsApi.decide(application.id, { status: target === "note" ? application.status : target!, notes: notes.trim(), expected_status: application.status }),
    onSuccess: (updated) => {
      queryClient.setQueryData(["applications", application.id], updated);
      queryClient.invalidateQueries({ queryKey: ["applications", application.id, "history"] });
      queryClient.invalidateQueries({ queryKey: ["jobs", application.job_id] });
      queryClient.invalidateQueries({ queryKey: ["candidates", application.candidate_id] });
      queryClient.invalidateQueries({ queryKey: ["analytics"] });
      toast.success(target === "note" ? "Note added to the history" : `Moved to ${updated.status}`);
      setTarget(null);
      setNotes("");
      setError(null);
      setTouched(false);
    },
    onError: (err) => {
      if (isApiError(err) && err.status === 409) {
        setError(`${err.message.replace(/\.?\s*$/, ".")} The latest status and history are now shown; your note was kept. Choose an action again.`);
        queryClient.invalidateQueries({ queryKey: ["applications", application.id] });
        queryClient.invalidateQueries({ queryKey: ["applications", application.id, "history"] });
      } else if (isApiError(err) && err.status === 422) {
        setError(Object.values(err.fieldErrors()).join(" ") || err.message);
      } else {
        setError(isApiError(err) ? err.message : "The decision could not be saved.");
      }
    },
  });

  const rejecting = target === "Rejected";
  const noteRequired = rejecting || target === "note";
  const noteError =
    rejecting && notes.trim().length < REJECTION_NOTE_MIN
      ? `Explain the rejection in at least ${REJECTION_NOTE_MIN} characters (${notes.trim().length}/${REJECTION_NOTE_MIN}).`
      : target === "note" && !notes.trim()
        ? "Write the note to add."
        : null;
  const terminal = workflow.data?.terminal_statuses.includes(application.status);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Decision</CardTitle>
        <CardDescription>
          Current status: <StatusBadge status={application.status} />
        </CardDescription>
      </CardHeader>
      <CardContent>
        {workflow.isPending ? (
          <Skeleton className="h-32" />
        ) : workflow.isError ? (
          <ErrorState error={workflow.error} onRetry={() => workflow.refetch()} className="py-4" />
        ) : (
          <form
            noValidate
            onSubmit={(event) => {
              event.preventDefault();
              setTouched(true);
              if (!target) {
                setError("Choose an action.");
                return;
              }
              if (noteError) return;
              setError(null);
              decide.mutate();
            }}
            className="space-y-4"
          >
            {terminal && (
              <p className="flex items-start gap-2 rounded-md bg-muted px-3 py-2 text-sm">
                <Lock className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                Rejected is final. You can still add notes to the history.
              </p>
            )}
            <fieldset>
              <legend className="mb-2 text-sm font-medium">Action</legend>
              <div className="grid gap-2">
                {allowed.map((status) => (
                  <DecisionOption key={status} name="decision" checked={target === status} onChange={() => setTarget(status)}>
                    <span className="flex items-center gap-2">
                      <ArrowRight className="size-4 text-muted-foreground" aria-hidden="true" />
                      Move to <StatusBadge status={status} />
                    </span>
                  </DecisionOption>
                ))}
                <DecisionOption name="decision" checked={target === "note"} onChange={() => setTarget("note")}>
                  <span className="flex items-center gap-2">
                    <MessageSquare className="size-4 text-muted-foreground" aria-hidden="true" />
                    Add a note only (status stays {application.status})
                  </span>
                </DecisionOption>
              </div>
            </fieldset>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="decision-notes">
                {rejecting ? "Reason for rejection" : target === "note" ? "Note" : "Decision note"}
                {noteRequired ? <span className="ml-0.5 text-destructive" aria-hidden="true">*</span> : <span className="ml-1 font-normal text-muted-foreground">(optional)</span>}
              </Label>
              <Textarea
                id="decision-notes"
                rows={4}
                maxLength={5000}
                value={notes}
                onChange={(event) => setNotes(event.target.value)}
                onBlur={() => setTouched(true)}
                aria-invalid={touched && Boolean(noteError)}
                aria-describedby="decision-notes-help"
                placeholder={rejecting ? "Explain which requirement was not met" : "Context for the team"}
              />
              <p id="decision-notes-help" className={cn("text-xs", touched && noteError ? "font-medium text-destructive" : "text-muted-foreground")}>
                {touched && noteError ? noteError : rejecting ? `Required, at least ${REJECTION_NOTE_MIN} characters. Recorded in the history.` : "Recorded in the history with your name and the time."}
              </p>
            </div>
            <InlineError message={error} />
            <Button type="submit" className="w-full" variant={rejecting ? "destructive" : "default"} loading={decide.isPending} disabled={!target}>
              {target === "note" ? "Add note" : rejecting ? "Reject application" : target ? `Move to ${target}` : "Choose an action"}
            </Button>
          </form>
        )}
      </CardContent>
    </Card>
  );
}

function DecisionOption({ name, checked, onChange, children }: { name: string; checked: boolean; onChange: () => void; children: React.ReactNode }) {
  return (
    <label className="flex cursor-pointer items-center gap-3 rounded-md border px-3 py-2 text-sm hover:bg-muted/50 has-[:checked]:border-primary has-[:checked]:bg-primary-soft has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring">
      <input type="radio" name={name} className="accent-[hsl(var(--primary))]" checked={checked} onChange={onChange} />
      {children}
    </label>
  );
}

function HistoryTimeline({ applicationId }: { applicationId: number }) {
  const history = useQuery({ queryKey: ["applications", applicationId, "history"], queryFn: () => applicationsApi.history(applicationId) });
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <History className="size-4 text-muted-foreground" aria-hidden="true" /> History
        </CardTitle>
      </CardHeader>
      <CardContent>
        {history.isPending ? (
          <Skeleton className="h-24" />
        ) : history.isError ? (
          <ErrorState error={history.error} onRetry={() => history.refetch()} className="py-4" />
        ) : (
          <ol className="relative space-y-4 border-l pl-5">
            {[...history.data].reverse().map((entry) => (
              <li key={entry.id} className="relative">
                <span className="absolute -left-[1.6rem] top-1 size-2.5 rounded-full border-2 border-card bg-primary" aria-hidden="true" />
                <div className="flex flex-wrap items-center gap-1.5 text-sm">
                  {entry.previous_status === null ? (
                    <>
                      Created as <StatusBadge status={entry.new_status} />
                    </>
                  ) : entry.previous_status === entry.new_status ? (
                    <span className="font-medium">Note added</span>
                  ) : (
                    <>
                      <StatusBadge status={entry.previous_status} />
                      <ArrowRight className="size-3.5 text-muted-foreground" aria-label="to" />
                      <StatusBadge status={entry.new_status} />
                    </>
                  )}
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  {entry.changed_by_name ?? "Unknown user"} · <time dateTime={entry.changed_at}>{formatDateTime(entry.changed_at)}</time>
                </p>
                {entry.notes && <p className="mt-1.5 whitespace-pre-line rounded-md bg-muted px-2.5 py-1.5 text-sm">{entry.notes}</p>}
              </li>
            ))}
          </ol>
        )}
      </CardContent>
    </Card>
  );
}


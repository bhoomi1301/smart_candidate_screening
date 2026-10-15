import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Briefcase, GraduationCap, Mail, Pencil, Phone, Plus, Timer, Trash2 } from "lucide-react";
import * as React from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { AssessmentBadge, EligibilityBadge, JobStatusBadge, StaleBadge, StatusBadge } from "@/components/common/badges";
import { ConfirmDialog, EmptyState, ErrorState, InlineError, PageHeader, PageSkeleton, errorMessage } from "@/components/common/feedback";
import { Button } from "@/components/ui/button";
import { NativeSelect } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/overlays";
import { Card, CardContent, CardDescription, CardHeader, CardTitle, Label, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/primitives";
import { ResumeCard } from "@/features/resumes/resume-card";
import { applicationsApi, candidatesApi, jobsApi } from "@/lib/api/endpoints";
import type { CandidateDetail } from "@/lib/api/types";
import { toastError } from "@/lib/forms";
import { formatDate, formatDateTime, formatScore, formatYears, initials } from "@/lib/utils";

export function CandidateProfilePage() {
  const id = Number(useParams().candidateId);
  const candidate = useQuery({ queryKey: ["candidates", id], queryFn: () => candidatesApi.get(id) });
  if (candidate.isPending) return <PageSkeleton />;
  if (candidate.isError)
    return (
      <>
        <PageHeader title="Candidate" back={{ to: "/candidates", label: "Back to candidates" }} />
        <Card>
          <ErrorState error={candidate.error} onRetry={() => candidate.refetch()} />
        </Card>
      </>
    );
  return <CandidateProfile candidate={candidate.data} />;
}

function CandidateProfile({ candidate }: { candidate: CandidateDetail }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [confirmDelete, setConfirmDelete] = React.useState(false);
  const [applyOpen, setApplyOpen] = React.useState(false);
  const remove = useMutation({
    mutationFn: () => candidatesApi.remove(candidate.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["candidates"] });
      queryClient.invalidateQueries({ queryKey: ["analytics"] });
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      toast.success(`${candidate.full_name} was deleted`);
      navigate("/candidates", { replace: true });
    },
    onError: (error) => toastError(error),
  });
  const applications = [...candidate.applications].sort((a, b) => b.created_at.localeCompare(a.created_at));

  return (
    <>
      <PageHeader
        back={{ to: "/candidates", label: "Back to candidates" }}
        title={
          <span className="flex items-center gap-3">
            <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-primary-soft text-sm font-semibold text-accent-foreground" aria-hidden="true">
              {initials(candidate.full_name)}
            </span>
            <span className="truncate">{candidate.full_name}</span>
          </span>
        }
        description={`Added ${formatDate(candidate.created_at)} · Updated ${formatDate(candidate.updated_at)}`}
        actions={
          <>
            <Button variant="outline" onClick={() => setConfirmDelete(true)}>
              <Trash2 aria-hidden="true" /> Delete
            </Button>
            <Button variant="outline" asChild>
              <Link to={`/candidates/${candidate.id}/edit`}>
                <Pencil aria-hidden="true" /> Edit
              </Link>
            </Button>
            <Button onClick={() => setApplyOpen(true)}>
              <Plus aria-hidden="true" /> Apply to job
            </Button>
          </>
        }
      />

      <div className="grid gap-4 lg:grid-cols-[1fr_2fr]">
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Details</CardTitle>
            </CardHeader>
            <CardContent>
              <dl className="space-y-3 text-sm">
                <DetailRow icon={Mail} label="Email">
                  <a href={`mailto:${candidate.email}`} className="break-all hover:underline">
                    {candidate.email}
                  </a>
                </DetailRow>
                <DetailRow icon={Phone} label="Phone">
                  {candidate.phone ?? <span className="text-muted-foreground">Not recorded</span>}
                </DetailRow>
                <DetailRow icon={Timer} label="Experience">
                  {candidate.total_experience === null ? <span className="text-muted-foreground">Not recorded</span> : formatYears(candidate.total_experience)}
                </DetailRow>
              </dl>
            </CardContent>
          </Card>
          <ResumeCard candidate={candidate} />
          <Card>
            <CardHeader>
              <CardTitle>Skills</CardTitle>
            </CardHeader>
            <CardContent>
              {candidate.technical_skills.length === 0 ? (
                <p className="text-sm text-muted-foreground">No skills recorded. Screening will mark skill components as missing data.</p>
              ) : (
                <ul className="flex flex-wrap gap-1.5" aria-label="Skills">
                  {candidate.technical_skills.map((skill) => (
                    <li key={skill} className="rounded-md border bg-secondary px-2 py-0.5 text-sm">
                      {skill}
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Education</CardTitle>
            </CardHeader>
            <CardContent>
              {candidate.education.length === 0 ? (
                <p className="text-sm text-muted-foreground">No education recorded.</p>
              ) : (
                <ul className="space-y-3">
                  {candidate.education.map((item) => (
                    <li key={item.id} className="flex gap-3 text-sm">
                      <GraduationCap className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                      <div>
                        <p className="font-medium">{[item.degree, item.field_of_study].filter(Boolean).join(", ")}</p>
                        <p className="text-muted-foreground">{[item.institution, item.graduation_year].filter(Boolean).join(" · ") || "Institution not recorded"}</p>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </div>

        <Card className="self-start">
          <CardHeader>
            <CardTitle>Applications</CardTitle>
            <CardDescription>Each job has its own status, screening result, and history.</CardDescription>
          </CardHeader>
          {applications.length === 0 ? (
            <EmptyState
              icon={Briefcase}
              title="Not applied to any job"
              description="Apply this candidate to an open job to screen them against its requirements."
              action={
                <Button onClick={() => setApplyOpen(true)}>
                  <Plus aria-hidden="true" /> Apply to job
                </Button>
              }
            />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Job</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Score</TableHead>
                  <TableHead className="hidden md:table-cell">Eligibility</TableHead>
                  <TableHead className="hidden sm:table-cell">Applied</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {applications.map((application) => (
                  <TableRow key={application.id} className="cursor-pointer" onClick={() => navigate(`/applications/${application.id}`)}>
                    <TableCell>
                      <Link to={`/applications/${application.id}`} className="font-medium hover:underline" onClick={(event) => event.stopPropagation()}>
                        {application.job_title}
                      </Link>
                      {application.job_status === "closed" && (
                        <div className="mt-1">
                          <JobStatusBadge status="closed" />
                        </div>
                      )}
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={application.status} />
                    </TableCell>
                    <TableCell className="text-right font-semibold tabular">{formatScore(application.current_screening_score)}</TableCell>
                    <TableCell className="hidden md:table-cell">
                      <div className="flex flex-wrap gap-1">
                        <EligibilityBadge eligibility={application.screening_result?.eligibility ?? null} />
                        <AssessmentBadge status={application.screening_result?.assessment_status ?? null} />
                        <StaleBadge stale={application.screening_result?.is_stale ?? false} />
                      </div>
                    </TableCell>
                    <TableCell className="hidden whitespace-nowrap text-muted-foreground sm:table-cell" title={formatDateTime(application.created_at)}>
                      {formatDate(application.created_at)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </Card>
      </div>

      <ApplyToJobDialog candidate={candidate} open={applyOpen} onOpenChange={setApplyOpen} />
      <ConfirmDialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        title={`Delete ${candidate.full_name}?`}
        description={
          candidate.applications.length > 0
            ? `This permanently deletes the candidate and their ${candidate.applications.length} application(s), including screening results and decision history. This cannot be undone.`
            : "This permanently deletes the candidate. This cannot be undone."
        }
        confirmLabel="Delete candidate"
        loading={remove.isPending}
        onConfirm={() => remove.mutate()}
      />
    </>
  );
}

function DetailRow({ icon: Icon, label, children }: { icon: React.ElementType; label: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-3">
      <Icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
      <div className="min-w-0">
        <dt className="text-xs text-muted-foreground">{label}</dt>
        <dd>{children}</dd>
      </div>
    </div>
  );
}

function ApplyToJobDialog({ candidate, open, onOpenChange }: { candidate: CandidateDetail; open: boolean; onOpenChange: (open: boolean) => void }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [jobId, setJobId] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const jobs = useQuery({ queryKey: ["jobs", "list", { status: "open", limit: 100 }], queryFn: () => jobsApi.list({ status: "open", limit: 100 }), enabled: open });
  const appliedJobIds = new Set(candidate.applications.map((application) => application.job_id));
  const available = (jobs.data?.items ?? []).filter((job) => !appliedJobIds.has(job.id));
  const apply = useMutation({
    mutationFn: () => applicationsApi.create(Number(jobId), candidate.id),
    onSuccess: (application) => {
      queryClient.invalidateQueries({ queryKey: ["candidates"] });
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      queryClient.invalidateQueries({ queryKey: ["analytics"] });
      toast.success(`Applied and screened: score ${formatScore(application.current_screening_score)}`);
      onOpenChange(false);
      navigate(`/applications/${application.id}`);
    },
    onError: (err) => setError(errorMessage(err)),
  });
  React.useEffect(() => {
    if (open) {
      setJobId("");
      setError(null);
    }
  }, [open]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Apply {candidate.full_name} to a job</DialogTitle>
          <DialogDescription>The application starts as Pending and is screened immediately against the job’s requirements.</DialogDescription>
        </DialogHeader>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (!jobId) {
              setError("Choose a job.");
              return;
            }
            setError(null);
            apply.mutate();
          }}
          noValidate
        >
          <InlineError message={error} className="mb-3" />
          {jobs.isPending ? (
            <p className="text-sm text-muted-foreground">Loading open jobs…</p>
          ) : jobs.isError ? (
            <ErrorState error={jobs.error} onRetry={() => jobs.refetch()} className="py-4" />
          ) : available.length === 0 ? (
            <EmptyState
              icon={Briefcase}
              title={jobs.data.items.length === 0 ? "No open jobs" : "Already applied to every open job"}
              description={jobs.data.items.length === 0 ? "Create a job opening first." : undefined}
              action={
                jobs.data.items.length === 0 ? (
                  <Button asChild variant="outline">
                    <Link to="/jobs/new">Create a job</Link>
                  </Button>
                ) : undefined
              }
              className="py-6"
            />
          ) : (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="apply-job">Open job</Label>
              <NativeSelect id="apply-job" value={jobId} onChange={(event) => setJobId(event.target.value)} aria-invalid={Boolean(error && !jobId)}>
                <option value="">Select a job…</option>
                {available.map((job) => (
                  <option key={job.id} value={job.id}>
                    {job.title}
                    {job.department ? ` · ${job.department}` : ""}
                  </option>
                ))}
              </NativeSelect>
            </div>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={apply.isPending} disabled={available.length === 0}>
              Apply and screen
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Activity, BarChart3, Briefcase, ClipboardList, Gauge, Plus, Trophy, Users, X } from "lucide-react";
import * as React from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Cell, LabelList, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { EligibilityBadge, StatusBadge } from "@/components/common/badges";
import { EmptyState, ErrorState, PageHeader, StatCard } from "@/components/common/feedback";
import { Button } from "@/components/ui/button";
import { Input, NativeSelect } from "@/components/ui/input";
import { Card, CardContent, CardDescription, CardHeader, CardTitle, Skeleton } from "@/components/ui/primitives";
import { useCurrentUser } from "@/features/auth/auth-context";
import { analyticsApi } from "@/lib/api/endpoints";
import type { AnalyticsFilters, DashboardSummary } from "@/lib/api/types";
import { formatRelative, formatScore, pluralize, toNumber } from "@/lib/utils";

const STATUS_COLORS: Record<string, string> = {
  Pending: "hsl(220 9% 60%)",
  "Under Review": "hsl(243 75% 60%)",
  Shortlisted: "hsl(152 60% 36%)",
  Rejected: "hsl(0 65% 55%)",
};

function useFilters(): [AnalyticsFilters, (next: AnalyticsFilters) => void] {
  const [params, setParams] = useSearchParams();
  const filters: AnalyticsFilters = { date_from: params.get("from") ?? undefined, date_to: params.get("to") ?? undefined };
  const update = (next: AnalyticsFilters) => {
    const search = new URLSearchParams();
    if (next.date_from) search.set("from", next.date_from);
    if (next.date_to) search.set("to", next.date_to);
    setParams(search, { replace: true });
  };
  return [filters, update];
}

export function DashboardPage() {
  const user = useCurrentUser();
  const [filters, setFilters] = useFilters();
  const invalidRange = Boolean(filters.date_from && filters.date_to && filters.date_from > filters.date_to);
  const dashboard = useQuery({
    queryKey: ["analytics", "dashboard", filters],
    queryFn: () => analyticsApi.dashboard(filters),
    placeholderData: keepPreviousData,
    enabled: !invalidRange,
  });
  const firstName = user.full_name.split(" ")[0];

  return (
    <>
      <PageHeader
        title={`Welcome back, ${firstName}`}
        description="Recruitment activity and screening results for your workspace."
        actions={
          <>
            <Button variant="outline" asChild>
              <Link to="/candidates/new">
                <Plus aria-hidden="true" /> Add candidate
              </Link>
            </Button>
            <Button asChild>
              <Link to="/jobs/new">
                <Plus aria-hidden="true" /> Create job
              </Link>
            </Button>
          </>
        }
      />
      <DateFilters filters={filters} onChange={setFilters} invalid={invalidRange} />
      {dashboard.isPending ? (
        <DashboardSkeleton />
      ) : dashboard.isError ? (
        <Card>
          <ErrorState error={dashboard.error} onRetry={() => dashboard.refetch()} />
        </Card>
      ) : (
        <DashboardContent data={dashboard.data} filters={filters} />
      )}
    </>
  );
}

function DateFilters({ filters, onChange, invalid }: { filters: AnalyticsFilters; onChange: (next: AnalyticsFilters) => void; invalid: boolean }) {
  return (
    <div className="mb-5 flex flex-wrap items-end gap-3">
      <div className="flex flex-col gap-1.5">
        <label htmlFor="date-from" className="text-xs font-medium text-muted-foreground">
          From
        </label>
        <Input id="date-from" type="date" className="w-40" value={filters.date_from ?? ""} max={filters.date_to} onChange={(event) => onChange({ ...filters, date_from: event.target.value || undefined })} />
      </div>
      <div className="flex flex-col gap-1.5">
        <label htmlFor="date-to" className="text-xs font-medium text-muted-foreground">
          To
        </label>
        <Input id="date-to" type="date" className="w-40" value={filters.date_to ?? ""} min={filters.date_from} aria-invalid={invalid} onChange={(event) => onChange({ ...filters, date_to: event.target.value || undefined })} />
      </div>
      {(filters.date_from || filters.date_to) && (
        <Button variant="ghost" size="sm" onClick={() => onChange({})}>
          <X aria-hidden="true" /> Clear dates
        </Button>
      )}
      <p className="w-full text-xs text-muted-foreground sm:w-auto">
        {invalid ? <span className="font-medium text-destructive">“From” must be on or before “To”.</span> : "Dates filter candidates and applications by when they were added (UTC)."}
      </p>
    </div>
  );
}

function DashboardSkeleton() {
  return (
    <div className="space-y-4" role="status" aria-label="Loading dashboard">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {Array.from({ length: 4 }, (_, index) => (
          <Skeleton key={index} className="h-[92px]" />
        ))}
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Skeleton className="h-72" />
        <Skeleton className="h-72" />
      </div>
    </div>
  );
}

function DashboardContent({ data, filters }: { data: DashboardSummary; filters: AnalyticsFilters }) {
  const filtered = Boolean(filters.date_from || filters.date_to);
  const jobs = data.average_scores_by_job;
  if (!filtered && data.total_candidates === 0 && jobs.length === 0) {
    return (
      <Card>
        <EmptyState
          icon={ClipboardList}
          title="Your workspace is empty"
          description="Create a job opening with its requirements, add candidates, then apply them to the job to see screening results here."
          action={
            <div className="flex flex-wrap justify-center gap-2">
              <Button asChild>
                <Link to="/jobs/new">Create a job</Link>
              </Button>
              <Button variant="outline" asChild>
                <Link to="/candidates/new">Add a candidate</Link>
              </Button>
            </div>
          }
        />
      </Card>
    );
  }
  const overall = data.overall_scores;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard label="Candidates" value={data.total_candidates.toLocaleString()} icon={Users} hint={filtered ? "Added in range" : "In your talent pool"} />
        <StatCard label="Active job openings" value={data.active_job_openings.toLocaleString()} icon={Briefcase} hint="Currently open" />
        <StatCard label="Applications" value={data.total_applications.toLocaleString()} icon={ClipboardList} hint={`${pluralize(data.unique_applicants, "unique applicant")}`} />
        <StatCard
          label="Average score"
          value={overall.average_score === null ? "—" : formatScore(overall.average_score)}
          icon={Gauge}
          hint={overall.scored_count === 0 ? "No scored applications yet" : overall.incomplete_count > 0 ? `${overall.incomplete_count} with incomplete data` : `Across ${pluralize(overall.scored_count, "application")}`}
        />
      </div>
      <div className="grid grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-2">
        <StatusDistribution data={data} />
        <JobScores data={data} />
      </div>
      <div className="grid grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <TopApplicants jobs={jobs.filter((job) => job.application_count > 0)} />
        <RecentActivity />
      </div>
      <SkillGaps filters={filters} />
    </div>
  );
}

function StatusDistribution({ data }: { data: DashboardSummary }) {
  const rows = data.status_distribution.map((item) => ({ ...item, percent: toNumber(item.percentage) ?? 0 }));
  return (
    <Card>
      <CardHeader>
        <CardTitle>Application status</CardTitle>
        <CardDescription>Current status of {pluralize(data.total_applications, "application")}.</CardDescription>
      </CardHeader>
      <CardContent>
        {data.total_applications === 0 ? (
          <EmptyState icon={BarChart3} title="No applications yet" description="Apply candidates to a job to start tracking decisions." className="py-8" />
        ) : (
          <>
            <div className="h-48" aria-hidden="true">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={rows} layout="vertical" margin={{ left: 8, right: 48, top: 4, bottom: 4 }}>
                  <XAxis type="number" hide domain={[0, "dataMax"]} />
                  <YAxis type="category" dataKey="status" width={96} tickLine={false} axisLine={false} tick={{ fontSize: 12, fill: "hsl(222 47% 11%)" }} />
                  <Tooltip cursor={{ fill: "hsl(220 14% 96%)" }} formatter={(value: number, _name, item) => [`${value} (${item.payload.percentage}%)`, "Applications"]} />
                  <Bar dataKey="count" radius={[0, 4, 4, 0]} barSize={18} isAnimationActive={false}>
                    {rows.map((row) => (
                      <Cell key={row.status} fill={STATUS_COLORS[row.status]} />
                    ))}
                    <LabelList dataKey="count" position="right" className="fill-foreground text-xs" />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
            <ul className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
              {rows.map((row) => (
                <li key={row.status} className="flex items-center justify-between gap-2 rounded-md border px-2.5 py-1.5">
                  <StatusBadge status={row.status} />
                  <span className="whitespace-nowrap tabular text-muted-foreground">
                    {row.count} · {formatScore(row.percent)}%
                  </span>
                </li>
              ))}
            </ul>
          </>
        )}
      </CardContent>
    </Card>
  );
}

function JobScores({ data }: { data: DashboardSummary }) {
  const rows = data.average_scores_by_job
    .filter((job) => job.scored_count > 0)
    .map((job) => ({
      name: job.title.length > 22 ? `${job.title.slice(0, 21)}…` : job.title,
      title: job.title,
      average: toNumber(job.average_score),
      complete: toNumber(job.average_complete_score),
      job,
    }));
  return (
    <Card>
      <CardHeader>
        <CardTitle>Average score by job</CardTitle>
        <CardDescription>All scored applications vs. complete assessments only.</CardDescription>
      </CardHeader>
      <CardContent>
        {rows.length === 0 ? (
          <EmptyState icon={BarChart3} title="No scores yet" description="Scores appear once candidates are applied to jobs." className="py-8" />
        ) : (
          <>
            <div className="h-56" aria-hidden="true">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={rows} margin={{ left: -16, right: 8, top: 8, bottom: 0 }}>
                  <CartesianGrid vertical={false} stroke="hsl(220 13% 92%)" />
                  <XAxis dataKey="name" tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: "hsl(220 9% 40%)" }} interval={0} />
                  <YAxis domain={[0, 100]} tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: "hsl(220 9% 40%)" }} />
                  <Tooltip cursor={{ fill: "hsl(220 14% 96%)" }} formatter={(value) => formatScore(value as number | null)} labelFormatter={(_, payload) => payload?.[0]?.payload.title ?? ""} />
                  <Legend iconType="square" wrapperStyle={{ fontSize: 12 }} />
                  <Bar dataKey="average" name="All scored" fill="hsl(243 75% 58%)" radius={[3, 3, 0, 0]} maxBarSize={28} isAnimationActive={false} />
                  <Bar dataKey="complete" name="Complete only" fill="hsl(220 12% 70%)" radius={[3, 3, 0, 0]} maxBarSize={28} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <details className="mt-3 text-sm">
              <summary className="cursor-pointer rounded text-muted-foreground hover:text-foreground">Show as table</summary>
              <table className="mt-2 w-full text-left text-sm">
                <thead className="text-xs text-muted-foreground">
                  <tr>
                    <th className="py-1 font-medium">Job</th>
                    <th className="py-1 text-right font-medium">All scored</th>
                    <th className="py-1 text-right font-medium">Complete only</th>
                    <th className="py-1 text-right font-medium">Scored / incomplete</th>
                  </tr>
                </thead>
                <tbody className="tabular">
                  {rows.map(({ job }) => (
                    <tr key={job.job_id} className="border-t">
                      <td className="py-1.5">
                        <Link to={`/jobs/${job.job_id}`} className="hover:underline">
                          {job.title}
                        </Link>
                      </td>
                      <td className="py-1.5 text-right">{formatScore(job.average_score)}</td>
                      <td className="py-1.5 text-right">{formatScore(job.average_complete_score)}</td>
                      <td className="py-1.5 text-right">
                        {job.scored_count} / {job.incomplete_count}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          </>
        )}
      </CardContent>
    </Card>
  );
}

function TopApplicants({ jobs }: { jobs: DashboardSummary["average_scores_by_job"] }) {
  const [jobId, setJobId] = React.useState<number | null>(jobs[0]?.job_id ?? null);
  const selected = jobs.some((job) => job.job_id === jobId) ? jobId : (jobs[0]?.job_id ?? null);
  const top = useQuery({ queryKey: ["analytics", "top", selected], queryFn: () => analyticsApi.topApplicants(selected!, 5), enabled: selected !== null });
  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-start justify-between gap-3 space-y-0">
        <div>
          <CardTitle>Top applicants</CardTitle>
          <CardDescription>Ranked by screening score. Ranking supports decisions; it does not make them.</CardDescription>
        </div>
        {jobs.length > 0 && (
          <NativeSelect aria-label="Job" className="w-full sm:w-56" value={selected ?? ""} onChange={(event) => setJobId(Number(event.target.value))}>
            {jobs.map((job) => (
              <option key={job.job_id} value={job.job_id}>
                {job.title}
              </option>
            ))}
          </NativeSelect>
        )}
      </CardHeader>
      <CardContent>
        {jobs.length === 0 ? (
          <EmptyState icon={Trophy} title="No applicants to rank" description="Apply candidates to a job to see the highest-scoring applicants." className="py-8" />
        ) : top.isPending ? (
          <div className="space-y-2">
            {Array.from({ length: 3 }, (_, index) => (
              <Skeleton key={index} className="h-12" />
            ))}
          </div>
        ) : top.isError ? (
          <ErrorState error={top.error} onRetry={() => top.refetch()} className="py-6" />
        ) : (
          <ol className="divide-y">
            {top.data.items.map((item) => (
              <li key={item.application_id}>
                <Link to={`/applications/${item.application_id}`} className="flex items-center gap-3 rounded-md px-1 py-2.5 hover:bg-muted/50">
                  <span className="w-6 shrink-0 text-center text-sm font-semibold text-muted-foreground tabular" aria-label={`Rank ${item.rank}`}>
                    {item.rank}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium">{item.candidate.full_name}</span>
                    <span className="block truncate text-xs text-muted-foreground">{item.application_status}</span>
                  </span>
                  <span className="hidden sm:block">
                    <EligibilityBadge eligibility={item.eligibility} />
                  </span>
                  <span className="w-12 text-right text-sm font-semibold tabular">{formatScore(item.score)}</span>
                </Link>
              </li>
            ))}
          </ol>
        )}
        {selected !== null && top.data && top.data.total_applicants > top.data.items.length && (
          <Link to={`/jobs/${selected}`} className="mt-2 inline-block text-sm font-medium text-primary hover:underline">
            View all {top.data.total_applicants} applicants
          </Link>
        )}
      </CardContent>
    </Card>
  );
}

function RecentActivity() {
  const activity = useQuery({ queryKey: ["analytics", "activity"], queryFn: () => analyticsApi.activity(8) });
  return (
    <Card>
      <CardHeader>
        <CardTitle>Recent activity</CardTitle>
        <CardDescription>Latest recruitment actions in your workspace.</CardDescription>
      </CardHeader>
      <CardContent>
        {activity.isPending ? (
          <div className="space-y-3">
            {Array.from({ length: 4 }, (_, index) => (
              <Skeleton key={index} className="h-10" />
            ))}
          </div>
        ) : activity.isError ? (
          <ErrorState error={activity.error} onRetry={() => activity.refetch()} className="py-6" />
        ) : activity.data.items.length === 0 ? (
          <EmptyState icon={Activity} title="No activity yet" className="py-8" />
        ) : (
          <ul className="space-y-3">
            {activity.data.items.map((item) => {
              const subject = [item.candidate_name, item.job_title].filter(Boolean).join(" · ");
              return (
                <li key={item.id} className="flex gap-3 text-sm">
                  <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-primary" aria-hidden="true" />
                  <div className="min-w-0">
                    <p className="leading-snug">{item.description}</p>
                    <p className="truncate text-xs text-muted-foreground">
                      {subject && `${subject} · `}
                      {item.actor_name ?? "System"} · <time dateTime={item.created_at}>{formatRelative(item.created_at)}</time>
                    </p>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function SkillGaps({ filters }: { filters: AnalyticsFilters }) {
  const gaps = useQuery({ queryKey: ["analytics", "skill-gaps", filters], queryFn: () => analyticsApi.skillGaps({ ...filters, limit: 8 }) });
  return (
    <Card>
      <CardHeader>
        <CardTitle>Skill gaps</CardTitle>
        <CardDescription>Required skills most often missing among applicants with skill data.</CardDescription>
      </CardHeader>
      <CardContent>
        {gaps.isPending ? (
          <Skeleton className="h-24" />
        ) : gaps.isError ? (
          <ErrorState error={gaps.error} onRetry={() => gaps.refetch()} className="py-6" />
        ) : gaps.data.items.length === 0 ? (
          <p className="text-sm text-muted-foreground">{gaps.data.message}</p>
        ) : (
          <>
            <ul className="grid gap-x-8 gap-y-3 sm:grid-cols-2">
              {gaps.data.items.map((item) => (
                <li key={item.skill}>
                  <div className="flex items-baseline justify-between gap-2 text-sm">
                    <span className="font-medium">{item.skill}</span>
                    <span className="tabular text-muted-foreground">
                      missing in {item.missing_count} of {item.evaluated_applications} ({formatScore(item.missing_rate)}%)
                    </span>
                  </div>
                  <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden="true">
                    <div className="h-full rounded-full bg-warning" style={{ width: `${toNumber(item.missing_rate) ?? 0}%` }} />
                  </div>
                </li>
              ))}
            </ul>
            {gaps.data.excluded_without_skill_data > 0 && (
              <p className="mt-3 text-xs text-muted-foreground">
                {pluralize(gaps.data.excluded_without_skill_data, "application")} excluded because the candidate has no skills recorded.
              </p>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

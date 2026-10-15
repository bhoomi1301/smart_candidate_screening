import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Briefcase, Plus, Search } from "lucide-react";
import * as React from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { JobStatusBadge } from "@/components/common/badges";
import { EmptyState, ErrorState, PageHeader, Pagination, TableSkeleton } from "@/components/common/feedback";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/overlays";
import { Card, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/primitives";
import { SkillPreview } from "@/features/candidates/candidates-page";
import { jobsApi } from "@/lib/api/endpoints";
import type { JobListParams, JobStatus } from "@/lib/api/types";
import { formatDate, formatYears, pluralize, toNumber } from "@/lib/utils";

const PAGE_SIZE = 20;

export function JobsPage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const [search, setSearch] = React.useState(params.get("q") ?? "");
  const status = (params.get("status") as JobStatus | null) ?? undefined;
  const query: JobListParams = { status, q: params.get("q") || undefined, skip: toNumber(params.get("skip")) ?? 0, limit: PAGE_SIZE };

  const update = React.useCallback(
    (updates: Record<string, string | undefined>, resetPage = true) =>
      setParams(
        (current) => {
          const next = new URLSearchParams(current);
          for (const [key, value] of Object.entries(updates)) {
            if (value) next.set(key, value);
            else next.delete(key);
          }
          if (resetPage) next.delete("skip");
          return next;
        },
        { replace: true },
      ),
    [setParams],
  );

  React.useEffect(() => {
    const timer = window.setTimeout(() => {
      if ((params.get("q") ?? "") !== search.trim()) update({ q: search.trim() || undefined });
    }, 300);
    return () => window.clearTimeout(timer);
  }, [search, params, update]);

  const jobs = useQuery({ queryKey: ["jobs", "list", query], queryFn: () => jobsApi.list(query), placeholderData: keepPreviousData });
  const filtered = Boolean(query.q || query.status);

  return (
    <>
      <PageHeader
        title="Job openings"
        description={jobs.data ? `${pluralize(jobs.data.total, "job")}${filtered ? " match" : " in your workspace"}` : "Roles and their screening criteria"}
        actions={
          <Button asChild>
            <Link to="/jobs/new">
              <Plus aria-hidden="true" /> Create job
            </Link>
          </Button>
        }
      />
      <Card>
        <div className="flex flex-col gap-3 border-b p-3 sm:flex-row sm:items-center sm:justify-between">
          <Tabs value={status ?? "all"} onValueChange={(value) => update({ status: value === "all" ? undefined : value })}>
            <TabsList aria-label="Filter by status">
              <TabsTrigger value="all">All</TabsTrigger>
              <TabsTrigger value="open">Open</TabsTrigger>
              <TabsTrigger value="closed">Closed</TabsTrigger>
            </TabsList>
          </Tabs>
          <div className="relative sm:w-72">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
            <Input type="search" aria-label="Search jobs" placeholder="Search title or department" className="pl-8" value={search} onChange={(event) => setSearch(event.target.value)} />
          </div>
        </div>
        {jobs.isPending ? (
          <TableSkeleton rows={5} columns={4} />
        ) : jobs.isError ? (
          <ErrorState error={jobs.error} onRetry={() => jobs.refetch()} />
        ) : jobs.data.items.length === 0 ? (
          filtered ? (
            <EmptyState icon={Search} title="No jobs match" description="Try another search or status." />
          ) : (
            <EmptyState
              icon={Briefcase}
              title="No job openings yet"
              description="Create a job with required skills, experience, and qualifications to start screening candidates."
              action={
                <Button asChild>
                  <Link to="/jobs/new">Create your first job</Link>
                </Button>
              }
            />
          )
        ) : (
          <>
            <Table className={jobs.isPlaceholderData ? "opacity-60" : undefined}>
              <TableHeader>
                <TableRow>
                  <TableHead>Job</TableHead>
                  <TableHead className="hidden md:table-cell">Required skills</TableHead>
                  <TableHead className="hidden lg:table-cell">Min. experience</TableHead>
                  <TableHead className="text-right">Applicants</TableHead>
                  <TableHead className="hidden sm:table-cell">Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {jobs.data.items.map((job) => (
                  <TableRow key={job.id} className="cursor-pointer" onClick={() => navigate(`/jobs/${job.id}`)}>
                    <TableCell className="max-w-[18rem]">
                      <Link to={`/jobs/${job.id}`} className="block truncate font-medium hover:underline" onClick={(event) => event.stopPropagation()}>
                        {job.title}
                      </Link>
                      <span className="block truncate text-xs text-muted-foreground">
                        {job.department ?? "No department"} · Created {formatDate(job.created_at)}
                      </span>
                      <span className="mt-1 block sm:hidden">
                        <JobStatusBadge status={job.status} />
                      </span>
                    </TableCell>
                    <TableCell className="hidden md:table-cell">
                      <SkillPreview skills={job.required_skills} max={3} />
                    </TableCell>
                    <TableCell className="hidden whitespace-nowrap tabular lg:table-cell">{toNumber(job.minimum_experience) ? formatYears(job.minimum_experience) : "None"}</TableCell>
                    <TableCell className="text-right font-medium tabular">{job.application_count}</TableCell>
                    <TableCell className="hidden sm:table-cell">
                      <JobStatusBadge status={job.status} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <Pagination skip={query.skip ?? 0} limit={PAGE_SIZE} total={jobs.data.total} onChange={(skip) => update({ skip: skip ? String(skip) : undefined }, false)} label="jobs" />
          </>
        )}
      </Card>
    </>
  );
}

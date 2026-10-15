import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Filter, Plus, Search, Users, X } from "lucide-react";
import * as React from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { EmptyState, ErrorState, PageHeader, Pagination, TableSkeleton } from "@/components/common/feedback";
import { Button } from "@/components/ui/button";
import { Input, NativeSelect } from "@/components/ui/input";
import { Card, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/primitives";
import { candidatesApi, jobsApi } from "@/lib/api/endpoints";
import { APPLICATION_STATUSES, type ApplicationStatus, type CandidateListParams } from "@/lib/api/types";
import { formatDate, formatYears, pluralize, toNumber } from "@/lib/utils";

const PAGE_SIZE = 20;

function useDebounced<T>(value: T, delay = 300): T {
  const [debounced, setDebounced] = React.useState(value);
  React.useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

export function CandidatesPage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const [search, setSearch] = React.useState(params.get("q") ?? "");
  const [showFilters, setShowFilters] = React.useState(Boolean(params.get("skill") || params.get("status") || params.get("job_id") || params.get("min") || params.get("max")));
  const debouncedSearch = useDebounced(search.trim());

  const setParam = React.useCallback(
    (updates: Record<string, string | undefined>, resetPage = true) => {
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
      );
    },
    [setParams],
  );

  React.useEffect(() => {
    if ((params.get("q") ?? "") !== debouncedSearch) setParam({ q: debouncedSearch || undefined });
  }, [debouncedSearch, params, setParam]);

  const min = params.get("min") ?? "";
  const max = params.get("max") ?? "";
  const rangeInvalid = min !== "" && max !== "" && Number(min) > Number(max);
  const query: CandidateListParams = {
    q: params.get("q") || undefined,
    skill: params.get("skill") || undefined,
    status: (params.get("status") as ApplicationStatus) || undefined,
    job_id: toNumber(params.get("job_id")) ?? undefined,
    min_experience: toNumber(min) ?? undefined,
    max_experience: toNumber(max) ?? undefined,
    skip: toNumber(params.get("skip")) ?? 0,
    limit: PAGE_SIZE,
  };
  const candidates = useQuery({
    queryKey: ["candidates", "list", query],
    queryFn: ({ signal }) => candidatesApi.list(query, signal),
    placeholderData: keepPreviousData,
    enabled: !rangeInvalid,
  });
  const jobs = useQuery({ queryKey: ["jobs", "options"], queryFn: () => jobsApi.list({ limit: 100 }), enabled: showFilters });
  const activeFilters = [query.skill, query.status, query.job_id, query.min_experience, query.max_experience].filter((value) => value !== undefined).length;
  const hasQuery = Boolean(query.q) || activeFilters > 0;

  return (
    <>
      <PageHeader
        title="Candidates"
        description={candidates.data ? `${pluralize(candidates.data.total, "candidate")}${hasQuery ? " match your search" : " in your workspace"}` : "Your talent pool"}
        actions={
          <Button asChild>
            <Link to="/candidates/new">
              <Plus aria-hidden="true" /> Add candidate
            </Link>
          </Button>
        }
      />
      <Card>
        <div className="flex flex-col gap-3 border-b p-3 sm:flex-row sm:items-center">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
            <Input type="search" aria-label="Search candidates" placeholder="Search by name, email, or skill" className="pl-8" value={search} onChange={(event) => setSearch(event.target.value)} />
          </div>
          <Button variant="outline" onClick={() => setShowFilters((value) => !value)} aria-expanded={showFilters} aria-controls="candidate-filters">
            <Filter aria-hidden="true" /> Filters{activeFilters > 0 && ` (${activeFilters})`}
          </Button>
        </div>
        {showFilters && (
          <div id="candidate-filters" className="grid gap-3 border-b bg-muted/30 p-3 sm:grid-cols-2 lg:grid-cols-5">
            <FilterField label="Skill" id="filter-skill">
              <Input key={query.skill ?? ""} id="filter-skill" placeholder="e.g. Python" defaultValue={query.skill ?? ""} onBlur={(event) => setParam({ skill: event.target.value.trim() || undefined })} onKeyDown={(event) => event.key === "Enter" && setParam({ skill: event.currentTarget.value.trim() || undefined })} />
            </FilterField>
            <FilterField label="Application status" id="filter-status">
              <NativeSelect id="filter-status" value={query.status ?? ""} onChange={(event) => setParam({ status: event.target.value || undefined })}>
                <option value="">Any status</option>
                {APPLICATION_STATUSES.map((status) => (
                  <option key={status}>{status}</option>
                ))}
              </NativeSelect>
            </FilterField>
            <FilterField label="Applied to job" id="filter-job">
              <NativeSelect id="filter-job" value={query.job_id ?? ""} onChange={(event) => setParam({ job_id: event.target.value || undefined })}>
                <option value="">Any job</option>
                {jobs.data?.items.map((job) => (
                  <option key={job.id} value={job.id}>
                    {job.title}
                    {job.status === "closed" ? " (closed)" : ""}
                  </option>
                ))}
              </NativeSelect>
            </FilterField>
            <FilterField label="Min. years" id="filter-min">
              <Input id="filter-min" type="number" min={0} max={80} step="0.5" inputMode="decimal" value={min} aria-invalid={rangeInvalid} onChange={(event) => setParam({ min: event.target.value || undefined })} />
            </FilterField>
            <FilterField label="Max. years" id="filter-max" error={rangeInvalid ? "Must be at least the minimum" : undefined}>
              <Input id="filter-max" type="number" min={0} max={80} step="0.5" inputMode="decimal" value={max} aria-invalid={rangeInvalid} onChange={(event) => setParam({ max: event.target.value || undefined })} />
            </FilterField>
            {activeFilters > 0 && (
              <div className="sm:col-span-2 lg:col-span-5">
                <Button variant="ghost" size="sm" onClick={() => setParam({ skill: undefined, status: undefined, job_id: undefined, min: undefined, max: undefined })}>
                  <X aria-hidden="true" /> Clear filters
                </Button>
              </div>
            )}
          </div>
        )}

        {candidates.isPending ? (
          <TableSkeleton rows={6} columns={4} />
        ) : candidates.isError ? (
          <ErrorState error={candidates.error} onRetry={() => candidates.refetch()} />
        ) : candidates.data.items.length === 0 ? (
          hasQuery ? (
            <EmptyState icon={Search} title="No candidates match" description="Try a different search term or clear some filters." />
          ) : (
            <EmptyState
              icon={Users}
              title="No candidates yet"
              description="Add candidates with their skills, experience, and education to screen them against your jobs."
              action={
                <Button asChild>
                  <Link to="/candidates/new">Add your first candidate</Link>
                </Button>
              }
            />
          )
        ) : (
          <>
            <Table aria-busy={candidates.isFetching} className={candidates.isPlaceholderData ? "opacity-60" : undefined}>
              <TableHeader>
                <TableRow>
                  <TableHead>Candidate</TableHead>
                  <TableHead className="hidden md:table-cell">Skills</TableHead>
                  <TableHead className="hidden sm:table-cell">Experience</TableHead>
                  <TableHead className="hidden lg:table-cell">Added</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {candidates.data.items.map((candidate) => (
                  <TableRow key={candidate.id} className="cursor-pointer" onClick={() => navigate(`/candidates/${candidate.id}`)}>
                    <TableCell className="max-w-[16rem]">
                      <Link to={`/candidates/${candidate.id}`} className="block truncate font-medium hover:underline" onClick={(event) => event.stopPropagation()}>
                        {candidate.full_name}
                      </Link>
                      <span className="block truncate text-xs text-muted-foreground">{candidate.email}</span>
                    </TableCell>
                    <TableCell className="hidden md:table-cell">
                      <SkillPreview skills={candidate.technical_skills} />
                    </TableCell>
                    <TableCell className="hidden whitespace-nowrap tabular sm:table-cell">{formatYears(candidate.total_experience)}</TableCell>
                    <TableCell className="hidden whitespace-nowrap text-muted-foreground lg:table-cell">{formatDate(candidate.created_at)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <Pagination skip={query.skip ?? 0} limit={PAGE_SIZE} total={candidates.data.total} onChange={(skip) => setParam({ skip: skip ? String(skip) : undefined }, false)} label="candidates" />
          </>
        )}
      </Card>
    </>
  );
}

function FilterField({ label, id, error, children }: { label: string; id: string; error?: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-xs font-medium text-muted-foreground">
        {label}
      </label>
      {children}
      {error && <p className="text-xs font-medium text-destructive">{error}</p>}
    </div>
  );
}

export function SkillPreview({ skills, max = 4 }: { skills: string[]; max?: number }) {
  if (skills.length === 0) return <span className="text-xs text-muted-foreground">No skills recorded</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {skills.slice(0, max).map((skill) => (
        <span key={skill} className="rounded bg-secondary px-1.5 py-0.5 text-xs">
          {skill}
        </span>
      ))}
      {skills.length > max && <span className="px-1 text-xs text-muted-foreground">+{skills.length - max} more</span>}
    </div>
  );
}

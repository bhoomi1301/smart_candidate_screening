import { http, setCsrfToken } from "./client";
import type {
  ActivityFeed,
  AnalyticsFilters,
  Application,
  ApplicationStatus,
  AuditLogEntry,
  AuthResponse,
  Candidate,
  CandidateDetail,
  CandidateInput,
  CandidateListParams,
  DashboardSummary,
  DecisionInput,
  Eligibility,
  Job,
  JobInput,
  JobListParams,
  JobStatus,
  LoginInput,
  Page,
  RankingPage,
  RegisterInput,
  ResumeExtraction,
  ResumeUpload,
  Screening,
  SkillGapSummary,
  StatusHistoryEntry,
  TopApplicants,
  User,
  UserCreateInput,
  Workflow,
} from "./types";

const withCsrf = (response: AuthResponse) => {
  setCsrfToken(response.csrf_token);
  return response;
};

export const authApi = {
  login: (input: LoginInput) => http.post<AuthResponse>("/api/auth/login", input).then(withCsrf),
  register: (input: RegisterInput) => http.post<AuthResponse>("/api/auth/register", input).then(withCsrf),
  me: () => http.get<User>("/api/auth/me"),
  logout: () => http.post<void>("/api/auth/logout").finally(() => setCsrfToken(null)),
};

export const usersApi = {
  list: () => http.get<User[]>("/api/users"),
  create: (input: UserCreateInput) => http.post<User>("/api/users", input),
  setActive: (id: number, isActive: boolean) => http.patch<User>(`/api/users/${id}/active`, undefined, { is_active: isActive }),
};

export const auditApi = {
  list: (params: { actor_id?: number; action?: string; skip?: number; limit?: number }) => http.get<Page<AuditLogEntry>>("/api/audit-logs", params),
};

export const candidatesApi = {
  list: (params: CandidateListParams, signal?: AbortSignal) => http.get<Page<Candidate>>("/api/candidates", { ...params }, signal),
  get: (id: number) => http.get<CandidateDetail>(`/api/candidates/${id}`),
  create: (input: CandidateInput) => http.post<Candidate>("/api/candidates", input),
  update: (id: number, input: CandidateInput) => http.put<Candidate>(`/api/candidates/${id}`, input),
  remove: (id: number) => http.delete(`/api/candidates/${id}`),
  uploadResume: (id: number, file: File) => http.upload<ResumeUpload>(`/api/candidates/${id}/resume`, resumeForm(file)),
  downloadResume: (id: number) => http.blob(`/api/candidates/${id}/resume/file`),
  resumeSuggestions: (id: number) => http.get<ResumeExtraction>(`/api/candidates/${id}/resume/suggestions`),
  removeResume: (id: number) => http.delete(`/api/candidates/${id}/resume`),
};

function resumeForm(file: File): FormData {
  const form = new FormData();
  form.append("file", file, file.name);
  return form;
}

export const resumesApi = {
  /** Validate a PDF and get unverified suggestions without storing it (new-candidate prefill). */
  extract: (file: File) => http.upload<ResumeExtraction>("/api/resumes/extract", resumeForm(file)),
};

export const jobsApi = {
  list: (params: JobListParams) => http.get<Page<Job>>("/api/jobs", { ...params }),
  get: (id: number) => http.get<Job>(`/api/jobs/${id}`),
  create: (input: JobInput) => http.post<Job>("/api/jobs", input),
  update: (id: number, input: JobInput) => http.put<Job>(`/api/jobs/${id}`, input),
  setStatus: (id: number, status: JobStatus) => http.patch<Job>(`/api/jobs/${id}/status`, { status }),
  remove: (id: number) => http.delete(`/api/jobs/${id}`),
  rankings: (id: number, params: { eligibility?: Eligibility; skip?: number; limit?: number }) => http.get<RankingPage>(`/api/jobs/${id}/rankings`, params),
  refreshScreening: (id: number, includeRejected = false) =>
    http.post<{ job_id: number; refreshed: number; include_rejected: boolean }>(`/api/jobs/${id}/screening`, undefined, { include_rejected: includeRejected }),
};

export const applicationsApi = {
  create: (jobId: number, candidateId: number) => http.post<Application>(`/api/jobs/${jobId}/applications`, { candidate_id: candidateId }),
  get: (id: number) => http.get<Application>(`/api/applications/${id}`),
  decide: (id: number, input: DecisionInput) => http.patch<Application>(`/api/applications/${id}`, input),
  history: (id: number) => http.get<StatusHistoryEntry[]>(`/api/applications/${id}/history`),
  workflow: () => http.get<Workflow>("/api/applications/workflow"),
  screening: (id: number) => http.get<Screening>(`/api/applications/${id}/screening`),
  refreshScreening: (id: number) => http.post<Screening>(`/api/applications/${id}/screening`),
  forJob: (jobId: number, params: { status?: ApplicationStatus; skip?: number; limit?: number }) =>
    http.get<Page<Application>>(`/api/jobs/${jobId}/applications`, params),
};

export const analyticsApi = {
  dashboard: (filters: AnalyticsFilters) => http.get<DashboardSummary>("/api/analytics/dashboard", { ...filters }),
  topApplicants: (jobId: number, limit = 5) => http.get<TopApplicants>(`/api/analytics/jobs/${jobId}/top-applicants`, { limit }),
  activity: (limit = 10) => http.get<ActivityFeed>("/api/analytics/activity", { limit }),
  skillGaps: (filters: AnalyticsFilters & { min_applications?: number; limit?: number }) => http.get<SkillGapSummary>("/api/analytics/skill-gaps", { ...filters }),
};

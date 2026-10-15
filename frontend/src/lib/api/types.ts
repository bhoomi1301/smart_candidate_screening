// Shared API types. They mirror the FastAPI Pydantic schemas in backend/app/schemas.
// Decimal fields arrive as strings (e.g. "47.53") to preserve precision.

export type Decimal = string;
export type ISODateTime = string;

export type Role = "admin" | "hr";
export type ApplicationStatus = "Pending" | "Under Review" | "Shortlisted" | "Rejected";
export type JobStatus = "open" | "closed";
export type Eligibility = "eligible" | "not_eligible" | "undetermined";
export type AssessmentStatus = "complete" | "incomplete";

export const APPLICATION_STATUSES: ApplicationStatus[] = ["Pending", "Under Review", "Shortlisted", "Rejected"];

export interface Page<T> {
  items: T[];
  total: number;
  skip: number;
  limit: number;
}

// ---- Auth & users ----------------------------------------------------------

export interface User {
  id: number;
  workspace_id: number;
  full_name: string;
  email: string;
  role: Role;
  is_active: boolean;
  created_at: ISODateTime;
}

export interface AuthResponse {
  user: User;
  workspace_id: number;
  access_expires_in: number;
  refresh_expires_in: number;
  csrf_token: string;
}

export interface LoginInput {
  email: string;
  password: string;
}

export interface RegisterInput {
  workspace_name: string;
  full_name: string;
  email: string;
  password: string;
  password_confirmation: string;
}

export interface UserCreateInput {
  full_name: string;
  email: string;
  password: string;
}

// ---- Candidates ------------------------------------------------------------

export interface Education {
  id: number;
  institution: string | null;
  degree: string;
  field_of_study: string | null;
  graduation_year: number | null;
}

export type EducationInput = Omit<Education, "id">;

export interface Candidate {
  id: number;
  workspace_id: number;
  full_name: string;
  email: string;
  phone: string | null;
  total_experience: Decimal | null;
  technical_skills: string[];
  education: Education[];
  created_at: ISODateTime;
  updated_at: ISODateTime;
}

export interface CandidateInput {
  full_name: string;
  email: string;
  phone: string | null;
  total_experience: number | null;
  technical_skills: string[];
  education: EducationInput[];
}

export interface Resume {
  original_filename: string;
  content_type: string;
  size_bytes: number;
  uploaded_at: ISODateTime;
  page_count: number | null;
  file_available: boolean;
}

export interface TextSuggestion {
  value: string;
  evidence: string;
}

export interface EducationSuggestion {
  degree: string;
  field_of_study: string | null;
  institution: string | null;
  graduation_year: number | null;
  evidence: string;
}

export interface ResumeSuggestions {
  full_name: (TextSuggestion & { confidence: "low" }) | null;
  emails: TextSuggestion[];
  phones: TextSuggestion[];
  skills: TextSuggestion[];
  education: EducationSuggestion[];
  total_experience: { value: number; method: "stated" | "date_ranges"; evidence: string } | null;
}

export interface ResumeExtraction {
  status: "ok" | "no_text" | "no_suggestions" | "failed";
  message: string;
  page_count: number;
  pages_scanned: number;
  text_characters: number;
  truncated: boolean;
  suggestions: ResumeSuggestions;
  notice: string;
}

export interface ResumeUpload {
  resume: Resume;
  extraction: ResumeExtraction;
}

export interface StatusHistoryEvent {
  previous_status: ApplicationStatus | null;
  new_status: ApplicationStatus;
  changed_by: number | null;
  notes: string;
  changed_at: ISODateTime;
}

export interface StatusHistoryEntry extends StatusHistoryEvent {
  id: number;
  application_id: number;
  changed_by_name: string | null;
}

export interface ScreeningResult {
  score: Decimal;
  score_breakdown: ScreeningBreakdown;
  matched_skills: string[];
  missing_mandatory_skills: string[];
  eligibility: Eligibility;
  assessment_status: AssessmentStatus;
  evaluated_at: ISODateTime;
  scoring_version: string;
  is_stale: boolean;
  stale_reason: string | null;
}

export interface CandidateApplication {
  id: number;
  job_id: number;
  job_title: string;
  job_status: JobStatus;
  status: ApplicationStatus;
  current_screening_score: Decimal | null;
  decision_notes: string;
  screening_result: ScreeningResult | null;
  status_history: StatusHistoryEvent[];
  created_at: ISODateTime;
}

export interface CandidateDetail extends Candidate {
  resume: Resume | null;
  applications: CandidateApplication[];
}

export interface CandidateListParams {
  q?: string;
  skill?: string;
  status?: ApplicationStatus;
  job_id?: number;
  min_experience?: number;
  max_experience?: number;
  skip?: number;
  limit?: number;
}

// ---- Jobs ------------------------------------------------------------------

export interface CriterionWeights {
  required_skills: Decimal | number;
  preferred_skills: Decimal | number;
  experience: Decimal | number;
  qualifications: Decimal | number;
}

export interface Qualification {
  id: number;
  name: string;
  is_mandatory: boolean;
  weight: Decimal | null;
}

export interface QualificationInput {
  name: string;
  is_mandatory: boolean;
  weight: number | null;
}

export interface Job {
  id: number;
  workspace_id: number;
  title: string;
  department: string | null;
  description: string;
  required_skills: string[];
  preferred_skills: string[];
  required_skill_weights: Record<string, Decimal>;
  preferred_skill_weights: Record<string, Decimal>;
  minimum_experience: Decimal;
  qualifications: Qualification[];
  criterion_weights: CriterionWeights;
  status: JobStatus;
  application_count: number;
  created_at: ISODateTime;
  updated_at: ISODateTime;
}

export interface JobInput {
  title: string;
  department: string | null;
  description: string;
  required_skills: string[];
  preferred_skills: string[];
  required_skill_weights: Record<string, number>;
  preferred_skill_weights: Record<string, number>;
  minimum_experience: number;
  qualifications: QualificationInput[];
  criterion_weights: { required_skills: number; preferred_skills: number; experience: number; qualifications: number };
}

export interface JobListParams {
  status?: JobStatus;
  q?: string;
  department?: string;
  skip?: number;
  limit?: number;
}

// ---- Applications ----------------------------------------------------------

export interface ApplicationCandidate {
  id: number;
  full_name: string;
  email: string;
  total_experience: Decimal | null;
  technical_skills: string[];
}

export interface Application {
  id: number;
  workspace_id: number;
  candidate_id: number;
  job_id: number;
  status: ApplicationStatus;
  current_screening_score: Decimal | null;
  decision_notes: string;
  created_at: ISODateTime;
  updated_at: ISODateTime;
  screening_result: ScreeningResult | null;
  status_history: StatusHistoryEvent[];
  candidate: ApplicationCandidate;
}

export interface DecisionInput {
  status: ApplicationStatus;
  notes: string;
  expected_status?: ApplicationStatus;
}

export interface Workflow {
  statuses: ApplicationStatus[];
  initial_status: ApplicationStatus;
  terminal_statuses: ApplicationStatus[];
  transitions: { from_status: ApplicationStatus; allowed: ApplicationStatus[] }[];
  rules: string[];
}

// ---- Screening -------------------------------------------------------------

export type ComponentName = "required_skills" | "preferred_skills" | "experience" | "qualifications";
export type ComponentStatus = "evaluated" | "not_applicable" | "missing_data";

export interface BreakdownComponent {
  status: ComponentStatus;
  score: number | null;
  configured_weight: number;
  effective_weight: number;
  points: number;
  matched?: string[];
  missing?: string[];
  candidate_years?: number | null;
  required_years?: number | null;
  difference_years?: number | null;
  meets_requirement?: boolean | null;
  rule?: string;
  evidence?: QualificationEvidence[];
}

export interface QualificationEvidence {
  criterion: string;
  is_mandatory: boolean;
  weight: number | null;
  matched: boolean | null;
  evidence: string | null;
}

export interface ScreeningWarning {
  code: string;
  message: string;
}

export interface ScreeningBreakdown {
  scoring_version: string;
  score: number;
  score_upper_bound: number;
  assessment_status: AssessmentStatus;
  eligibility: Eligibility;
  eligibility_failures: string[];
  undetermined_criteria: string[];
  weights: Record<ComponentName, number>;
  components: Record<ComponentName, BreakdownComponent>;
  matched_skills: string[];
  missing_mandatory_skills: string[];
  preferred_skills_matched: string[];
  preferred_skills_missing: string[];
  experience: { candidate_years: number | null; required_years: number | null; difference_years: number | null; meets_requirement: boolean | null };
  qualification_evidence: QualificationEvidence[];
  warnings: ScreeningWarning[];
  decision_notice: string;
}

export interface Screening extends ScreeningResult {
  application_id: number;
  job_id: number;
  candidate_id: number;
  application_status: ApplicationStatus;
  decision_notice: string;
}

export interface RankedApplication {
  rank: number;
  application_id: number;
  application_status: ApplicationStatus;
  applied_at: ISODateTime;
  score: Decimal | null;
  score_tied: boolean;
  eligibility: Eligibility | null;
  assessment_status: AssessmentStatus | null;
  missing_mandatory_skills: string[];
  is_stale: boolean;
  evaluated_at: ISODateTime | null;
  candidate: ApplicationCandidate;
}

export interface RankingPage extends Page<RankedApplication> {
  job_id: number;
  ordering: string;
  decision_notice: string;
}

// ---- Analytics -------------------------------------------------------------

export interface AnalyticsFilters {
  date_from?: string;
  date_to?: string;
  job_id?: number;
  department?: string;
  job_status?: JobStatus;
}

export interface ScoreCoverage {
  application_count: number;
  scored_count: number;
  complete_count: number;
  incomplete_count: number;
  stale_count: number;
  unscored_count: number;
  average_score: Decimal | null;
  average_complete_score: Decimal | null;
}

export interface JobScoreSummary extends ScoreCoverage {
  job_id: number;
  title: string;
  department: string | null;
  job_status: JobStatus;
}

export interface DashboardSummary {
  generated_at: ISODateTime;
  filters: Record<string, unknown>;
  total_candidates: number;
  active_job_openings: number;
  total_applications: number;
  unique_applicants: number;
  application_statuses: { pending: number; under_review: number; shortlisted: number; rejected: number };
  status_distribution: { status: ApplicationStatus; count: number; percentage: Decimal }[];
  overall_scores: ScoreCoverage;
  average_scores_by_job: JobScoreSummary[];
}

export interface TopApplicants {
  job_id: number;
  job_title: string;
  job_status: JobStatus;
  total_applicants: number;
  items: RankedApplication[];
  ordering: string;
  decision_notice: string;
}

export interface ActivityItem {
  id: number;
  action: string;
  category: "candidate" | "job" | "application" | "screening";
  description: string;
  actor_id: number | null;
  actor_name: string | null;
  resource_type: string;
  resource_id: number | null;
  candidate_name: string | null;
  job_title: string | null;
  created_at: ISODateTime;
}

export interface ActivityFeed {
  items: ActivityItem[];
  total: number;
  limit: number;
}

export interface SkillGapSummary {
  min_applications: number;
  sufficient_data: boolean;
  message: string;
  excluded_without_skill_data: number;
  items: { skill: string; jobs_requiring: number; evaluated_applications: number; missing_count: number; missing_rate: Decimal }[];
}

export interface AuditLogEntry {
  id: number;
  actor_id: number | null;
  actor_name: string | null;
  action: string;
  resource_type: string;
  resource_id: number | null;
  metadata: Record<string, unknown>;
  created_at: ISODateTime;
}

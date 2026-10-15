import { describe, expect, it } from "vitest";
import { candidateSchema, toCandidateInput, type CandidateFormValues } from "@/features/candidates/candidate-form-page";
import { DEFAULT_WEIGHTS, jobSchema, toJobInput, type JobFormValues } from "@/features/jobs/job-form-page";

const candidate = (overrides: Partial<CandidateFormValues> = {}): CandidateFormValues => ({
  full_name: "Ada Lovelace",
  email: "ada@example.com",
  phone: "",
  total_experience: "",
  technical_skills: ["Python"],
  education: [],
  ...overrides,
});

const job = (overrides: Partial<JobFormValues> = {}): JobFormValues => ({
  title: "Backend Engineer",
  department: "",
  description: "",
  required_skills: ["Python", "SQL"],
  preferred_skills: [],
  minimum_experience: "3",
  qualifications: [],
  criterion_weights: { ...DEFAULT_WEIGHTS },
  use_skill_weights: false,
  required_skill_weights: {},
  preferred_skill_weights: {},
  ...overrides,
});

const issues = (result: { success: boolean; error?: { issues: { path: (string | number)[]; message: string }[] } }) =>
  result.success ? [] : result.error!.issues.map((issue) => `${issue.path.join(".")}: ${issue.message}`);

describe("candidate form schema (mirrors the API)", () => {
  it("accepts a valid candidate and converts blanks to null", () => {
    const values = candidate({ phone: " +1 (555) 010-2030 ", total_experience: "4.5", education: [{ degree: "BSc", field_of_study: "", institution: "", graduation_year: "2020" }] });
    expect(issues(candidateSchema.safeParse(values))).toEqual([]);
    expect(toCandidateInput(values)).toEqual({
      full_name: "Ada Lovelace",
      email: "ada@example.com",
      phone: "+1 (555) 010-2030",
      total_experience: 4.5,
      technical_skills: ["Python"],
      education: [{ degree: "BSc", field_of_study: null, institution: null, graduation_year: 2020 }],
    });
    expect(toCandidateInput(candidate()).total_experience).toBeNull();
  });

  it.each([
    [{ full_name: " A " }, "full_name"],
    [{ email: "not-an-email" }, "email"],
    [{ phone: "call me" }, "phone"],
    [{ phone: "12345" }, "phone"],
    [{ total_experience: "81" }, "total_experience"],
    [{ total_experience: "2.555" }, "total_experience"],
    [{ education: [{ degree: "", field_of_study: "", institution: "", graduation_year: "" }] }, "education.0.degree"],
    [{ education: [{ degree: "BSc", field_of_study: "", institution: "", graduation_year: "1800" }] }, "education.0.graduation_year"],
  ])("rejects %j", (override, path) => {
    expect(issues(candidateSchema.safeParse(candidate(override as Partial<CandidateFormValues>))).some((issue) => issue.startsWith(`${path}:`))).toBe(true);
  });
});

describe("job form schema (mirrors the API)", () => {
  it("accepts the default 50/20/20/10 weights", () => {
    expect(issues(jobSchema.safeParse(job()))).toEqual([]);
  });

  it("requires weights to total exactly 100 and required skills above 0", () => {
    expect(issues(jobSchema.safeParse(job({ criterion_weights: { ...DEFAULT_WEIGHTS, qualifications: "20" } })))).toContain("criterion_weights._total: Weights must total 100 (currently 110)");
    expect(issues(jobSchema.safeParse(job({ criterion_weights: { required_skills: "0", preferred_skills: "40", experience: "40", qualifications: "20" } })))).toContain(
      "criterion_weights.required_skills: Must be greater than 0",
    );
  });

  it("rejects missing required skills, overlaps, and duplicate qualifications", () => {
    expect(issues(jobSchema.safeParse(job({ required_skills: [] })))).toContain("required_skills: Add at least one required skill");
    expect(issues(jobSchema.safeParse(job({ preferred_skills: ["python"] })))).toContain("preferred_skills: Already required: python");
    const duplicated = job({ qualifications: [{ name: "BSc", is_mandatory: true, weight: "" }, { name: "bsc", is_mandatory: false, weight: "" }] });
    expect(issues(jobSchema.safeParse(duplicated))).toContain("qualifications.1.name: Duplicate qualification");
  });

  it("enforces all-or-none qualification weights totalling 100", () => {
    const partial = job({ qualifications: [{ name: "BSc", is_mandatory: true, weight: "100" }, { name: "AWS", is_mandatory: false, weight: "" }] });
    expect(issues(jobSchema.safeParse(partial))).toContain("qualifications._weights: Set a weight for every qualification, or for none");
    const wrongTotal = job({ qualifications: [{ name: "BSc", is_mandatory: true, weight: "30" }, { name: "AWS", is_mandatory: false, weight: "30" }] });
    expect(issues(jobSchema.safeParse(wrongTotal))).toContain("qualifications._weights: Qualification weights must total 100 (currently 60)");
  });

  it("validates per-skill weights, including skill names with dots", () => {
    const values = job({ required_skills: ["Python", "node.js"], use_skill_weights: true, required_skill_weights: { Python: "70", "node.js": "20" } });
    expect(issues(jobSchema.safeParse(values))).toContain("required_skill_weights._total: Must total 100 (currently 90)");
    const fixed = { ...values, required_skill_weights: { Python: "70", "node.js": "30" } };
    expect(issues(jobSchema.safeParse(fixed))).toEqual([]);
    expect(toJobInput(fixed).required_skill_weights).toEqual({ Python: 70, "node.js": 30 });
    expect(toJobInput({ ...fixed, use_skill_weights: false }).required_skill_weights).toEqual({});
  });

  it("builds the API payload with numbers and nulls", () => {
    const input = toJobInput(job({ department: "  ", qualifications: [{ name: " BSc ", is_mandatory: true, weight: "" }] }));
    expect(input).toMatchObject({
      department: null,
      minimum_experience: 3,
      qualifications: [{ name: "BSc", is_mandatory: true, weight: null }],
      criterion_weights: { required_skills: 50, preferred_skills: 20, experience: 20, qualifications: 10 },
    });
  });
});

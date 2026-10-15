import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { EligibilityBadge, StatusBadge } from "@/components/common/badges";
import type { ScreeningBreakdown } from "@/lib/api/types";
import { ComponentBreakdown, EligibilityPanel, PointsBar, ScoreExplanation, ScoreRing } from "./screening-components";

// A real engine output (backend tests: missing SQL and Kubernetes, experience 6 of 4, qualification matched).
const breakdown: ScreeningBreakdown = {
  scoring_version: "screening-v2",
  score: 66.67,
  score_upper_bound: 66.67,
  assessment_status: "complete",
  eligibility: "not_eligible",
  eligibility_failures: ["required_skills"],
  undetermined_criteria: [],
  weights: { required_skills: 50, preferred_skills: 20, experience: 20, qualifications: 10 },
  components: {
    required_skills: { status: "evaluated", score: 33.33, configured_weight: 50, effective_weight: 50, points: 16.67, matched: ["python"], missing: ["kubernetes", "sql"] },
    preferred_skills: { status: "evaluated", score: 100, configured_weight: 20, effective_weight: 20, points: 20, matched: ["aws", "docker"], missing: [] },
    experience: { status: "evaluated", score: 100, configured_weight: 20, effective_weight: 20, points: 20, candidate_years: 6, required_years: 4, difference_years: 2, meets_requirement: true },
    qualifications: { status: "evaluated", score: 100, configured_weight: 10, effective_weight: 10, points: 10, evidence: [] },
  },
  matched_skills: ["aws", "docker", "python"],
  missing_mandatory_skills: ["kubernetes", "sql"],
  preferred_skills_matched: ["aws", "docker"],
  preferred_skills_missing: [],
  experience: { candidate_years: 6, required_years: 4, difference_years: 2, meets_requirement: true },
  qualification_evidence: [{ criterion: "BSc Computer Science", is_mandatory: true, weight: null, matched: true, evidence: "B.Sc. Computer Science" }],
  warnings: [{ code: "missing_mandatory_skills", message: "Missing required skills: kubernetes, sql" }],
  decision_notice: "This score ranks applicants to support HR review. It does not make hiring decisions; application status changes are always made by a person.",
};

describe("screening components", () => {
  it("labels the score ring for assistive technology and explains incomplete ranges", () => {
    const { rerender } = render(<ScoreRing score={66.67} />);
    expect(screen.getByRole("figure", { name: "Score 66.67 out of 100, Partial match" })).toBeInTheDocument();
    rerender(<ScoreRing score={35} upperBound={55} />);
    expect(screen.getByText("Could reach 55 once missing data is added")).toBeInTheDocument();
    expect(screen.getByText("Weak match")).toBeInTheDocument();
  });

  it("shows matched and missing skills with text, not colour alone", () => {
    render(<ComponentBreakdown breakdown={breakdown} />);
    const python = screen.getByText("python").closest("li")!;
    expect(within(python).getByText("(matched)")).toBeInTheDocument();
    expect(within(screen.getByText("sql").closest("li")!).getByText("(missing)")).toBeInTheDocument();
    expect(screen.getByText(/6 of 4 required years \(\+2; extra years earn no extra points\)/)).toBeInTheDocument();
    expect(screen.getByText(/matched by “B.Sc. Computer Science”/)).toBeInTheDocument();
    expect(screen.getAllByText("+20")).toHaveLength(2);
  });

  it("states eligibility in words and lists warnings", () => {
    render(<EligibilityPanel breakdown={breakdown} />);
    expect(screen.getByText("Not eligible")).toBeInTheDocument();
    expect(within(screen.getByRole("list", { name: "Screening warnings" })).getByText("Missing required skills: kubernetes, sql")).toBeInTheDocument();
  });

  it("describes the points bar and the arithmetic behind the score", () => {
    render(
      <>
        <PointsBar breakdown={breakdown} />
        <ScoreExplanation breakdown={breakdown} />
      </>,
    );
    expect(screen.getByRole("img", { name: /Required skills 16.67 of 50 points; Preferred skills 20 of 20 points/ })).toBeInTheDocument();
    expect(screen.getByText("16.67 + 20 + 20 + 10 = 66.67")).toBeInTheDocument();
    expect(screen.getByText(/does not make hiring decisions/)).toBeInTheDocument();
  });

  it("marks redistributed and missing-data components explicitly", () => {
    const partial: ScreeningBreakdown = {
      ...breakdown,
      assessment_status: "incomplete",
      components: {
        ...breakdown.components,
        preferred_skills: { status: "not_applicable", score: null, configured_weight: 20, effective_weight: 0, points: 0, matched: [], missing: [] },
        experience: { status: "missing_data", score: 0, configured_weight: 20, effective_weight: 25, points: 0 },
      },
      experience: { candidate_years: null, required_years: 4, difference_years: null, meets_requirement: null },
    };
    render(<ComponentBreakdown breakdown={partial} />);
    expect(screen.getByText("Not applicable")).toBeInTheDocument();
    expect(screen.getByText("Missing data")).toBeInTheDocument();
    expect(screen.getByText("Candidate experience is not recorded (job requires 4 years).")).toBeInTheDocument();
    expect(screen.getByText(/Weight 20% → 25% after redistribution/)).toBeInTheDocument();
  });

  it("pairs status and eligibility colours with words", () => {
    render(
      <>
        <StatusBadge status="Shortlisted" />
        <EligibilityBadge eligibility="undetermined" />
        <EligibilityBadge eligibility={null} />
      </>,
    );
    expect(screen.getByText("Shortlisted")).toBeInTheDocument();
    expect(screen.getByText("Undetermined")).toHaveAttribute("title", "Candidate data is missing for a mandatory check");
    expect(screen.getByText("Not screened")).toBeInTheDocument();
  });
});

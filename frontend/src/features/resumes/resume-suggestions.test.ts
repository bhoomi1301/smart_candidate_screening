import { describe, expect, it } from "vitest";
import type { CandidateFormValues } from "@/features/candidates/candidate-form-page";
import type { ResumeSuggestions } from "@/lib/api/types";
import { applySuggestions, defaultSelection, resumeFileProblem } from "./resume-suggestions";

const suggestions: ResumeSuggestions = {
  full_name: { value: "Priya Natarajan", evidence: "Priya Natarajan", confidence: "low" },
  emails: [{ value: "priya.n@example.com", evidence: "priya.n@example.com" }],
  phones: [{ value: "+1 (555) 014-2233", evidence: "+1 (555) 014-2233" }],
  skills: [
    { value: "Python", evidence: "Skills: Python, Docker" },
    { value: "Docker", evidence: "Skills: Python, Docker" },
  ],
  education: [
    { degree: "BSc", field_of_study: "Computer Science", institution: "University of Toronto", graduation_year: 2017, evidence: "B.Sc. in Computer Science" },
    { degree: "MSc", field_of_study: null, institution: null, graduation_year: null, evidence: "Master of Science" },
  ],
  total_experience: { value: 6, method: "stated", evidence: "6+ years of experience" },
};

const empty: CandidateFormValues = { full_name: "", email: "", phone: "", total_experience: "", technical_skills: [], education: [] };
const existing: CandidateFormValues = {
  full_name: "Priya N.",
  email: "priya@company.example",
  phone: "",
  total_experience: "5",
  technical_skills: ["python", "SQL"],
  education: [{ degree: "BSc", field_of_study: "Computer Science", institution: "", graduation_year: "" }],
};

describe("resume suggestion review", () => {
  it("pre-selects everything for an empty form", () => {
    const merged = applySuggestions(empty, defaultSelection(empty, suggestions));
    expect(merged).toEqual({
      full_name: "Priya Natarajan",
      email: "priya.n@example.com",
      phone: "+1 (555) 014-2233",
      total_experience: "6",
      technical_skills: ["Python", "Docker"],
      education: [
        { degree: "BSc", field_of_study: "Computer Science", institution: "University of Toronto", graduation_year: "2017" },
        { degree: "MSc", field_of_study: "", institution: "", graduation_year: "" },
      ],
    });
  });

  it("keeps existing values by default and only adds what is new", () => {
    const selection = defaultSelection(existing, suggestions);
    expect(selection.fullName.use).toBe(false);
    expect(selection.email).toBeNull();
    expect(selection.experience.use).toBe(false);
    expect(selection.skills).toEqual(["Docker"]); // "Python" is already listed (case-insensitive)
    expect(selection.education.map((item) => item.use)).toEqual([false, true]);
    const merged = applySuggestions(existing, selection);
    expect(merged.full_name).toBe("Priya N.");
    expect(merged.email).toBe("priya@company.example");
    expect(merged.phone).toBe("+1 (555) 014-2233");
    expect(merged.total_experience).toBe("5");
    expect(merged.technical_skills).toEqual(["python", "SQL", "Docker"]);
    expect(merged.education).toHaveLength(2);
  });

  it("applies HR's edits and choices instead of the raw suggestion", () => {
    const selection = defaultSelection(existing, suggestions);
    const merged = applySuggestions(existing, {
      ...selection,
      fullName: { use: true, value: " Priya Natarajan-Rao " },
      email: "priya.n@example.com",
      experience: { use: true, value: "5.5" },
      skills: [],
      education: selection.education.map((item) => ({ ...item, use: false })),
    });
    expect(merged).toMatchObject({ full_name: "Priya Natarajan-Rao", email: "priya.n@example.com", total_experience: "5.5", technical_skills: ["python", "SQL"] });
    expect(merged.education).toEqual(existing.education);
  });

  it("checks files before upload (the server still validates content)", () => {
    const file = (name: string, type: string, size = 100) => new File([new Uint8Array(size)], name, { type });
    expect(resumeFileProblem(file("cv.pdf", "application/pdf"))).toBeNull();
    expect(resumeFileProblem(file("cv.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"))).toBe("Choose a PDF file.");
    expect(resumeFileProblem(file("cv.pdf", "image/png"))).toBe("Choose a PDF file.");
    expect(resumeFileProblem(file("cv.pdf", "application/pdf", 0))).toBe("The file is empty.");
    expect(resumeFileProblem(file("cv.pdf", "application/pdf", 5 * 1024 * 1024 + 1))).toBe("The PDF must be 5 MB or smaller.");
  });
});

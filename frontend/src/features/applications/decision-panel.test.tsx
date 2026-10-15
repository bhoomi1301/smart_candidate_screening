import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Field } from "@/components/common/form";
import { Input } from "@/components/ui/input";
import { ApiError } from "@/lib/api/client";
import type { Application } from "@/lib/api/types";

const decide = vi.fn();
vi.mock("@/lib/api/endpoints", () => ({
  applicationsApi: {
    workflow: async () => ({
      statuses: ["Pending", "Under Review", "Shortlisted", "Rejected"],
      initial_status: "Pending",
      terminal_statuses: ["Rejected"],
      transitions: [
        { from_status: "Pending", allowed: ["Under Review", "Rejected"] },
        { from_status: "Under Review", allowed: ["Shortlisted", "Rejected"] },
        { from_status: "Shortlisted", allowed: ["Under Review", "Rejected"] },
        { from_status: "Rejected", allowed: [] },
      ],
      rules: [],
    }),
    decide: (...args: unknown[]) => decide(...args),
  },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const { DecisionPanel } = await import("./application-page");

const application = (status: Application["status"]): Application => ({
  id: 9,
  workspace_id: 1,
  candidate_id: 3,
  job_id: 2,
  status,
  current_screening_score: "66.67",
  decision_notes: "",
  created_at: "2026-10-15T05:58:00Z",
  updated_at: "2026-10-15T05:58:00Z",
  screening_result: null,
  status_history: [],
  candidate: { id: 3, full_name: "Priya Natarajan", email: "priya@example.com", total_experience: "6.00", technical_skills: [] },
});

function renderPanel(status: Application["status"]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <DecisionPanel application={application(status)} />
    </QueryClientProvider>,
  );
}

describe("DecisionPanel", () => {
  it("offers only the transitions the workflow allows", async () => {
    renderPanel("Pending");
    expect(await screen.findByRole("radio", { name: /Move to Under Review/ })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /Move to Rejected/ })).toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: /Move to Shortlisted/ })).not.toBeInTheDocument();
  });

  it("requires an explanatory note before rejecting and sends expected_status", async () => {
    const user = userEvent.setup();
    decide.mockResolvedValue({ ...application("Rejected") });
    renderPanel("Pending");
    await user.click(await screen.findByRole("radio", { name: /Move to Rejected/ }));
    await user.type(screen.getByLabelText(/Reason for rejection/), "too short");
    await user.click(screen.getByRole("button", { name: "Reject application" }));
    expect(screen.getByText("Explain the rejection in at least 10 characters (9/10).")).toBeInTheDocument();
    expect(decide).not.toHaveBeenCalled();

    await user.type(screen.getByLabelText(/Reason for rejection/), " — lacks SQL");
    await user.click(screen.getByRole("button", { name: "Reject application" }));
    expect(decide).toHaveBeenCalledWith(9, { status: "Rejected", notes: "too short — lacks SQL", expected_status: "Pending" });
  });

  it("explains a conflict from another reviewer and keeps the note", async () => {
    const user = userEvent.setup();
    decide.mockRejectedValue(new ApiError(409, "conflict", "Application is now Shortlisted, not Pending; reload before deciding"));
    renderPanel("Pending");
    await user.click(await screen.findByRole("radio", { name: /Move to Under Review/ }));
    await user.type(screen.getByLabelText(/Decision note/), "Looks promising");
    await user.click(screen.getByRole("button", { name: "Move to Under Review" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Application is now Shortlisted, not Pending; reload before deciding. The latest status and history are now shown; your note was kept.");
    expect(screen.getByLabelText(/Decision note/)).toHaveValue("Looks promising");
  });

  it("explains that Rejected is final but still allows notes", async () => {
    renderPanel("Rejected");
    expect(await screen.findByText(/Rejected is final/)).toBeInTheDocument();
    expect(screen.getAllByRole("radio")).toHaveLength(1);
    expect(screen.getByRole("radio", { name: /Add a note only/ })).toBeInTheDocument();
  });
});

describe("Field", () => {
  it("wires the label, hint, and error to the control", () => {
    render(
      <Field id="email" label="Email" hint="Must be unique" error="Enter a valid email address" required>
        {(props) => <Input {...props} />}
      </Field>,
    );
    const input = screen.getByLabelText(/Email/);
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAccessibleDescription("Enter a valid email address");
  });
});

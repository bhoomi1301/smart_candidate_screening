// Status and decision badges always pair colour with an icon and text, so meaning never depends on colour alone.
import { AlertTriangle, Ban, CheckCircle2, CircleDashed, CircleDot, Clock, HelpCircle, Lock, Search, Star, XCircle } from "lucide-react";
import { Badge, type BadgeProps } from "@/components/ui/primitives";
import type { ApplicationStatus, AssessmentStatus, Eligibility, JobStatus } from "@/lib/api/types";

const statusStyles: Record<ApplicationStatus, { variant: BadgeProps["variant"]; icon: React.ElementType }> = {
  Pending: { variant: "neutral", icon: Clock },
  "Under Review": { variant: "primary", icon: Search },
  Shortlisted: { variant: "success", icon: Star },
  Rejected: { variant: "destructive", icon: Ban },
};

export function StatusBadge({ status }: { status: ApplicationStatus }) {
  const { variant, icon: Icon } = statusStyles[status];
  return (
    <Badge variant={variant}>
      <Icon aria-hidden="true" />
      {status}
    </Badge>
  );
}

const eligibilityStyles: Record<Eligibility, { variant: BadgeProps["variant"]; icon: React.ElementType; label: string; description: string }> = {
  eligible: { variant: "success", icon: CheckCircle2, label: "Eligible", description: "Meets every mandatory requirement" },
  not_eligible: { variant: "destructive", icon: XCircle, label: "Not eligible", description: "Misses at least one mandatory requirement" },
  undetermined: { variant: "warning", icon: HelpCircle, label: "Undetermined", description: "Candidate data is missing for a mandatory check" },
};

export const eligibilityLabel = (value: Eligibility) => eligibilityStyles[value].label;
export const eligibilityDescription = (value: Eligibility) => eligibilityStyles[value].description;

export function EligibilityBadge({ eligibility }: { eligibility: Eligibility | null }) {
  if (!eligibility) return <Badge variant="outline">Not screened</Badge>;
  const { variant, icon: Icon, label, description } = eligibilityStyles[eligibility];
  return (
    <Badge variant={variant} title={description}>
      <Icon aria-hidden="true" />
      {label}
    </Badge>
  );
}

export function AssessmentBadge({ status }: { status: AssessmentStatus | null }) {
  if (status !== "incomplete") return null;
  return (
    <Badge variant="warning" title="Some candidate information is missing; the score is a lower bound">
      <CircleDashed aria-hidden="true" />
      Incomplete data
    </Badge>
  );
}

export function StaleBadge({ stale }: { stale: boolean }) {
  if (!stale) return null;
  return (
    <Badge variant="warning" title="Scored against older data; refresh to recalculate">
      <AlertTriangle aria-hidden="true" />
      Out of date
    </Badge>
  );
}

export function JobStatusBadge({ status }: { status: JobStatus }) {
  return status === "open" ? (
    <Badge variant="success">
      <CircleDot aria-hidden="true" />
      Open
    </Badge>
  ) : (
    <Badge variant="neutral">
      <Lock aria-hidden="true" />
      Closed
    </Badge>
  );
}

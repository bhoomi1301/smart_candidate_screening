// Screening visualisations. Every state is conveyed by text and icons as well as colour.
import { AlertTriangle, Ban, Check, CircleDashed, Info, Minus, X } from "lucide-react";
import * as React from "react";
import { EligibilityBadge, eligibilityDescription } from "@/components/common/badges";
import { Badge } from "@/components/ui/primitives";
import type { BreakdownComponent, ComponentName, ComponentStatus, Eligibility, QualificationEvidence, ScreeningBreakdown } from "@/lib/api/types";
import { cn, formatScore } from "@/lib/utils";

export const COMPONENT_ORDER: ComponentName[] = ["required_skills", "preferred_skills", "experience", "qualifications"];
export const COMPONENT_LABELS: Record<ComponentName, string> = {
  required_skills: "Required skills",
  preferred_skills: "Preferred skills",
  experience: "Experience",
  qualifications: "Qualifications",
};
// Distinct hues plus a text legend; colour is never the only cue.
const COMPONENT_COLORS: Record<ComponentName, string> = {
  required_skills: "bg-indigo-600",
  preferred_skills: "bg-sky-500",
  experience: "bg-teal-600",
  qualifications: "bg-amber-500",
};

export function scoreTone(score: number | null): { label: string; text: string; stroke: string } {
  if (score === null) return { label: "Not scored", text: "text-muted-foreground", stroke: "stroke-muted-foreground" };
  if (score >= 75) return { label: "Strong match", text: "text-success", stroke: "stroke-success" };
  if (score >= 50) return { label: "Partial match", text: "text-accent-foreground", stroke: "stroke-primary" };
  return { label: "Weak match", text: "text-destructive", stroke: "stroke-destructive" };
}

export function ScoreRing({ score, upperBound, size = 128 }: { score: number | null; upperBound?: number | null; size?: number }) {
  const radius = 52;
  const circumference = 2 * Math.PI * radius;
  const value = Math.max(0, Math.min(100, score ?? 0));
  const tone = scoreTone(score);
  const showRange = upperBound !== undefined && upperBound !== null && score !== null && upperBound > score;
  return (
    <figure className="flex flex-col items-center gap-1" aria-label={score === null ? "Not scored" : `Score ${formatScore(score)} out of 100, ${tone.label}`}>
      <div className="relative" style={{ width: size, height: size }}>
        <svg viewBox="0 0 120 120" width={size} height={size} aria-hidden="true" className="-rotate-90">
          <circle cx="60" cy="60" r={radius} fill="none" strokeWidth="10" className="stroke-muted" />
          {showRange && (
            <circle cx="60" cy="60" r={radius} fill="none" strokeWidth="10" strokeDasharray={`${(upperBound! / 100) * circumference} ${circumference}`} className="stroke-warning/30" strokeLinecap="round" />
          )}
          <circle cx="60" cy="60" r={radius} fill="none" strokeWidth="10" strokeDasharray={`${(value / 100) * circumference} ${circumference}`} className={tone.stroke} strokeLinecap="round" />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center" aria-hidden="true">
          <span className="text-3xl font-semibold tabular">{score === null ? "—" : formatScore(score)}</span>
          <span className="text-xs text-muted-foreground">out of 100</span>
        </div>
      </div>
      <figcaption className={cn("text-sm font-medium", tone.text)}>{tone.label}</figcaption>
      {showRange && <p className="text-center text-xs text-muted-foreground">Could reach {formatScore(upperBound)} once missing data is added</p>}
    </figure>
  );
}

export function SkillChip({ name, state }: { name: string; state: "matched" | "missing" | "unknown" }) {
  const styles = {
    matched: { className: "border-success/30 bg-success-soft text-success", icon: Check, label: "matched" },
    missing: { className: "border-destructive/30 bg-destructive-soft text-destructive", icon: X, label: "missing" },
    unknown: { className: "border-warning/30 bg-warning-soft text-warning", icon: CircleDashed, label: "unknown, no skill data" },
  }[state];
  const Icon = styles.icon;
  return (
    <li className={cn("inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-medium", styles.className)}>
      <Icon className="size-3.5" aria-hidden="true" />
      {name}
      <span className="sr-only">({styles.label})</span>
    </li>
  );
}

function SkillChipList({ matched = [], missing = [], unknown = false, emptyText }: { matched?: string[]; missing?: string[]; unknown?: boolean; emptyText: string }) {
  if (matched.length + missing.length === 0) return <p className="text-xs text-muted-foreground">{emptyText}</p>;
  return (
    <ul className="flex flex-wrap gap-1.5">
      {matched.map((skill) => (
        <SkillChip key={skill} name={skill} state="matched" />
      ))}
      {missing.map((skill) => (
        <SkillChip key={skill} name={skill} state={unknown ? "unknown" : "missing"} />
      ))}
    </ul>
  );
}

const statusMeta: Record<ComponentStatus, { label: string; variant: "neutral" | "warning" | "outline"; icon: React.ElementType }> = {
  evaluated: { label: "Evaluated", variant: "outline", icon: Check },
  not_applicable: { label: "Not applicable", variant: "neutral", icon: Minus },
  missing_data: { label: "Missing data", variant: "warning", icon: CircleDashed },
};

/** Horizontal bar of the points each component contributed, with a text legend. */
export function PointsBar({ breakdown, compact = false }: { breakdown: ScreeningBreakdown; compact?: boolean }) {
  const parts = COMPONENT_ORDER.map((name) => ({ name, component: breakdown.components[name] })).filter(({ component }) => component.status !== "not_applicable");
  return (
    <div>
      <div className="flex h-2.5 w-full overflow-hidden rounded-full bg-muted" role="img" aria-label={parts.map(({ name, component }) => `${COMPONENT_LABELS[name]} ${formatScore(component.points)} of ${formatScore(component.effective_weight)} points`).join("; ")}>
        {parts.map(({ name, component }) => (
          <div key={name} className={COMPONENT_COLORS[name]} style={{ width: `${component.points}%` }} />
        ))}
      </div>
      {!compact && (
        <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
          {parts.map(({ name, component }) => (
            <li key={name} className="flex items-center gap-1.5">
              <span className={cn("size-2 rounded-sm", COMPONENT_COLORS[name])} aria-hidden="true" />
              {COMPONENT_LABELS[name]} <span className="font-medium text-foreground tabular">{formatScore(component.points)}</span>/{formatScore(component.effective_weight)}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ComponentCard({ name, component, breakdown }: { name: ComponentName; component: BreakdownComponent; breakdown: ScreeningBreakdown }) {
  const meta = statusMeta[component.status];
  const StatusIcon = meta.icon;
  const applicable = component.status !== "not_applicable";
  return (
    <div className={cn("rounded-lg border p-3", !applicable && "bg-muted/40")}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className={cn("size-2.5 rounded-sm", applicable ? COMPONENT_COLORS[name] : "bg-muted-foreground/40")} aria-hidden="true" />
          <h4 className="text-sm font-semibold">{COMPONENT_LABELS[name]}</h4>
          <Badge variant={meta.variant}>
            <StatusIcon aria-hidden="true" />
            {meta.label}
          </Badge>
        </div>
        {applicable && (
          <p className="text-sm tabular">
            <span className="font-semibold">+{formatScore(component.points)}</span>
            <span className="text-muted-foreground"> / {formatScore(component.effective_weight)} pts</span>
          </p>
        )}
      </div>
      {applicable && (
        <div className="mt-2 flex items-center gap-3">
          <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted" aria-hidden="true">
            <div className={cn("h-full rounded-full", COMPONENT_COLORS[name])} style={{ width: `${component.score ?? 0}%` }} />
          </div>
          <span className="shrink-0 whitespace-nowrap text-right text-xs text-muted-foreground tabular">{formatScore(component.score)}% achieved</span>
        </div>
      )}
      <p className="mt-1.5 text-xs text-muted-foreground">
        Weight {formatScore(component.configured_weight)}%
        {applicable && component.effective_weight !== component.configured_weight && ` → ${formatScore(component.effective_weight)}% after redistribution`}
        {!applicable && " → shared with the other components (no job criteria)"}
      </p>
      <div className="mt-3">
        {name === "required_skills" && (
          <SkillChipList matched={component.matched} missing={component.missing} unknown={component.status === "missing_data"} emptyText="No required skills configured." />
        )}
        {name === "preferred_skills" && (
          <SkillChipList matched={component.matched} missing={component.missing} unknown={component.status === "missing_data"} emptyText="This job has no preferred skills." />
        )}
        {name === "experience" && <ExperienceDetail breakdown={breakdown} status={component.status} />}
        {name === "qualifications" && <QualificationDetail evidence={breakdown.qualification_evidence} />}
      </div>
    </div>
  );
}

function ExperienceDetail({ breakdown, status }: { breakdown: ScreeningBreakdown; status: ComponentStatus }) {
  const { candidate_years: years, required_years: required, difference_years: difference, meets_requirement: meets } = breakdown.experience;
  if (status === "not_applicable") return <p className="text-xs text-muted-foreground">No minimum experience required{years !== null ? `; candidate has ${formatScore(years)} years.` : "."}</p>;
  if (status === "missing_data") return <p className="text-xs text-warning">Candidate experience is not recorded (job requires {formatScore(required)} years).</p>;
  return (
    <p className="flex items-start gap-1.5 text-xs">
      {meets ? <Check className="mt-px size-3.5 shrink-0 text-success" aria-hidden="true" /> : <X className="mt-px size-3.5 shrink-0 text-destructive" aria-hidden="true" />}
      <span>
        {formatScore(years)} of {formatScore(required)} required years
        {difference !== null && difference > 0 && ` (+${formatScore(difference)}; extra years earn no extra points)`}
        {difference !== null && difference < 0 && ` (${formatScore(Math.abs(difference))} short; scored proportionally)`}.
      </span>
    </p>
  );
}

function QualificationDetail({ evidence }: { evidence: QualificationEvidence[] }) {
  if (evidence.length === 0) return <p className="text-xs text-muted-foreground">This job lists no qualifications.</p>;
  return (
    <ul className="space-y-1.5">
      {evidence.map((item) => {
        const Icon = item.matched === true ? Check : item.matched === false ? X : CircleDashed;
        const color = item.matched === true ? "text-success" : item.matched === false ? "text-destructive" : "text-warning";
        return (
          <li key={item.criterion} className="flex items-start gap-1.5 text-xs">
            <Icon className={cn("mt-px size-3.5 shrink-0", color)} aria-hidden="true" />
            <span>
              <span className="font-medium">{item.criterion}</span>
              <span className="text-muted-foreground">
                {" "}
                · {item.is_mandatory ? "mandatory" : "optional"}
                {item.weight !== null && ` · weight ${formatScore(item.weight)}`}
                {" · "}
                {item.matched === true ? `matched by “${item.evidence}”` : item.matched === false ? "not found in candidate education" : "unknown (no education recorded)"}
              </span>
            </span>
          </li>
        );
      })}
    </ul>
  );
}

export function EligibilityPanel({ breakdown }: { breakdown: ScreeningBreakdown }) {
  const icons: Record<string, React.ElementType> = {
    missing_mandatory_skills: Ban,
    below_minimum_experience: Ban,
    missing_mandatory_qualifications: Ban,
    weights_redistributed: Info,
  };
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <EligibilityBadge eligibility={breakdown.eligibility} />
        <span className="text-sm text-muted-foreground">{eligibilityDescription(breakdown.eligibility as Eligibility)}.</span>
      </div>
      {breakdown.warnings.length > 0 && (
        <ul className="space-y-2" aria-label="Screening warnings">
          {breakdown.warnings.map((warning) => {
            const Icon = icons[warning.code] ?? AlertTriangle;
            const info = warning.code === "weights_redistributed";
            return (
              <li key={warning.code} className={cn("flex items-start gap-2 rounded-md border px-3 py-2 text-sm", info ? "bg-muted/50" : warning.code.startsWith("missing_") && warning.code.endsWith("_data") ? "border-warning/30 bg-warning-soft" : "border-destructive/25 bg-destructive-soft")}>
                <Icon className={cn("mt-0.5 size-4 shrink-0", info ? "text-muted-foreground" : warning.code.endsWith("_data") ? "text-warning" : "text-destructive")} aria-hidden="true" />
                <span>{warning.message}</span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

export function ScoreExplanation({ breakdown }: { breakdown: ScreeningBreakdown }) {
  const parts = COMPONENT_ORDER.filter((name) => breakdown.components[name].status !== "not_applicable");
  return (
    <div className="space-y-2 text-sm text-muted-foreground">
      <p>
        The score is the sum of points from each component. A component earns <em>effective weight × its achievement</em>. Default weights are 50% required skills, 20% preferred skills, 20% experience, and
        10% qualifications; a component the job doesn’t use has its weight shared proportionally among the others.
      </p>
      <p className="rounded-md bg-muted px-3 py-2 font-mono text-xs text-foreground">
        {parts.map((name) => `${formatScore(breakdown.components[name].points)}`).join(" + ")} = {formatScore(breakdown.score)}
      </p>
      <p>Skills match exactly or through listed synonyms (no guessing). Missing candidate information scores zero and marks the assessment incomplete instead of counting as a failure.</p>
      <p className="font-medium text-foreground">{breakdown.decision_notice}</p>
      <p className="text-xs">Scoring version {breakdown.scoring_version}.</p>
    </div>
  );
}

export function ComponentBreakdown({ breakdown }: { breakdown: ScreeningBreakdown }) {
  return (
    <div className="grid gap-3 md:grid-cols-2">
      {COMPONENT_ORDER.map((name) => (
        <ComponentCard key={name} name={name} component={breakdown.components[name]} breakdown={breakdown} />
      ))}
    </div>
  );
}

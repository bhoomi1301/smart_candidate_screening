import { useMutation } from "@tanstack/react-query";
import { FileUp, X } from "lucide-react";
import * as React from "react";
import { InlineError, errorMessage } from "@/components/common/feedback";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/primitives";
import type { CandidateFormValues } from "@/features/candidates/candidate-form-page";
import { resumesApi } from "@/lib/api/endpoints";
import type { ResumeExtraction } from "@/lib/api/types";
import { ExtractionStatus, RESUME_MAX_MB, SuggestionsDialog, resumeFileProblem } from "./resume-suggestions";

/** Hidden native file input driven by a button, so it stays keyboard accessible. */
export function PdfPicker({ label, onPick, disabled, loading, variant = "outline" }: { label: string; onPick: (file: File) => void; disabled?: boolean; loading?: boolean; variant?: "outline" | "default" }) {
  const input = React.useRef<HTMLInputElement>(null);
  return (
    <>
      <input
        ref={input}
        type="file"
        accept="application/pdf,.pdf"
        className="sr-only"
        tabIndex={-1}
        aria-hidden="true"
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = "";
          if (file) onPick(file);
        }}
      />
      <Button type="button" variant={variant} disabled={disabled} loading={loading} onClick={() => input.current?.click()}>
        {!loading && <FileUp aria-hidden="true" />}
        {label}
      </Button>
    </>
  );
}

/** New-candidate prefill: extract suggestions without storing; the file is attached after the candidate is created. */
export function ResumeStarter({
  file,
  getValues,
  onApply,
  onFileChange,
}: {
  file: File | null;
  getValues: () => CandidateFormValues;
  onApply: (values: CandidateFormValues) => void;
  onFileChange: (file: File | null) => void;
}) {
  const [error, setError] = React.useState<string | null>(null);
  const [extraction, setExtraction] = React.useState<ResumeExtraction | null>(null);
  const [reviewing, setReviewing] = React.useState(false);
  const extract = useMutation({
    mutationFn: resumesApi.extract,
    onSuccess: (result, picked) => {
      onFileChange(picked);
      setExtraction(result);
      if (result.status === "ok") setReviewing(true);
    },
    onError: (err) => {
      onFileChange(null);
      setError(errorMessage(err));
    },
  });
  const pick = (picked: File) => {
    setError(null);
    setExtraction(null);
    const problem = resumeFileProblem(picked);
    if (problem) {
      setError(problem);
      return;
    }
    extract.mutate(picked);
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Start from a resume (optional)</CardTitle>
        <CardDescription>Upload a PDF (up to {RESUME_MAX_MB} MB) to suggest details. You review every suggestion, and the file is attached when you save.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <PdfPicker label={file ? "Choose a different PDF" : "Choose PDF"} onPick={pick} loading={extract.isPending} />
          {file && (
            <span className="inline-flex items-center gap-1 rounded-md border bg-secondary py-1 pl-2.5 pr-1 text-sm">
              <span className="max-w-[16rem] truncate">{file.name}</span>
              <button
                type="button"
                className="rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
                aria-label={`Do not attach ${file.name}`}
                onClick={() => {
                  onFileChange(null);
                  setExtraction(null);
                }}
              >
                <X className="size-3.5" aria-hidden="true" />
              </button>
            </span>
          )}
          {extraction?.status === "ok" && (
            <Button type="button" variant="ghost" onClick={() => setReviewing(true)}>
              Review suggestions again
            </Button>
          )}
        </div>
        <InlineError message={error} />
        {extraction && <ExtractionStatus extraction={extraction} />}
      </CardContent>
      <SuggestionsDialog open={reviewing} onOpenChange={setReviewing} extraction={extraction} current={getValues()} onApply={onApply} applyLabel="Fill the form" />
    </Card>
  );
}

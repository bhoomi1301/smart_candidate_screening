import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Download, FileSearch, FileText, ShieldCheck, Trash2 } from "lucide-react";
import * as React from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { ConfirmDialog, InlineError, errorMessage } from "@/components/common/feedback";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/primitives";
import { toCandidateFormValues } from "@/features/candidates/candidate-form-page";
import { candidatesApi } from "@/lib/api/endpoints";
import type { CandidateDetail, ResumeExtraction } from "@/lib/api/types";
import { toastError } from "@/lib/forms";
import { formatDate } from "@/lib/utils";
import { PdfPicker } from "./resume-starter";
import { ExtractionStatus, RESUME_MAX_MB, SuggestionsDialog, resumeFileProblem } from "./resume-suggestions";

const formatSize = (bytes: number) => (bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / (1024 * 1024)).toFixed(1)} MB`);

export function ResumeCard({ candidate }: { candidate: CandidateDetail }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [error, setError] = React.useState<string | null>(null);
  const [extraction, setExtraction] = React.useState<ResumeExtraction | null>(null);
  const [reviewing, setReviewing] = React.useState(false);
  const [confirmRemove, setConfirmRemove] = React.useState(false);
  const resume = candidate.resume;
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["candidates", candidate.id] });

  const showExtraction = (result: ResumeExtraction) => {
    setExtraction(result);
    if (result.status === "ok") setReviewing(true);
  };
  const upload = useMutation({
    mutationFn: (file: File) => candidatesApi.uploadResume(candidate.id, file),
    onSuccess: (result) => {
      refresh();
      toast.success(resume ? "Resume replaced" : "Resume uploaded");
      showExtraction(result.extraction);
    },
    onError: (err) => setError(errorMessage(err)),
  });
  const suggestions = useMutation({ mutationFn: () => candidatesApi.resumeSuggestions(candidate.id), onSuccess: showExtraction, onError: (err) => setError(errorMessage(err)) });
  const download = useMutation({
    mutationFn: () => candidatesApi.downloadResume(candidate.id),
    onSuccess: (blob) => {
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = resume?.original_filename ?? "resume.pdf";
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    },
    onError: (err) => toastError(err, "The resume could not be downloaded."),
  });
  const remove = useMutation({
    mutationFn: () => candidatesApi.removeResume(candidate.id),
    onSuccess: () => {
      refresh();
      setExtraction(null);
      setConfirmRemove(false);
      toast.success("Resume removed");
    },
    onError: (err) => {
      setConfirmRemove(false);
      toastError(err);
    },
  });
  const pick = (file: File) => {
    setError(null);
    const problem = resumeFileProblem(file);
    if (problem) setError(problem);
    else upload.mutate(file);
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Resume</CardTitle>
        {!resume && <CardDescription>PDF only, up to {RESUME_MAX_MB} MB. Details are suggested from the text; nothing changes until you review and save.</CardDescription>}
      </CardHeader>
      <CardContent className="space-y-3">
        {resume ? (
          <>
            <div className="flex items-start gap-3 text-sm">
              <FileText className="mt-0.5 size-5 shrink-0 text-muted-foreground" aria-hidden="true" />
              <div className="min-w-0">
                <p className="truncate font-medium" title={resume.original_filename}>
                  {resume.original_filename}
                </p>
                <p className="text-xs text-muted-foreground">
                  {formatSize(resume.size_bytes)}
                  {resume.page_count !== null && ` · ${resume.page_count} ${resume.page_count === 1 ? "page" : "pages"}`} · Uploaded {formatDate(resume.uploaded_at)}
                </p>
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              {resume.file_available && (
                <>
                  <Button size="sm" variant="outline" loading={download.isPending} onClick={() => download.mutate()}>
                    {!download.isPending && <Download aria-hidden="true" />} Download
                  </Button>
                  <Button size="sm" variant="outline" loading={suggestions.isPending} onClick={() => suggestions.mutate()}>
                    {!suggestions.isPending && <FileSearch aria-hidden="true" />} Review extracted details
                  </Button>
                </>
              )}
              <PdfPicker label="Replace" onPick={pick} loading={upload.isPending} />
              <Button size="sm" variant="ghost" onClick={() => setConfirmRemove(true)} aria-label="Remove resume">
                <Trash2 aria-hidden="true" />
              </Button>
            </div>
            {!resume.file_available && <p className="text-xs text-muted-foreground">Only details about this resume were recorded; no file is stored. Upload the PDF to enable download.</p>}
          </>
        ) : (
          <PdfPicker label="Upload PDF resume" onPick={pick} loading={upload.isPending} />
        )}
        <InlineError message={error} />
        {extraction && <ExtractionStatus extraction={extraction} />}
        <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
          <ShieldCheck className="mt-px size-3.5 shrink-0" aria-hidden="true" />
          Stored privately in your workspace; only signed-in members can download it.
        </p>
      </CardContent>
      <SuggestionsDialog
        open={reviewing}
        onOpenChange={setReviewing}
        extraction={extraction}
        current={toCandidateFormValues(candidate)}
        applyLabel="Continue to edit"
        onApply={(values) => navigate(`/candidates/${candidate.id}/edit`, { state: { resumePrefill: values } })}
      />
      <ConfirmDialog
        open={confirmRemove}
        onOpenChange={setConfirmRemove}
        title="Remove this resume?"
        description="The stored PDF is deleted permanently. The candidate’s details are not changed."
        confirmLabel="Remove resume"
        loading={remove.isPending}
        onConfirm={() => remove.mutate()}
      />
    </Card>
  );
}

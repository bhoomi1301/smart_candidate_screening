import { Compass } from "lucide-react";
import { lazy, Suspense, type ComponentType, type ReactNode } from "react";
import { Link, Route, Routes } from "react-router-dom";
import { EmptyState, PageSkeleton } from "@/components/common/feedback";
import { AppShell } from "@/components/layout/app-shell";
import { Button } from "@/components/ui/button";
import { AuthProvider } from "@/features/auth/auth-context";
import { LoginPage, RegisterPage } from "@/features/auth/auth-pages";
import { RedirectIfAuthenticated, RequireAuth } from "@/features/auth/guards";

// Route-level code splitting keeps charts and heavy forms out of the initial bundle.
function named<K extends string>(loader: () => Promise<Record<K, ComponentType>>, name: K) {
  return lazy(() => loader().then((module) => ({ default: module[name] })));
}
const DashboardPage = named(() => import("@/features/dashboard/dashboard-page"), "DashboardPage");
const CandidatesPage = named(() => import("@/features/candidates/candidates-page"), "CandidatesPage");
const CandidateFormPage = named(() => import("@/features/candidates/candidate-form-page"), "CandidateFormPage");
const CandidateProfilePage = named(() => import("@/features/candidates/candidate-profile-page"), "CandidateProfilePage");
const JobsPage = named(() => import("@/features/jobs/jobs-page"), "JobsPage");
const JobFormPage = named(() => import("@/features/jobs/job-form-page"), "JobFormPage");
const JobDetailPage = named(() => import("@/features/jobs/job-detail-page"), "JobDetailPage");
const ApplicationPage = named(() => import("@/features/applications/application-page"), "ApplicationPage");
const AccountPage = named(() => import("@/features/account/account-page"), "AccountPage");

function NotFoundPage() {
  return (
    <EmptyState
      icon={Compass}
      title="Page not found"
      description="The address may be mistyped, or the page has moved."
      action={
        <Button asChild>
          <Link to="/">Go to dashboard</Link>
        </Button>
      }
      className="py-24"
    />
  );
}

const page = (element: ReactNode) => <Suspense fallback={<PageSkeleton />}>{element}</Suspense>;

export function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route element={<RedirectIfAuthenticated />}>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
        </Route>
        <Route element={<RequireAuth />}>
          <Route element={<AppShell />}>
            <Route index element={page(<DashboardPage />)} />
            <Route path="candidates" element={page(<CandidatesPage />)} />
            <Route path="candidates/new" element={page(<CandidateFormPage />)} />
            <Route path="candidates/:candidateId" element={page(<CandidateProfilePage />)} />
            <Route path="candidates/:candidateId/edit" element={page(<CandidateFormPage key="edit" />)} />
            <Route path="jobs" element={page(<JobsPage />)} />
            <Route path="jobs/new" element={page(<JobFormPage />)} />
            <Route path="jobs/:jobId" element={page(<JobDetailPage />)} />
            <Route path="jobs/:jobId/edit" element={page(<JobFormPage key="edit" />)} />
            <Route path="applications/:applicationId" element={page(<ApplicationPage />)} />
            <Route path="account" element={page(<AccountPage />)} />
            <Route path="*" element={<NotFoundPage />} />
          </Route>
        </Route>
      </Routes>
    </AuthProvider>
  );
}

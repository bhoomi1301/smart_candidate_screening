import { Loader2 } from "lucide-react";
import { Navigate, Outlet, useLocation, useSearchParams } from "react-router-dom";
import { useAuth } from "./auth-context";

function FullPageSpinner() {
  return (
    <div className="flex min-h-screen items-center justify-center" role="status">
      <Loader2 className="size-6 animate-spin text-muted-foreground" aria-hidden="true" />
      <span className="sr-only">Loading</span>
    </div>
  );
}

/** Client-side gate for UX only; the API enforces authentication and authorization on every request. */
export function RequireAuth() {
  const { user, isLoading } = useAuth();
  const location = useLocation();
  if (isLoading) return <FullPageSpinner />;
  if (!user) return <Navigate to={`/login?next=${encodeURIComponent(location.pathname + location.search)}`} replace />;
  return <Outlet />;
}

export function RedirectIfAuthenticated() {
  const { user, isLoading } = useAuth();
  const [params] = useSearchParams();
  if (isLoading) return <FullPageSpinner />;
  // Also runs right after sign-in (the user appears in the auth cache), so it must honour ?next=.
  if (user) return <Navigate to={safeNextPath(params.get("next"))} replace />;
  return <Outlet />;
}

/** Only follow same-app relative paths after sign-in (never an absolute or protocol-relative URL). */
export function safeNextPath(next: string | null): string {
  // Same-app paths only: reject protocol-relative ("//x") and backslash ("/x") forms browsers treat as other hosts.
  return next && next.startsWith("/") && !next.startsWith("//") && !next.includes("\\") ? next : "/";
}

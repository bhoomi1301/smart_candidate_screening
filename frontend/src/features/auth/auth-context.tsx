import { useQuery, useQueryClient } from "@tanstack/react-query";
import * as React from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { isApiError, onSessionExpired } from "@/lib/api/client";
import { authApi } from "@/lib/api/endpoints";
import type { LoginInput, RegisterInput, User } from "@/lib/api/types";

interface AuthContextValue {
  user: User | null;
  isLoading: boolean;
  login: (input: LoginInput) => Promise<User>;
  register: (input: RegisterInput) => Promise<User>;
  logout: () => Promise<void>;
}

const AuthContext = React.createContext<AuthContextValue | null>(null);
export const ME_QUERY_KEY = ["auth", "me"] as const;

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();
  const locationRef = React.useRef(location);
  locationRef.current = location;

  const me = useQuery({
    queryKey: ME_QUERY_KEY,
    queryFn: async () => {
      try {
        return await authApi.me();
      } catch (error) {
        // The client already tried a refresh; a 401 here simply means "signed out".
        if (isApiError(error) && error.status === 401) return null;
        throw error;
      }
    },
    staleTime: 5 * 60 * 1000,
    retry: false,
  });

  React.useEffect(
    () =>
      onSessionExpired(() => {
        const wasSignedIn = Boolean(queryClient.getQueryData(ME_QUERY_KEY));
        queryClient.setQueryData(ME_QUERY_KEY, null);
        queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== "auth" });
        if (wasSignedIn) {
          toast.warning("Your session expired. Please sign in again.");
          const { pathname, search } = locationRef.current;
          navigate(`/login?next=${encodeURIComponent(pathname + search)}`, { replace: true });
        }
      }),
    [navigate, queryClient],
  );

  const value = React.useMemo<AuthContextValue>(
    () => ({
      user: me.data ?? null,
      isLoading: me.isLoading,
      login: async (input) => {
        const response = await authApi.login(input);
        queryClient.setQueryData(ME_QUERY_KEY, response.user);
        return response.user;
      },
      register: async (input) => {
        const response = await authApi.register(input);
        queryClient.setQueryData(ME_QUERY_KEY, response.user);
        return response.user;
      },
      logout: async () => {
        try {
          await authApi.logout();
        } finally {
          queryClient.clear();
          queryClient.setQueryData(ME_QUERY_KEY, null);
        }
      },
    }),
    [me.data, me.isLoading, queryClient],
  );

  if (me.isError) {
    // Server unreachable or failing: show a recoverable message rather than a misleading sign-in page.
    return (
      <div className="flex min-h-screen items-center justify-center p-6 text-center">
        <div>
          <p className="font-medium">TalentLens cannot reach the server.</p>
          <p className="mt-1 text-sm text-muted-foreground">Check that the API is running, then reload.</p>
          <button className="mt-4 rounded-md border px-3 py-1.5 text-sm hover:bg-muted" onClick={() => me.refetch()}>
            Retry
          </button>
        </div>
      </div>
    );
  }
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = React.useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}

/** Narrowed hook for pages under RequireAuth. */
export function useCurrentUser(): User {
  const { user } = useAuth();
  if (!user) throw new Error("useCurrentUser used outside an authenticated route");
  return user;
}

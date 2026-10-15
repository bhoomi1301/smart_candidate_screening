import { Briefcase, ChevronsUpDown, LayoutDashboard, LogOut, Menu, UserCircle, Users } from "lucide-react";
import * as React from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogTitle, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger, SheetContent } from "@/components/ui/overlays";
import { useAuth, useCurrentUser } from "@/features/auth/auth-context";
import { cn, initials } from "@/lib/utils";
import { Logo } from "./logo";

const NAV_ITEMS = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/candidates", label: "Candidates", icon: Users },
  { to: "/jobs", label: "Jobs", icon: Briefcase },
  { to: "/account", label: "Account", icon: UserCircle },
];

function NavList({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav aria-label="Main" className="flex flex-col gap-0.5 px-3">
      {NAV_ITEMS.map(({ to, label, icon: Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
              isActive ? "bg-primary-soft text-accent-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground",
            )
          }
        >
          <Icon className="size-4" aria-hidden="true" />
          {label}
        </NavLink>
      ))}
    </nav>
  );
}

function UserMenu() {
  const user = useCurrentUser();
  const { logout } = useAuth();
  const navigate = useNavigate();
  const signOut = async () => {
    try {
      await logout();
    } catch {
      // The session is cleared locally even if the server call failed.
    }
    toast.success("Signed out");
    navigate("/login", { replace: true });
  };
  return (
    <DropdownMenu>
      <DropdownMenuTrigger className="flex w-full items-center gap-3 rounded-md p-2 text-left hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring">
        <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-primary-soft text-xs font-semibold text-accent-foreground" aria-hidden="true">
          {initials(user.full_name)}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium">{user.full_name}</span>
          <span className="block truncate text-xs text-muted-foreground">{user.role === "admin" ? "Admin" : "HR"}</span>
        </span>
        <ChevronsUpDown className="size-4 text-muted-foreground" aria-hidden="true" />
        <span className="sr-only">Open account menu</span>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuLabel>
          <span className="block truncate font-medium">{user.full_name}</span>
          <span className="block truncate text-xs text-muted-foreground">{user.email}</span>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => navigate("/account")}>
          <UserCircle aria-hidden="true" /> Account
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={signOut}>
          <LogOut aria-hidden="true" /> Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function AppShell() {
  const [mobileOpen, setMobileOpen] = React.useState(false);
  const location = useLocation();
  const mainRef = React.useRef<HTMLElement>(null);

  // Move focus to the page on navigation so keyboard and screen-reader users land on new content.
  React.useEffect(() => {
    mainRef.current?.focus({ preventScroll: true });
    window.scrollTo({ top: 0 });
  }, [location.pathname]);

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[15rem_1fr]">
      <a href="#main" className="sr-only z-50 rounded-md bg-card px-3 py-2 focus:not-sr-only focus:fixed focus:left-3 focus:top-3">
        Skip to content
      </a>
      <aside className="sticky top-0 hidden h-screen flex-col border-r bg-card lg:flex">
        <Link to="/" className="mx-3 mb-4 mt-4 rounded-md px-3 py-1.5">
          <Logo />
        </Link>
        <NavList />
        <div className="mt-auto border-t p-3">
          <UserMenu />
        </div>
      </aside>

      <header className="sticky top-0 z-40 flex h-14 items-center gap-2 border-b bg-card/95 px-4 backdrop-blur lg:hidden">
        <Dialog open={mobileOpen} onOpenChange={setMobileOpen}>
          <Button variant="ghost" size="icon" aria-label="Open navigation" onClick={() => setMobileOpen(true)}>
            <Menu aria-hidden="true" />
          </Button>
          <SheetContent aria-describedby={undefined}>
            <DialogTitle className="sr-only">Navigation</DialogTitle>
            <div className="px-6 pb-4 pt-5">
              <Logo />
            </div>
            <NavList onNavigate={() => setMobileOpen(false)} />
            <div className="mt-auto border-t p-3">
              <UserMenu />
            </div>
          </SheetContent>
        </Dialog>
        <Link to="/" aria-label="TalentLens dashboard">
          <Logo />
        </Link>
      </header>

      <main id="main" ref={mainRef} tabIndex={-1} className="min-w-0 px-4 py-6 focus:outline-none sm:px-6 lg:px-8 lg:py-8">
        <div className="mx-auto max-w-6xl">
          <Outlet />
        </div>
      </main>
    </div>
  );
}

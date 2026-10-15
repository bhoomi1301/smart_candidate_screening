import { zodResolver } from "@hookform/resolvers/zod";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, LogOut, ShieldCheck, UserPlus, Users } from "lucide-react";
import * as React from "react";
import { useForm } from "react-hook-form";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { z } from "zod";
import { ConfirmDialog, EmptyState, ErrorState, InlineError, PageHeader, Pagination, TableSkeleton } from "@/components/common/feedback";
import { Field } from "@/components/common/form";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/overlays";
import { Badge, Card, CardContent, CardDescription, CardHeader, CardTitle, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/primitives";
import { useAuth, useCurrentUser } from "@/features/auth/auth-context";
import { auditApi, usersApi } from "@/lib/api/endpoints";
import type { AuditLogEntry, User } from "@/lib/api/types";
import { applyServerErrors, toastError } from "@/lib/forms";
import { formatDate, formatDateTime, initials } from "@/lib/utils";

const ACTIVITY_PAGE = 15;

export function AccountPage() {
  const user = useCurrentUser();
  const { logout } = useAuth();
  const navigate = useNavigate();
  const signOut = async () => {
    try {
      await logout();
    } catch {
      // Cleared locally regardless.
    }
    toast.success("Signed out");
    navigate("/login", { replace: true });
  };
  return (
    <>
      <PageHeader
        title="Account"
        description="Your profile, your activity, and workspace members."
        actions={
          <Button variant="outline" onClick={signOut}>
            <LogOut aria-hidden="true" /> Sign out
          </Button>
        }
      />
      <div className="grid gap-4 lg:grid-cols-[20rem_minmax(0,1fr)]">
        <Card className="self-start">
          <CardContent className="flex flex-col items-center gap-3 pt-5 text-center sm:pt-6">
            <span className="flex size-14 items-center justify-center rounded-full bg-primary-soft text-lg font-semibold text-accent-foreground" aria-hidden="true">
              {initials(user.full_name)}
            </span>
            <div>
              <p className="font-semibold">{user.full_name}</p>
              <p className="break-all text-sm text-muted-foreground">{user.email}</p>
            </div>
            <Badge variant={user.role === "admin" ? "primary" : "neutral"}>
              <ShieldCheck aria-hidden="true" />
              {user.role === "admin" ? "Admin" : "HR"}
            </Badge>
            <dl className="mt-2 w-full space-y-1 border-t pt-3 text-left text-sm">
              <div className="flex justify-between gap-2">
                <dt className="text-muted-foreground">Member since</dt>
                <dd>{formatDate(user.created_at)}</dd>
              </div>
              <div className="flex justify-between gap-2">
                <dt className="text-muted-foreground">Workspace ID</dt>
                <dd className="tabular">{user.workspace_id}</dd>
              </div>
            </dl>
            <p className="text-left text-xs text-muted-foreground">
              {user.role === "admin" ? "Admins manage workspace members and can view everyone’s activity." : "HR members manage candidates, jobs, and decisions. Workspace members are managed by an admin."}
            </p>
          </CardContent>
        </Card>
        <div className="min-w-0 space-y-4">
          {user.role === "admin" && <TeamMembers currentUser={user} />}
          <MyActivity />
        </div>
      </div>
    </>
  );
}

function describeAudit(entry: AuditLogEntry): string {
  const labels: Record<string, string> = {
    "auth.login": "Signed in",
    "auth.logout": "Signed out",
    "auth.refresh": "Session renewed",
    "workspace.register": "Created the workspace",
    "user.create": "Added a workspace member",
    "user.activate": "Reactivated a member",
    "user.deactivate": "Deactivated a member",
    "candidate.create": "Added a candidate",
    "candidate.update": "Updated a candidate",
    "candidate.delete": "Deleted a candidate",
    "candidate.resume_upload": "Uploaded a resume",
    "candidate.resume_download": "Downloaded a resume",
    "candidate.resume_delete": "Removed a resume",
    "job.create": "Created a job",
    "job.update": "Updated job criteria",
    "job.status": "Changed a job’s status",
    "job.delete": "Deleted a job",
    "application.create": "Applied a candidate to a job",
    "application.decision": "Recorded a decision",
    "application.note": "Added an application note",
    "screening.evaluate": "Screened an application",
    "screening.recalculate": "Recalculated screening results",
  };
  const base = labels[entry.action] ?? entry.action;
  const meta = entry.metadata as { previous_status?: string; new_status?: string; status?: string };
  if (entry.action === "application.decision" && meta.previous_status) return `${base}: ${meta.previous_status} → ${meta.new_status}`;
  if (entry.action === "job.status" && meta.previous_status) return `${base}: ${meta.previous_status} → ${meta.status}`;
  return base;
}

function MyActivity() {
  const user = useCurrentUser();
  const [skip, setSkip] = React.useState(0);
  const activity = useQuery({
    queryKey: ["audit", "mine", skip],
    queryFn: () => auditApi.list({ actor_id: user.id, skip, limit: ACTIVITY_PAGE }),
    placeholderData: keepPreviousData,
  });
  return (
    <Card>
      <CardHeader>
        <CardTitle>Your activity</CardTitle>
        <CardDescription>Everything recorded under your account, newest first.</CardDescription>
      </CardHeader>
      {activity.isPending ? (
        <TableSkeleton rows={5} columns={2} />
      ) : activity.isError ? (
        <ErrorState error={activity.error} onRetry={() => activity.refetch()} />
      ) : activity.data.items.length === 0 ? (
        <EmptyState icon={Activity} title="No activity yet" />
      ) : (
        <>
          <ul className="divide-y border-t">
            {activity.data.items.map((entry) => (
              <li key={entry.id} className="flex flex-col gap-0.5 px-4 py-2.5 text-sm sm:flex-row sm:items-center sm:justify-between sm:px-5">
                <span>
                  {describeAudit(entry)}
                  {entry.resource_id !== null && entry.resource_type !== "user" && entry.resource_type !== "workspace" && (
                    <span className="text-muted-foreground">
                      {" "}
                      · {entry.resource_type} #{entry.resource_id}
                    </span>
                  )}
                </span>
                <time dateTime={entry.created_at} className="shrink-0 text-xs text-muted-foreground">
                  {formatDateTime(entry.created_at)}
                </time>
              </li>
            ))}
          </ul>
          <Pagination skip={skip} limit={ACTIVITY_PAGE} total={activity.data.total} onChange={setSkip} label="entries" />
        </>
      )}
    </Card>
  );
}

function TeamMembers({ currentUser }: { currentUser: User }) {
  const queryClient = useQueryClient();
  const [adding, setAdding] = React.useState(false);
  const [pending, setPending] = React.useState<User | null>(null);
  const users = useQuery({ queryKey: ["users"], queryFn: usersApi.list });
  const toggle = useMutation({
    mutationFn: (member: User) => usersApi.setActive(member.id, !member.is_active),
    onSuccess: (member) => {
      queryClient.invalidateQueries({ queryKey: ["users"] });
      toast.success(member.is_active ? `${member.full_name} can sign in again` : `${member.full_name} was deactivated and signed out`);
      setPending(null);
    },
    onError: (error) => {
      setPending(null);
      toastError(error);
    },
  });
  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-start justify-between gap-3 space-y-0">
        <div>
          <CardTitle>Workspace members</CardTitle>
          <CardDescription>Members can sign in and work on recruitment in this workspace.</CardDescription>
        </div>
        <Button size="sm" onClick={() => setAdding(true)}>
          <UserPlus aria-hidden="true" /> Add HR member
        </Button>
      </CardHeader>
      {users.isPending ? (
        <TableSkeleton rows={3} columns={3} />
      ) : users.isError ? (
        <ErrorState error={users.error} onRetry={() => users.refetch()} />
      ) : users.data.length === 0 ? (
        <EmptyState icon={Users} title="No members" />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Member</TableHead>
              <TableHead className="hidden sm:table-cell">Role</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="text-right">
                <span className="sr-only">Actions</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {users.data.map((member) => (
              <TableRow key={member.id}>
                <TableCell>
                  <span className="block font-medium">
                    {member.full_name}
                    {member.id === currentUser.id && <span className="text-muted-foreground"> (you)</span>}
                  </span>
                  <span className="block break-all text-xs text-muted-foreground">{member.email}</span>
                </TableCell>
                <TableCell className="hidden sm:table-cell">{member.role === "admin" ? "Admin" : "HR"}</TableCell>
                <TableCell>
                  <Badge variant={member.is_active ? "success" : "neutral"}>{member.is_active ? "Active" : "Deactivated"}</Badge>
                </TableCell>
                <TableCell className="text-right">
                  {member.id !== currentUser.id && (
                    <Button variant="outline" size="sm" onClick={() => (member.is_active ? setPending(member) : toggle.mutate(member))} loading={toggle.isPending && toggle.variables?.id === member.id}>
                      {member.is_active ? "Deactivate" : "Reactivate"}
                    </Button>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      <AddMemberDialog open={adding} onOpenChange={setAdding} />
      <ConfirmDialog
        open={pending !== null}
        onOpenChange={(open) => !open && setPending(null)}
        title={`Deactivate ${pending?.full_name}?`}
        description="They will be signed out immediately and cannot sign in until reactivated. Their past decisions and activity are kept."
        confirmLabel="Deactivate"
        loading={toggle.isPending}
        onConfirm={() => pending && toggle.mutate(pending)}
      />
    </Card>
  );
}

const memberSchema = z.object({
  full_name: z.string().trim().min(2, "Use at least 2 characters").max(160),
  email: z.string().trim().min(1, "Email is required").email("Enter a valid email address"),
  password: z.string().min(12, "Use at least 12 characters").max(256),
});
type MemberValues = z.infer<typeof memberSchema>;

function AddMemberDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const queryClient = useQueryClient();
  const [formError, setFormError] = React.useState<string | null>(null);
  const form = useForm<MemberValues>({ resolver: zodResolver(memberSchema), defaultValues: { full_name: "", email: "", password: "" } });
  const { errors } = form.formState;
  React.useEffect(() => {
    if (open) {
      form.reset();
      setFormError(null);
    }
  }, [open, form]);
  const create = useMutation({
    mutationFn: usersApi.create,
    onSuccess: (member) => {
      queryClient.invalidateQueries({ queryKey: ["users"] });
      toast.success(`${member.full_name} was added as an HR member`);
      onOpenChange(false);
    },
    onError: (error) => setFormError(applyServerErrors(error, form.setError, ["full_name", "email", "password"])),
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add an HR member</DialogTitle>
          <DialogDescription>Share the initial password with them securely. New members always get the HR role.</DialogDescription>
        </DialogHeader>
        <form noValidate className="space-y-4" onSubmit={form.handleSubmit((values) => create.mutate(values))}>
          <InlineError message={formError} />
          <Field id="member-name" label="Full name" error={errors.full_name?.message} required>
            {(props) => <Input autoComplete="off" {...props} {...form.register("full_name")} />}
          </Field>
          <Field id="member-email" label="Email" error={errors.email?.message} required>
            {(props) => <Input type="email" autoComplete="off" {...props} {...form.register("email")} />}
          </Field>
          <Field id="member-password" label="Initial password" error={errors.password?.message} hint="At least 12 characters." required>
            {(props) => <Input type="password" autoComplete="new-password" {...props} {...form.register("password")} />}
          </Field>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={create.isPending}>
              Add member
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

import { zodResolver } from "@hookform/resolvers/zod";
import { CheckCircle2 } from "lucide-react";
import * as React from "react";
import { useForm } from "react-hook-form";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { z } from "zod";
import { InlineError } from "@/components/common/feedback";
import { Field } from "@/components/common/form";
import { Logo } from "@/components/layout/logo";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { applyServerErrors } from "@/lib/forms";
import { useAuth } from "./auth-context";
import { safeNextPath } from "./guards";

function AuthLayout({ title, subtitle, children, footer }: { title: string; subtitle: string; children: React.ReactNode; footer: React.ReactNode }) {
  return (
    <div className="grid min-h-screen lg:grid-cols-[1fr_minmax(0,34rem)]">
      <aside className="hidden flex-col justify-between border-r bg-card p-10 lg:flex">
        <Logo />
        <div className="max-w-md">
          <h2 className="text-2xl font-semibold tracking-tight">Screen candidates with reasons you can explain.</h2>
          <ul className="mt-6 space-y-3 text-sm text-muted-foreground">
            {[
              "Deterministic scores with a component-by-component breakdown",
              "Matched and missing skills, eligibility, and missing-data warnings",
              "A full decision history for every application",
            ].map((item) => (
              <li key={item} className="flex gap-2">
                <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden="true" />
                {item}
              </li>
            ))}
          </ul>
        </div>
        <p className="text-xs text-muted-foreground">Scores support HR decisions; people make the decisions.</p>
      </aside>
      <main className="flex items-center justify-center px-4 py-10 sm:px-8">
        <div className="w-full max-w-sm">
          <div className="mb-8 lg:hidden">
            <Logo />
          </div>
          <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>
          <div className="mt-6">{children}</div>
          <p className="mt-6 text-sm text-muted-foreground">{footer}</p>
        </div>
      </main>
    </div>
  );
}

const loginSchema = z.object({
  email: z.string().trim().min(1, "Enter your email").email("Enter a valid email address"),
  password: z.string().min(1, "Enter your password"),
});
type LoginValues = z.infer<typeof loginSchema>;

export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [formError, setFormError] = React.useState<string | null>(null);
  const form = useForm<LoginValues>({ resolver: zodResolver(loginSchema), defaultValues: { email: "", password: "" } });
  const { errors, isSubmitting } = form.formState;

  const onSubmit = form.handleSubmit(async (values) => {
    setFormError(null);
    try {
      await login(values);
      navigate(safeNextPath(params.get("next")), { replace: true });
    } catch (error) {
      setFormError(applyServerErrors(error, form.setError, ["email", "password"]));
    }
  });

  return (
    <AuthLayout
      title="Sign in"
      subtitle="Welcome back to TalentLens."
      footer={
        <>
          New to TalentLens?{" "}
          <Link to="/register" className="font-medium text-primary hover:underline">
            Create a workspace
          </Link>
        </>
      }
    >
      <form onSubmit={onSubmit} noValidate className="space-y-4">
        <InlineError message={formError} />
        <Field id="email" label="Work email" error={errors.email?.message}>
          {(props) => <Input type="email" autoComplete="email" autoFocus {...props} {...form.register("email")} />}
        </Field>
        <Field id="password" label="Password" error={errors.password?.message}>
          {(props) => <Input type="password" autoComplete="current-password" {...props} {...form.register("password")} />}
        </Field>
        <Button type="submit" className="w-full" loading={isSubmitting}>
          Sign in
        </Button>
      </form>
    </AuthLayout>
  );
}

const registerSchema = z
  .object({
    workspace_name: z.string().trim().min(2, "Use at least 2 characters").max(160),
    full_name: z.string().trim().min(2, "Use at least 2 characters").max(160),
    email: z.string().trim().min(1, "Enter your email").email("Enter a valid email address"),
    password: z.string().min(12, "Use at least 12 characters").max(256),
    password_confirmation: z.string().min(1, "Confirm your password"),
  })
  .refine((values) => values.password === values.password_confirmation, { path: ["password_confirmation"], message: "Passwords do not match" });
type RegisterValues = z.infer<typeof registerSchema>;
const REGISTER_FIELDS = ["workspace_name", "full_name", "email", "password", "password_confirmation"] as const;

export function RegisterPage() {
  const { register: registerWorkspace } = useAuth();
  const navigate = useNavigate();
  const [formError, setFormError] = React.useState<string | null>(null);
  const form = useForm<RegisterValues>({
    resolver: zodResolver(registerSchema),
    defaultValues: { workspace_name: "", full_name: "", email: "", password: "", password_confirmation: "" },
  });
  const { errors, isSubmitting } = form.formState;

  const onSubmit = form.handleSubmit(async (values) => {
    setFormError(null);
    try {
      await registerWorkspace(values);
      navigate("/", { replace: true });
    } catch (error) {
      setFormError(applyServerErrors(error, form.setError, REGISTER_FIELDS));
    }
  });

  return (
    <AuthLayout
      title="Create your workspace"
      subtitle="You'll be the first HR member. Your data stays isolated from other workspaces."
      footer={
        <>
          Already have an account?{" "}
          <Link to="/login" className="font-medium text-primary hover:underline">
            Sign in
          </Link>
        </>
      }
    >
      <form onSubmit={onSubmit} noValidate className="space-y-4">
        <InlineError message={formError} />
        <Field id="workspace_name" label="Company or team name" error={errors.workspace_name?.message} required>
          {(props) => <Input autoComplete="organization" autoFocus {...props} {...form.register("workspace_name")} />}
        </Field>
        <Field id="full_name" label="Your full name" error={errors.full_name?.message} required>
          {(props) => <Input autoComplete="name" {...props} {...form.register("full_name")} />}
        </Field>
        <Field id="email" label="Work email" error={errors.email?.message} required>
          {(props) => <Input type="email" autoComplete="email" {...props} {...form.register("email")} />}
        </Field>
        <Field id="password" label="Password" error={errors.password?.message} hint="At least 12 characters." required>
          {(props) => <Input type="password" autoComplete="new-password" {...props} {...form.register("password")} />}
        </Field>
        <Field id="password_confirmation" label="Confirm password" error={errors.password_confirmation?.message} required>
          {(props) => <Input type="password" autoComplete="new-password" {...props} {...form.register("password_confirmation")} />}
        </Field>
        <Button type="submit" className="w-full" loading={isSubmitting}>
          Create workspace
        </Button>
      </form>
    </AuthLayout>
  );
}

import { type FormEvent, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";

import { Button, Card, ErrorNote, Field, PasswordInput } from "../components/ui";
import { ThemeToggle } from "../customer/CustomerLayout";
import { auth } from "../lib/api";

export function homeFor(role: string | undefined) {
  return role === "super_admin" ? "/admin" : role === "rider" ? "/rider" : "/hotel";
}

/** Change your own password. Required after an admin reset (D28), where the temporary password
 * is the "current" one. */
export function PasswordPage() {
  const navigate = useNavigate();
  const me = auth.user();
  const forced = !!me?.must_change_password;
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  if (!me) return <Navigate to="/login" replace />;

  const mismatch = again.length > 0 && again !== next;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (next !== again) return;
    setBusy(true);
    setError(null);
    try {
      await auth.changePassword(current, next);
      navigate(homeFor(me?.role), { replace: true });
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="relative flex min-h-dvh items-center justify-center p-4">
      <div className="absolute top-4 right-4">
        <ThemeToggle />
      </div>
      <Card className="w-full max-w-sm p-6">
        <h1 className="mb-1 text-2xl font-bold">{forced ? "Choose your password" : "Change password"}</h1>
        <p className="mb-6 text-sm text-muted">
          {forced ? "Your password was reset. Pick a new one only you know before you continue." : `Signed in as ${me.name}`}
        </p>
        <form onSubmit={submit} className="flex flex-col gap-4">
          <Field label={forced ? "Temporary password" : "Current password"}>
            {(id) => <PasswordInput id={id} autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required />}
          </Field>
          <Field label="New password" hint="At least 8 characters.">
            {(id) => <PasswordInput id={id} autoComplete="new-password" minLength={8} value={next} onChange={(e) => setNext(e.target.value)} required />}
          </Field>
          <Field label="New password again" error={mismatch ? "The two passwords are different" : undefined}>
            {(id) => <PasswordInput id={id} autoComplete="new-password" value={again} onChange={(e) => setAgain(e.target.value)} aria-invalid={mismatch} required />}
          </Field>
          <ErrorNote error={error} />
          <Button type="submit" size="lg" busy={busy} disabled={mismatch || next.length < 8}>
            Save password
          </Button>
        </form>
        <p className="mt-5 border-t border-line pt-4 text-center text-sm text-muted">
          {forced ? (
            <button onClick={() => auth.logout().then(() => navigate("/login"))} className="font-semibold text-brand hover:underline">Log out</button>
          ) : (
            <Link to={homeFor(me.role)} className="font-semibold text-brand hover:underline">Back</Link>
          )}
        </p>
      </Card>
    </main>
  );
}

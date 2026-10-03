import { type FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { Button, Card, ErrorNote, Field, Input } from "../components/ui";
import { ThemeToggle } from "../customer/CustomerLayout";
import { auth } from "../lib/api";

export function LoginPage() {
  const navigate = useNavigate();
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await auth.login(phone, password);
      const role = auth.user()?.role;
      navigate(role === "super_admin" ? "/admin" : role === "rider" ? "/rider" : "/hotel");
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
        <h1 className="mb-1 text-2xl font-bold text-brand">Chakula</h1>
        <p className="mb-6 text-sm text-muted">Staff and rider login</p>
        <form onSubmit={submit} className="flex flex-col gap-4">
          <Field label="Phone number">
            {(id) => (
              <Input
                id={id}
                type="tel"
                autoComplete="username"
                inputMode="tel"
                placeholder="0712 345 678"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                required
              />
            )}
          </Field>
          <Field label="Password">
            {(id) => (
              <Input
                id={id}
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            )}
          </Field>
          <ErrorNote error={error} />
          <Button type="submit" size="lg" busy={busy}>
            Log in
          </Button>
        </form>
        <p className="mt-5 border-t border-line pt-4 text-center text-sm text-muted">
          Want to deliver with Chakula?{" "}
          <Link to="/rider/join" className="font-semibold text-brand hover:underline">Become a rider</Link>
        </p>
      </Card>
    </main>
  );
}

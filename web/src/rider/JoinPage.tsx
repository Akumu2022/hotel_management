/** Become a rider (DECISIONS D21): three simple steps, one submission at the end.
 *  1. Your details  2. Photos (ID front, ID back, selfie)  3. Check & send
 * Every problem is shown in words under its field; nothing is sent until everything is right,
 * and the account is created only when the whole application arrives complete. */
import clsx from "clsx";
import { ArrowLeft, ArrowRight, Bike, Camera, CheckCircle2, IdCard, Pencil, ShieldCheck, UserRound } from "lucide-react";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { Button, Field, Input } from "../components/ui";
import { ThemeToggle } from "../customer/CustomerLayout";
import { ApiError, type Session, auth, request } from "../lib/api";
import { compressImage } from "../lib/format";

type Details = { name: string; national_id: string; phone: string; residence_area: string; next_of_kin: string; next_of_kin_phone: string; password: string };
type Kind = "id_front" | "id_back" | "selfie";
type Errors = Partial<Record<keyof Details | Kind | "consent" | "form", string>>;

const DRAFT = "rider-application-v1";
const STEP_OF: Record<string, 1 | 2 | 3> = { name: 1, national_id: 1, phone: 1, residence_area: 1, next_of_kin: 1, next_of_kin_phone: 1, password: 1, id_front: 2, id_back: 2, selfie: 2, consent: 3 };
const PHOTOS: { kind: Kind; title: string; hint: string; icon: ReactNode; capture: "environment" | "user" }[] = [
  { kind: "id_front", title: "ID front", hint: "Side with your photo. Whole card in view, no glare.", icon: <IdCard className="size-6" />, capture: "environment" },
  { kind: "id_back", title: "ID back", hint: "The back of the same ID card.", icon: <IdCard className="size-6" />, capture: "environment" },
  { kind: "selfie", title: "Selfie", hint: "Your face, clear and well lit.", icon: <UserRound className="size-6" />, capture: "user" },
];

/** 0712 345 678 / +254 712 345 678 / 254712345678 -> 254712345678, or null. */
function kenyanPhone(raw: string): string | null {
  const d = raw.replace(/[\s\-()]/g, "").replace(/^\+/, "");
  if (/^0[17]\d{8}$/.test(d)) return `254${d.slice(1)}`;
  if (/^254[17]\d{8}$/.test(d)) return d;
  if (/^[17]\d{8}$/.test(d)) return `254${d}`;
  return null;
}
const twoNames = (s: string) => s.trim().split(/\s+/).filter(Boolean).length >= 2;

function checkDetails(f: Details): Errors {
  const e: Errors = {};
  if (!twoNames(f.name)) e.name = "Write your full name as on your ID: at least two names.";
  if (!/^\d{6,9}$/.test(f.national_id)) e.national_id = "ID numbers are 6 to 9 digits.";
  const mine = kenyanPhone(f.phone);
  if (!mine) e.phone = "Enter a phone number like 0712 345 678.";
  if (f.residence_area.trim().length < 3) e.residence_area = "Write your estate or area, e.g. Kanduyi.";
  if (!twoNames(f.next_of_kin)) e.next_of_kin = "Write their full name: at least two names.";
  const kin = kenyanPhone(f.next_of_kin_phone);
  if (!kin) e.next_of_kin_phone = "Enter a phone number like 0712 345 678.";
  else if (kin === mine) e.next_of_kin_phone = "Use your next of kin's own number, not yours.";
  if (f.password.length < 8) e.password = "Use at least 8 characters.";
  return e;
}

function Steps({ step }: { step: 1 | 2 | 3 }) {
  return (
    <ol className="mb-5 grid grid-cols-3 gap-2" aria-label="Application progress">
      {["Your details", "Photos", "Check & send"].map((s, i) => (
        <li key={s} className="flex flex-col gap-1.5">
          <span className={clsx("h-1.5 rounded-full", i < step ? "bg-brand" : "bg-line")} />
          <span className={clsx("text-xs", i + 1 === step ? "font-bold text-ink" : "text-muted")}>
            {i + 1}. {s}
          </span>
        </li>
      ))}
    </ol>
  );
}

/** Kept for the "fix your application" screen. */
export function RiderSteps({ step }: { step: 1 | 2 | 3 }) {
  return <Steps step={step} />;
}

function PhotoPicker({ p, file, error, onPick }: { p: (typeof PHOTOS)[number]; file: Blob | null; error?: string; onPick: (f: File) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!file) {
      setUrl(null);
      return;
    }
    const u = URL.createObjectURL(file);
    setUrl(u);
    return () => URL.revokeObjectURL(u);
  }, [file]);
  return (
    <div>
      <button
        type="button"
        onClick={() => input.current?.click()}
        className={clsx(
          "flex w-full items-center gap-4 rounded-2xl border-2 p-3 text-left transition-colors",
          error ? "border-bad bg-bad-soft/40" : file ? "border-ok bg-ok-soft/40" : "border-dashed border-line bg-surface hover:border-brand",
        )}
      >
        <span className="flex size-20 shrink-0 items-center justify-center overflow-hidden rounded-xl bg-brand-soft text-brand">
          {url ? <img src={url} alt="" className="size-full object-cover" /> : p.icon}
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-1.5 text-[1rem] font-bold">
            {file ? <CheckCircle2 className="size-5 text-ok" /> : null} {p.title}
          </span>
          <span className="block text-sm text-muted">{p.hint}</span>
        </span>
        <span className={clsx("flex shrink-0 items-center gap-1.5 rounded-xl px-3.5 py-2.5 text-sm font-bold", file ? "border border-line" : "bg-brand text-white")}>
          <Camera className="size-4" /> {file ? "Retake" : "Take"}
        </span>
      </button>
      {error ? <p className="mt-1.5 text-sm font-medium text-bad">{error}</p> : null}
      <input
        ref={input}
        type="file"
        accept="image/*"
        capture={p.capture}
        className="hidden"
        aria-label={p.title}
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onPick(f);
          e.target.value = "";
        }}
      />
    </div>
  );
}

function Row({ label, value, onEdit }: { label: string; value: string; onEdit: () => void }) {
  return (
    <div className="flex items-start justify-between gap-3 py-2.5">
      <span className="min-w-0">
        <span className="block text-xs font-semibold text-muted uppercase">{label}</span>
        <span className="block font-medium break-words">{value}</span>
      </span>
      <button type="button" onClick={onEdit} aria-label={`Edit ${label}`} className="flex size-9 shrink-0 items-center justify-center rounded-lg text-muted hover:bg-subtle hover:text-brand">
        <Pencil className="size-4" />
      </button>
    </div>
  );
}

export function JoinPage() {
  const navigate = useNavigate();
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [f, setF] = useState<Details>(() => {
    const empty = { name: "", national_id: "", phone: "", residence_area: "", next_of_kin: "", next_of_kin_phone: "", password: "" };
    try {
      return { ...empty, ...JSON.parse(sessionStorage.getItem(DRAFT) ?? "{}"), password: "" };
    } catch {
      return empty;
    }
  });
  const [photos, setPhotos] = useState<Record<Kind, Blob | null>>({ id_front: null, id_back: null, selfie: null });
  const [consent, setConsent] = useState(false);
  const [errors, setErrors] = useState<Errors>({});
  const [busy, setBusy] = useState(false);

  // Keep typed details if the page reloads (never the password).
  useEffect(() => {
    try {
      const { password: _skip, ...rest } = f;
      sessionStorage.setItem(DRAFT, JSON.stringify(rest));
    } catch {
      /* private mode */
    }
  }, [f]);
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, [step]);

  const set = (k: keyof Details) => (e: React.ChangeEvent<HTMLInputElement>) => {
    setF({ ...f, [k]: k === "national_id" ? e.target.value.replace(/\D/g, "") : e.target.value });
    if (errors[k]) setErrors({ ...errors, [k]: undefined });
  };

  function next() {
    if (step === 1) {
      const e = checkDetails(f);
      setErrors(e);
      if (Object.keys(e).length) {
        document.querySelector<HTMLInputElement>(`[name="${Object.keys(e)[0]}"]`)?.focus();
        return;
      }
      setStep(2);
    } else if (step === 2) {
      const e: Errors = {};
      for (const p of PHOTOS) if (!photos[p.kind]) e[p.kind] = p.kind === "selfie" ? "Take your selfie." : `Take the ${p.title} photo.`;
      setErrors(e);
      if (!Object.keys(e).length) setStep(3);
    }
  }

  async function pick(kind: Kind, file: File) {
    setErrors({ ...errors, [kind]: undefined });
    try {
      setPhotos((ps) => ({ ...ps, [kind]: null }));
      const small = await compressImage(file);
      setPhotos((ps) => ({ ...ps, [kind]: small }));
    } catch {
      setErrors((e) => ({ ...e, [kind]: "That photo couldn't be read. Try again." }));
    }
  }

  async function submit() {
    if (!consent) {
      setErrors({ consent: "Tick the box to agree to the ID check." });
      return;
    }
    setBusy(true);
    setErrors({});
    const form = new FormData();
    for (const [k, v] of Object.entries(f)) form.append(k, k.endsWith("phone") ? (kenyanPhone(v) ?? v) : v.trim());
    form.append("consent", "true");
    for (const p of PHOTOS) form.append(p.kind, photos[p.kind]!, `${p.kind}.jpg`);
    try {
      auth.adopt(await request<Session>("POST", "/riders/apply", undefined, { form, auth: false }));
      sessionStorage.removeItem(DRAFT);
      navigate("/rider");
    } catch (err) {
      // Send the person back to the step and field that needs fixing.
      if (err instanceof ApiError) {
        const field = (err.extra?.field as string | undefined) ?? (err.fields?.[0]?.loc.at(-1) as string | undefined);
        if (field && STEP_OF[field]) {
          // A business message goes under its field; schema errors also get the summary.
          setErrors(err.fields?.length ? { [field]: "Please check this.", form: err.message } : { [field]: err.message });
          setStep(STEP_OF[field]);
        } else setErrors({ form: err.message });
      } else setErrors({ form: "Something went wrong. Please try again." });
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-lg flex-col p-4 pb-10">
      <div className="mb-5 flex items-center justify-between">
        <Link to="/" className="flex items-center gap-2 text-xl font-extrabold text-brand">
          <span className="flex size-10 items-center justify-center rounded-xl bg-brand text-white"><Bike className="size-5" /></span>
          Chakula Riders
        </Link>
        <ThemeToggle />
      </div>
      <h1 className="text-2xl font-bold">{step === 1 ? "Become a rider" : step === 2 ? "Take 3 photos" : "Check and send"}</h1>
      <p className="mb-5 text-[0.9375rem] text-muted">
        {step === 1
          ? "Deliver food in Bungoma town and get paid per trip. It takes about 3 minutes."
          : step === 2
            ? "Use your phone camera. We check every rider's ID before their first job."
            : "Make sure everything is right, then send your application."}
      </p>
      <Steps step={step} />

      {errors.form && step !== 3 ? <p role="alert" className="mb-4 rounded-xl bg-bad-soft px-4 py-3 text-sm font-semibold text-bad">{errors.form}</p> : null}

      {step === 1 ? (
        <form noValidate onSubmit={(e) => { e.preventDefault(); next(); }} className="flex flex-col gap-4 rounded-3xl bg-surface p-5 shadow-sm">
          <Field label="Full name (as on your ID)" error={errors.name}>{(id) => <Input id={id} name="name" value={f.name} onChange={set("name")} autoComplete="name" placeholder="e.g. Wafula Simiyu Barasa" aria-invalid={!!errors.name} />}</Field>
          <Field label="ID number" error={errors.national_id}>{(id) => <Input id={id} name="national_id" value={f.national_id} onChange={set("national_id")} inputMode="numeric" maxLength={9} placeholder="e.g. 30123456" aria-invalid={!!errors.national_id} />}</Field>
          <Field label="Your phone (M-Pesa)" error={errors.phone}>{(id) => <Input id={id} name="phone" type="tel" value={f.phone} onChange={set("phone")} inputMode="tel" autoComplete="tel" placeholder="0712 345 678" aria-invalid={!!errors.phone} />}</Field>
          <Field label="Where you live" hint="Estate or area, e.g. Kanduyi near the stage" error={errors.residence_area}>{(id) => <Input id={id} name="residence_area" value={f.residence_area} onChange={set("residence_area")} aria-invalid={!!errors.residence_area} />}</Field>
          <fieldset className="flex flex-col gap-4 rounded-2xl border border-line p-4">
            <legend className="px-1 text-sm font-bold">Next of kin</legend>
            <Field label="Their full name" error={errors.next_of_kin}>{(id) => <Input id={id} name="next_of_kin" value={f.next_of_kin} onChange={set("next_of_kin")} aria-invalid={!!errors.next_of_kin} />}</Field>
            <Field label="Their phone" error={errors.next_of_kin_phone}>{(id) => <Input id={id} name="next_of_kin_phone" type="tel" value={f.next_of_kin_phone} onChange={set("next_of_kin_phone")} inputMode="tel" placeholder="0712 345 678" aria-invalid={!!errors.next_of_kin_phone} />}</Field>
          </fieldset>
          <Field label="Create a password" hint="At least 8 characters. You'll use it to log in." error={errors.password}>{(id) => <Input id={id} name="password" type="password" value={f.password} onChange={set("password")} autoComplete="new-password" aria-invalid={!!errors.password} />}</Field>
          <Button type="submit" size="lg">Next: photos <ArrowRight className="size-5" /></Button>
        </form>
      ) : step === 2 ? (
        <div className="flex flex-col gap-3">
          {PHOTOS.map((p) => <PhotoPicker key={p.kind} p={p} file={photos[p.kind]} error={errors[p.kind]} onPick={(file) => void pick(p.kind, file)} />)}
          <div className="mt-2 grid grid-cols-[auto_1fr] gap-2">
            <Button variant="secondary" size="lg" onClick={() => setStep(1)}><ArrowLeft className="size-5" /> Back</Button>
            <Button size="lg" onClick={next}>Next: check <ArrowRight className="size-5" /></Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          <section className="rounded-3xl bg-surface p-5 shadow-sm">
            <div className="divide-y divide-line">
              <Row label="Full name" value={f.name.trim()} onEdit={() => setStep(1)} />
              <Row label="ID number" value={f.national_id} onEdit={() => setStep(1)} />
              <Row label="Phone (M-Pesa)" value={f.phone} onEdit={() => setStep(1)} />
              <Row label="Lives in" value={f.residence_area.trim()} onEdit={() => setStep(1)} />
              <Row label="Next of kin" value={`${f.next_of_kin.trim()} · ${f.next_of_kin_phone}`} onEdit={() => setStep(1)} />
            </div>
          </section>
          <section className="grid grid-cols-3 gap-2">
            {PHOTOS.map((p) => (
              <button key={p.kind} type="button" onClick={() => setStep(2)} className="flex flex-col gap-1.5 text-center">
                <Thumb blob={photos[p.kind]} />
                <span className="text-xs font-semibold">{p.title}</span>
              </button>
            ))}
          </section>
          <label className={clsx("flex items-start gap-3 rounded-2xl border-2 bg-surface p-4 text-sm", errors.consent ? "border-bad" : "border-line")}>
            <input type="checkbox" checked={consent} onChange={(e) => { setConsent(e.target.checked); setErrors({}); }} className="mt-0.5 size-6 shrink-0 accent-[var(--color-brand)]" />
            <span>
              I agree that Chakula keeps my ID photos and selfie to confirm who I am and to keep customers safe. Only the Chakula team can see them. I can ask for them to be deleted when I stop riding.
            </span>
          </label>
          {errors.consent ? <p className="-mt-2 text-sm font-medium text-bad">{errors.consent}</p> : null}
          {errors.form ? <p role="alert" className="rounded-xl bg-bad-soft px-4 py-3 text-sm font-semibold text-bad">{errors.form}</p> : null}
          <div className="grid grid-cols-[auto_1fr] gap-2">
            <Button variant="secondary" size="lg" onClick={() => setStep(2)} disabled={busy}><ArrowLeft className="size-5" /> Back</Button>
            <Button size="lg" onClick={() => void submit()} busy={busy}>{busy ? "Sending…" : "Submit application"}</Button>
          </div>
          <p className="flex items-start gap-2 text-xs text-muted">
            <ShieldCheck className="mt-0.5 size-4 shrink-0 text-ok" /> Your ID is seen only by the Chakula team, never by hotels or customers.
          </p>
        </div>
      )}

      <p className="mt-6 text-center text-sm text-muted">
        Already applied? <Link to="/login" className="font-semibold text-brand hover:underline">Log in</Link>
      </p>
    </main>
  );
}

function Thumb({ blob }: { blob: Blob | null }) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!blob) return;
    const u = URL.createObjectURL(blob);
    setUrl(u);
    return () => URL.revokeObjectURL(u);
  }, [blob]);
  return <span className="block aspect-square overflow-hidden rounded-xl bg-subtle">{url ? <img src={url} alt="" className="size-full object-cover" /> : null}</span>;
}

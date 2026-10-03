/** Super admin tools: every hotel's Till phone (SMS forwarder app, M8), and a payment simulator
 * for testing: paste a real Till SMS and it runs through the same parser and matching. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { FlaskConical, Smartphone } from "lucide-react";
import { useState } from "react";

import { PairingBox, PhoneCard, type TillPhone, useUnpair } from "../components/TillPhones";
import { ErrorNote, Skeleton } from "../components/ui";
import { api } from "../lib/api";

type Hotel = { id: string; name: string; till_number: string };

function Simulator() {
  const qc = useQueryClient();
  const hotels = useQuery({ queryKey: ["admin", "hotels"], queryFn: () => api.get<{ items: Hotel[] }>("/admin/hotels?limit=100") });
  const [till, setTill] = useState("");
  const [code, setCode] = useState("");
  const [amount, setAmount] = useState("");
  const [kind, setKind] = useState<"sms" | "payment" | "reversal">("sms");
  const [raw, setRaw] = useState("");
  const send = useMutation({
    mutationFn: () =>
      kind === "sms"
        ? api.post<{ result: string; message?: string; parse_status?: string; code?: string; amount?: number }>("/admin/test-sms", { till_number: till, raw_text: raw })
        : api.post<{ result: string; message?: string; parse_status?: string; code?: string; amount?: number }>("/admin/test-payment", { till_number: till, code, amount: Number(amount) || 1, kind }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "reviews"] }),
  });
  return (
    <section className="rounded-3xl border border-line bg-surface p-5">
      <h2 className="flex items-center gap-2 text-[1rem] font-bold"><FlaskConical className="size-5 text-brand" /> Test payment</h2>
      <p className="mb-4 text-sm text-muted">Paste a real Till SMS (or fake one) and it runs through the parser and matching exactly as the SMS app (M8) will send it.</p>
      <div className="flex flex-col gap-2.5">
        <select aria-label="Till" value={till} onChange={(e) => setTill(e.target.value)} className="h-11 rounded-xl border border-line bg-surface px-3 text-sm">
          <option value="">Choose a hotel's Till…</option>
          {hotels.data?.items.map((h) => <option key={h.id} value={h.till_number}>{h.name} · {h.till_number}</option>)}
        </select>
        <div className="grid grid-cols-3 gap-1 rounded-xl bg-subtle p-1 text-sm font-semibold">
          {(
            [
              ["sms", "Paste SMS"],
              ["payment", "Payment"],
              ["reversal", "Reversal"],
            ] as const
          ).map(([k, label]) => (
            <button key={k} onClick={() => setKind(k)} className={clsx("h-9 rounded-lg", kind === k ? "bg-surface shadow-sm" : "text-muted")}>{label}</button>
          ))}
        </div>
        {kind === "sms" ? (
          <textarea
            aria-label="M-Pesa SMS text"
            placeholder="Paste the whole M-Pesa message from the Till phone…"
            value={raw}
            onChange={(e) => setRaw(e.target.value)}
            rows={5}
            className="rounded-xl border border-line bg-surface p-3 text-sm outline-none focus:border-brand"
          />
        ) : null}
        {kind !== "sms" ? <input aria-label="M-Pesa code" placeholder="Code e.g. SJK3ABC12D" value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} className="money h-11 rounded-xl border border-line bg-surface px-3 font-bold tracking-wider outline-none focus:border-brand" /> : null}
        {kind === "payment" ? (
          <input aria-label="Amount" inputMode="numeric" placeholder="Amount KES" value={amount} onChange={(e) => setAmount(e.target.value.replace(/\D/g, ""))} className="money h-11 rounded-xl border border-line bg-surface px-3 font-bold outline-none focus:border-brand" />
        ) : null}
        <button onClick={() => send.mutate()} disabled={!till || send.isPending || (kind === "sms" ? raw.trim().length < 20 : code.length !== 10 || (kind === "payment" && !amount))} className="h-11 rounded-xl bg-brand font-semibold text-white disabled:bg-line disabled:text-muted">
          {kind === "sms" ? "Read and match this SMS" : `Send test ${kind}`}
        </button>
        {send.data ? (
          <p className={clsx("rounded-xl px-3 py-2 text-sm font-medium", send.data.result === "paid" ? "bg-ok-soft text-ok" : "bg-subtle")}>
            {send.data.parse_status ? (
              <>
                Read: <strong>{send.data.parse_status}</strong>
                {send.data.code ? ` · ${send.data.code}` : ""}
                {send.data.amount != null ? ` · KES ${send.data.amount}` : ""}
                <br />
              </>
            ) : null}
            Result: <strong>{send.data.result}</strong>{send.data.message ? `: ${send.data.message}` : ""}
          </p>
        ) : null}
        <ErrorNote error={send.error} />
      </div>
    </section>
  );
}

const PHONES = ["admin", "forwarder"];

function TillPhones() {
  const q = useQuery({ queryKey: PHONES, queryFn: () => api.get<{ devices: TillPhone[]; unpaired_hotels: { id: string; name: string }[] }>("/admin/forwarder"), refetchInterval: 30_000 });
  const unpair = useUnpair((id) => `/admin/forwarder/${id}`, PHONES);
  const [pairFor, setPairFor] = useState("");
  const devices = q.data?.devices ?? [];
  const bad = devices.filter((d) => d.problems.length).length;
  return (
    <section className="rounded-3xl border border-line bg-surface p-5">
      <h2 className="flex items-center gap-2 text-[1rem] font-bold">
        <Smartphone className="size-5 text-brand" /> Till phones
        <span className={clsx("rounded-full px-2.5 py-0.5 text-xs font-semibold", bad ? "bg-bad-soft text-bad" : "bg-ok-soft text-ok")}>
          {devices.length - bad} of {devices.length} working
        </span>
      </h2>
      <p className="mb-4 text-sm text-muted">Each hotel's Till phone sends its M-Pesa messages, so payments confirm by themselves.</p>
      {q.isLoading ? <Skeleton className="h-24" /> : null}
      <div className="flex flex-col gap-3">
        {devices.map((d) => (
          <PhoneCard key={d.id} d={d} unpairing={unpair.isPending} onUnpair={() => window.confirm(`Disconnect ${d.hotel_name}'s phone?`) && unpair.mutate(d.id)} />
        ))}
      </div>
      {q.data?.unpaired_hotels.length ? (
        <div className="mt-4">
          <p className="mb-2 text-sm font-semibold text-warn">No phone yet: {q.data.unpaired_hotels.map((h) => h.name).join(", ")}</p>
          <select aria-label="Pair a phone for" value={pairFor} onChange={(e) => setPairFor(e.target.value)} className="mb-3 h-11 w-full rounded-xl border border-line bg-surface px-3 text-sm sm:w-80">
            <option value="">Pair a phone for…</option>
            {q.data.unpaired_hotels.map((h) => <option key={h.id} value={h.id}>{h.name}</option>)}
          </select>
          {pairFor ? <PairingBox key={pairFor} create={() => api.post("/admin/forwarder/pairing", { hotel_id: pairFor })} invalidate={PHONES} /> : null}
        </div>
      ) : null}
      <ErrorNote error={unpair.error} />
    </section>
  );
}

export function ToolsPage() {
  return (
    <div className="flex flex-col gap-5 p-4 sm:p-6">
      <div>
        <h1 className="text-2xl font-bold">Tools</h1>
        <p className="text-sm text-muted">Till phones, and a payment simulator for testing.</p>
      </div>
      <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
        <TillPhones />
        <Simulator />
      </div>
    </div>
  );
}

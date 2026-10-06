"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Upload } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type {
  HoldingsSnapshotOut,
  V4Account,
  V4AccountPositions,
  V4Coverage,
  V4Import,
  V4Preview,
  V4ImportChange,
  V4Reconcile,
} from "@/lib/types";
import Card from "@/components/ui/Card";
import Button from "@/components/ui/Button";
import EmptyState from "@/components/ui/EmptyState";
import AngelPanel from "@/components/holdings/AngelPanel";
import { Wallet } from "lucide-react";

const INPUT =
  "mt-1 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent";

const ASSET_TYPES = ["listed_equity", "etf", "mutual_fund", "deposit", "gold", "cash", "other"];
const IDENTIFIED = new Set(["listed_equity", "etf", "mutual_fund"]);

const CSV_TEMPLATE =
  "asset_type,isin,symbol,description,units,value,valuation_date,cost_basis,locked,ownership\n" +
  "listed_equity,INE002A01018,RELIANCE,,10,25000.50,2026-09-01,,false,sole\n" +
  "deposit,,,SBI fixed deposit,,100000,2026-09-01,,true,sole\n";

const RESOLUTION_LABEL: Record<string, string> = {
  resolved: "Matched",
  ambiguous: "Needs confirmation",
  unresolved: "Unmatched",
  not_applicable: "n/a",
};

function rupees(v: string | null): string {
  if (v === null) return "unknown";
  const n = Number(v);
  return Number.isNaN(n) ? "unknown" : `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
}

function errMsg(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

type RawRow = Record<string, string>;

function ImportBox({ account, onDone }: { account: V4Account; onDone: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [rows, setRows] = useState<RawRow[]>([]);
  const [form, setForm] = useState({
    asset_type: "listed_equity",
    isin: "",
    name: "",
    units: "",
    value: "",
    valuation_date: new Date().toISOString().slice(0, 10),
  });
  const [preview, setPreview] = useState<V4Preview | null>(null);
  const [key, setKey] = useState<string | null>(null);
  const [ack, setAck] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<V4Import | null>(null);
  // Bumped to remount the file input, so choosing the same file again fires onChange.
  const [fileInputKey, setFileInputKey] = useState(0);

  function reset() {
    setPreview(null);
    setKey(null);
    setAck(false);
    setResult(null);
    setError(null);
  }

  function addRow() {
    reset();
    if (!form.name.trim() && !form.isin.trim()) {
      setError("Enter an ISIN or a symbol/name.");
      return;
    }
    const identified = IDENTIFIED.has(form.asset_type);
    setRows((r) => [
      ...r,
      {
        asset_type: form.asset_type,
        isin: form.isin.trim(),
        symbol: identified ? form.name.trim() : "",
        description: identified ? "" : form.name.trim(),
        units: form.units.trim(),
        value: form.value.trim(),
        valuation_date: form.valuation_date,
      },
    ]);
    setForm({ ...form, isin: "", name: "", units: "", value: "" });
  }

  async function runPreview() {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      let res: V4Preview;
      if (file) {
        const fd = new FormData();
        fd.append("account_id", account.id);
        fd.append("file", file);
        res = await api.postMultipart<V4Preview>("/api/v4/imports/csv/preview", fd);
      } else {
        res = await api.post<V4Preview>("/api/v4/imports/manual/preview", { account_id: account.id, rows });
      }
      setPreview(res);
      setKey(crypto.randomUUID()); // one key per previewed content: a retried confirm replays, never duplicates
      setAck(false);
    } catch (err) {
      setPreview(null);
      setError(errMsg(err, "Preview failed"));
    } finally {
      setBusy(false);
    }
  }

  async function confirm() {
    if (!key) return;
    setBusy(true);
    setError(null);
    try {
      let res: V4Import;
      if (file) {
        const fd = new FormData();
        fd.append("account_id", account.id);
        fd.append("idempotency_key", key);
        fd.append("acknowledge_conflicts", String(ack));
        fd.append("file", file);
        res = await api.postMultipart<V4Import>("/api/v4/imports/csv/confirm", fd);
      } else {
        res = await api.post<V4Import>("/api/v4/imports/manual/confirm", {
          account_id: account.id,
          rows,
          idempotency_key: key,
          acknowledge_conflicts: ack,
        });
      }
      setResult(res);
      setPreview(null);
      setKey(null);
      setRows([]);
      setFile(null);
      setFileInputKey((k) => k + 1);
      onDone();
    } catch (err) {
      setError(errMsg(err, "Import failed"));
    } finally {
      setBusy(false);
    }
  }

  function downloadTemplate() {
    const url = URL.createObjectURL(new Blob([CSV_TEMPLATE], { type: "text/csv" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "holdings-template.csv";
    a.click();
    URL.revokeObjectURL(url);
  }

  const rec = preview?.reconcile ?? null;
  const removesHoldings = (rec?.removed.length ?? 0) > 0;
  const needsAck = (preview?.conflicts.length ?? 0) > 0 || removesHoldings;

  return (
    <div className="mt-4 space-y-3 border-t border-border pt-4">
      <p className="text-sm font-medium text-text-primary">
        Replace holdings in “{account.label}” <span className="text-text-muted">(a new import replaces this account only)</span>
      </p>

      <div className="flex flex-wrap items-center gap-3">
        <label className="inline-flex cursor-pointer items-center gap-2 rounded-md border border-border bg-surface px-3 py-1.5 text-xs font-medium text-text-primary hover:bg-bg focus-within:ring-2 focus-within:ring-accent">
          <Upload className="h-4 w-4" /> {file ? file.name : "Choose CSV file"}
          <input
            key={fileInputKey}
            type="file"
            accept=".csv,text/csv"
            className="sr-only"
            onChange={(e) => {
              reset();
              setFile(e.target.files?.[0] ?? null);
              setRows([]);
            }}
          />
        </label>
        <button type="button" onClick={downloadTemplate} className="text-xs text-accent hover:underline">
          Download CSV template
        </button>
        {file && (
          <button type="button" onClick={() => { reset(); setFile(null); setFileInputKey((k) => k + 1); }} className="text-xs text-negative hover:underline">
            Clear file
          </button>
        )}
      </div>

      {!file && (
        <>
          <p className="text-xs text-text-muted">…or add rows by hand:</p>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
            <label className="text-sm text-text-primary">
              Type
              <select className={INPUT} value={form.asset_type} onChange={(e) => setForm({ ...form, asset_type: e.target.value })}>
                {ASSET_TYPES.map((t) => (
                  <option key={t} value={t}>{t.replace("_", " ")}</option>
                ))}
              </select>
            </label>
            <label className="text-sm text-text-primary">
              ISIN (optional)
              <input className={INPUT} value={form.isin} onChange={(e) => setForm({ ...form, isin: e.target.value })} placeholder="INE002A01018" />
            </label>
            <label className="text-sm text-text-primary">
              Symbol / name
              <input className={INPUT} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </label>
            <label className="text-sm text-text-primary">
              Units
              <input className={INPUT} inputMode="decimal" value={form.units} onChange={(e) => setForm({ ...form, units: e.target.value })} />
            </label>
            <label className="text-sm text-text-primary">
              Value (₹)
              <input className={INPUT} inputMode="decimal" value={form.value} onChange={(e) => setForm({ ...form, value: e.target.value })} />
            </label>
            <label className="text-sm text-text-primary">
              Valuation date
              <input type="date" className={INPUT} value={form.valuation_date} onChange={(e) => setForm({ ...form, valuation_date: e.target.value })} />
            </label>
          </div>
          <Button variant="secondary" size="sm" onClick={addRow}>Add row</Button>
          {rows.length > 0 && (
            <ul className="text-xs text-text-muted">
              {rows.map((r, i) => (
                <li key={i}>
                  {i + 1}. {r.asset_type} · {r.isin || r.symbol || r.description} · units {r.units || "-"} · value {r.value || "-"}{" "}
                  <button className="text-negative hover:underline" onClick={() => { reset(); setRows((x) => x.filter((_, j) => j !== i)); }}>
                    remove
                  </button>
                </li>
              ))}
            </ul>
          )}
        </>
      )}

      <div className="flex gap-2">
        <Button size="sm" onClick={runPreview} loading={busy} disabled={!file && rows.length === 0}>
          Preview import
        </Button>
        {preview?.can_confirm && (
          <Button size="sm" variant="secondary" onClick={confirm} loading={busy} disabled={needsAck && !ack}>
            {rec && rec.previous_row_count > 0 ? "Confirm replacement" : "Confirm import"}
          </Button>
        )}
      </div>

      {error && <p role="alert" className="text-sm text-negative">{error}</p>}

      {preview && (
        <div className="space-y-2 rounded-md border border-border bg-bg p-3 text-sm" aria-live="polite">
          <p className="text-text-muted">
            {preview.row_count} row(s) · {preview.errors.length} error(s) · {preview.unresolved_count} without a confirmed instrument match
          </p>
          {preview.errors.length > 0 && (
            <div className="flex items-start gap-2 text-negative">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <ul className="list-inside list-disc">
                {preview.errors.map((e, i) => (
                  <li key={i}>Row {e.row}, {e.field}: {e.message}</li>
                ))}
              </ul>
            </div>
          )}
          {rec && <ReconcileSummary rec={rec} ack={ack} setAck={setAck} />}
          {(preview.conflicts.length > 0) && (
            <div className="flex items-start gap-2 text-warning">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <div>
                <ul className="list-inside list-disc">
                  {preview.conflicts.map((c, i) => (
                    <li key={i}>Row {c.row}: {c.detail}</li>
                  ))}
                </ul>
                <label className="mt-1 flex items-center gap-2 text-text-primary">
                  <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
                  These are intentional (e.g. separate lots)
                </label>
              </div>
            </div>
          )}
          {preview.rows.length > 0 && (
            <div tabIndex={0} className="overflow-x-auto">
              <table className="w-full text-xs">
                <caption className="sr-only">Import preview</caption>
                <thead>
                  <tr className="border-b border-border text-left text-text-muted">
                    <th scope="col" className="py-1 pr-3">Row</th>
                    <th scope="col" className="py-1 pr-3">Identifier</th>
                    <th scope="col" className="py-1 pr-3">Value</th>
                    <th scope="col" className="py-1">Instrument match</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.rows.map((r) => (
                    <tr key={r.ordinal} className="border-b border-border last:border-0">
                      <td className="py-1 pr-3">{r.ordinal}</td>
                      <td className="py-1 pr-3 text-text-primary">{r.raw_identifier}</td>
                      <td className="py-1 pr-3 text-text-muted">{rupees(r.value)}</td>
                      <td className="py-1 text-text-muted">
                        {RESOLUTION_LABEL[r.resolution]}
                        {r.resolution_note ? ` (${r.resolution_note.replace(/_/g, " ")})` : ""}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {result && (
        <p role="status" className="text-sm text-positive">
          {result.replayed ? "This import was already saved; nothing changed." : `Saved ${result.row_count} holding(s) to “${account.label}”.`}
        </p>
      )}
    </div>
  );
}

function AccountCard({ account, onChanged, legacy }: { account: V4Account; onChanged: () => void; legacy: HoldingsSnapshotOut | null }) {
  const [positions, setPositions] = useState<V4AccountPositions | null>(null);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .get<V4AccountPositions>(`/api/v4/accounts/${account.id}/positions`)
      .then(setPositions)
      .catch((e) => setError(errMsg(e, "Failed to load positions")));
  }, [account.id, account.latest_import?.id]);

  useEffect(() => {
    load();
  }, [load]);

  async function toggleIncluded() {
    try {
      await api.put(`/api/v4/accounts/${account.id}`, { expected_version: account.version, included: !account.included });
      onChanged();
    } catch (e) {
      setError(errMsg(e, "Update failed"));
      if (e instanceof ApiError && e.status === 409) onChanged();
    }
  }

  async function adopt() {
    if (!legacy) return;
    try {
      await api.post(`/api/v4/accounts/${account.id}/adopt-legacy-snapshot`, { snapshot_id: legacy.id });
      onChanged();
    } catch (e) {
      setError(errMsg(e, "Adoption failed"));
    }
  }

  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="font-medium text-text-primary">{account.label}</h3>
          <p className="text-xs text-text-muted">
            {account.source_type} ·{" "}
            {account.latest_import
              ? `last import ${new Date(account.latest_import.created_at).toLocaleString("en-IN")} (${account.latest_import.row_count} rows)`
              : "no import yet"}
            {!account.included && " · excluded from portfolio"}
          </p>
        </div>
        <div className="flex gap-2">
          <Button size="sm" variant="secondary" onClick={toggleIncluded}>
            {account.included ? "Exclude" : "Include"}
          </Button>
          {account.source_type !== "angel_one" && (
            <Button size="sm" variant="secondary" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
              {open ? "Close import" : "Import holdings"}
            </Button>
          )}
        </div>
      </div>
      {error && <p role="alert" className="mt-2 text-sm text-negative">{error}</p>}

      {positions && positions.positions.length > 0 && (
        <details className="mt-3">
          <summary className="cursor-pointer text-sm text-text-muted">
            {positions.positions.length} holding(s) in this account · already included in the portfolio table above
          </summary>
        <div tabIndex={0} className="mt-2 overflow-x-auto">
          <table className="w-full text-sm">
            <caption className="sr-only">Holdings in {account.label}</caption>
            <thead>
              <tr className="border-b border-border text-left text-text-muted">
                <th scope="col" className="py-1 pr-4">Holding</th>
                <th scope="col" className="py-1 pr-4">Type</th>
                <th scope="col" className="py-1 pr-4">Units</th>
                <th scope="col" className="py-1 pr-4">Value</th>
                <th scope="col" className="py-1 pr-4">As of</th>
                <th scope="col" className="py-1">Match</th>
              </tr>
            </thead>
            <tbody>
              {positions.positions.map((p) => (
                <tr key={p.row_ordinal} className="border-b border-border last:border-0">
                  <td className="py-1 pr-4 font-medium text-text-primary">{p.security_id ? <Link href={`/market/${p.security_id}`} className="hover:text-accent hover:underline">{p.display_name ?? p.raw_identifier ?? "unknown"}</Link> : (p.display_name ?? p.raw_identifier ?? "unknown")}</td>
                  <td className="py-1 pr-4 text-text-muted">{p.asset_type.replace("_", " ")}</td>
                  <td className="py-1 pr-4 text-text-muted">{p.units ? Number(p.units) : "-"}</td>
                  <td className="py-1 pr-4 text-text-muted">{rupees(p.value)}</td>
                  <td className="py-1 pr-4 text-text-muted">{p.valuation_date}</td>
                  <td className="py-1 text-text-muted">{p.identity === "catalogue" ? "Recognised in the market list" : RESOLUTION_LABEL[p.resolution]}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        </details>
      )}

      {legacy && !account.latest_import && account.source_type !== "angel_one" && (
        <div className="mt-3">
          <Button size="sm" variant="secondary" onClick={adopt}>
            Copy my old snapshot ({legacy.positions.length} rows) into this account
          </Button>
        </div>
      )}

      {open && <ImportBox account={account} onDone={() => { onChanged(); load(); }} />}
    </Card>
  );
}

function qty(c: V4ImportChange, side: "before" | "after"): string {
  const u = side === "before" ? c.before_units : c.after_units;
  const v = side === "before" ? c.before_value : c.after_value;
  if (u && v) return `${u} units, ${rupees(v)}`;
  if (u) return `${u} units`;
  return v ? rupees(v) : "no amount";
}

function ReconcileSummary({ rec, ack, setAck }: { rec: V4Reconcile; ack: boolean; setAck: (b: boolean) => void }) {
  if (rec.previous_row_count === 0) {
    return <p className="text-text-muted">This is the first import into this account: {rec.added.length} holding(s) will be added.</p>;
  }
  const none = rec.added.length === 0 && rec.removed.length === 0 && rec.changed.length === 0;
  return (
    <div className="rounded-md border border-border bg-surface p-3" aria-label="What this replacement changes">
      <p className="font-medium text-text-primary">
        What this replaces{rec.previous_import_at ? ` (your import of ${new Date(rec.previous_import_at).toLocaleDateString("en-IN")}, ${rec.previous_row_count} rows)` : ""}
      </p>
      {none ? (
        <p className="mt-1 text-text-muted">Identical to what is saved: {rec.unchanged} holding(s) unchanged. Saving again changes nothing.</p>
      ) : (
        <>
          <p className="mt-1 text-text-muted">
            {rec.added.length} added · {rec.changed.length} changed · {rec.removed.length} removed · {rec.unchanged} unchanged
          </p>
          {rec.removed.length > 0 && (
            <div className="mt-2">
              <p className="font-medium text-warning">Removed from this account</p>
              <ul className="list-inside list-disc text-text-muted">
                {rec.removed.map((c, i) => <li key={i}>{c.identifier}: {qty(c, "before")}{c.goal_claims > 0 ? ` · ${c.goal_claims} goal set-aside(s) will be flagged for your review` : ""}</li>)}
              </ul>
            </div>
          )}
          {rec.changed.length > 0 && (
            <div className="mt-2">
              <p className="font-medium text-text-primary">Changed</p>
              <ul className="list-inside list-disc text-text-muted">
                {rec.changed.map((c, i) => <li key={i}>{c.identifier}: {qty(c, "before")} → {qty(c, "after")}{c.goal_claims > 0 ? ` · ${c.goal_claims} goal set-aside(s) re-checked` : ""}</li>)}
              </ul>
            </div>
          )}
          {rec.added.length > 0 && (
            <div className="mt-2">
              <p className="font-medium text-text-primary">Added</p>
              <ul className="list-inside list-disc text-text-muted">
                {rec.added.map((c, i) => <li key={i}>{c.identifier}: {qty(c, "after")}</li>)}
              </ul>
            </div>
          )}
          {rec.removed.length > 0 && (
            <label className="mt-2 flex items-center gap-2 text-text-primary">
              <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
              I understand the removed holdings will leave this account. Other accounts are not affected.
            </label>
          )}
        </>
      )}
    </div>
  );
}

export default function AccountsPanel({ onChanged }: { onChanged?: () => void } = {}) {
  const [accounts, setAccounts] = useState<V4Account[] | null>(null);
  const [coverage, setCoverage] = useState<V4Coverage | null>(null);
  const [legacy, setLegacy] = useState<HoldingsSnapshotOut | null>(null);
  const [label, setLabel] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [missing, setMissing] = useState("");

  const load = useCallback(() => {
    onChanged?.();
    api.get<V4Account[]>("/api/v4/accounts").then(setAccounts).catch((e) => setError(errMsg(e, "Failed to load accounts")));
    api.get<V4Coverage>("/api/v4/account-coverage").then(setCoverage).catch(() => undefined);
    api
      .get<HoldingsSnapshotOut>("/api/holdings/latest")
      .then(setLegacy)
      .catch(() => setLegacy(null));
  }, [onChanged]);

  useEffect(() => {
    load();
  }, [load]);

  async function createAccount() {
    setError(null);
    try {
      await api.post("/api/v4/accounts", { label, source_type: "manual" });
      setLabel("");
      load();
    } catch (e) {
      setError(errMsg(e, "Could not create account"));
    }
  }

  async function saveCoverage(status: V4Coverage["status"]) {
    if (!coverage) return;
    setError(null);
    try {
      const list = status === "partial" ? missing.split(",").map((s) => s.trim()).filter(Boolean) : [];
      setCoverage(
        await api.put<V4Coverage>("/api/v4/account-coverage", {
          expected_version: coverage.version,
          status,
          missing_account_types: list,
        })
      );
    } catch (e) {
      setError(errMsg(e, "Could not save"));
      load();
    }
  }

  return (
    <section className="space-y-4" aria-labelledby="accounts-heading">
      <div>
        <h2 id="accounts-heading" className="text-lg font-semibold text-text-primary">Accounts</h2>
        <p className="text-sm text-text-muted">
          Each source (broker, bank, gold, deposits…) is its own account. Importing into one account never changes another.
        </p>
      </div>

      <Card title="Are all your investments here?">
        <p className="mb-2 text-sm text-text-muted">
          Current answer: <strong className="text-text-primary">{coverage?.status ?? "…"}</strong>
          {coverage && coverage.missing_account_types.length > 0 && ` · missing: ${coverage.missing_account_types.join(", ")}`}
          {" · "}until you confirm all accounts are added, totals are “known portfolio value”, not your total wealth.
        </p>
        <div className="flex flex-wrap items-end gap-2">
          <Button size="sm" variant="secondary" onClick={() => saveCoverage("complete")}>Yes, everything is added</Button>
          <label className="text-xs text-text-muted">
            Missing (comma separated)
            <input className={INPUT} value={missing} onChange={(e) => setMissing(e.target.value)} placeholder="mutual funds, PPF" />
          </label>
          <Button size="sm" variant="secondary" onClick={() => saveCoverage("partial")}>Some are missing</Button>
        </div>
      </Card>

      <AngelPanel onSynced={load} />

      {error && <p role="alert" className="text-sm text-negative">{error}</p>}

      {accounts && accounts.length === 0 ? (
        <EmptyState icon={Wallet} title="No accounts yet" message="Create an account below, then import holdings from a CSV or by hand." />
      ) : (
        <div className="space-y-3">
          {accounts?.map((a) => (
            <AccountCard key={a.id} account={a} onChanged={load} legacy={legacy} />
          ))}
        </div>
      )}

      <Card title="Add an account">
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-sm text-text-primary">
            Name
            <input className={INPUT} value={label} onChange={(e) => setLabel(e.target.value)} placeholder="e.g. Zerodha, Bank FDs, Gold" />
          </label>
          <Button size="sm" onClick={createAccount} disabled={!label.trim()}>Create account</Button>
        </div>
        <p className="mt-2 text-xs text-text-muted">Angel One is connected from a terminal on this computer (see above), not created here. For anything else, add an account and import it by CSV or by hand.</p>
      </Card>
    </section>
  );
}

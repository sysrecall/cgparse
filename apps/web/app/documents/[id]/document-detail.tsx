"use client";

import Link from "next/link";
import { useState, type ReactNode } from "react";

import { ConfidenceBadge } from "@/components/ConfidenceBadge";
import { DetailSkeleton } from "@/components/Skeletons";
import { StatusBadge } from "@/components/StatusBadge";
import {
  FIELD_LABELS,
  HEADER_FIELD_ORDER,
  MONEY_FIELDS,
  SOURCE_KIND_LABELS,
  type DocumentDetail as DocumentDetailData,
  type LineItem,
  type ValidationFinding,
  formatBytes,
  formatDate,
  reprocessDocument,
  submitCorrection,
  useDocument,
  useDocumentSource,
} from "@/lib/api";

interface LineItemDraft {
  description: string;
  quantity: string;
  unit_price: string;
  amount: string;
}

function toDraft(item: LineItem): LineItemDraft {
  return {
    description: item.description ?? "",
    quantity: item.quantity === null ? "" : String(item.quantity),
    unit_price: item.unit_price === null ? "" : String(item.unit_price),
    amount: item.amount === null ? "" : String(item.amount),
  };
}

function emptyDraft(): LineItemDraft {
  return { description: "", quantity: "", unit_price: "", amount: "" };
}

export function DocumentDetail({ id }: { id: string }) {
  const { data, error, isLoading, mutate } = useDocument(id);
  const { data: source, mutate: mutateSource } = useDocumentSource(id);

  const [reprocessing, setReprocessing] = useState<"parse" | "extract" | null>(
    null,
  );
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  if (isLoading && !data) return <DetailSkeleton />;

  if (error || !data) {
    return (
      <div className="container-page py-20">
        <div className="card mx-auto max-w-lg p-8 text-center">
          <h2 className="text-[24px]">Document not found</h2>
          <p className="mt-2 text-[15px] text-body">
            {error?.message ?? "This document does not exist."}
          </p>
          <Link href="/documents" className="btn-primary mt-5">
            Back to documents
          </Link>
        </div>
      </div>
    );
  }

  const findings: ValidationFinding[] = data.validation_results;
  const busy = data.status === "queued" || data.status === "processing";
  const editable = Boolean(data.extraction) && !busy;

  async function reprocess(from: "parse" | "extract") {
    const message =
      from === "parse"
        ? "Re-run parsing, extraction, validation and indexing? Human edits are preserved."
        : "Re-run extraction, validation and indexing from the parsed text? Human edits are preserved.";
    if (!window.confirm(message)) return;
    setReprocessing(from);
    setActionError(null);
    setNotice(null);
    try {
      await reprocessDocument(id, from);
      await Promise.all([mutate(), mutateSource()]);
      setNotice("Reprocess queued. This page updates automatically.");
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Could not reprocess");
    } finally {
      setReprocessing(null);
    }
  }

  return (
    <div className="container-page py-8">
      <Link
        href="/documents"
        className="inline-flex items-center gap-1.5 text-[14px] font-medium text-body transition-colors hover:text-primary"
      >
        <svg
          width="15"
          height="15"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M19 12H5M11 18l-6-6 6-6" />
        </svg>
        All documents
      </Link>

      {/* Header */}
      <div className="card mt-4 p-6">
        <div className="flex flex-wrap items-start justify-between gap-5">
          <div className="min-w-0">
            <h1 className="break-words text-[26px] leading-tight md:text-[32px]">
              {data.original_filename}
            </h1>
            <div className="mt-3 flex flex-wrap items-center gap-2 text-[13px] text-body">
              <StatusBadge status={data.status} />
              <MetaChip>
                {SOURCE_KIND_LABELS[data.source_kind] ?? data.source_kind}
              </MetaChip>
              <MetaChip>{formatBytes(data.size_bytes)}</MetaChip>
              {data.page_count !== null ? (
                <MetaChip>
                  {data.page_count} page{data.page_count === 1 ? "" : "s"}
                </MetaChip>
              ) : null}
              <MetaChip>Uploaded {formatDate(data.created_at)}</MetaChip>
              {data.ocr_confidence !== null ? (
                <MetaChip>
                  OCR {Math.round(data.ocr_confidence * 100)}%
                </MetaChip>
              ) : null}
            </div>
          </div>
          <div className="text-right">
            <ConfidenceBadge
              value={data.extraction?.document_confidence}
              showLabel
            />
            <p className="mt-1 text-[12px] text-muted">
              {data.extraction
                ? `Model: ${data.extraction.extraction_model}`
                : "No extraction yet"}
            </p>
          </div>
        </div>

        {data.failure_reason ? (
          <div className="mt-4 rounded-md border border-[#f5c2c7] bg-[#fdecee] px-4 py-3 text-[14px] text-danger">
            <strong className="font-medium">Pipeline failed:</strong>{" "}
            {data.failure_reason}
          </div>
        ) : null}

        {busy ? (
          <div className="mt-4 flex items-center gap-2 rounded-md border border-[#bfe3e8] bg-[#e8f6f8] px-4 py-3 text-[14px] text-info">
            <span className="h-2 w-2 animate-pulse rounded-full bg-current" />
            The pipeline is working on this document. This page refreshes
            automatically.
          </div>
        ) : null}

        <div className="mt-5 flex flex-wrap items-center gap-2 border-t border-line pt-5">
          <span className="mr-1 text-[13px] font-medium text-heading">
            Reprocess:
          </span>
          <button
            type="button"
            className="btn-ghost !px-4 !py-2 !text-[14px]"
            disabled={busy || reprocessing !== null}
            onClick={() => void reprocess("extract")}
          >
            {reprocessing === "extract" ? "Queueing…" : "From extract"}
          </button>
          <button
            type="button"
            className="btn-ghost !px-4 !py-2 !text-[14px]"
            disabled={busy || reprocessing !== null}
            onClick={() => void reprocess("parse")}
          >
            {reprocessing === "parse" ? "Queueing…" : "From parse"}
          </button>
          <span className="text-[12px] text-muted">
            Human corrections are preserved.
          </span>
        </div>
      </div>

      {actionError ? (
        <div className="mt-4 rounded-md border border-[#f5c2c7] bg-[#fdecee] px-4 py-3 text-[14px] text-danger">
          {actionError}
        </div>
      ) : null}
      {notice ? (
        <div className="mt-4 rounded-md border border-[#bfe6c9] bg-[#eaf7ee] px-4 py-3 text-[14px] text-success">
          {notice}
        </div>
      ) : null}

      <div className="mt-6 grid gap-6 lg:grid-cols-[1.35fr_1fr]">
        <ExtractionEditor
          // Remount when the extraction is replaced or the document reaches a
          // new state, so the form always starts from the latest server data.
          key={`${data.extraction?.id ?? "none"}:${data.status}`}
          id={id}
          data={data}
          editable={editable}
          mutate={mutate}
          onSaved={setNotice}
          onError={setActionError}
        />

        <div className="space-y-6">
          <section className="card p-6">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-[22px]">Validation</h2>
              <span className="text-[12px] text-muted">
                {findings.length} finding{findings.length === 1 ? "" : "s"}
              </span>
            </div>

            {findings.length === 0 ? (
              data.extraction ? (
                <p className="mt-4 rounded-md border border-[#bfe6c9] bg-[#eaf7ee] px-4 py-3 text-[14px] text-success">
                  All checks passed.
                </p>
              ) : (
                <p className="mt-4 text-[14px] text-body">
                  Validation runs after extraction.
                </p>
              )
            ) : (
              <ul className="mt-4 space-y-3">
                {findings.map((finding, index) => (
                  <li
                    key={`${finding.rule_id}-${index}`}
                    className={`rounded-md border px-4 py-3 text-[14px] ${severityClass(finding.severity)}`}
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-[11px] font-semibold uppercase tracking-wide">
                        {finding.severity}
                      </span>
                      <span className="font-medium">{finding.rule_id}</span>
                      {finding.field ? (
                        <span className="text-[12px] opacity-80">
                          field: {finding.field}
                        </span>
                      ) : null}
                    </div>
                    <p className="mt-1.5 leading-snug">{finding.message}</p>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="card p-6">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-[22px]">Source text</h2>
              <span className="text-[12px] text-muted">
                {source
                  ? source.pages.length
                    ? `${source.pages.length} page${source.pages.length === 1 ? "" : "s"}`
                    : `${source.chunks.length} row${source.chunks.length === 1 ? "" : "s"}`
                  : "—"}
              </span>
            </div>

            {!source ? (
              <div className="mt-4 space-y-2">
                <div className="skeleton h-4 w-full" />
                <div className="skeleton h-4 w-5/6" />
                <div className="skeleton h-4 w-2/3" />
              </div>
            ) : source.pages.length > 0 ? (
              <div className="mt-4 max-h-[26rem] space-y-4 overflow-y-auto pr-1">
                {source.pages.map((page) => (
                  <div key={page.page_number}>
                    <div className="mb-1 flex items-center gap-2">
                      <span className="text-[12px] font-medium uppercase tracking-wide text-primary">
                        Page {page.page_number}
                      </span>
                      {page.ocr_confidence !== null ? (
                        <span className="text-[11px] text-muted">
                          OCR {Math.round(page.ocr_confidence * 100)}%
                        </span>
                      ) : null}
                    </div>
                    <pre className="whitespace-pre-wrap break-words rounded-md bg-surface-alt p-3 font-body text-[12.5px] leading-relaxed text-body">
                      {page.raw_text?.trim() || "No text on this page."}
                    </pre>
                  </div>
                ))}
              </div>
            ) : source.chunks.length > 0 ? (
              <div className="mt-4 max-h-[26rem] space-y-2 overflow-y-auto pr-1">
                {source.chunks.map((chunk, index) => (
                  <pre
                    key={index}
                    className="whitespace-pre-wrap break-words rounded-md bg-surface-alt p-3 font-body text-[12.5px] leading-relaxed text-body"
                  >
                    {chunk.content}
                  </pre>
                ))}
              </div>
            ) : (
              <p className="mt-4 text-[14px] text-body">
                No source text stored yet.
              </p>
            )}
          </section>

          <section className="card p-6">
            <h2 className="text-[22px]">Processing history</h2>
            {data.history.length === 0 ? (
              <p className="mt-4 text-[14px] text-body">No events recorded.</p>
            ) : (
              <ol className="mt-4 max-h-[20rem] space-y-3 overflow-y-auto pr-1">
                {data.history.map((event, index) => (
                  <li key={index} className="flex gap-3">
                    <span
                      className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${eventDot(event.status)}`}
                      aria-hidden="true"
                    />
                    <div className="min-w-0">
                      <p className="text-[13px] font-medium text-heading">
                        {event.stage}
                        <span className="ml-1.5 font-normal text-muted">
                          {event.status}
                        </span>
                      </p>
                      <p className="text-[12px] text-muted">
                        {formatDate(event.created_at)}
                      </p>
                      {event.detail ? (
                        <p
                          className="mt-0.5 truncate text-[12px] text-body"
                          title={event.detail}
                        >
                          {event.detail}
                        </p>
                      ) : null}
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

function ExtractionEditor({
  id,
  data,
  editable,
  mutate,
  onSaved,
  onError,
}: {
  id: string;
  data: DocumentDetailData;
  editable: boolean;
  mutate: () => Promise<unknown>;
  onSaved: (message: string) => void;
  onError: (message: string) => void;
}) {
  const [form, setForm] = useState<Record<string, string>>(() => {
    const next: Record<string, string> = {};
    for (const key of HEADER_FIELD_ORDER) {
      const value = data.extraction?.fields[key]?.value;
      next[key] = value === null || value === undefined ? "" : String(value);
    }
    return next;
  });
  const [items, setItems] = useState<LineItemDraft[]>(() =>
    data.line_items.map(toDraft),
  );
  const [savingFields, setSavingFields] = useState(false);
  const [savingItems, setSavingItems] = useState(false);

  const changedFields: Record<string, string | null> = {};
  if (data.extraction) {
    for (const key of HEADER_FIELD_ORDER) {
      const original = data.extraction.fields[key]?.value;
      const current = form[key] ?? "";
      if (String(original ?? "") === current) continue;
      changedFields[key] = current.trim() === "" ? null : current.trim();
    }
  }
  const changedCount = Object.keys(changedFields).length;

  async function saveFields() {
    if (changedCount === 0) return;
    setSavingFields(true);
    onError("");
    onSaved("");
    try {
      await submitCorrection(id, { fields: changedFields });
      await mutate();
      onSaved("Corrections saved. Re-validation is running.");
    } catch (err) {
      onError(err instanceof Error ? err.message : "Could not save");
    } finally {
      setSavingFields(false);
    }
  }

  async function saveItems() {
    const invalid = items.some((item) =>
      [item.quantity, item.unit_price, item.amount].some(
        (value) => value.trim() !== "" && Number.isNaN(Number(value)),
      ),
    );
    if (invalid) {
      onError("Quantity, unit price and amount must be numbers.");
      return;
    }
    if (
      !window.confirm(
        "Saving replaces all line items for this document. Continue?",
      )
    ) {
      return;
    }
    setSavingItems(true);
    onError("");
    onSaved("");
    try {
      await submitCorrection(id, {
        line_items: items.map((item) => ({
          description: item.description.trim() === "" ? null : item.description,
          quantity: item.quantity.trim() === "" ? null : Number(item.quantity),
          unit_price:
            item.unit_price.trim() === "" ? null : Number(item.unit_price),
          amount: item.amount.trim() === "" ? null : Number(item.amount),
        })),
      });
      await mutate();
      onSaved("Line items saved. Re-validation is running.");
    } catch (err) {
      onError(err instanceof Error ? err.message : "Could not save");
    } finally {
      setSavingItems(false);
    }
  }

  return (
    <div className="space-y-6">
      <section className="card p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-[22px]">Extracted fields</h2>
            <p className="mt-1 text-[13px] text-body">
              Values the pipeline was not sure about stay empty — they are never
              guessed.
            </p>
          </div>
          <button
            type="button"
            className="btn-primary !px-4 !py-2 !text-[14px]"
            disabled={!editable || savingFields || changedCount === 0}
            onClick={() => void saveFields()}
          >
            {savingFields
              ? "Saving…"
              : `Save fields${changedCount ? ` (${changedCount})` : ""}`}
          </button>
        </div>

        {data.extraction ? (
          <div className="mt-5 grid gap-4 sm:grid-cols-2">
            {HEADER_FIELD_ORDER.map((key) => {
              const entry = data.extraction?.fields[key];
              return (
                <div key={key}>
                  <div className="mb-1.5 flex items-center justify-between gap-2">
                    <label
                      htmlFor={`field-${key}`}
                      className="text-[13px] font-medium text-heading"
                    >
                      {FIELD_LABELS[key]}
                    </label>
                    <span className="flex items-center gap-1.5">
                      <SourceTag source={entry?.source ?? null} />
                      <ConfidenceBadge value={entry?.confidence} />
                    </span>
                  </div>
                  <input
                    id={`field-${key}`}
                    className="input"
                    type="text"
                    inputMode={MONEY_FIELDS.has(key) ? "decimal" : "text"}
                    value={form[key] ?? ""}
                    placeholder="Not extracted"
                    disabled={!editable}
                    onChange={(e) =>
                      setForm((prev) => ({ ...prev, [key]: e.target.value }))
                    }
                  />
                </div>
              );
            })}
          </div>
        ) : (
          <p className="mt-5 text-[15px] text-body">
            Extraction has not produced fields yet. If the document is queued or
            processing, this page will update automatically.
          </p>
        )}
      </section>

      <section className="card p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-[22px]">Line items</h2>
            <p className="mt-1 text-[13px] text-body">
              {data.line_items.length} item
              {data.line_items.length === 1 ? "" : "s"} · saving replaces the
              whole set.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="btn-ghost !px-4 !py-2 !text-[14px]"
              disabled={!editable}
              onClick={() => setItems((prev) => [...prev, emptyDraft()])}
            >
              Add row
            </button>
            <button
              type="button"
              className="btn-primary !px-4 !py-2 !text-[14px]"
              disabled={!editable || savingItems}
              onClick={() => void saveItems()}
            >
              {savingItems ? "Saving…" : "Save line items"}
            </button>
          </div>
        </div>

        {items.length === 0 ? (
          <p className="mt-5 text-[15px] text-body">No line items extracted.</p>
        ) : (
          <div className="mt-5 overflow-x-auto">
            <table className="w-full min-w-[620px] border-collapse text-left">
              <thead>
                <tr className="border-b border-line text-[12px] uppercase tracking-[0.06em] text-muted">
                  <th className="w-8 py-2 pr-2 font-medium">#</th>
                  <th className="py-2 pr-2 font-medium">Description</th>
                  <th className="w-20 py-2 pr-2 font-medium">Qty</th>
                  <th className="w-28 py-2 pr-2 font-medium">Unit price</th>
                  <th className="w-28 py-2 pr-2 font-medium">Amount</th>
                  <th className="w-10 py-2" />
                </tr>
              </thead>
              <tbody>
                {items.map((item, index) => (
                  <tr key={index} className="border-b border-line/70">
                    <td className="py-2 pr-2 text-[13px] tabular-nums text-muted">
                      {index + 1}
                    </td>
                    <td className="py-2 pr-2">
                      <input
                        aria-label={`Line ${index + 1} description`}
                        className="input !py-1.5 !text-[14px]"
                        value={item.description}
                        disabled={!editable}
                        onChange={(e) =>
                          setItems((prev) =>
                            prev.map((row, i) =>
                              i === index
                                ? { ...row, description: e.target.value }
                                : row,
                            ),
                          )
                        }
                      />
                    </td>
                    {(["quantity", "unit_price", "amount"] as const).map(
                      (field) => (
                        <td key={field} className="py-2 pr-2">
                          <input
                            aria-label={`Line ${index + 1} ${field.replace("_", " ")}`}
                            className="input !py-1.5 !text-[14px] tabular-nums"
                            inputMode="decimal"
                            value={item[field]}
                            disabled={!editable}
                            onChange={(e) =>
                              setItems((prev) =>
                                prev.map((row, i) =>
                                  i === index
                                    ? { ...row, [field]: e.target.value }
                                    : row,
                                ),
                              )
                            }
                          />
                        </td>
                      ),
                    )}
                    <td className="py-2 text-right">
                      <button
                        type="button"
                        aria-label={`Remove line ${index + 1}`}
                        className="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted transition-colors hover:bg-[#fdecee] hover:text-danger disabled:opacity-40"
                        disabled={!editable}
                        onClick={() =>
                          setItems((prev) => prev.filter((_, i) => i !== index))
                        }
                      >
                        <svg
                          width="15"
                          height="15"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="2"
                          strokeLinecap="round"
                          aria-hidden="true"
                        >
                          <path d="M6 6l12 12M18 6L6 18" />
                        </svg>
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

function MetaChip({ children }: { children: ReactNode }) {
  return (
    <span className="rounded-full border border-line bg-surface-alt px-2.5 py-0.5 text-[12px] text-body">
      {children}
    </span>
  );
}

function SourceTag({ source }: { source: string | null }) {
  if (!source) return null;
  const label =
    source === "human" ? "Human" : source === "llm" ? "LLM" : "Rule";
  const tone =
    source === "human"
      ? "border-[#ffd2c2] bg-primary-soft text-primary"
      : "border-line bg-surface-alt text-muted";
  return (
    <span
      className={`rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide ${tone}`}
      title={`Value source: ${source}`}
    >
      {label}
    </span>
  );
}

function severityClass(severity: ValidationFinding["severity"]): string {
  switch (severity) {
    case "error":
      return "border-[#f5c2c7] bg-[#fdecee] text-danger";
    case "warning":
      return "border-[#ffe6a3] bg-[#fff8e1] text-[#8a6100]";
    default:
      return "border-[#bfe3e8] bg-[#e8f6f8] text-info";
  }
}

function eventDot(status: string): string {
  switch (status) {
    case "ok":
      return "bg-success";
    case "failed":
      return "bg-danger";
    case "retrying":
      return "bg-[#ffc107]";
    default:
      return "bg-muted";
  }
}

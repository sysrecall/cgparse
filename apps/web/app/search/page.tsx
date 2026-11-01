"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import {
  type DocumentStatus,
  SOURCE_KIND_LABELS,
  STATUS_LABELS,
  STATUS_ORDER,
  formatDate,
  useSearch,
} from "@/lib/api";

const PAGE_SIZE = 20;

interface Filters {
  status: DocumentStatus | "all";
  supplier: string;
  minTotal: string;
  currency: string;
}

const EMPTY_FILTERS: Filters = {
  status: "all",
  supplier: "",
  minTotal: "",
  currency: "",
};

export default function SearchPage() {
  const [input, setInput] = useState("");
  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [showFilters, setShowFilters] = useState(false);
  const [semantic, setSemantic] = useState(false);
  const [page, setPage] = useState(1);

  useEffect(() => {
    const timer = setTimeout(() => {
      setQuery(input.trim());
      setPage(1);
    }, 350);
    return () => clearTimeout(timer);
  }, [input]);

  const { data, error, isLoading, isValidating } = useSearch(
    query,
    filters,
    page,
    PAGE_SIZE,
    semantic,
  );

  function updateFilters(patch: Partial<Filters>) {
    setFilters((prev) => ({ ...prev, ...patch }));
    setPage(1);
  }

  function clearFilters() {
    setFilters(EMPTY_FILTERS);
    setPage(1);
  }

  const activeFilters = [
    filters.status !== "all" ? 1 : 0,
    filters.supplier.trim() ? 1 : 0,
    filters.minTotal.trim() ? 1 : 0,
    filters.currency.trim() ? 1 : 0,
  ].reduce((a, b) => a + b, 0);

  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <>
      <PageHeader
        eyebrow="Find anything"
        title="Search documents"
        description="Keyword search across document text and filenames, or hybrid semantic search that also matches paraphrases. Filter by status, supplier, currency and minimum total."
      >
        <div className="mt-6">
          <div className="flex flex-col gap-2 sm:flex-row">
            <div className="relative flex-1">
              <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted">
                <svg
                  width="18"
                  height="18"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                >
                  <circle cx="11" cy="11" r="7" />
                  <path d="M21 21l-4.3-4.3" />
                </svg>
              </span>
              <input
                type="search"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Try “invoice”, “Acme”, “INV-2026”…"
                className="input !py-3 !pl-10 !text-[16px]"
                aria-label="Search documents"
              />
            </div>
            <button
              type="button"
              className={`btn-ghost whitespace-nowrap ${
                semantic ? "!border-primary !text-primary" : ""
              }`}
              onClick={() => {
                setSemantic((value) => !value);
                setPage(1);
              }}
              aria-pressed={semantic}
              title="Blend keyword and vector ranking; matches paraphrases as well as exact terms"
            >
              Semantic
            </button>
            <button
              type="button"
              className="btn-ghost whitespace-nowrap"
              onClick={() => setShowFilters((v) => !v)}
              aria-expanded={showFilters}
            >
              Filters
              {activeFilters > 0 ? (
                <span className="inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-primary px-1 text-[11px] text-white">
                  {activeFilters}
                </span>
              ) : null}
            </button>
          </div>

          {showFilters ? (
            <div className="mt-4 grid gap-3 rounded-lg border border-line bg-surface p-4 sm:grid-cols-2 lg:grid-cols-4">
              <div>
                <label
                  htmlFor="filter-status"
                  className="mb-1 block text-[12px] font-medium text-heading"
                >
                  Status
                </label>
                <select
                  id="filter-status"
                  className="input"
                  value={filters.status}
                  onChange={(e) =>
                    updateFilters({
                      status: e.target.value as DocumentStatus | "all",
                    })
                  }
                >
                  <option value="all">Any status</option>
                  {STATUS_ORDER.map((status) => (
                    <option key={status} value={status}>
                      {STATUS_LABELS[status]}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label
                  htmlFor="filter-supplier"
                  className="mb-1 block text-[12px] font-medium text-heading"
                >
                  Supplier
                </label>
                <input
                  id="filter-supplier"
                  className="input"
                  value={filters.supplier}
                  onChange={(e) => updateFilters({ supplier: e.target.value })}
                  placeholder="e.g. Acme"
                />
              </div>
              <div>
                <label
                  htmlFor="filter-total"
                  className="mb-1 block text-[12px] font-medium text-heading"
                >
                  Minimum total
                </label>
                <input
                  id="filter-total"
                  className="input"
                  inputMode="decimal"
                  value={filters.minTotal}
                  onChange={(e) => updateFilters({ minTotal: e.target.value })}
                  placeholder="e.g. 1000"
                />
              </div>
              <div>
                <label
                  htmlFor="filter-currency"
                  className="mb-1 block text-[12px] font-medium text-heading"
                >
                  Currency
                </label>
                <input
                  id="filter-currency"
                  className="input"
                  value={filters.currency}
                  onChange={(e) =>
                    updateFilters({ currency: e.target.value.toUpperCase() })
                  }
                  placeholder="e.g. USD"
                  maxLength={3}
                />
              </div>
              {activeFilters > 0 ? (
                <div className="sm:col-span-2 lg:col-span-4">
                  <button
                    type="button"
                    className="text-[13px] font-medium text-primary hover:underline"
                    onClick={clearFilters}
                  >
                    Clear filters
                  </button>
                </div>
              ) : null}
            </div>
          ) : null}

          <p className="mt-3 text-[12.5px] text-muted">
            {semantic
              ? "Hybrid ranking: full-text matches fused with the nearest embedding chunks, so paraphrases surface too."
              : "Keyword search over document text and filenames. Turn on Semantic to also match paraphrases."}
          </p>
        </div>
      </PageHeader>

      <div className="container-page py-10">
        {error ? (
          <div className="rounded-md border border-[#f5c2c7] bg-[#fdecee] px-4 py-3 text-[14px] text-danger">
            Search failed: {error.message}
          </div>
        ) : null}

        {!query ? (
          <EmptyState
            title="Start typing to search"
            description="Search matches words inside document text and filenames. Add filters to narrow by status, supplier, currency or total."
            icon={
              <svg
                width="24"
                height="24"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <circle cx="11" cy="11" r="7" />
                <path d="M21 21l-4.3-4.3" />
              </svg>
            }
          />
        ) : isLoading && !data ? (
          <div className="space-y-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="card space-y-3 p-5">
                <div className="skeleton h-5 w-64" />
                <div className="skeleton h-4 w-full" />
                <div className="skeleton h-4 w-4/5" />
              </div>
            ))}
          </div>
        ) : data && data.items.length === 0 ? (
          <EmptyState
            title={`No results for “${query}”`}
            description="Try a different keyword, or loosen the filters."
          />
        ) : data ? (
          <>
            <div className="mb-5 flex flex-wrap items-center justify-between gap-2">
              <p className="text-[14px] text-body">
                {total} result{total === 1 ? "" : "s"} for{" "}
                <span className="font-medium text-heading">“{query}”</span>
                {isValidating ? (
                  <span className="ml-2 text-[12px] text-muted">updating…</span>
                ) : null}
              </p>
            </div>

            <div className="space-y-4">
              {data.items.map((hit) => (
                <article key={hit.id} className="card card-hover p-5">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <Link
                        href={`/documents/${hit.id}`}
                        className="block truncate font-heading text-[18px] font-semibold text-heading transition-colors hover:text-primary"
                        title={hit.original_filename}
                      >
                        {hit.original_filename}
                      </Link>
                      <div className="mt-2 flex flex-wrap items-center gap-2 text-[12px] text-body">
                        <StatusBadge status={hit.status} />
                        <span className="rounded-full border border-line bg-surface-alt px-2 py-0.5">
                          {SOURCE_KIND_LABELS[hit.source_kind] ?? hit.source_kind}
                        </span>
                        <span>{formatDate(hit.created_at)}</span>
                      </div>
                    </div>
                    <Link
                      href={`/documents/${hit.id}`}
                      className="text-[13px] font-medium text-primary hover:underline"
                    >
                      Open document →
                    </Link>
                  </div>

                  {hit.snippets.length > 0 ? (
                    <ul className="mt-4 space-y-2">
                      {hit.snippets.map((snippet, index) => (
                        <li
                          key={index}
                          className="rounded-md bg-surface-alt px-3.5 py-2.5"
                        >
                          <span className="mb-1 block text-[10.5px] font-medium uppercase tracking-[0.1em] text-muted">
                            {snippet.chunk_type === "row"
                              ? `Row ${snippet.page_number ?? "—"}`
                              : snippet.chunk_type}
                          </span>
                          <p className="break-words text-[13.5px] leading-relaxed text-body">
                            <Highlight text={snippet.text} query={query} />
                          </p>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="mt-3 text-[13px] text-muted">
                      Filename match — no matching text snippet.
                    </p>
                  )}
                </article>
              ))}
            </div>

            {total > PAGE_SIZE ? (
              <div className="mt-6 flex flex-wrap items-center justify-between gap-3 text-[14px] text-body">
                <p>
                  Page {page} of {totalPages}
                </p>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    className="btn-ghost !px-4 !py-2 !text-[14px]"
                    disabled={page <= 1}
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                  >
                    Previous
                  </button>
                  <button
                    type="button"
                    className="btn-ghost !px-4 !py-2 !text-[14px]"
                    disabled={page >= totalPages}
                    onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  >
                    Next
                  </button>
                </div>
              </div>
            ) : null}
          </>
        ) : null}
      </div>
    </>
  );
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function Highlight({ text, query }: { text: string; query: string }) {
  const terms = query
    .trim()
    .split(/\s+/)
    .filter((term) => term.length > 1)
    .map(escapeRegExp);

  if (terms.length === 0) return <>{text}</>;

  const parts = text.split(new RegExp(`(${terms.join("|")})`, "gi"));
  return (
    <>
      {parts.map((part, index) =>
        index % 2 === 1 ? (
          <mark
            key={index}
            className="rounded-sm bg-primary/15 px-0.5 text-heading"
          >
            {part}
          </mark>
        ) : (
          <span key={index}>{part}</span>
        ),
      )}
    </>
  );
}

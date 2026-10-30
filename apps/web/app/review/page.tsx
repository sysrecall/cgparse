"use client";

import Link from "next/link";

import { DocumentTable } from "@/components/DocumentTable";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { TableSkeleton } from "@/components/Skeletons";
import { useDocuments } from "@/lib/api";

const RULES = [
  { id: "missing_field", label: "Required field missing", severity: "error" },
  { id: "type_and_format", label: "Wrong date or number format", severity: "error" },
  { id: "line_items_sum", label: "Line items ≠ subtotal", severity: "error" },
  { id: "subtotal_tax_total", label: "Subtotal + tax ≠ total", severity: "error" },
  { id: "negative_or_impossible_values", label: "Negative values", severity: "error" },
  { id: "duplicate_invoice", label: "Duplicate invoice", severity: "warning" },
];

export default function ReviewPage() {
  const { data, error, isLoading } = useDocuments({
    status: "needs_review",
    size: 50,
  });

  const count = data?.total ?? 0;

  return (
    <>
      <PageHeader
        eyebrow="Human in the loop"
        title="Review queue"
        description="Documents with at least one error-severity finding. Open one, correct the fields or line items, and save — validation re-runs automatically."
        actions={
          <Link href="/documents" className="btn-ghost">
            All documents
          </Link>
        }
      >
        {data ? (
          <p className="mt-3 text-[14px] font-medium text-heading">
            {count === 0
              ? "Nothing is waiting for review."
              : `${count} document${count === 1 ? "" : "s"} waiting for review.`}
          </p>
        ) : null}
      </PageHeader>

      <div className="container-page py-10">
        <div className="mb-8 grid gap-6 md:grid-cols-[1.4fr_1fr]">
          <div className="card p-6">
            <h2 className="text-[20px]">Why a document lands here</h2>
            <p className="mt-1.5 text-[14px] text-body">
              The rule engine runs after every extraction and correction. Any
              error-severity finding moves the document to this queue.
            </p>
            <ul className="mt-4 grid gap-2 sm:grid-cols-2">
              {RULES.map((rule) => (
                <li
                  key={rule.id}
                  className="flex items-start gap-2 text-[13.5px] text-body"
                >
                  <span
                    className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${
                      rule.severity === "error" ? "bg-danger" : "bg-[#ffc107]"
                    }`}
                    aria-hidden="true"
                  />
                  <span>
                    {rule.label}
                    <span className="ml-1.5 text-[11px] uppercase tracking-wide text-muted">
                      {rule.severity}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          </div>

          <div className="card bg-ink p-6 text-white">
            <p className="text-[12px] uppercase tracking-[0.12em] text-white/50">
              Resolution loop
            </p>
            <ol className="mt-4 space-y-3 text-[14px] text-white/75">
              <li className="flex gap-3">
                <span className="font-heading font-semibold text-primary">
                  01
                </span>
                Open the document and compare fields with the source text.
              </li>
              <li className="flex gap-3">
                <span className="font-heading font-semibold text-primary">
                  02
                </span>
                Correct the header fields or replace the line items and save.
              </li>
              <li className="flex gap-3">
                <span className="font-heading font-semibold text-primary">
                  03
                </span>
                Validation re-runs in the background; the document leaves the
                queue when it is clean.
              </li>
            </ol>
            <p className="mt-5 border-t border-white/10 pt-4 text-[12px] text-white/45">
              Corrections are stored with confidence 1.0 and source “human”, and
              survive reprocessing.
            </p>
          </div>
        </div>

        {error ? (
          <div className="mb-6 rounded-md border border-[#f5c2c7] bg-[#fdecee] px-4 py-3 text-[14px] text-danger">
            Could not load the review queue: {error.message}
          </div>
        ) : null}

        {isLoading && !data ? (
          <TableSkeleton />
        ) : data && data.items.length === 0 ? (
          <EmptyState
            title="Nothing to review"
            description="Every document has passed validation. New uploads that fail a rule will appear here automatically."
            action={{ href: "/documents", label: "Browse documents" }}
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
                <path d="M20 6L9 17l-5-5" />
              </svg>
            }
          />
        ) : (
          <DocumentTable
            items={data?.items}
            loading={isLoading}
            emptyTitle="Nothing to review"
            emptyDescription="Every document has passed validation."
          />
        )}
      </div>
    </>
  );
}

"use client";

import Link from "next/link";
import { useState } from "react";

import { DocumentTable } from "@/components/DocumentTable";
import { PageHeader } from "@/components/PageHeader";
import {
  type DocumentStatus,
  STATUS_LABELS,
  STATUS_ORDER,
  useDocuments,
} from "@/lib/api";

const PAGE_SIZE = 20;

export default function DocumentsPage() {
  const [status, setStatus] = useState<DocumentStatus | "all">("all");
  const [page, setPage] = useState(1);
  const { data, error, isLoading } = useDocuments({
    page,
    size: PAGE_SIZE,
    status,
  });

  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  function chooseStatus(next: DocumentStatus | "all") {
    setStatus(next);
    setPage(1);
  }

  return (
    <>
      <PageHeader
        eyebrow="Library"
        title="Documents"
        description="Everything ingested so far, newest first. Open a document to review its extraction, findings and source text."
        actions={
          <Link href="/#upload" className="btn-primary">
            Upload documents
          </Link>
        }
      />

      <div className="container-page py-10">
        <div className="mb-6 flex flex-wrap items-center gap-2">
          <button
            type="button"
            className="chip"
            data-active={status === "all"}
            onClick={() => chooseStatus("all")}
          >
            All
            {status === "all" && data ? (
              <span className="tabular-nums opacity-80">{total}</span>
            ) : null}
          </button>
          {STATUS_ORDER.map((value) => (
            <button
              key={value}
              type="button"
              className="chip"
              data-active={status === value}
              onClick={() => chooseStatus(value)}
            >
              {STATUS_LABELS[value]}
            </button>
          ))}
        </div>

        {error ? (
          <div className="mb-6 rounded-md border border-[#f5c2c7] bg-[#fdecee] px-4 py-3 text-[14px] text-danger">
            Could not load documents: {error.message}
          </div>
        ) : null}

        <DocumentTable
          items={data?.items}
          loading={isLoading}
          emptyTitle={
            status === "all"
              ? "No documents yet"
              : `No ${STATUS_LABELS[status].toLowerCase()} documents`
          }
          emptyDescription={
            status === "all"
              ? "Upload a PDF, image or spreadsheet to start the pipeline."
              : "Try another status filter, or upload a new document."
          }
        />

        {data && total > PAGE_SIZE ? (
          <div className="mt-6 flex flex-wrap items-center justify-between gap-3 text-[14px] text-body">
            <p>
              Showing {(page - 1) * PAGE_SIZE + 1}–
              {Math.min(page * PAGE_SIZE, total)} of {total}
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
              <span className="px-2 tabular-nums">
                {page} / {totalPages}
              </span>
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
      </div>
    </>
  );
}

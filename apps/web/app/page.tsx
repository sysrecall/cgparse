"use client";

import Link from "next/link";

import { DocumentTable } from "@/components/DocumentTable";
import { UploadDropzone } from "@/components/UploadDropzone";
import { useDocuments, useDocumentStats } from "@/lib/api";

const FORMATS = ["PDF", "JPG", "PNG", "XLSX", "XLS", "CSV"];

const STEPS = [
  {
    index: "01",
    title: "Upload",
    body: "Drop in invoices, receipts or spreadsheets. Files are stored in Tigris and the pipeline starts immediately.",
  },
  {
    index: "02",
    title: "Extract",
    body: "Digital text is read directly; scans go through OCR. Heuristics run first, the LLM fills only what is missing.",
  },
  {
    index: "03",
    title: "Validate & search",
    body: "Six rules check the numbers. Anything uncertain is flagged for review — never guessed — and indexed for search.",
  },
];

export default function Home() {
  const stats = useDocumentStats();
  const recent = useDocuments({ size: 6 });

  const inPipeline = (stats.data?.queued ?? 0) + (stats.data?.processing ?? 0);

  return (
    <>
      {/* Hero + upload */}
      <section className="relative overflow-hidden bg-surface-alt">
        <div
          className="pointer-events-none absolute -left-32 -top-24 h-80 w-80 rounded-full bg-primary/10 blur-3xl"
          aria-hidden="true"
        />
        <div
          className="pointer-events-none absolute -bottom-32 right-0 h-80 w-80 rounded-full bg-primary/5 blur-3xl"
          aria-hidden="true"
        />

        <div className="container-page relative grid gap-12 py-16 lg:grid-cols-[1.05fr_1fr] lg:items-center lg:py-20">
          <div>
            <p className="eyebrow">Document intelligence</p>
            <h1 className="mt-3 max-w-xl text-[38px] leading-[1.1] md:text-[52px]">
              Turn documents into{" "}
              <span className="text-primary">decisions</span>.
            </h1>
            <p className="mt-5 max-w-lg text-[17px] leading-relaxed text-body">
              Upload invoices, receipts and spreadsheets. CareGuide extracts the
              fields, checks the maths, flags what it is unsure about and makes
              everything searchable.
            </p>
            <p className="mt-3 max-w-lg text-[15px] text-body">
              <strong className="font-medium text-heading">
                No invented data.
              </strong>{" "}
              Uncertain values stay empty and land in a human review queue.
            </p>

            <div className="mt-7 flex flex-wrap items-center gap-3">
              <Link href="/documents" className="btn-primary">
                Browse documents
              </Link>
              <Link href="/search" className="btn-ghost">
                Search documents
              </Link>
            </div>

            <div className="mt-7 flex flex-wrap items-center gap-2">
              {FORMATS.map((format) => (
                <span
                  key={format}
                  className="rounded-full border border-line bg-surface px-3 py-1 text-[12px] font-medium text-body"
                >
                  {format}
                </span>
              ))}
            </div>
          </div>

          <div
            id="upload"
            className="card scroll-mt-24 p-6 shadow-card md:p-7"
          >
            <p className="eyebrow">Start here</p>
            <h2 className="mt-1 text-[24px]">Upload documents</h2>
            <p className="mb-5 mt-2 text-[14px] text-body">
              Each file is processed independently. You can upload several at
              once.
            </p>
            <UploadDropzone />
          </div>
        </div>
      </section>

      {/* Stats band */}
      <section className="bg-ink">
        <div className="container-page grid grid-cols-2 gap-8 py-12 md:grid-cols-4">
          <Stat label="Documents" value={stats.data?.total} />
          <Stat label="Validated" value={stats.data?.validated} tone="success" />
          <Stat
            label="Needs review"
            value={stats.data?.needs_review}
            tone="primary"
          />
          <Stat label="In pipeline" value={stats.data ? inPipeline : undefined} />
        </div>
      </section>

      {/* How it works */}
      <section className="section">
        <div className="container-page">
          <div className="max-w-2xl">
            <p className="eyebrow">How it works</p>
            <h2 className="mt-2">A pipeline built for human review</h2>
            <p className="mt-3 text-[16px] text-body">
              Every stage is explicit, retryable and recorded — so you always
              know where a document is and why.
            </p>
          </div>

          <div className="mt-10 grid gap-6 md:grid-cols-3">
            {STEPS.map((step) => (
              <article key={step.index} className="card card-hover p-6">
                <span className="font-heading text-[40px] font-bold leading-none text-primary/20">
                  {step.index}
                </span>
                <h3 className="mt-4 text-[21px]">{step.title}</h3>
                <p className="mt-2 text-[15px] text-body">{step.body}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      {/* Recent documents */}
      <section className="border-t border-line bg-surface-alt/60 pb-20 pt-16">
        <div className="container-page">
          <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
            <div>
              <p className="eyebrow">Latest activity</p>
              <h2 className="mt-2 text-[28px]">Recent documents</h2>
            </div>
            <Link
              href="/documents"
              className="text-[15px] font-medium text-primary hover:underline"
            >
              View all documents →
            </Link>
          </div>
          <DocumentTable
            items={recent.data?.items}
            loading={recent.isLoading}
          />
        </div>
      </section>
    </>
  );
}

function Stat({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: number | undefined;
  tone?: "default" | "success" | "primary";
}) {
  const color =
    tone === "success"
      ? "text-[#6ee7a0]"
      : tone === "primary"
        ? "text-primary"
        : "text-white";
  return (
    <div>
      <p
        className={`font-heading text-[42px] font-bold leading-none tabular-nums md:text-[48px] ${color}`}
      >
        {value === undefined ? (
          <span className="inline-block h-[42px] w-16 animate-pulse rounded bg-white/10" />
        ) : (
          value
        )}
      </p>
      <p className="mt-2 text-[13px] uppercase tracking-[0.1em] text-white/55">
        {label}
      </p>
    </div>
  );
}

"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { useSWRConfig } from "swr";

import { type UploadItem, uploadDocuments } from "@/lib/api";

const ACCEPT = ".pdf,.png,.jpg,.jpeg,.xlsx,.xls,.csv";
const EXTENSIONS = ACCEPT.split(",");
const MAX_MB = 200;

function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot === -1 ? "" : name.slice(dot).toLowerCase();
}

export function UploadDropzone() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [results, setResults] = useState<UploadItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { mutate } = useSWRConfig();

  async function handleFiles(fileList: FileList | File[]) {
    const files = Array.from(fileList);
    if (files.length === 0) return;

    setError(null);
    setResults(null);

    const rejected: UploadItem[] = [];
    const accepted: File[] = [];
    for (const file of files) {
      if (!EXTENSIONS.includes(extensionOf(file.name))) {
        rejected.push({
          filename: file.name,
          document_id: null,
          status: null,
          error: `Unsupported type — use ${EXTENSIONS.join(", ")}`,
        });
      } else if (file.size > MAX_MB * 1024 * 1024) {
        rejected.push({
          filename: file.name,
          document_id: null,
          status: null,
          error: `File is larger than ${MAX_MB} MB`,
        });
      } else {
        accepted.push(file);
      }
    }

    if (accepted.length === 0) {
      setResults(rejected);
      return;
    }

    setUploading(true);
    try {
      const response = await uploadDocuments(accepted);
      setResults([...response.items, ...rejected]);
      // Refresh every document list/stats key so the new rows appear and
      // start polling while they are queued/processing.
      await mutate(
        (key) =>
          typeof key === "string" && key.startsWith("/api/v1/documents"),
        undefined,
        { revalidate: true },
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
      setResults(rejected.length ? rejected : null);
    } finally {
      setUploading(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  return (
    <div>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          void handleFiles(e.dataTransfer.files);
        }}
        className={`flex flex-col items-center justify-center gap-4 rounded-lg border-2 border-dashed px-6 py-12 text-center transition-colors ${
          dragging
            ? "border-primary bg-primary-soft"
            : "border-line bg-surface-alt/60"
        }`}
      >
        <div className="flex h-14 w-14 items-center justify-center rounded-full bg-primary-soft text-primary">
          <svg
            width="26"
            height="26"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <path d="M17 8l-5-5-5 5" />
            <path d="M12 3v12" />
          </svg>
        </div>

        <div>
          <p className="font-heading text-[18px] font-semibold text-heading">
            {uploading ? "Uploading…" : "Drag & drop documents here"}
          </p>
          <p className="mt-1 text-[14px] text-body">
            PDF, JPG, PNG, XLSX, XLS or CSV · up to {MAX_MB} MB each
          </p>
        </div>

        <button
          type="button"
          className="btn-primary"
          disabled={uploading}
          onClick={() => inputRef.current?.click()}
        >
          {uploading ? "Uploading…" : "Browse files"}
        </button>

        <input
          ref={inputRef}
          type="file"
          multiple
          accept={ACCEPT}
          className="hidden"
          onChange={(e) => {
            if (e.target.files) void handleFiles(e.target.files);
          }}
        />
      </div>

      {error ? (
        <p className="mt-4 rounded-md border border-[#f5c2c7] bg-[#fdecee] px-4 py-3 text-[14px] text-danger">
          {error}
        </p>
      ) : null}

      {results ? (
        <ul className="mt-4 space-y-2">
          {results.map((item) => (
            <li
              key={`${item.filename}-${item.document_id ?? "err"}`}
              className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-line bg-surface px-4 py-2.5 text-[14px]"
            >
              <span className="flex min-w-0 items-center gap-2">
                <span
                  className={`h-2 w-2 shrink-0 rounded-full ${
                    item.error ? "bg-danger" : "bg-success"
                  }`}
                  aria-hidden="true"
                />
                <span className="truncate text-heading" title={item.filename}>
                  {item.filename}
                </span>
              </span>
              {item.error ? (
                <span className="text-danger">{item.error}</span>
              ) : item.document_id ? (
                <Link
                  href={`/documents/${item.document_id}`}
                  className="font-medium text-primary hover:underline"
                >
                  Open document →
                </Link>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

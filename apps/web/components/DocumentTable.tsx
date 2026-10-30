import Link from "next/link";

import { EmptyState } from "@/components/EmptyState";
import { StatusBadge } from "@/components/StatusBadge";
import { TableSkeleton } from "@/components/Skeletons";
import {
  type DocumentSummary,
  SOURCE_KIND_LABELS,
  formatBytes,
  formatDate,
} from "@/lib/api";

export function DocumentTable({
  items,
  loading = false,
  emptyTitle = "No documents yet",
  emptyDescription = "Upload a PDF, image or spreadsheet to start the pipeline.",
  emptyAction = { href: "/#upload", label: "Upload documents" },
}: {
  items: DocumentSummary[] | undefined;
  loading?: boolean;
  emptyTitle?: string;
  emptyDescription?: string;
  emptyAction?: { href: string; label: string };
}) {
  if (loading && !items) return <TableSkeleton />;

  if (!items || items.length === 0) {
    return (
      <EmptyState
        title={emptyTitle}
        description={emptyDescription}
        action={emptyAction}
      />
    );
  }

  return (
    <div className="card overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] border-collapse text-left">
          <thead>
            <tr className="border-b border-line bg-surface-alt text-[12px] uppercase tracking-[0.08em] text-muted">
              <th className="px-5 py-3 font-medium">Document</th>
              <th className="px-4 py-3 font-medium">Status</th>
              <th className="px-4 py-3 font-medium">Pages</th>
              <th className="px-4 py-3 font-medium">Size</th>
              <th className="px-4 py-3 font-medium">Uploaded</th>
              <th className="w-12 px-4 py-3" />
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {items.map((doc) => (
              <tr
                key={doc.id}
                className="group transition-colors hover:bg-primary-soft/60"
              >
                <td className="px-5 py-4">
                  <Link
                    href={`/documents/${doc.id}`}
                    className="block max-w-[320px] truncate font-medium text-heading transition-colors group-hover:text-primary"
                    title={doc.original_filename}
                  >
                    {doc.original_filename}
                  </Link>
                  <span className="mt-0.5 block text-[12px] text-muted">
                    {SOURCE_KIND_LABELS[doc.source_kind] ?? doc.source_kind}
                  </span>
                </td>
                <td className="px-4 py-4">
                  <StatusBadge status={doc.status} />
                </td>
                <td className="px-4 py-4 text-[14px] tabular-nums text-body">
                  {doc.page_count ?? "—"}
                </td>
                <td className="px-4 py-4 text-[14px] tabular-nums text-body">
                  {formatBytes(doc.size_bytes)}
                </td>
                <td className="px-4 py-4 text-[14px] text-body">
                  {formatDate(doc.created_at)}
                </td>
                <td className="px-4 py-4 text-right">
                  <Link
                    href={`/documents/${doc.id}`}
                    aria-label={`Open ${doc.original_filename}`}
                    className="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted transition-colors hover:bg-primary hover:text-white"
                  >
                    <svg
                      width="16"
                      height="16"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      aria-hidden="true"
                    >
                      <path d="M5 12h14M13 6l6 6-6 6" />
                    </svg>
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

import type { DocumentStatus } from "@/lib/api";
import { STATUS_LABELS } from "@/lib/api";

const STYLES: Record<DocumentStatus, string> = {
  validated: "border-[#bfe6c9] bg-[#eaf7ee] text-success",
  needs_review: "border-[#ffe6a3] bg-[#fff8e1] text-[#a97600]",
  processing: "border-[#bfe3e8] bg-[#e8f6f8] text-info",
  queued: "border-line bg-surface-alt text-body",
  failed: "border-[#f5c2c7] bg-[#fdecee] text-danger",
};

export function StatusBadge({
  status,
  className = "",
}: {
  status: DocumentStatus;
  className?: string;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-[12px] font-medium ${STYLES[status]} ${className}`}
    >
      <span
        className={`h-1.5 w-1.5 rounded-full bg-current ${
          status === "processing" ? "animate-pulse" : ""
        }`}
        aria-hidden="true"
      />
      {STATUS_LABELS[status]}
    </span>
  );
}

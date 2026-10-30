import useSWR, { type SWRResponse } from "swr";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://localhost:8000";

export type DocumentStatus =
  | "queued"
  | "processing"
  | "validated"
  | "needs_review"
  | "failed";

export const STATUS_LABELS: Record<DocumentStatus, string> = {
  queued: "Queued",
  processing: "Processing",
  validated: "Validated",
  needs_review: "Needs review",
  failed: "Failed",
};

export const STATUS_ORDER: DocumentStatus[] = [
  "queued",
  "processing",
  "validated",
  "needs_review",
  "failed",
];

export const SOURCE_KIND_LABELS: Record<string, string> = {
  pdf: "PDF",
  image: "Image",
  spreadsheet: "Spreadsheet",
  csv: "CSV",
};

export const HEADER_FIELD_ORDER = [
  "invoice_number",
  "invoice_date",
  "supplier_name",
  "customer_name",
  "subtotal",
  "tax",
  "total",
  "currency",
] as const;

export const FIELD_LABELS: Record<string, string> = {
  invoice_number: "Invoice number",
  invoice_date: "Invoice date",
  supplier_name: "Supplier",
  customer_name: "Customer",
  subtotal: "Subtotal",
  tax: "Tax",
  total: "Total",
  currency: "Currency",
};

export const MONEY_FIELDS = new Set(["subtotal", "tax", "total"]);

export interface DocumentSummary {
  id: string;
  original_filename: string;
  source_kind: string;
  status: DocumentStatus;
  size_bytes: number;
  page_count: number | null;
  created_at: string;
}

export interface DocumentList {
  total: number;
  page: number;
  size: number;
  items: DocumentSummary[];
}

export interface FieldEntry {
  value: string | number | null;
  confidence: number;
  source_span?: Record<string, unknown> | null;
  source?: string | null;
}

export type Fields = Record<string, FieldEntry>;

export interface LineItem {
  id: string;
  position: number;
  description: string | null;
  quantity: number | null;
  unit_price: number | null;
  amount: number | null;
  confidence: number | null;
  source: string;
}

export interface ValidationFinding {
  rule_id: string;
  severity: "error" | "warning" | "info";
  message: string;
  field: string | null;
}

export interface ProcessingEvent {
  stage: string;
  status: string;
  detail: string | null;
  created_at: string;
}

export interface Extraction {
  id: string;
  fields: Fields;
  document_confidence: number;
  extraction_model: string;
  created_at: string;
}

export interface DocumentDetail {
  id: string;
  original_filename: string;
  mime_type: string;
  source_kind: string;
  status: DocumentStatus;
  size_bytes: number;
  page_count: number | null;
  ocr_confidence: number | null;
  failure_reason: string | null;
  created_at: string;
  updated_at: string;
  extraction: Extraction | null;
  line_items: LineItem[];
  validation_results: ValidationFinding[];
  history: ProcessingEvent[];
}

export interface SourcePage {
  page_number: number;
  raw_text: string | null;
  ocr_confidence: number | null;
}

export interface SourceChunk {
  chunk_type: string;
  content: string;
  meta: Record<string, unknown> | null;
}

export interface DocumentSource {
  document_id: string;
  page_count: number;
  pages: SourcePage[];
  chunks: SourceChunk[];
}

export interface SearchSnippet {
  chunk_type: string;
  text: string;
  page_number: number | null;
}

export interface SearchHit {
  id: string;
  original_filename: string;
  status: DocumentStatus;
  source_kind: string;
  created_at: string;
  rank: number;
  snippets: SearchSnippet[];
}

export interface SearchResponse {
  query: string;
  semantic: boolean;
  total: number;
  page: number;
  size: number;
  items: SearchHit[];
}

export interface UploadItem {
  filename: string;
  document_id: string | null;
  status: string | null;
  error: string | null;
}

export interface UploadResponse {
  items: UploadItem[];
}

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function errorMessage(res: Response): Promise<string> {
  try {
    const body = await res.json();
    const detail = body?.detail;
    if (typeof detail === "string") return detail;
    if (detail) return JSON.stringify(detail);
  } catch {
    /* non-JSON error body */
  }
  return `${res.status} ${res.statusText}`;
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store", ...init });
  if (!res.ok) throw new ApiError(await errorMessage(res), res.status);
  return (await res.json()) as T;
}

export function useDocuments(params: {
  page?: number;
  size?: number;
  status?: DocumentStatus | "all";
}): SWRResponse<DocumentList, ApiError> {
  const qs = new URLSearchParams();
  qs.set("page", String(params.page ?? 1));
  qs.set("size", String(params.size ?? 20));
  if (params.status && params.status !== "all") qs.set("status", params.status);
  return useSWR<DocumentList, ApiError>(
    `/api/v1/documents?${qs.toString()}`,
    apiFetch,
    {
      keepPreviousData: true,
      // Poll while any visible document is still in the pipeline.
      refreshInterval: (data) =>
        data?.items.some(
          (item) => item.status === "queued" || item.status === "processing",
        )
          ? 3000
          : 0,
    },
  );
}

export interface DocumentStats {
  total: number;
  validated: number;
  needs_review: number;
  processing: number;
  queued: number;
  failed: number;
}

/**
 * Aggregate counts from the list endpoint (size=1 keeps each request tiny).
 * There is no dedicated stats route, so this fans out one request per status.
 */
export function useDocumentStats(): SWRResponse<DocumentStats, ApiError> {
  return useSWR<DocumentStats, ApiError>(
    "/api/v1/documents/stats",
    async () => {
      const statuses = STATUS_ORDER;
      const [all, ...counts] = await Promise.all([
        apiFetch<DocumentList>("/api/v1/documents?page=1&size=1"),
        ...statuses.map((status) =>
          apiFetch<DocumentList>(
            `/api/v1/documents?page=1&size=1&status=${status}`,
          ),
        ),
      ]);
      const byStatus = Object.fromEntries(
        statuses.map((status, i) => [status, counts[i].total]),
      ) as Record<DocumentStatus, number>;
      return {
        total: all.total,
        validated: byStatus.validated,
        needs_review: byStatus.needs_review,
        processing: byStatus.processing,
        queued: byStatus.queued,
        failed: byStatus.failed,
      };
    },
    { refreshInterval: 10_000 },
  );
}

export function useDocument(id: string): SWRResponse<DocumentDetail, ApiError> {
  return useSWR<DocumentDetail, ApiError>(`/api/v1/documents/${id}`, apiFetch, {
    // Poll only while the pipeline is working; stop on a terminal state.
    refreshInterval: (data) =>
      data && (data.status === "queued" || data.status === "processing") ? 2500 : 0,
  });
}

export function useDocumentSource(
  id: string,
): SWRResponse<DocumentSource, ApiError> {
  return useSWR<DocumentSource, ApiError>(
    `/api/v1/documents/${id}/pages`,
    apiFetch,
  );
}

export function useSearch(
  query: string,
  filters: {
    status?: DocumentStatus | "all";
    supplier?: string;
    minTotal?: string;
    currency?: string;
  },
  page = 1,
  size = 20,
): SWRResponse<SearchResponse, ApiError> {
  const qs = new URLSearchParams({ q: query });
  qs.set("page", String(page));
  qs.set("size", String(size));
  if (filters.status && filters.status !== "all") qs.set("status", filters.status);
  if (filters.supplier) qs.set("supplier", filters.supplier);
  if (filters.minTotal) qs.set("min_total", filters.minTotal);
  if (filters.currency) qs.set("currency", filters.currency);
  const key = query.trim() ? `/api/v1/search?${qs.toString()}` : null;
  return useSWR<SearchResponse, ApiError>(key, apiFetch, {
    keepPreviousData: true,
  });
}

export async function uploadDocuments(files: File[]): Promise<UploadResponse> {
  const form = new FormData();
  for (const file of files) form.append("files", file);
  const res = await fetch(`${API_BASE}/api/v1/documents`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw new ApiError(await errorMessage(res), res.status);
  return (await res.json()) as UploadResponse;
}

export interface CorrectionPayload {
  fields?: Record<string, string | number | null>;
  line_items?: Array<{
    description: string | null;
    quantity: number | null;
    unit_price: number | null;
    amount: number | null;
  }>;
}

export async function submitCorrection(
  id: string,
  payload: CorrectionPayload,
): Promise<unknown> {
  return apiFetch(`/api/v1/documents/${id}/corrections`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function reprocessDocument(
  id: string,
  from: "parse" | "extract",
): Promise<unknown> {
  return apiFetch(`/api/v1/documents/${id}/reprocess?from=${from}`, {
    method: "POST",
  });
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

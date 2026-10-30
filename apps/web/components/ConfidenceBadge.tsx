export function ConfidenceBadge({
  value,
  showLabel = false,
}: {
  value: number | null | undefined;
  showLabel?: boolean;
}) {
  if (value === null || value === undefined) {
    return (
      <span className="text-[12px] text-muted" title="No confidence score">
        —
      </span>
    );
  }

  const pct = Math.round(value * 100);
  const tone =
    value >= 0.8
      ? "border-[#bfe6c9] bg-[#eaf7ee] text-success"
      : value >= 0.5
        ? "border-[#ffe6a3] bg-[#fff8e1] text-[#a97600]"
        : "border-[#f5c2c7] bg-[#fdecee] text-danger";

  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium tabular-nums ${tone}`}
      title={`Extraction confidence: ${pct}%`}
    >
      {pct}%{showLabel ? " confidence" : ""}
    </span>
  );
}

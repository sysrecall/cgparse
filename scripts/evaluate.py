"""Evaluation harness — runs the real pipeline over the labeled corpus.

The full chain (parse → extract[heuristics+LLM] → validate → index) is executed
in-process against a **dedicated test database** with object storage replaced by
an in-memory map and Redis pub/sub replaced by a list. Parsers, the LLM and the
rule engine are all real.

Requirements
    TEST_DATABASE_URL   Supabase dev project (session-pooler IPv4 URL)

Usage
    uv run --project services/processing python scripts/evaluate.py
    uv run --project services/processing python scripts/evaluate.py --workers 4
    uv run --project services/processing python scripts/evaluate.py --limit 5 --no-llm   # smoke

Outputs
    docs/metrics_report.md   human-readable report
    docs/metrics.json        chart-ready raw metrics + per-document results
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "seed" / "eval"
DOCUMENTS = SEED / "documents"
GROUND_TRUTH = SEED / "ground_truth.json"

HEADER_FIELDS = (
    "invoice_number",
    "invoice_date",
    "supplier_name",
    "customer_name",
    "subtotal",
    "tax",
    "total",
    "currency",
)
MONEY_FIELDS = {"subtotal", "tax", "total"}
MONEY_TOLERANCE = 0.01
FUZZY_THRESHOLD = 0.90
ITEM_DESC_THRESHOLD = 0.70


# ── value normalization ──────────────────────────────────────────────────────


def canonical(field: str, value: object) -> float | str | None:
    """Normalize a ground-truth or extracted value for exact comparison."""
    from app_core.schemas.extraction import money_to_float

    if value is None or value == "":
        return None
    if field in MONEY_FIELDS:
        parsed = money_to_float(value)
        return None if parsed is None else round(parsed, 2)
    if field == "currency":
        return str(value).strip().upper()
    return " ".join(str(value).split())


def fuzzy_equal(a: object, b: object, field: str) -> bool:
    left, right = canonical(field, a), canonical(field, b)
    if left is None or right is None:
        return left is right
    if isinstance(left, float) and isinstance(right, float):
        return abs(left - right) <= MONEY_TOLERANCE
    return SequenceMatcher(None, str(left).casefold(), str(right).casefold()).ratio() >= FUZZY_THRESHOLD


def numbers_close(a: object, b: object) -> bool:
    from app_core.schemas.extraction import money_to_float

    if a is None and b is None:
        return True
    left, right = money_to_float(a), money_to_float(b)
    if left is None or right is None:
        return left is right
    return abs(left - right) <= MONEY_TOLERANCE


# ── database + pipeline wiring ───────────────────────────────────────────────


def prepare_environment() -> tuple[str, object, object]:
    from app_core.db import normalize_database_url
    from app_core.testing import (
        apply_migrations,
        configure_test_env,
        test_database_url,
    )
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    configure_test_env()
    url = test_database_url()
    if not url:
        print(
            "TEST_DATABASE_URL is not set — evaluation targets a dedicated Supabase\n"
            "dev project. Export it (session-pooler IPv4 URL) and re-run.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    apply_migrations(url)
    engine = create_engine(normalize_database_url(url), pool_pre_ping=True)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return url, engine, factory


def cleanup_eval_documents(factory) -> int:
    """Delete only prior ``eval_*`` rows — never touches anything else."""
    from sqlalchemy import text

    with factory() as session:
        result = session.execute(text("DELETE FROM documents WHERE original_filename LIKE 'eval\\_%'"))
        session.commit()
        return result.rowcount or 0


def insert_documents(factory, records: list[dict], storage: dict[str, bytes]) -> list[dict]:
    from app_core.models.document import Document

    prepared = []
    with factory() as session:
        for record in records:
            data = (DOCUMENTS / record["filename"]).read_bytes()
            document_id = uuid.uuid4()
            storage_key = f"eval/{record['filename']}"
            storage[storage_key] = data
            session.add(
                Document(
                    id=document_id,
                    original_filename=record["filename"],
                    checksum_sha256=hashlib.sha256(data).hexdigest(),
                    mime_type=record["mime_type"],
                    source_kind=record["source_kind"],
                    storage_key=storage_key,
                    size_bytes=len(data),
                    status="queued",
                )
            )
            prepared.append({**record, "_document_id": document_id, "_storage_key": storage_key})
        session.commit()
    return prepared


def patch_pipeline(factory, storage: dict[str, bytes], published: list[dict]) -> None:
    from app.queues import pipeline

    @contextmanager
    def session_scope():
        session = factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    pipeline.session_scope = session_scope
    pipeline.download = lambda key: storage[key]
    pipeline.publish = published.append


def disable_llm() -> None:
    from app.llm import extract as extraction
    from app_core.schemas.extraction import ExtractionOut

    extraction._llm_pass = lambda text, structured_columns=None: ExtractionOut()  # type: ignore[assignment]


# ── run ──────────────────────────────────────────────────────────────────────


def run_parse_extract(record: dict) -> dict:
    from app.queues import pipeline

    timings: dict[str, float] = {}
    document_id = record["_document_id"]
    try:
        start = time.perf_counter()
        pipeline.parse_document.run(str(document_id))
        timings["parse"] = time.perf_counter() - start
    except Exception as exc:  # noqa: BLE001 — a failure is a datapoint, not a crash
        timings["parse"] = time.perf_counter() - start
        return {"filename": record["filename"], "timings": timings, "error": f"parse: {type(exc).__name__}: {exc}"}
    try:
        start = time.perf_counter()
        pipeline.extract_document.run(str(document_id))
        timings["extract"] = time.perf_counter() - start
    except Exception as exc:  # noqa: BLE001
        timings["extract"] = time.perf_counter() - start
        return {"filename": record["filename"], "timings": timings, "error": f"extract: {type(exc).__name__}: {exc}"}
    return {"filename": record["filename"], "timings": timings, "error": None}


def run_validate_index(factory, record: dict, outcome: dict) -> None:
    from app.queues import pipeline

    if outcome.get("error"):
        return
    document_id = record["_document_id"]
    for stage, task in (("validate", pipeline.validate_document), ("index", pipeline.index_document)):
        start = time.perf_counter()
        try:
            task.run(str(document_id))
        except Exception as exc:  # noqa: BLE001
            outcome["timings"][stage] = time.perf_counter() - start
            outcome["error"] = f"{stage}: {type(exc).__name__}: {exc}"
            return
        outcome["timings"][stage] = time.perf_counter() - start


def collect_results(factory, records: list[dict], outcomes: dict[str, dict]) -> list[dict]:
    from app_core.models.document import Document
    from app_core.models.extraction import Extraction
    from app_core.models.validation_result import ValidationResult
    from sqlalchemy import select

    results = []
    with factory() as session:
        for record in records:
            document_id = record["_document_id"]
            document = session.get(Document, document_id)
            extraction = session.scalars(
                select(Extraction)
                .where(Extraction.document_id == document_id)
                .order_by(Extraction.created_at.desc())
            ).first()
            fields = {name: None for name in HEADER_FIELDS}
            findings: list[dict] = []
            items: list[dict] = []
            if extraction is not None:
                for name in HEADER_FIELDS:
                    entry = (extraction.fields or {}).get(name) or {}
                    fields[name] = entry.get("value")
                findings = [
                    {"rule_id": v.rule_id, "severity": v.severity}
                    for v in session.scalars(
                        select(ValidationResult).where(ValidationResult.extraction_id == extraction.id)
                    )
                ]
                items = [
                    {
                        "description": item.description,
                        "quantity": float(item.quantity) if item.quantity is not None else None,
                        "unit_price": float(item.unit_price) if item.unit_price is not None else None,
                        "amount": float(item.amount) if item.amount is not None else None,
                    }
                    for item in extraction.line_items
                ]
            outcome = outcomes[record["filename"]]
            results.append(
                {
                    "filename": record["filename"],
                    "edge_case": record["edge_case"],
                    "expected_status": record["expected_status"],
                    "actual_status": document.status if document else "missing",
                    "failure_reason": document.failure_reason if document else None,
                    "expected_rules": list(record["expected_rules"]),
                    "actual_rules": [f["rule_id"] for f in findings],
                    "expected_fields": record["fields"],
                    "actual_fields": fields,
                    "expected_line_items": record["line_items"],
                    "actual_line_items": items,
                    "timings": outcome["timings"],
                    "error": outcome.get("error"),
                }
            )
    return results


# ── metrics ──────────────────────────────────────────────────────────────────


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
    return ordered[index]


def compute_field_metrics(results: list[dict]) -> dict:
    evaluable = [r for r in results if r["actual_status"] != "failed" and r["error"] is None]
    per_field: dict[str, dict] = {
        name: {
            "total": 0,
            "exact": 0,
            "fuzzy": 0,
            "expected_null": 0,
            "predicted_null": 0,
            "null_tp": 0,
            "null_fp": 0,
            "null_fn": 0,
            "hallucinated": 0,
        }
        for name in HEADER_FIELDS
    }

    for record in evaluable:
        for name in HEADER_FIELDS:
            expected = record["expected_fields"][name]
            actual = record["actual_fields"][name]
            metric = per_field[name]
            metric["total"] += 1
            exp_c = canonical(name, expected)
            act_c = canonical(name, actual)
            if exp_c is None:
                metric["expected_null"] += 1
                if act_c is None:
                    metric["null_tp"] += 1
                    metric["exact"] += 1
                    metric["fuzzy"] += 1
                else:
                    metric["null_fp"] += 1
                    metric["hallucinated"] += 1
            else:
                if act_c is None:
                    metric["null_fn"] += 1
                else:
                    if exp_c == act_c:
                        metric["exact"] += 1
                    if fuzzy_equal(expected, actual, name):
                        metric["fuzzy"] += 1
            if act_c is None:
                metric["predicted_null"] += 1

    for metric in per_field.values():
        total = metric["total"] or 1
        metric["exact_accuracy"] = round(metric["exact"] / total, 4)
        metric["fuzzy_accuracy"] = round(metric["fuzzy"] / total, 4)
        null_pred = metric["null_tp"] + metric["null_fp"]
        null_actual = metric["null_tp"] + metric["null_fn"]
        metric["null_precision"] = round(metric["null_tp"] / null_pred, 4) if null_pred else None
        metric["null_recall"] = round(metric["null_tp"] / null_actual, 4) if null_actual else None
        metric["hallucination_rate"] = (
            round(metric["hallucinated"] / metric["expected_null"], 4) if metric["expected_null"] else None
        )

    macro_exact = round(statistics.fmean(m["exact_accuracy"] for m in per_field.values()), 4)
    macro_fuzzy = round(statistics.fmean(m["fuzzy_accuracy"] for m in per_field.values()), 4)
    return {
        "documents_evaluated": len(evaluable),
        "per_field": per_field,
        "macro_exact_accuracy": macro_exact,
        "macro_fuzzy_accuracy": macro_fuzzy,
    }


def _match_line_items(expected: list[dict], actual: list[dict]) -> list[tuple[dict, dict]]:
    used: set[int] = set()
    pairs: list[tuple[dict, dict]] = []
    for want in expected:
        best: tuple[float, int] | None = None
        for index, have in enumerate(actual):
            if index in used:
                continue
            if not (
                numbers_close(want["quantity"], have["quantity"])
                and numbers_close(want["unit_price"], have["unit_price"])
                and numbers_close(want["amount"], have["amount"])
            ):
                continue
            want_desc = (want["description"] or "").casefold()
            have_desc = (have["description"] or "").casefold()
            ratio = SequenceMatcher(None, want_desc, have_desc).ratio()
            if ratio >= ITEM_DESC_THRESHOLD and (best is None or ratio > best[0]):
                best = (ratio, index)
        if best is not None:
            used.add(best[1])
            pairs.append((want, actual[best[1]]))
    return pairs


def compute_line_item_metrics(results: list[dict]) -> dict:
    evaluable = [r for r in results if r["actual_status"] != "failed" and r["error"] is None]
    expected_total = matched = extracted_total = 0
    field_correct = {"description": 0, "quantity": 0, "unit_price": 0, "amount": 0}
    docs_with_items_expected = 0
    docs_all_items_matched = 0

    for record in evaluable:
        expected = record["expected_line_items"]
        actual = record["actual_line_items"]
        expected_total += len(expected)
        extracted_total += len(actual)
        pairs = _match_line_items(expected, actual)
        matched += len(pairs)
        for want, have in pairs:
            for field in field_correct:
                if field == "description":
                    if SequenceMatcher(
                        None, (want[field] or "").casefold(), (have[field] or "").casefold()
                    ).ratio() >= FUZZY_THRESHOLD:
                        field_correct[field] += 1
                elif numbers_close(want[field], have[field]):
                    field_correct[field] += 1
        if expected:
            docs_with_items_expected += 1
            if len(pairs) == len(expected):
                docs_all_items_matched += 1

    return {
        "expected_items": expected_total,
        "extracted_items": extracted_total,
        "matched_items": matched,
        "recall": round(matched / expected_total, 4) if expected_total else None,
        "precision": round(matched / extracted_total, 4) if extracted_total else None,
        "docs_with_expected_items": docs_with_items_expected,
        "docs_all_items_matched": docs_all_items_matched,
        "field_accuracy": {
            field: round(count / matched, 4) if matched else None for field, count in field_correct.items()
        },
    }


def compute_validation_metrics(results: list[dict]) -> dict:
    tp = fp = fn = 0
    per_rule: dict[str, dict[str, int]] = {}
    for record in results:
        expected = set(record["expected_rules"])
        actual = set(record["actual_rules"])
        tp += len(expected & actual)
        fp += len(actual - expected)
        fn += len(expected - actual)
        for rule in expected | actual:
            bucket = per_rule.setdefault(rule, {"tp": 0, "fp": 0, "fn": 0})
            if rule in expected and rule in actual:
                bucket["tp"] += 1
            elif rule in actual:
                bucket["fp"] += 1
            elif rule in expected:
                bucket["fn"] += 1

    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    f1 = (2 * precision * recall / (precision + recall)) if precision and recall else None
    return {
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "precision": round(precision, 4) if precision is not None else None,
        "recall": round(recall, 4) if recall is not None else None,
        "f1": round(f1, 4) if f1 is not None else None,
        "per_rule": per_rule,
    }


def compute_status_metrics(results: list[dict]) -> dict:
    total = len(results)
    counts = {"validated": 0, "needs_review": 0, "failed": 0, "other": 0}
    status_correct = 0
    failures = []
    for record in results:
        actual = record["actual_status"]
        counts[actual if actual in counts else "other"] += 1
        if actual == record["expected_status"]:
            status_correct += 1
        if actual == "failed" or record["error"]:
            failures.append(
                {
                    "filename": record["filename"],
                    "edge_case": record["edge_case"],
                    "error": record["error"] or record["failure_reason"],
                }
            )
    return {
        "total": total,
        "validated": counts["validated"],
        "needs_review": counts["needs_review"],
        "failed": counts["failed"],
        "success_rate": round(counts["validated"] / total, 4) if total else None,
        "review_rate": round(counts["needs_review"] / total, 4) if total else None,
        "failure_rate": round((counts["failed"] + counts["other"]) / total, 4) if total else None,
        "expected_status_accuracy": round(status_correct / total, 4) if total else None,
        "failures": failures,
    }


def compute_timing_metrics(results: list[dict], wall_seconds: float, usage: list[dict]) -> dict:
    stages = {"parse": [], "extract": [], "validate": [], "index": []}
    totals = []
    for record in results:
        total = 0.0
        for stage, value in record["timings"].items():
            if stage in stages:
                stages[stage].append(value)
                total += value
        totals.append(total)
    stage_summary = {
        stage: {
            "count": len(values),
            "p50": round(statistics.median(values), 3) if values else None,
            "p95": round(_percentile(values, 0.95), 3) if values else None,
        }
        for stage, values in stages.items()
    }
    tokens = {
        "calls": len(usage),
        "prompt_tokens": sum(u.get("prompt_tokens", 0) for u in usage),
        "completion_tokens": sum(u.get("completion_tokens", 0) for u in usage),
        "total_tokens": sum(u.get("total_tokens", 0) for u in usage),
    }
    documents = len(results)
    tokens["tokens_per_document"] = round(tokens["total_tokens"] / documents, 1) if documents else None
    return {
        "wall_seconds": round(wall_seconds, 2),
        "documents": documents,
        "throughput_docs_per_second": round(documents / wall_seconds, 4) if wall_seconds else None,
        "per_stage_seconds": stage_summary,
        "per_document_seconds": {
            "p50": round(statistics.median(totals), 3) if totals else None,
            "p95": round(_percentile(totals, 0.95), 3) if totals else None,
            "max": round(max(totals), 3) if totals else None,
        },
        "llm_tokens": tokens,
    }


# ── report ───────────────────────────────────────────────────────────────────


def _fmt(value: object, digits: int = 4) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _embedding_header() -> str:
    from app_core.settings import get_embedding_settings

    settings = get_embedding_settings()
    return f"{settings.model} at {settings.dimensions} dims"


def render_report(metadata: dict, metrics: dict, results: list[dict]) -> str:
    fields = metrics["fields"]
    lines = metrics["line_items"]
    validation = metrics["validation"]
    status = metrics["status"]
    timing = metrics["timing"]

    out: list[str] = []
    out.append("# Evaluation report — document intelligence pipeline\n")
    out.append(f"- **Generated:** {metadata['generated_at']}")
    out.append(f"- **Model:** `{metadata['model']}` (LLM pass {'enabled' if metadata['llm'] else 'disabled'})")
    out.append(f"- **Embeddings:** `{_embedding_header()}` (index stage)")
    out.append(f"- **Corpus:** {status['total']} documents from `seed/eval/`")
    out.append(f"- **Workers:** {metadata['workers']} · **Database:** dedicated Supabase dev project")
    out.append("")

    out.append("## 1. Headline\n")
    out.append("| Metric | Value |")
    out.append("|---|---|")
    out.append(f"| Validated (success rate) | {status['validated']} ({_fmt(status['success_rate'], 4)}) |")
    out.append(f"| Needs review | {status['needs_review']} ({_fmt(status['review_rate'], 4)}) |")
    out.append(f"| Failed | {status['failed']} ({_fmt(status['failure_rate'], 4)}) |")
    out.append(f"| Expected-status accuracy | {_fmt(status['expected_status_accuracy'])} |")
    out.append(f"| Macro field accuracy (exact) | {_fmt(fields['macro_exact_accuracy'])} |")
    out.append(f"| Macro field accuracy (fuzzy) | {_fmt(fields['macro_fuzzy_accuracy'])} |")
    out.append(f"| Line-item recall | {_fmt(lines['recall'])} |")
    out.append(f"| Line-item precision | {_fmt(lines['precision'])} |")
    out.append(f"| Validation rule F1 | {_fmt(validation['f1'])} |")
    out.append(f"| Wall time | {timing['wall_seconds']} s ({_fmt(timing['throughput_docs_per_second'])} docs/s) |")
    out.append(f"| LLM tokens | {timing['llm_tokens']['total_tokens']} total, "
               f"{timing['llm_tokens']['tokens_per_document']} / doc |")
    out.append("")

    out.append("## 2. Field extraction\n")
    out.append("| Field | Exact | Fuzzy | Null precision | Null recall | Hallucination rate |")
    out.append("|---|---|---|---|---|---|")
    for name in HEADER_FIELDS:
        metric = fields["per_field"][name]
        out.append(
            f"| {name} | {_fmt(metric['exact_accuracy'])} | {_fmt(metric['fuzzy_accuracy'])} | "
            f"{_fmt(metric['null_precision'])} | {_fmt(metric['null_recall'])} | "
            f"{_fmt(metric['hallucination_rate'])} |"
        )
    out.append("")
    out.append(
        "Null precision/recall treat \"field absent\" as the positive class: a high "
        "hallucination rate means the model invented values for fields the source omitted.\n"
    )

    out.append("## 3. Line items\n")
    out.append("| Metric | Value |")
    out.append("|---|---|")
    out.append(f"| Expected items | {lines['expected_items']} |")
    out.append(f"| Extracted items | {lines['extracted_items']} |")
    out.append(f"| Matched items | {lines['matched_items']} |")
    out.append(f"| Recall | {_fmt(lines['recall'])} |")
    out.append(f"| Precision | {_fmt(lines['precision'])} |")
    out.append(f"| Documents with all items matched | "
               f"{lines['docs_all_items_matched']}/{lines['docs_with_expected_items']} |")
    out.append("")
    out.append("Per-attribute accuracy over matched items:\n")
    out.append("| Attribute | Accuracy |")
    out.append("|---|---|")
    for field, value in lines["field_accuracy"].items():
        out.append(f"| {field} | {_fmt(value)} |")
    out.append("")

    out.append("## 4. Validation rules\n")
    out.append(
        f"Micro precision **{_fmt(validation['precision'])}**, recall **{_fmt(validation['recall'])}**, "
        f"F1 **{_fmt(validation['f1'])}** "
        f"(TP {validation['true_positives']}, FP {validation['false_positives']}, "
        f"FN {validation['false_negatives']}).\n"
    )
    out.append("| Rule | TP | FP | FN |")
    out.append("|---|---|---|---|")
    for rule, bucket in sorted(validation["per_rule"].items()):
        out.append(f"| {rule} | {bucket['tp']} | {bucket['fp']} | {bucket['fn']} |")
    out.append("")

    out.append("## 5. Performance\n")
    out.append("| Stage | n | p50 (s) | p95 (s) |")
    out.append("|---|---|---|---|")
    for stage, summary in timing["per_stage_seconds"].items():
        out.append(f"| {stage} | {summary['count']} | {_fmt(summary['p50'], 2)} | {_fmt(summary['p95'], 2)} |")
    out.append("")
    out.append(
        f"Per-document total: p50 {_fmt(timing['per_document_seconds']['p50'], 2)} s · "
        f"p95 {_fmt(timing['per_document_seconds']['p95'], 2)} s · "
        f"max {_fmt(timing['per_document_seconds']['max'], 2)} s.\n"
    )

    out.append("## 6. Per-document results\n")
    out.append("| Document | Edge case | Expected | Actual | Rules (expected / actual) |")
    out.append("|---|---|---|---|---|")
    for record in results:
        expected_rules = ", ".join(record["expected_rules"]) or "—"
        actual_rules = ", ".join(record["actual_rules"]) or "—"
        out.append(
            f"| {record['filename']} | {record['edge_case']} | {record['expected_status']} | "
            f"{record['actual_status']} | {expected_rules} / {actual_rules} |"
        )
    out.append("")

    if status["failures"]:
        out.append("## 7. Failures\n")
        out.append("| Document | Edge case | Error |")
        out.append("|---|---|---|")
        for failure in status["failures"]:
            out.append(f"| {failure['filename']} | {failure['edge_case']} | {failure['error']} |")
        out.append("")

    out.append("## 8. Known limitations\n")
    out.append(
        "- Negative line-item values are blocked by DB `CHECK` constraints, so the\n"
        "  `negative_or_impossible_values` rule can only be covered by unit tests, not by\n"
        "  persisted corpus documents.\n"
        "- `duplicate_invoice` compares each extraction against every *other* persisted\n"
        "  extraction, so both members of a duplicate pair are flagged (a warning never\n"
        "  moves a document to review on its own).\n"
        "- Heuristic dates are literal evidence: a non-ISO date (e.g. `MM/DD/YYYY`) is kept\n"
        "  verbatim and flagged by `type_and_format` rather than auto-converted.\n"
        "- OCR (PaddleOCR-VL) and the LLM are nondeterministic providers; reruns can move\n"
        "  per-document results by a small amount.\n"
    )
    return "\n".join(out)


# ── entrypoint ───────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the pipeline over the labeled corpus.")
    parser.add_argument("--workers", type=int, default=4, help="concurrent parse/extract workers")
    parser.add_argument("--limit", type=int, default=None, help="evaluate only the first N documents")
    parser.add_argument("--no-llm", action="store_true", help="heuristics only (smoke run)")
    parser.add_argument("--report", type=Path, default=ROOT / "docs" / "metrics_report.md")
    parser.add_argument("--json", type=Path, default=ROOT / "docs" / "metrics.json")
    args = parser.parse_args()

    if not GROUND_TRUTH.exists():
        print("ground truth missing — run scripts/make_eval_dataset.py first", file=sys.stderr)
        raise SystemExit(2)
    if not DOCUMENTS.exists() or not any(DOCUMENTS.iterdir()):
        print("corpus documents missing — run scripts/make_eval_dataset.py first", file=sys.stderr)
        raise SystemExit(2)

    records = json.loads(GROUND_TRUTH.read_text())
    if args.limit:
        records = records[: args.limit]

    _url, engine, factory = prepare_environment()
    _ = engine  # kept alive for the duration of the run

    from app_core.clients import llm as llm_client

    usage: list[dict] = []
    llm_client.set_usage_sink(usage)
    if args.no_llm:
        disable_llm()

    storage: dict[str, bytes] = {}
    published: list[dict] = []
    removed = cleanup_eval_documents(factory)
    prepared = insert_documents(factory, records, storage)
    patch_pipeline(factory, storage, published)

    print(f"evaluating {len(prepared)} documents (removed {removed} prior eval rows)…")
    started = time.perf_counter()
    outcomes: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(run_parse_extract, record): record for record in prepared}
        for future in as_completed(futures):
            outcome = future.result()
            outcomes[outcome["filename"]] = outcome
            flag = "OK " if not outcome["error"] else "ERR"
            print(f"  [{flag}] {outcome['filename']}")

    # Validation is sequential: the duplicate rule depends on committed peers.
    for record in prepared:
        run_validate_index(factory, record, outcomes[record["filename"]])

    wall_seconds = time.perf_counter() - started
    results = collect_results(factory, prepared, outcomes)

    fields = compute_field_metrics(results)
    line_items = compute_line_item_metrics(results)
    validation = compute_validation_metrics(results)
    status = compute_status_metrics(results)
    timing = compute_timing_metrics(results, wall_seconds, usage)
    from app_core.settings import get_processing_settings

    metadata = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": get_processing_settings().llm_model,
        "llm": not args.no_llm,
        "workers": args.workers,
        "corpus": len(records),
    }
    metrics = {
        "metadata": metadata,
        "fields": fields,
        "line_items": line_items,
        "validation": validation,
        "status": status,
        "timing": timing,
        "documents": results,
    }

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(render_report(metadata, metrics, results))
    args.json.write_text(json.dumps(metrics, indent=2) + "\n")

    print(f"\nwrote {args.report}")
    print(f"wrote {args.json}")
    print(
        f"validated={status['validated']} review={status['needs_review']} "
        f"failed={status['failed']} · macro exact accuracy={fields['macro_exact_accuracy']} · "
        f"{timing['wall_seconds']}s"
    )


if __name__ == "__main__":
    main()

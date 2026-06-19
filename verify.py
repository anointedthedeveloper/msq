"""
Verify downloaded question files in the questions/ folder.

Usage:
    python verify.py                       # verify all files
    python verify.py --subject mathematics # verify one subject
    python verify.py --fix                 # remove bad entries and re-save

Exit codes:
    0 = all files passed
    1 = one or more errors found
"""

import argparse
import json
import re
import sys
from pathlib import Path

QUESTIONS_DIR = "questions"

KNOWN_EXAM_TYPES = {"JAMB", "WAEC", "NECO", "NABTEB", "GCE", ""}
YEAR_RE   = re.compile(r"^\d{4}$")
ANSWER_RE = re.compile(r"^[A-E]$")


def check_question(q: dict, index: int) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) for one question dict."""
    errors   = []
    warnings = []
    qid = q.get("id", f"index-{index}")

    if not isinstance(q.get("id"), int) or q["id"] <= 0:
        errors.append(f"Q#{qid}: 'id' must be a positive integer, got {q.get('id')!r}")

    if not q.get("subject"):
        errors.append(f"Q#{qid}: 'subject' is empty")

    if q.get("exam_type", "").upper() not in KNOWN_EXAM_TYPES:
        warnings.append(f"Q#{qid}: unknown exam_type {q['exam_type']!r}")

    year = str(q.get("exam_year", ""))
    if year and not YEAR_RE.match(year):
        warnings.append(f"Q#{qid}: suspicious exam_year {year!r}")

    if not str(q.get("question", "")).strip():
        errors.append(f"Q#{qid}: 'question' is empty")

    opts = q.get("options", {})
    if not isinstance(opts, dict) or len(opts) < 2:
        errors.append(f"Q#{qid}: 'options' has fewer than 2 entries: {opts!r}")

    ans = q.get("correct_answer", "")
    if ans and not ANSWER_RE.match(ans):
        errors.append(f"Q#{qid}: invalid correct_answer {ans!r}")
    if not ans:
        warnings.append(f"Q#{qid}: correct_answer is empty")

    if not isinstance(q.get("explanation", ""), str):
        errors.append(f"Q#{qid}: 'explanation' is not a string")

    if q.get("image_url") and not q.get("image_cloudinary"):
        warnings.append(f"Q#{qid}: has image_url but image_cloudinary is empty")

    if q.get("explanation_image_url") and not q.get("explanation_image_cloudinary"):
        warnings.append(f"Q#{qid}: has explanation_image_url but explanation_image_cloudinary is empty")

    return errors, warnings


def verify_file(path: str, fix: bool = False) -> tuple[int, int, int]:
    """Verify one JSON file. Returns (total, error_count, warning_count)."""
    print(f"\nVerifying: {path}")

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"  ERROR: Invalid JSON — {e}")
        return 0, 1, 0
    except Exception as e:
        print(f"  ERROR: Could not read file — {e}")
        return 0, 1, 0

    if not isinstance(data, list):
        print("  ERROR: Top-level structure is not a list")
        return 0, 1, 0

    total     = len(data)
    err_count = 0
    wrn_count = 0
    bad_ids   = set()

    # Duplicate ID check
    seen  = set()
    dupes = set()
    for q in data:
        qid = q.get("id")
        if qid in seen:
            dupes.add(qid)
        seen.add(qid)
    if dupes:
        print(f"  ERROR: Duplicate IDs: {sorted(dupes)}")
        err_count += len(dupes)

    for i, q in enumerate(data):
        errors, warnings = check_question(q, i)
        for e in errors:
            print(f"  ERROR: {e}")
            err_count += 1
            bad_ids.add(q.get("id"))
        for w in warnings:
            print(f"  WARN:  {w}")
            wrn_count += 1

    if fix and bad_ids:
        clean   = [q for q in data if q.get("id") not in bad_ids]
        removed = total - len(clean)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(clean, f, ensure_ascii=False, indent=2)
        print(f"  FIXED: removed {removed} bad question(s) and re-saved")
        total     = len(clean)
        err_count = 0

    if err_count == 0 and wrn_count == 0:
        print(f"  OK: {total} questions, no issues")
    elif err_count == 0:
        print(f"  PASS: {total} questions, {wrn_count} warning(s)")
    else:
        print(f"  FAIL: {total} questions, {err_count} error(s), {wrn_count} warning(s)")

    return total, err_count, wrn_count


def main():
    parser = argparse.ArgumentParser(
        description="Verify scraped question JSON files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python verify.py                       # check all subjects
  python verify.py --subject mathematics # check one subject
  python verify.py --fix                 # auto-remove bad entries
        """,
    )
    parser.add_argument("--subject", default=None, metavar="SLUG",
                        help="Subject slug to verify (default: all)")
    parser.add_argument("--fix", action="store_true",
                        help="Remove bad questions and re-save")
    args = parser.parse_args()

    questions_dir = Path(QUESTIONS_DIR)
    if not questions_dir.exists():
        print(f"ERROR: Directory '{QUESTIONS_DIR}/' not found.")
        sys.exit(1)

    if args.subject:
        files = [questions_dir / f"{args.subject}.json"]
    else:
        files = sorted(questions_dir.glob("*.json"))
        files = list(files)

    if not files:
        print(f"No JSON files found in {QUESTIONS_DIR}/")
        sys.exit(0)

    grand_total  = 0
    grand_errors = 0
    grand_warns  = 0
    failed_files = []

    for f in files:
        if not Path(f).exists():
            print(f"\nERROR: File not found: {f}")
            grand_errors += 1
            failed_files.append(str(f))
            continue
        total, errs, warns = verify_file(str(f), fix=args.fix)
        grand_total  += total
        grand_errors += errs
        grand_warns  += warns
        if errs > 0:
            failed_files.append(str(f))

    # Summary
    print()
    print("=" * 60)
    print("SUMMARY")
    print(f"  Files checked    : {len(files)}")
    print(f"  Total questions  : {grand_total}")
    print(f"  Errors           : {grand_errors}")
    print(f"  Warnings         : {grand_warns}")

    if failed_files:
        print("\n  Failed files:")
        for ff in failed_files:
            print(f"    - {ff}")

    if grand_errors == 0:
        print("\n  RESULT: All files passed.")
    else:
        print("\n  RESULT: FAILED. Run with --fix to auto-clean bad entries.")
    print("=" * 60)

    sys.exit(0 if grand_errors == 0 else 1)


if __name__ == "__main__":
    main()

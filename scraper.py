"""
Myschool.ng Past Questions Scraper
Scrapes past questions from https://myschool.ng/classroom

Usage:
    python scraper.py                           # scrapes mathematics (default)
    python scraper.py --subject physics         # scrapes physics
    python scraper.py --subject mathematics --pages 10
    python scraper.py --all                     # all subjects (parallel, 4 workers)
    python scraper.py --all --workers 8         # all subjects with 8 workers
    python scraper.py --list-subjects
    python scraper.py --no-details              # fast mode, no answers
    python scraper.py --no-images               # skip Cloudinary uploads
"""

import argparse
import json
import os
import random
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import cloudinary
import cloudinary.uploader
import requests
from bs4 import BeautifulSoup, NavigableString
from dotenv import load_dotenv
from tqdm import tqdm

# ── Credentials ───────────────────────────────────────────────────────────────
load_dotenv()

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    secure=True,
)

# ── Constants ─────────────────────────────────────────────────────────────────
BASE_URL      = "https://myschool.ng"
CLASSROOM_URL = f"{BASE_URL}/classroom"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]

def get_headers() -> dict:
    """Get headers with random User-Agent."""
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Referer": "https://myschool.ng/",
        "DNT": "1",
        "Connection": "keep-alive",
    }

REQUEST_DELAY = 2.0   # between listing pages (increased)
DETAIL_DELAY  = 1.5   # between question detail pages (increased)
IMAGE_DELAY   = 0.5   # between Cloudinary uploads

# ── Subject list ──────────────────────────────────────────────────────────────
SUBJECTS = [
    {"name": "Mathematics",                          "slug": "mathematics"},
    {"name": "English Language",                     "slug": "english-language"},
    {"name": "Chemistry",                            "slug": "chemistry"},
    {"name": "Physics",                              "slug": "physics"},
    {"name": "Biology",                              "slug": "biology"},
    {"name": "Geography",                            "slug": "geography"},
    {"name": "Literature in English",                "slug": "literature-in-english"},
    {"name": "Economics",                            "slug": "economics"},
    {"name": "Commerce",                             "slug": "commerce"},
    {"name": "Accounts - Principles of Accounts",   "slug": "accounts-principles-of-accounts"},
    {"name": "Government",                           "slug": "government"},
    {"name": "Christian Religious Knowledge (CRK)", "slug": "christian-religious-knowledge-crk"},
    {"name": "Agricultural Science",                "slug": "agricultural-science"},
    {"name": "Islamic Religious Knowledge (IRK)",   "slug": "islamic-religious-knowledge-irk"},
    {"name": "History",                              "slug": "history"},
    {"name": "Fine Arts",                            "slug": "fine-arts"},
    {"name": "Music",                                "slug": "music"},
    {"name": "French",                               "slug": "french"},
    {"name": "Animal Husbandry",                    "slug": "animal-husbandry"},
    {"name": "Insurance",                            "slug": "insurance"},
    {"name": "Civic Education",                     "slug": "civic-education"},
    {"name": "Further Mathematics",                 "slug": "further-mathematics"},
    {"name": "Yoruba",                               "slug": "yoruba"},
    {"name": "Igbo",                                 "slug": "igbo"},
    {"name": "Arabic",                               "slug": "arabic"},
    {"name": "Home Economics",                      "slug": "home-economics"},
    {"name": "Hausa",                                "slug": "hausa"},
    {"name": "Book Keeping",                        "slug": "book-keeping"},
    {"name": "Data Processing",                     "slug": "data-processing"},
    {"name": "Catering Craft Practice",             "slug": "catering-craft-practice"},
    {"name": "Computer Studies",                    "slug": "computer-studies"},
    {"name": "Marketing",                            "slug": "marketing"},
    {"name": "Physical Education",                  "slug": "physical-education"},
    {"name": "Office Practice",                     "slug": "office-practice"},
    {"name": "Technical Drawing",                   "slug": "technical-drawing"},
    {"name": "Food and Nutrition",                  "slug": "food-and-nutrition"},
    {"name": "Home Management",                     "slug": "home-management"},
]


# ── HTTP helpers ───────────────────────────────────────────────────────────────

def get_page(url: str, retries: int = 3) -> BeautifulSoup | None:
    """Fetch a URL and return BeautifulSoup, or None on failure."""
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=get_headers(), timeout=20)
            if resp.status_code == 200:
                resp.encoding = "utf-8"
                return BeautifulSoup(resp.text, "lxml")
            elif resp.status_code == 429:
                wait = 15 * (attempt + 1)
                print(f"  Rate limited. Waiting {wait}s...")
                time.sleep(wait)
            elif resp.status_code == 500:
                # Server error - retry with longer delay
                wait = 10 * (attempt + 1)
                print(f"  HTTP 500 for {url} - retry {attempt + 1}/{retries} in {wait}s...")
                time.sleep(wait)
            elif resp.status_code == 404:
                return None
            else:
                print(f"  HTTP {resp.status_code} for {url}")
                time.sleep(3)
        except requests.RequestException as e:
            print(f"  Request error ({attempt + 1}/{retries}): {e}")
            time.sleep(3)
    return None


# ── Cloudinary upload ─────────────────────────────────────────────────────────

_upload_cache: dict[str, str] = {}   # src_url → cloudinary_url


def upload_to_cloudinary(src_url: str, subject_slug: str, retries: int = 3) -> str:
    """
    Upload image from src_url directly to Cloudinary.
    Returns the CDN secure_url, or "" on failure.
    Skips images that return non-200 (broken/missing).
    """
    # Convert relative URLs to absolute URLs
    original_url = src_url
    if src_url.startswith("/"):
        src_url = f"{BASE_URL}{src_url}"
        print(f"    [CDN] Converted relative to absolute: {original_url} -> {src_url}")
    
    if src_url in _upload_cache:
        print(f"    [CDN] Using cached URL for: {original_url}")
        return _upload_cache[src_url]

    # Quick HEAD check — skip broken images immediately
    try:
        head = requests.head(src_url, headers=get_headers(), timeout=10)
        if head.status_code != 200:
            print(f"    [SKIP] Image not available (HTTP {head.status_code}): {src_url}")
            _upload_cache[src_url] = ""
            return ""
        print(f"    [CDN] HEAD check passed: {src_url}")
    except requests.RequestException as e:
        print(f"    [SKIP] Image HEAD request failed: {e}")
        _upload_cache[src_url] = ""
        return ""

    filename  = src_url.split("/")[-1]
    # Clean filename for Cloudinary public_id (remove URL encoding)
    clean_filename = filename.replace("%20", "_").replace("%28", "(").replace("%29", ")")
    public_id = f"myschool/{subject_slug}/{os.path.splitext(clean_filename)[0]}"

    # Check if image already exists on Cloudinary
    try:
        existing = cloudinary.api.resource(public_id, resource_type="image")
        if existing:
            cdn_url = existing.get("secure_url", "")
            if cdn_url:
                _upload_cache[src_url] = cdn_url
                print(f"    [CDN] Already exists on Cloudinary: {filename}")
                return cdn_url
    except Exception:
        # Resource doesn't exist or API error, proceed with upload
        pass

    for attempt in range(retries):
        try:
            print(f"    [CDN] Attempting upload ({attempt + 1}/{retries}): {src_url}")
            result = cloudinary.uploader.upload(
                src_url,
                public_id=public_id,
                overwrite=False,
                resource_type="image",
            )
            cdn_url = result["secure_url"]
            _upload_cache[src_url] = cdn_url
            print(f"    [CDN] Uploaded: {filename}")
            return cdn_url
        except Exception as e:
            err = str(e)
            # If the image itself is invalid/corrupt, don't retry
            if "Invalid image" in err or "not a valid" in err.lower():
                print(f"    [SKIP] Invalid image: {filename}")
                _upload_cache[src_url] = ""
                return ""
            print(f"    [CDN] Upload error ({attempt + 1}/{retries}): {e}")
            time.sleep(3)

    print(f"    [CDN] Failed after {retries} retries: {filename}")
    _upload_cache[src_url] = ""
    return ""


# ── Pagination ─────────────────────────────────────────────────────────────────

def get_total_pages(soup: BeautifulSoup) -> int:
    max_page = 1
    for a in soup.find_all("a", href=True):
        m = re.search(r"\?page=(\d+)", a["href"])
        if m:
            max_page = max(max_page, int(m.group(1)))
    for a in soup.find_all("a", string=re.compile(r"^\d+$")):
        try:
            max_page = max(max_page, int(a.get_text(strip=True)))
        except ValueError:
            pass
    return max_page


# ── HTML → clean text/LaTeX ────────────────────────────────────────────────────

def elem_to_text(elem) -> str:
    """
    Convert a BeautifulSoup element to a clean text string.
    Preserves LaTeX \\(...\\) and \\[...\\] as-is.
    Joins inline content with spaces, paragraphs with newlines.
    """
    if elem is None:
        return ""
    parts = []
    for child in elem.children:
        if isinstance(child, NavigableString):
            t = str(child).replace("\xa0", " ").strip()
            if t:
                parts.append(t)
        elif child.name in ("p", "div", "br"):
            inner = elem_to_text(child).strip()
            if inner:
                parts.append(inner)
        elif child.name in ("strong", "em", "b", "i", "span", "ins", "a"):
            inner = elem_to_text(child).strip()
            if inner:
                parts.append(inner)
        elif child.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            inner = elem_to_text(child).strip()
            if inner:
                parts.append(inner)
        else:
            # Skip nav/ad elements
            cls = " ".join(child.get("class", []))
            if any(x in cls for x in ["badge", "btn", "t_container", "sharethis"]):
                continue
            inner = elem_to_text(child).strip()
            if inner:
                parts.append(inner)
    return "\n".join(parts) if any("\n" in p for p in parts) else " ".join(parts)


def is_garbage_text(text: str) -> bool:
    """Detect if text is garbage (e.g., repeated single characters like 'o\no\no')."""
    if not text or len(text) < 10:
        return True
    
    # Check for repeated single character patterns
    lines = text.split('\n')
    if len(lines) > 3:
        # Check if most lines are the same single character
        unique_chars = set(line.strip() for line in lines if line.strip())
        if len(unique_chars) == 1 and len(list(unique_chars)[0]) == 1:
            return True
    
    # Check for text that's mostly degree symbols or similar
    if re.match(r'^[o°\s\n]+$', text):
        return True
    
    return False


def get_explanation_html(soup: BeautifulSoup) -> tuple[str, str]:
    """
    Extract explanation text and explanation image URL from the detail page.
    Returns (explanation_text, explanation_image_url).
    Captures ALL paragraphs in the explanation block, not just the first.
    """
    expl_header = soup.find(string=re.compile(r"^Explanation$", re.IGNORECASE))
    if not expl_header:
        return "", ""

    expl_parent = expl_header.find_parent()
    if not expl_parent:
        return "", ""

    # The explanation content lives in the same parent div as the header
    # Collect ALL <p> siblings/children after the <h5>Explanation</h5>
    container = expl_parent.parent
    if container is None:
        return "", ""

    # Find all <p> tags inside the explanation container (sibling of h5 or children)
    # Strategy: get the div that wraps both the h5 and the paragraphs
    text_parts = []
    expl_img_url = ""

    # Walk the container's children after the Explanation h5
    found_header = False
    for child in container.children:
        if isinstance(child, NavigableString):
            continue
        if child == expl_parent:
            found_header = True
            continue
        if not found_header:
            continue
        # Stop at navigation buttons or contribution sections
        cls = " ".join(child.get("class", []))
        if any(x in cls for x in ["clearfix", "mt-5", "sharethis", "contributions"]):
            break
        tag = child.name
        if tag in ("p", "div", "ul", "ol", "table"):
            # Check for explanation image
            img = child.find("img", src=re.compile(r"storage/classroom/"))
            if img:
                expl_img_url = img["src"]
            text = elem_to_text(child).strip()
            if text:
                text_parts.append(text)

    # Also check direct children of expl_parent (e.g. when p tags are siblings of h5)
    if not text_parts:
        for sib in expl_parent.find_next_siblings():
            cls = " ".join(sib.get("class", []))
            if any(x in cls for x in ["clearfix", "mt-5", "sharethis"]):
                break
            img = sib.find("img", src=re.compile(r"storage/classroom/"))
            if img:
                expl_img_url = img["src"]
            text = elem_to_text(sib).strip()
            if text:
                text_parts.append(text)

    expl_text = "\n".join(text_parts).strip()
    
    # Filter out garbage text
    if is_garbage_text(expl_text):
        return "", expl_img_url
    
    return expl_text, expl_img_url


# ── Listing page parser ────────────────────────────────────────────────────────

def parse_questions_from_listing(soup: BeautifulSoup, subject_slug: str) -> list[dict]:
    """Extract question stubs from a subject listing page."""
    questions = []
    pattern = re.compile(
        rf"https?://myschool\.ng/classroom/{re.escape(subject_slug)}/(\d+)"
    )

    for link in soup.find_all("a", href=pattern):
        href = link["href"].split("?")[0]
        m = pattern.search(href)
        if not m:
            continue
        q_id = int(m.group(1))

        container = link.parent
        if container is None:
            continue

        block_text = container.get_text(separator="\n", strip=True)

        # Exam type and year
        exam_info = re.search(
            r"\b(JAMB|WAEC|NECO|NABTEB|GCE)\s+(\d{4})\b", block_text, re.IGNORECASE
        )
        exam_type = exam_info.group(1).upper() if exam_info else ""
        exam_year = exam_info.group(2) if exam_info else ""

        # Options
        options: dict[str, str] = {}
        for opt in re.finditer(
            r"\b([A-E])\.\s+(.+?)(?=\n[A-E]\.\s+|\[View|View\s+Answer"
            r"|\n(?:JAMB|WAEC|NECO|NABTEB)\b|\Z)",
            block_text, re.DOTALL,
        ):
            options[opt.group(1)] = opt.group(2).strip()

        # Question text (before first option)
        question_text = ""
        first_opt = re.search(r"\bA\.\s+", block_text)
        if first_opt:
            raw = re.sub(r"^\d+\s*", "", block_text[:first_opt.start()].strip()).strip()
            question_text = raw

        # Classroom image (not ads)
        image_url = ""
        for img in container.find_all("img", src=re.compile(r"storage/classroom/")):
            image_url = img["src"]
            break

        questions.append({
            "id": q_id,
            "subject": subject_slug,
            "exam_type": exam_type,
            "exam_year": exam_year,
            "question": question_text,
            "options": options,
            "image_url": image_url,
            "image_cloudinary": "",
            "correct_answer": "",
            "explanation": "",
            "explanation_image_url": "",
            "explanation_image_cloudinary": "",
            "url": href,
        })

    return questions


# ── Detail page parser ─────────────────────────────────────────────────────────

def enrich_with_detail(question: dict, upload_images: bool, max_retries: int = 3) -> dict:
    """
    Fetch the detail page and fill:
    - question text (full, from <p> tags in question-desc)
    - passage/context (for English comprehension etc.)
    - options (from <ul class="list-unstyled">)
    - correct_answer
    - explanation (ALL paragraphs)
    - image URLs + Cloudinary CDN URLs
    
    Args:
        max_retries: Number of times to retry fetching explanation if it's garbage/empty
    """
    soup = get_page(question["url"])
    if not soup:
        return question

    subject_slug = question["subject"]

    # ── Question descriptor block ──────────────────────────────────────────
    q_desc = soup.find("div", class_="question-desc")
    if q_desc:
        # Image
        img_tag = q_desc.find("img", src=re.compile(r"storage/classroom/"))
        if img_tag and not question["image_url"]:
            question["image_url"] = img_tag["src"]

        # Passage / context card (novel references, reading passages, etc.)
        card = q_desc.find("div", class_="card")
        if card:
            question["passage"] = card.get_text(separator=" ", strip=True)
        else:
            question.setdefault("passage", "")

        # Question text: join ALL <p> tags in question-desc
        # (some questions have multi-paragraph setup text)
        paras = []
        for p in q_desc.find_all("p"):
            t = elem_to_text(p).strip()
            if t:
                paras.append(t)
        if paras:
            question["question"] = "\n".join(paras)

    else:
        question.setdefault("passage", "")

    # ── Options ───────────────────────────────────────────────────────────
    ul = soup.find("ul", class_="list-unstyled")
    if ul:
        options: dict[str, str] = {}
        for li in ul.find_all("li"):
            strong = li.find("strong")
            if strong:
                key = strong.get_text(strip=True).rstrip(".")
                strong.decompose()
                value = elem_to_text(li).strip()
                if key and value:
                    options[key] = value
        if options:
            question["options"] = options

    # ── Correct answer ─────────────────────────────────────────────────────
    correct_tag = soup.find(class_="text-success",
                            string=re.compile(r"Correct Answer", re.IGNORECASE))
    if not correct_tag:
        correct_tag = soup.find(string=re.compile(r"Correct Answer", re.IGNORECASE))
    if correct_tag:
        text = (correct_tag.get_text(strip=True)
                if hasattr(correct_tag, "get_text")
                else str(correct_tag))
        m = re.search(r"Option\s*([A-E])", text, re.IGNORECASE)
        if m:
            question["correct_answer"] = m.group(1).upper()

    # ── Explanation (full multi-paragraph) with retry logic ────────────────
    expl_text, expl_img_url = get_explanation_html(soup)
    
    # Retry if explanation is garbage or empty
    for retry in range(max_retries):
        if expl_text and not is_garbage_text(expl_text):
            break
        if retry < max_retries - 1:
            print(f"    [RETRY] Explanation garbage/empty for Q#{question['id']}, retry {retry + 1}/{max_retries}")
            time.sleep(1)
            soup = get_page(question["url"])
            if soup:
                expl_text, expl_img_url = get_explanation_html(soup)
    
    question["explanation"] = expl_text
    if expl_img_url:
        question["explanation_image_url"] = expl_img_url

    # ── Exam type/year from breadcrumb ────────────────────────────────────
    if not question["exam_type"] or not question["exam_year"]:
        for a in soup.select("a[href*='exam_type'], a[href*='exam_year']"):
            href = a.get("href", "")
            et = re.search(r"exam_type=(\w+)", href)
            ey = re.search(r"exam_year=(\d+)", href)
            if et and not question["exam_type"]:
                question["exam_type"] = et.group(1).upper()
            if ey and not question["exam_year"]:
                question["exam_year"] = ey.group(1)

    # ── Cloudinary uploads ─────────────────────────────────────────────────
    if upload_images:
        for src_field, cdn_field in [
            ("image_url",             "image_cloudinary"),
            ("explanation_image_url", "explanation_image_cloudinary"),
        ]:
            src_url = question.get(src_field, "")
            if src_url and not question.get(cdn_field):
                time.sleep(IMAGE_DELAY)
                cdn_url = upload_to_cloudinary(src_url, subject_slug)
                if cdn_url:
                    question[cdn_field] = cdn_url
                    print(f"    [CDN] {cdn_url.split('/')[-1]}")

    return question


# ── Git autocommit ─────────────────────────────────────────────────────────────

SKIPPED_QUESTIONS_FILE = "skipped_questions.json"


# ── Main scraper ───────────────────────────────────────────────────────────────

def validate_question(question: dict) -> tuple[bool, str]:
    """Validate a question has required fields. Returns (is_valid, reason)."""
    # Check question text is not empty or just symbols
    q_text = str(question.get("question", "")).strip()
    if not q_text or len(q_text) < 5:
        return False, "Question text is empty or too short"
    
    # Check for garbage text (repeated single characters)
    if is_garbage_text(q_text):
        return False, "Question text appears to be garbage"
    
    # Check options exist and have meaningful content
    options = question.get("options", {})
    if not isinstance(options, dict) or len(options) < 2:
        return False, "Question has fewer than 2 options"
    
    # Check option values are not empty (allow single characters like numbers/letters)
    for key, value in options.items():
        if not str(value).strip():
            return False, f"Option {key} is empty"
    
    return True, ""


def add_skipped_question(question: dict, reason: str):
    """Add a skipped question to the skipped_questions.json file."""
    skipped_entry = {
        "id": question.get("id"),
        "subject": question.get("subject"),
        "url": question.get("url"),
        "reason": reason,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    }
    
    # Load existing skipped questions
    skipped = []
    if os.path.exists(SKIPPED_QUESTIONS_FILE):
        try:
            with open(SKIPPED_QUESTIONS_FILE, "r", encoding="utf-8") as f:
                skipped = json.load(f)
        except (json.JSONDecodeError, IOError):
            skipped = []
    
    # Add new entry
    skipped.append(skipped_entry)
    
    # Save
    with open(SKIPPED_QUESTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(skipped, f, ensure_ascii=False, indent=2)


def scrape_subject(
    subject_slug: str,
    max_pages: int | None = None,
    output_dir: str = "questions",
    fetch_details: bool = True,
    upload_images: bool = True,
) -> list[dict]:
    """
    Scrape all past questions for a subject and save to
    {output_dir}/{subject_slug}.json

    JSON schema per question:
    {
        "id": 26348,
        "subject": "mathematics",
        "exam_type": "WAEC",
        "exam_year": "1998",
        "question": "In PQR...",
        "passage": "",                          // reading passage if any
        "options": {"A": "...", "B": "..."},
        "image_url": "https://myschool.ng/...", // original
        "image_cloudinary": "https://res.cloudinary.com/...",
        "correct_answer": "B",
        "explanation": "Full multi-paragraph explanation...",
        "explanation_image_url": "",
        "explanation_image_cloudinary": "",
        "url": "https://myschool.ng/classroom/mathematics/26348"
    }

    Args:
        commit_frequency: Commit every N questions (default: 1 for per-question commits)
    """
    subject_url = f"{CLASSROOM_URL}/{subject_slug}"
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    output_file = os.path.join(output_dir, f"{subject_slug}.json")

    # Resume from previous run
    existing_ids: set[int] = set()
    all_questions: list[dict] = []
    skipped_count = 0
    pages_skipped = 0
    if os.path.exists(output_file):
        with open(output_file, "r", encoding="utf-8") as f:
            all_questions = json.load(f)
        existing_ids = {q["id"] for q in all_questions}
        print(f"  Resuming: {len(existing_ids)} questions already saved.")

    print(f"\n{'='*60}")
    print(f"  Subject    : {subject_slug}")
    print(f"  Details    : {fetch_details} | Cloudinary: {upload_images}")
    print(f"{'='*60}")

    soup = get_page(subject_url)
    if not soup:
        print(f"  ERROR: Could not fetch {subject_url}")
        return all_questions

    total_pages = get_total_pages(soup)
    if max_pages:
        total_pages = min(total_pages, max_pages)
    print(f"  Pages      : {total_pages}\n")

    for page_num in range(1, total_pages + 1):
        page_url = f"{subject_url}?page={page_num}" if page_num > 1 else subject_url

        if page_num > 1:
            # Add random jitter to delay to avoid detection
            delay = REQUEST_DELAY + random.uniform(0.5, 1.5)
            time.sleep(delay)
            soup = get_page(page_url)
            if not soup:
                print(f"  Page {page_num}: fetch failed, skipping.")
                pages_skipped += 1
                continue

        stubs = parse_questions_from_listing(soup, subject_slug)
        new_stubs = [s for s in stubs if s["id"] not in existing_ids]
        print(f"  Page {page_num:>4}/{total_pages} | {len(stubs)} q | {len(new_stubs)} new")

        for stub in new_stubs:
            if fetch_details:
                # Add random jitter to delay to avoid detection
                delay = DETAIL_DELAY + random.uniform(0.3, 0.7)
                time.sleep(delay)
                question = enrich_with_detail(stub, upload_images)
            else:
                question = stub

            # Validate question before saving
            is_valid, reason = validate_question(question)
            if not is_valid:
                print(f"    [SKIP] Q#{question['id']}: {reason}")
                add_skipped_question(question, reason)
                skipped_count += 1
                continue

            all_questions.append(question)
            existing_ids.add(question["id"])

            has_img = "[IMG]" if question.get("image_cloudinary") or question.get("image_url") else ""
            print(f"    Q#{question['id']:<6} {question['exam_type']:<5} "
                  f"{question['exam_year']} ans={question['correct_answer'] or '?'} {has_img}")

        # Save after every page
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(all_questions, f, ensure_ascii=False, indent=2)

    print(f"\n  Done: {len(all_questions)} questions -> {output_file}")
    print(f"  Summary: {len(all_questions)} saved, {skipped_count} skipped, {pages_skipped} pages failed")
    
    return all_questions


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Scrape past questions from myschool.ng/classroom",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scraper.py                                    # mathematics, all pages
  python scraper.py --subject physics                  # physics, all pages
  python scraper.py --subject mathematics --pages 5    # first 5 pages
  python scraper.py --all                              # every subject
  python scraper.py --subject biology --no-images      # skip Cloudinary
  python scraper.py --subject biology --no-details     # fast, no answers
  python scraper.py --list-subjects                    # show all slugs
        """,
    )
    parser.add_argument("--subject",  default="mathematics", metavar="SLUG")
    parser.add_argument("--pages",    type=int, default=None, metavar="N")
    parser.add_argument("--output",   default="questions",   metavar="DIR")
    parser.add_argument("--no-details",    action="store_true")
    parser.add_argument("--no-images",     action="store_true")
    parser.add_argument("--list-subjects", action="store_true")
    parser.add_argument("--all",           action="store_true")
    parser.add_argument("--workers",       type=int, default=4, metavar="N", help="Parallel workers (default: 4)")

    args = parser.parse_args()

    if args.list_subjects:
        print(f"\n{'#':>3}  {'Name':<45} Slug")
        print("-" * 75)
        for i, s in enumerate(SUBJECTS, 1):
            print(f"{i:>3}. {s['name']:<45} {s['slug']}")
        return

    fetch_details = not args.no_details
    upload_images = not args.no_images

    if args.all:
        print(f"\nScraping {len(SUBJECTS)} subjects with {args.workers} workers...\n")
        
        def scrape_wrapper(subject):
            return scrape_subject(
                subject["slug"], 
                args.pages, 
                args.output, 
                fetch_details, 
                upload_images
            )
        
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(scrape_wrapper, s): s for s in SUBJECTS}
            
            with tqdm(total=len(SUBJECTS), desc="Overall Progress", unit="subject") as pbar:
                for future in as_completed(futures):
                    subject = futures[future]
                    try:
                        future.result()
                        pbar.set_postfix_str(f"{subject['name']}")
                        pbar.update(1)
                    except Exception as e:
                        print(f"  ERROR scraping {subject['name']}: {e}")
                        pbar.update(1)
        
        print("\nAll subjects done!")
        return

    valid_slugs = {s["slug"] for s in SUBJECTS}
    if args.subject not in valid_slugs:
        print(f"Unknown slug: '{args.subject}'. Run --list-subjects.")
        return

    scrape_subject(args.subject, args.pages, args.output, fetch_details, upload_images)


if __name__ == "__main__":
    main()

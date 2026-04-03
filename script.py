#!/usr/bin/env python3
"""
translate_to_sql.py

Start with exporting in a JSON file all the missing translations with the following query:

SELECT
	"module_id" ,
	"key",
	value
FROM
	core.translations
WHERE
	language_id = 'en'
	AND module_id IN ('core', 'services', 'unit_of_measure', 'inventory', 'seed_inventory') -- Change this list to the modules you want to translate
	AND "key" NOT IN (SELECT KEY from core.translations WHERE language_id = 'fr') -- Change 'fr' to your target language
ORDER BY module_id ;

Try with a subset first

Reads a JSON file containing an array of objects like:
  {"module_id": "core", "key": "user.name", "value": "User name"}

Generates a SQL file with one CALL per translation:
  CALL module_id.p_create_translation('target_lang', 'key', 'value');

Check the dates format of the following translations, it happens that it replaces DD, MM or YYYY with the wrong format:
'defaultDatetime',
'longDatetime',
'localDatetime',
'longLocalDatetime',
'defaultDate',
'localDate'

Check the language names translations (en, fr, de, pt, es) as well that must remain the name in the local language and not translate it to the target language (ex: en should be English in all languages, not Anglais in French or Inglés in Spanish).

Configuration sources (priority: CLI > .env > defaults):
  - .env file (default path: .env)
  - CLI arguments (--api-key, --input, --output, ...)

Features:
  - Preserves placeholders like {{id}} by masking them before translation and restoring them after.
  - Batches translation requests to DeepL to respect size/quotas.
  - Escapes single quotes for SQL by doubling them.
  - Uses module_id per JSON object; falls back to DEFAULT_MODULE_ID from .env or CLI.
  - Validates module_id to avoid injection (allowed chars: letters, digits, underscore, dot).
  - Supports a --no-translate mode to use existing translations in the JSON.

Dependencies:
  pip install requests python-dotenv
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import requests
from requests.adapters import HTTPAdapter, Retry

# Optional import of dotenv; if not available, load_dotenv is a noop.
try:
    from dotenv import load_dotenv
except Exception:
    def load_dotenv(path: Optional[str] = None):
        return

# Regex to find placeholders like {{ ... }}
PLACEHOLDER_RE = re.compile(r"{{\s*[^}]+\s*}}")

# Token template unlikely to collide with translated text
TOKEN_FMT = "___PH_{idx}__{uid}___"

# Validate module_id: allow letters, digits, underscore and dot (no spaces, no quotes, no semicolons)
MODULE_ID_RE = re.compile(r"^[A-Za-z0-9_.]+$")


def sql_escape(s: str) -> str:
    """Escape single quotes for SQL literals by doubling them."""
    return s.replace("'", "''")


def mask_placeholders(text: str, mapping: Dict[str, str], uid: str) -> str:
    """
    Replace each {{...}} placeholder with a unique token.
    mapping is mutated to map token -> original placeholder.
    uid is a short random id to avoid cross-entry collisions.
    """
    def repl(match):
        idx = len(mapping)
        token = TOKEN_FMT.format(idx=idx, uid=uid)
        mapping[token] = match.group(0)
        return token
    return PLACEHOLDER_RE.sub(repl, text)


def unmask_placeholders(text: str, mapping: Dict[str, str]) -> str:
    """Replace tokens with the original placeholders from mapping."""
    for token, placeholder in mapping.items():
        text = text.replace(token, placeholder)
    return text


def create_requests_session(retries: int = 3, backoff: float = 0.3) -> requests.Session:
    """
    Create a requests.Session with retry logic for transient HTTP errors.
    Retries on status codes like 429, 500, 502, 503, 504.
    """
    session = requests.Session()
    retry = Retry(
        total=retries,
        backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["POST", "GET"]),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def translate_batch_deepl(
    texts: List[str],
    api_key: str,
    deepl_url: str,
    source_lang: str = "en",
    target_lang: str = "fr",
    session: Optional[requests.Session] = None
) -> List[str]:
    """
    Translate a list of texts using DeepL (one HTTP request per batch).
    Returns the list of translated texts in the same order.
    """
    if not texts:
        return []
    if session is None:
        session = create_requests_session()

    headers = {"Authorization": f"DeepL-Auth-Key {api_key}"}
    data = []
    for t in texts:
        data.append(("text", t))
    data.append(("target_lang", target_lang))
    data.append(("source_lang", source_lang))

    resp = session.post(deepl_url, data=data, headers=headers, timeout=60)
    resp.raise_for_status()
    j = resp.json()
    return [item["text"] for item in j.get("translations", [])]


def build_sql_line(module_id: str, target_lang: str, key: str, value: str) -> str:
    """
    Build the SQL CALL line using the provided module_id.
    module_id is used as an identifier (not quoted). It must be validated beforehand.
    """
    k = sql_escape(key)
    v = sql_escape(value)
    t = sql_escape(target_lang)
    return f"CALL {module_id}.p_create_translation('{t}', '{k}', '{v}');"


def chunked(seq: List, size: int):
    """Yield successive chunks from seq of length 'size'."""
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def str_to_bool(s: Optional[str]) -> bool:
    if s is None:
        return False
    return str(s).strip().lower() in ("1", "true", "yes", "y")


def validate_module_id(mid: Optional[str]) -> Optional[str]:
    """Return mid if valid, else None."""
    if mid is None:
        return None
    mid = str(mid).strip()
    if not mid:
        return None
    if MODULE_ID_RE.match(mid):
        return mid
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Translate JSON -> SQL (DeepL) while preserving {{...}} placeholders and using per-entry module_id."
    )
    parser.add_argument("--dotenv", default=".env", help="Path to .env file (default: .env)")
    parser.add_argument("--api-key", help="DeepL API key (overrides DEEPL_API_KEY in .env)")
    parser.add_argument("--input", help="Input JSON file (array of {module_id, key, value})")
    parser.add_argument("--output", help="Output SQL file")
    parser.add_argument("--default-module", help="Default module_id when an entry lacks module_id (overrides DEFAULT_MODULE_ID in .env)")
    parser.add_argument("--no-translate", action="store_true", help="Do not call DeepL; use values from JSON directly")
    parser.add_argument("--source-lang", help="Source language (default en)")
    parser.add_argument("--target-lang", help="Target language (default fr)")
    parser.add_argument("--batch-size", type=int, help="Number of items per DeepL request (default 50)")
    parser.add_argument("--deepl-url", help="DeepL API URL (overrides DEEPL_API_URL in .env)")
    parser.add_argument("--on-missing-module", choices=("use-default", "error", "skip"),
                        default="use-default",
                        help="Behavior when module_id is missing or invalid for an entry (default: use-default)")
    args = parser.parse_args()

    # Load .env if present
    if args.dotenv and Path(args.dotenv).exists():
        load_dotenv(args.dotenv)

    # Configuration with precedence: CLI > .env > defaults
    api_key = args.api_key or os.getenv("DEEPL_API_KEY")
    input_file = args.input or os.getenv("INPUT_FILE") or "translations_en.json"
    output_file = args.output or os.getenv("OUTPUT_FILE") or "translations_fr.sql"
    default_module = args.default_module or os.getenv("DEFAULT_MODULE_ID") or "core"
    source_lang = args.source_lang or os.getenv("SOURCE_LANG") or "en"
    target_lang = args.target_lang or os.getenv("TARGET_LANG") or "fr"
    batch_size = args.batch_size or int(os.getenv("BATCH_SIZE") or 50)
    deepl_url = args.deepl_url or os.getenv("DEEPL_API_URL") or "https://api-free.deepl.com/v2/translate"
    env_no_translate = str_to_bool(os.getenv("NO_TRANSLATE"))
    no_translate = args.no_translate or env_no_translate
    on_missing_module = args.on_missing_module  # "use-default", "error", or "skip"

    # Validate default_module
    valid_default = validate_module_id(default_module)
    if valid_default is None:
        sys.stderr.write(f"ERROR: DEFAULT_MODULE_ID / --default-module is invalid: {default_module}\n")
        sys.exit(2)
    default_module = valid_default

    if not api_key and not no_translate:
        sys.stderr.write("ERROR: DeepL API key not provided. Use --api-key or set DEEPL_API_KEY in .env\n")
        sys.exit(2)

    infile = Path(input_file)
    outfile = Path(output_file)
    if not infile.exists():
        sys.stderr.write(f"ERROR: input file not found: {infile}\n")
        sys.exit(3)

    # Load JSON
    raw = json.loads(infile.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        sys.stderr.write("ERROR: input JSON must be an array of objects.\n")
        sys.exit(4)

    # Prepare items: for each object store (module_id, key, mapping, masked_text, original_value)
    uid = os.urandom(6).hex()  # short unique id to avoid token collisions
    items: List[Tuple[str, str, Dict[str, str], str, str]] = []  # (module_id, key, mapping, masked_text, original_value)
    texts_to_translate: List[str] = []

    skipped = 0
    errored = 0

    for idx, obj in enumerate(raw):
        raw_mid = obj.get("module_id")
        key = obj.get("key")
        val = obj.get("value", "")

        if key is None:
            sys.stderr.write(f"WARNING: entry index {idx} missing key -> skipped\n")
            skipped += 1
            continue

        mid = validate_module_id(raw_mid)
        if mid is None:
            # handle according to policy
            if on_missing_module == "use-default":
                mid = default_module
            elif on_missing_module == "skip":
                skipped += 1
                continue
            else:  # "error"
                sys.stderr.write(f"ERROR: entry index {idx} has missing/invalid module_id: {raw_mid}\n")
                errored += 1
                continue

        mapping: Dict[str, str] = {}
        if no_translate:
            masked = val
        else:
            masked = mask_placeholders(val, mapping, uid)
            texts_to_translate.append(masked)

        items.append((mid, key, mapping, masked, val))

    if errored:
        sys.stderr.write(f"Exiting due to {errored} entries with invalid module_id(s).\n")
        sys.exit(5)

    # Translate (or reuse existing)
    translated_texts: List[str]
    if no_translate:
        translated_texts = [it[4] for it in items]
    else:
        session = create_requests_session()
        all_translated: List[str] = []
        start_index = 0
        for chunk in chunked(texts_to_translate, batch_size):
            try:
                translated_chunk = translate_batch_deepl(
                    chunk,
                    api_key=api_key,
                    deepl_url=deepl_url,
                    source_lang=source_lang,
                    target_lang=target_lang,
                    session=session,
                )
            except Exception as e:
                sys.stderr.write(f"ERROR during translation (batch starting at {start_index}): {e}\n")
                sys.exit(6)
            if len(translated_chunk) != len(chunk):
                sys.stderr.write("ERROR: DeepL response length does not match request length.\n")
                sys.exit(7)
            all_translated.extend(translated_chunk)
            start_index += len(chunk)
        translated_texts = all_translated

    # Reinsert placeholders and build SQL lines
    out_lines: List[str] = []
    tt_iter = iter(translated_texts)
    for mid, key, mapping, masked, original in items:
        if no_translate:
            translated = original
        else:
            translated = next(tt_iter)
            translated = unmask_placeholders(translated, mapping)
        out_lines.append(build_sql_line(mid, target_lang, key, translated))

    # Write output
    outfile.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    print(f"Generated {outfile} — {len(out_lines)} lines (skipped={skipped}, errored={errored}, no_translate={no_translate})")


if __name__ == "__main__":
    main()
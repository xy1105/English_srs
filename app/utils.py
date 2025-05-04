# app/utils.py
import csv
from io import StringIO, BytesIO
from flask import current_app, flash
from datetime import datetime, timezone, timedelta # Added timedelta
from .db import get_db
import sqlite3
import re # Ensure re is imported
import os # Needed for allowed_file

# --- Datetime Helpers ---

def now_utc():
    """Return the current time in UTC."""
    return datetime.now(timezone.utc)

def parse_datetime_utc(date_string):
    """Safely parse ISO datetime string or YYYY-MM-DD HH:MM:SS into UTC datetime object."""
    if not date_string:
        return None
    try:
        dt = None
        # Handle already being a datetime object
        if isinstance(date_string, datetime):
            dt = date_string
        elif isinstance(date_string, str):
             # Try ISO format with Z or offset first
            try:
                # Handle 'Z' explicitly for older Python versions if needed
                cleaned_str = date_string.replace('Z', '+00:00')
                dt = datetime.fromisoformat(cleaned_str)
            except ValueError:
                # Fallback to common non-ISO formats
                formats_to_try = [
                    '%Y-%m-%d %H:%M:%S.%f%z', # ISO with microsecond and timezone
                    '%Y-%m-%d %H:%M:%S%z',    # ISO without microsecond
                    '%Y-%m-%d %H:%M:%S',      # Common format, assume UTC
                    '%Y-%m-%d',              # Date only, assume UTC start of day
                ]
                for fmt in formats_to_try:
                    try:
                        dt_naive = datetime.strptime(date_string, fmt)
                        # Assume UTC if format doesn't include timezone info
                        dt = dt_naive.replace(tzinfo=timezone.utc)
                        break # Stop trying formats once one works
                    except ValueError:
                        continue # Try next format
                if dt is None: # If no format matched
                    raise ValueError("String does not match known formats")
        else:
             # Not a string or datetime object
             return None

        # Ensure the final datetime object is timezone-aware and in UTC
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc) # Assume UTC if naive
        else:
            return dt.astimezone(timezone.utc) # Convert to UTC if it has other timezone

    except (ValueError, TypeError) as e:
        current_app.logger.warning(f"Could not parse datetime: '{date_string}'. Error: {e}")
        return None

def format_datetime_local(dt_utc_or_str, fmt='%Y-%m-%d %H:%M'):
    """Format a UTC datetime object or string into local time string."""
    dt_utc = parse_datetime_utc(dt_utc_or_str) # Try parsing if input is string

    if not dt_utc:
        return "N/A" # Or return empty string?

    # Convert to local time and format
    try:
        # Get local timezone automatically
        local_tz = datetime.now().astimezone().tzinfo
        dt_local = dt_utc.astimezone(local_tz)
        return dt_local.strftime(fmt)
    except Exception as e:
        # Fallback if local timezone conversion fails
        current_app.logger.error(f"Error formatting datetime {dt_utc} to local: {e}")
        # Return UTC time with indicator
        return dt_utc.strftime(fmt + " (UTC)")

def format_due_date_relative(due_date_str):
    """Provides a human-friendly relative time string for due dates (e.g., '今天', '3天后', '2天前')."""
    due_dt_utc = parse_datetime_utc(due_date_str)
    if not due_dt_utc:
        return "无效日期"

    # Compare dates only (ignore time part for relative days)
    today_utc_start = now_utc().date()
    due_date_utc_start = due_dt_utc.date()

    delta_days = (due_date_utc_start - today_utc_start).days

    if delta_days < 0:
        return f"{-delta_days} 天前"
    elif delta_days == 0:
        return "今天"
    elif delta_days == 1:
        return "明天"
    else:
        return f"{delta_days} 天后"

# --- CSV Handling ---

def _determine_max_columns(db, table_name, group_by_col):
    """Helper to find max related items per concept for CSV export."""
    try:
        # Ensure table and column names are safe (basic check)
        if not re.match(r'^[a-zA-Z0-9_]+$', table_name) or not re.match(r'^[a-zA-Z0-9_]+$', group_by_col):
             raise ValueError("Invalid table or column name for max column calculation.")
        query = f"SELECT MAX(cnt) FROM (SELECT COUNT(id) as cnt FROM {table_name} GROUP BY {group_by_col})"
        result = db.execute(query).fetchone()
        return result[0] if result and result[0] else 1
    except (sqlite3.Error, ValueError) as e:
        current_app.logger.warning(f"Could not determine max {table_name} for CSV export: {e}. Defaulting to 1.")
        return 1

def export_concepts_to_csv():
    """Exports all concepts, meanings, collocations, and tags to a CSV string."""
    db = get_db()
    output = StringIO()
    output.write('\ufeff') # UTF-8 BOM for better Excel compatibility

    try:
        # Determine max number of meanings and collocations per concept for header generation
        max_meanings = _determine_max_columns(db, 'meanings', 'concept_id')
        max_collocations = _determine_max_columns(db, 'collocations', 'concept_id')

        # Define CSV Headers
        headers = ['term', 'phonetic', 'tags', 'etymology', 'synonyms', 'audio_url',
                   'error_count', 'srs_interval', 'srs_efactor', 'srs_due_date', 'last_reviewed_date']
        # Add dynamic headers for meanings
        for i in range(1, max_meanings + 1):
            headers.extend([f'part_of_speech_{i}', f'definition_{i}'])
        # Add dynamic headers for collocations
        for i in range(1, max_collocations + 1):
            headers.extend([f'phrase_{i}', f'example_{i}'])

        writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL) # Use minimal quoting
        writer.writerow(headers)

        # Fetch all concepts with related data efficiently
        concepts_query = """
            SELECT c.*, GROUP_CONCAT(DISTINCT t.name) as tag_names
            FROM concepts c
            LEFT JOIN concept_tags ct ON c.id = ct.concept_id
            LEFT JOIN tags t ON ct.tag_id = t.id
            GROUP BY c.id
            ORDER BY c.term COLLATE NOCASE
        """
        concepts = db.execute(concepts_query).fetchall()

        # Fetch all meanings and collocations once and group them by concept_id
        meanings_map = {}
        collocations_map = {}

        meanings_raw = db.execute('SELECT * FROM meanings ORDER BY concept_id, id').fetchall()
        for m in meanings_raw:
            cid = m['concept_id']
            if cid not in meanings_map: meanings_map[cid] = []
            meanings_map[cid].append(m)

        collocations_raw = db.execute('SELECT * FROM collocations ORDER BY concept_id, id').fetchall()
        for c in collocations_raw:
            cid = c['concept_id']
            if cid not in collocations_map: collocations_map[cid] = []
            collocations_map[cid].append(c)

        # Iterate through concepts and build rows
        for concept in concepts:
            concept_id = concept['id']
            meanings = meanings_map.get(concept_id, [])
            collocations = collocations_map.get(concept_id, [])
            tags_str = concept['tag_names'] or '' # Use pre-fetched tags

            # Prepare row data dictionary matching headers
            row_data = {
                'term': concept['term'], 'phonetic': concept['phonetic'], 'tags': tags_str,
                'etymology': concept['etymology'], 'synonyms': concept['synonyms'], 'audio_url': concept['audio_url'],
                'error_count': concept['error_count'], 'srs_interval': concept['srs_interval'],
                'srs_efactor': concept['srs_efactor'],
                # Format dates explicitly for consistency, handle None
                'srs_due_date': format_datetime_local(concept['srs_due_date'], '%Y-%m-%d %H:%M:%S') if concept['srs_due_date'] else '',
                'last_reviewed_date': format_datetime_local(concept['last_reviewed_date'], '%Y-%m-%d %H:%M:%S') if concept['last_reviewed_date'] else '',
            }

            # Add meaning data to the row dict
            for i, meaning in enumerate(meanings):
                if i >= max_meanings: break
                row_data[f'part_of_speech_{i+1}'] = meaning['part_of_speech']
                row_data[f'definition_{i+1}'] = meaning['definition']

            # Add collocation data to the row dict
            for i, coll in enumerate(collocations):
                if i >= max_collocations: break
                row_data[f'phrase_{i+1}'] = coll['phrase']
                row_data[f'example_{i+1}'] = coll['example']

            # Write the row using the header order, providing empty string for missing keys
            writer.writerow([row_data.get(h, '') for h in headers])

        current_app.logger.info(f"Successfully prepared CSV export string for {len(concepts)} concepts.")
        return output.getvalue()

    except sqlite3.Error as e:
        current_app.logger.error(f"Database error during CSV export: {e}", exc_info=True)
        flash("导出 CSV 时发生数据库错误。", "danger")
        return None
    except Exception as e:
        current_app.logger.error(f"Unexpected error during CSV export: {e}", exc_info=True)
        flash("导出 CSV 时发生未知错误。", "danger")
        return None

def import_concepts_from_csv(csv_file_content):
    """Imports concepts from CSV content (bytes or string). Skips existing terms."""
    db = get_db()
    errors = []
    imported_count = 0
    skipped_count = 0
    processed_terms = set() # Track terms processed in this import run to avoid duplicates within the file

    # --- 1. Decode Content and Create Reader ---
    try:
        content_str = ""
        if isinstance(csv_file_content, bytes):
             # Try decoding with common encodings
             encodings_to_try = ['utf-8-sig', 'utf-8', 'gbk', 'gb18030']
             for enc in encodings_to_try:
                 try:
                     content_str = csv_file_content.decode(enc)
                     current_app.logger.info(f"Successfully decoded CSV with {enc}.")
                     break
                 except UnicodeDecodeError:
                     continue # Try next encoding
             if not content_str:
                 raise ValueError(f"无法解码 CSV 文件编码。请确保文件为 {', '.join(encodings_to_try)} 编码之一。")
        elif isinstance(csv_file_content, str):
             content_str = csv_file_content
        else:
             raise TypeError("Input must be bytes or string")

        # Replace null bytes which can cause issues with csv module
        content_str = content_str.replace('\x00', '')
        csvfile = StringIO(content_str)

        # Sniff dialect, fallback to default comma delimiter
        try:
            sample = csvfile.read(4096) # Read a larger sample
            dialect = csv.Sniffer().sniff(sample)
            csvfile.seek(0)
            reader = csv.DictReader(csvfile, dialect=dialect)
            current_app.logger.info(f"CSV dialect detected: delimiter='{dialect.delimiter}', quotechar='{dialect.quotechar}'")
        except csv.Error as sniff_err:
            current_app.logger.warning(f"CSV Sniffing failed ({sniff_err}), falling back to comma delimiter.")
            csvfile.seek(0)
            reader = csv.DictReader(csvfile) # Assume standard comma-separated

        # Check for required header ('term') case-insensitively
        if not reader.fieldnames:
             raise ValueError("CSV 文件为空或无法读取列标题。")

        fieldnames_lower = [str(f).lower().strip() for f in reader.fieldnames if f] # Ensure fieldnames are strings
        required_columns = ['term']
        if not all(col.lower() in fieldnames_lower for col in required_columns):
             missing = [col for col in required_columns if col.lower() not in fieldnames_lower]
             error_msg = f"CSV 文件缺少必需的列标题: {', '.join(missing)}"
             raise ValueError(error_msg)

    except Exception as e:
        error_msg = f"解析 CSV 文件时出错: {e}"
        errors.append(error_msg)
        flash(error_msg, "danger")
        current_app.logger.error(f"Error reading/parsing CSV header/dialect: {e}", exc_info=True)
        return 0, errors

    # --- 2. Process Rows ---
    initial_due_date = now_utc().strftime('%Y-%m-%d %H:%M:%S')
    initial_interval = 1
    initial_efactor = 2.5

    for row_num, row in enumerate(reader, start=2): # Start line count from 2 (after header)
        term = None # Initialize term for error reporting
        try:
            # Normalize keys to lowercase and handle potential None keys/values
            row_lower = {str(k).lower().strip(): str(v).strip() for k, v in row.items() if k is not None and v is not None}
            term = row_lower.get('term', '').strip()

            # Basic validation for the row
            if not term:
                errors.append(f"第 {row_num} 行缺少核心概念 'term'，已跳过。")
                skipped_count += 1
                continue
            term_lower = term.lower()
            if term_lower in processed_terms:
                errors.append(f"第 {row_num} 行的单词 '{term}' 在此文件中重复，已跳过。")
                skipped_count += 1
                continue

            # --- 3. Database Interaction per Row ---
            with db: # Transaction for each row's insert/update
                cursor = db.cursor()

                # Check if term already exists in the database (case-insensitive)
                existing_concept = cursor.execute("SELECT id FROM concepts WHERE lower(term) = ?", (term_lower,)).fetchone()

                if existing_concept:
                    errors.append(f"第 {row_num} 行的单词 '{term}' 已存在于数据库中 (ID: {existing_concept['id']})，已跳过。")
                    skipped_count += 1
                else:
                    # Insert new concept
                    phonetic = row_lower.get('phonetic', '')
                    etymology = row_lower.get('etymology', '')
                    synonyms = row_lower.get('synonyms', '')
                    audio_url = row_lower.get('audio_url', '')
                    tags_str = row_lower.get('tags', '')

                    # Get optional SRS values, providing defaults if missing/invalid
                    try: error_count = int(row_lower.get('error_count', 0))
                    except (ValueError, TypeError): error_count = 0
                    try: srs_interval = int(row_lower.get('srs_interval', initial_interval))
                    except (ValueError, TypeError): srs_interval = initial_interval
                    try: srs_efactor = float(row_lower.get('srs_efactor', initial_efactor))
                    except (ValueError, TypeError): srs_efactor = initial_efactor

                    # Use initial due date only if not provided or invalid in CSV
                    srs_due_date_str = row_lower.get('srs_due_date', '')
                    due_date_to_insert = parse_datetime_utc(srs_due_date_str)
                    due_date_str = due_date_to_insert.strftime('%Y-%m-%d %H:%M:%S') if due_date_to_insert else initial_due_date

                    # Parse last reviewed date if provided
                    last_reviewed_date_str = row_lower.get('last_reviewed_date', '')
                    last_reviewed_to_insert = parse_datetime_utc(last_reviewed_date_str)
                    last_reviewed_str = last_reviewed_to_insert.strftime('%Y-%m-%d %H:%M:%S') if last_reviewed_to_insert else None

                    cursor.execute(
                        """INSERT INTO concepts
                           (term, phonetic, etymology, synonyms, audio_url,
                            error_count, srs_interval, srs_efactor, srs_due_date, last_reviewed_date)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (term, phonetic, etymology, synonyms, audio_url,
                         error_count, srs_interval, srs_efactor, due_date_str, last_reviewed_str)
                    )
                    concept_id = cursor.lastrowid

                    # Handle Tags
                    tag_ids = get_or_create_tag_ids(tags_str)
                    if tag_ids:
                         if not update_concept_tags(concept_id, tag_ids):
                             raise sqlite3.Error(f"Failed to update tags for imported concept '{term}' (ID: {concept_id})")

                    # Handle Meanings and Collocations dynamically based on column suffixes
                    meanings_added = 0
                    collocations_added = 0
                    i = 1
                    while True:
                        pos_key = f'part_of_speech_{i}'
                        def_key = f'definition_{i}'
                        phrase_key = f'phrase_{i}'
                        example_key = f'example_{i}'

                        # Check if *any* key with this index exists in the row's data
                        has_any_key_for_index = any(k in row_lower for k in [pos_key, def_key, phrase_key, example_key])

                        if not has_any_key_for_index and i > 50: # Add a limit to prevent infinite loops on bad data
                            break # Assume no more columns

                        pos = row_lower.get(pos_key, '')
                        definition = row_lower.get(def_key, '')
                        phrase = row_lower.get(phrase_key, '')
                        example = row_lower.get(example_key, '')

                        # Insert meaning if both parts are present
                        if pos and definition:
                            cursor.execute("INSERT INTO meanings (concept_id, part_of_speech, definition) VALUES (?, ?, ?)",
                                           (concept_id, pos, definition))
                            meanings_added += 1

                        # Insert collocation if phrase is present
                        if phrase:
                            cursor.execute("INSERT INTO collocations (concept_id, phrase, example) VALUES (?, ?, ?)",
                                           (concept_id, phrase, example))
                            collocations_added += 1

                        # Exit loop if no data found for this index (avoid checking too many non-existent columns)
                        if not has_any_key_for_index:
                            break

                        i += 1

                    imported_count += 1
                    current_app.logger.debug(f"Imported '{term}' (ID:{concept_id}) with {meanings_added} meanings, {collocations_added} collocations.")

            # Mark term as processed regardless of whether it was inserted or skipped
            processed_terms.add(term_lower)

        except sqlite3.IntegrityError as e:
            db.rollback() # Ensure rollback on integrity error
            errors.append(f"第 {row_num} 行导入时发生完整性错误 (可能是 '{term}' 重复，或其他约束冲突): {e}")
            skipped_count += 1
            if term: processed_terms.add(term.lower()) # Mark as processed even if failed
        except sqlite3.Error as e:
            db.rollback()
            error_msg = f"第 {row_num} 行导入 '{term or '未知单词'}' 时发生数据库错误: {e}"
            errors.append(error_msg)
            current_app.logger.error(error_msg, exc_info=True)
            skipped_count += 1
        except Exception as e:
            db.rollback()
            error_msg = f"第 {row_num} 行导入 '{term or '未知单词'}' 时发生未知错误: {e}"
            errors.append(error_msg)
            current_app.logger.error(error_msg, exc_info=True)
            skipped_count += 1

    # --- 4. Final Report ---
    if imported_count > 0:
        flash(f"成功导入 {imported_count} 个新单词。", "success")
    if skipped_count > 0:
        flash(f"跳过 {skipped_count} 行（原因可能包括：已存在、数据缺失、格式错误、文件内重复）。", "warning")
    if not errors and imported_count == 0 and skipped_count == 0:
         flash("CSV 文件已处理，但未导入任何新单词（可能文件为空或所有单词已存在）。", "info")
    elif errors:
        # Show first few errors as flash messages
        for err in errors[:5]:
            flash(f"导入错误: {err}", "danger")
        if len(errors) > 5:
            flash(f"...还有 {len(errors)-5} 个错误未显示 (详情请查看应用日志)。", "danger")
        # Log all errors regardless of flashing
        current_app.logger.warning(f"CSV Import completed. Imported: {imported_count}, Skipped: {skipped_count}. Errors encountered: {len(errors)}")
        for i, err in enumerate(errors):
             current_app.logger.warning(f"  Import Error [{i+1}]: {err}")

    return imported_count, errors


# --- Tag Handling ---

def get_tags_for_concept(concept_id):
    """Fetches all tags (as dicts) associated with a given concept ID."""
    db = get_db()
    tags = []
    try:
        tags_raw = db.execute("""
            SELECT t.id, t.name
            FROM tags t JOIN concept_tags ct ON t.id = ct.tag_id
            WHERE ct.concept_id = ?
            ORDER BY t.name COLLATE NOCASE
        """, (concept_id,)).fetchall()
        tags = [dict(tag) for tag in tags_raw]
    except sqlite3.Error as e:
        current_app.logger.error(f"Error fetching tags for concept {concept_id}: {e}", exc_info=True)
    return tags

def get_or_create_tag_ids(tag_names_str):
    """
    Takes a comma-separated string of tag names.
    Finds existing tags or creates new ones (case-insensitive).
    Returns a list of unique tag IDs. Handles errors gracefully.
    """
    if not tag_names_str or not isinstance(tag_names_str, str):
        return []

    # Split, strip whitespace, and remove empty strings/duplicates (case-insensitive)
    unique_tag_names_lower = {name.strip().lower() for name in tag_names_str.split(',') if name.strip()}
    original_case_map = {name.strip().lower(): name.strip() for name in tag_names_str.split(',') if name.strip()}

    if not unique_tag_names_lower:
        return []

    db = get_db()
    tag_ids = []
    try:
        with db: # Use transaction for potential multiple inserts
            cursor = db.cursor()
            for name_lower in unique_tag_names_lower:
                # Check if tag exists (case-insensitive due to schema COLLATE NOCASE)
                cursor.execute("SELECT id FROM tags WHERE name = ?", (name_lower,))
                tag_row = cursor.fetchone()

                if tag_row:
                    tag_ids.append(tag_row['id'])
                else:
                    # Insert new tag, preserving original case from the first occurrence
                    original_case_name = original_case_map.get(name_lower, name_lower) # Fallback just in case
                    try:
                        cursor.execute("INSERT INTO tags (name) VALUES (?)", (original_case_name,))
                        new_tag_id = cursor.lastrowid
                        tag_ids.append(new_tag_id)
                        current_app.logger.info(f"Created new tag '{original_case_name}' with ID {new_tag_id}.")
                    except sqlite3.IntegrityError:
                         # Race condition? Tag created between SELECT and INSERT? Fetch ID again.
                         current_app.logger.warning(f"Tag '{original_case_name}' likely created concurrently. Fetching existing ID.")
                         cursor.execute("SELECT id FROM tags WHERE name = ?", (name_lower,))
                         tag_row = cursor.fetchone()
                         if tag_row:
                             tag_ids.append(tag_row['id'])
                         else: # Should not happen
                             raise sqlite3.Error(f"Could not insert or find tag '{original_case_name}' after IntegrityError.")

        # Return unique IDs (already unique due to using set earlier)
        return tag_ids
    except sqlite3.Error as e:
        current_app.logger.error(f"Error getting or creating tag IDs for '{tag_names_str}': {e}", exc_info=True)
        # Optionally flash an error message here?
        # flash("处理标签时发生数据库错误。", "danger")
        return [] # Return empty list on error

def update_concept_tags(concept_id, tag_ids):
    """Updates the tags for a concept. Replaces existing tags with the provided list."""
    db = get_db()
    try:
        with db: # Use transaction
            # 1. Delete existing associations for this concept
            db.execute("DELETE FROM concept_tags WHERE concept_id = ?", (concept_id,))

            # 2. Insert new associations if tag_ids is not empty
            if tag_ids:
                # Ensure IDs are unique before inserting
                unique_tag_ids = list(set(tag_ids)) # Ensure uniqueness
                if unique_tag_ids: # Check if list is not empty after ensuring uniqueness
                    values_to_insert = [(concept_id, tag_id) for tag_id in unique_tag_ids]
                    # Use INSERT OR IGNORE in case a tag somehow got deleted (unlikely with FKs)
                    db.executemany("INSERT OR IGNORE INTO concept_tags (concept_id, tag_id) VALUES (?, ?)", values_to_insert)
                    current_app.logger.debug(f"Updated tags for concept {concept_id} with IDs: {unique_tag_ids}")
            else:
                 current_app.logger.debug(f"Removed all tags for concept {concept_id}.")
        return True # Success
    except sqlite3.Error as e:
        current_app.logger.error(f"Error updating tags for concept {concept_id}: {e}", exc_info=True)
        return False # Failure

def get_all_tags():
    """Fetches all unique tags from the database, ordered by name (case-insensitive)."""
    db = get_db()
    tags = []
    try:
        tags_raw = db.execute("SELECT id, name FROM tags ORDER BY name COLLATE NOCASE").fetchall()
        tags = [dict(tag) for tag in tags_raw]
    except sqlite3.Error as e:
        current_app.logger.error(f"Error fetching all tags: {e}", exc_info=True)
    return tags

# --- Other Utilities ---

def allowed_file(filename, allowed_extensions={'csv', 'txt'}):
     """Checks if the filename has an allowed extension."""
     return '.' in filename and \
            filename.rsplit('.', 1)[1].lower() in allowed_extensions

def blank_out_term(text, term, placeholder="____"):
    """
    Replaces occurrences of a specific term within a text with a placeholder.
    Uses word boundaries and case-insensitivity for better matching.
    Handles potential regex errors. Returns original text on failure.
    """
    if not text or not term:
        return text

    try:
        # Escape the term for regex
        escaped_term = re.escape(term)
        # Attempt word boundary match first
        pattern = re.compile(r'\b' + escaped_term + r'\b', re.IGNORECASE)
        blanked_text_boundary = pattern.sub(placeholder, text)

        # If word boundary match worked AND introduced the placeholder, use it.
        if blanked_text_boundary != text and placeholder in blanked_text_boundary:
            return blanked_text_boundary
        else:
            # If word boundary didn't work or term isn't whole word, try simple replacement
            pattern_simple = re.compile(escaped_term, re.IGNORECASE)
            blanked_text_simple = pattern_simple.sub(placeholder, text)

            # Use simple replacement only if it worked and boundary didn't
            if blanked_text_simple != text and placeholder in blanked_text_simple:
                 current_app.logger.debug(f"Blanking term '{term}' in '{text}' using simple replacement.")
                 return blanked_text_simple
            else:
                 # If neither worked, log and return original
                 if blanked_text_boundary == text and blanked_text_simple == text:
                      current_app.logger.warning(f"Could not blank out term '{term}' in text '{text}'. Returning original.")
                 return text # Return original if blanking failed

    except re.error as e:
        current_app.logger.error(f"Regex error blanking out term '{term}' in text '{text}': {e}")
        return text # Return original text on regex error
    except Exception as e:
        current_app.logger.error(f"Unexpected error blanking out term '{term}' in text '{text}': {e}", exc_info=True)
        return text

def count_total_collocations():
    """计算数据库中总的搭配 (collocations) 数量。"""
    db = get_db()
    try:
        result = db.execute('SELECT COUNT(id) FROM collocations').fetchone()
        return result[0] if result else 0
    except sqlite3.Error as e:
        current_app.logger.error(f"Error counting total collocations: {e}", exc_info=True)
        return 0

def classify_mastery(interval):
    """Classifies mastery level based on SRS interval for display purposes."""
    if interval is None:
        return "New"
    try:
        interval_num = int(interval) # Ensure interval is treated as number
        if interval_num <= 1:
            return "New"
        elif interval_num < 7: # 2-6 days
            return "Learning"
        elif interval_num < 30: # 7-29 days
            return "Young"
        else: # 30+ days
            return "Mature"
    except (ValueError, TypeError):
         current_app.logger.warning(f"Could not classify mastery for invalid interval: {interval}")
         return "Unknown" # Or return "New"?

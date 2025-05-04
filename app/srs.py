# app/srs.py
import sqlite3
from datetime import datetime, timedelta, timezone
import collections # Import collections for defaultdict
from .db import get_db
from flask import current_app

# SRS 算法参数 (基于 SM-2 简化)
MIN_EFACTOR = 1.3
# Optional: Define default interval steps for early reviews
INITIAL_INTERVAL = 1 # Default interval if reset
FIRST_CORRECT_INTERVAL = 6 # Interval after first successful review (quality >= 3)

def update_srs(concept_id, quality):
    """
    根据用户对卡片的回答质量更新 SRS 数据。
    quality: 0 (完全忘记) 到 5 (非常轻松) 的整数。
    同时更新错误计数器。
    返回 True 表示成功, False 表示失败。
    """
    db = get_db()
    try:
        # Fetch existing data, using COALESCE for safe defaults if values are NULL
        concept = db.execute(
            """SELECT id,
                      COALESCE(srs_interval, ?) as srs_interval,
                      COALESCE(srs_efactor, ?) as srs_efactor,
                      COALESCE(error_count, 0) as error_count
               FROM concepts WHERE id = ?""",
            (INITIAL_INTERVAL, 2.5, concept_id,) # Provide defaults directly in query
        ).fetchone()

        if not concept:
            current_app.logger.error(f"SRS Update Failed: Concept with ID {concept_id} not found.")
            return False

        interval = concept['srs_interval']
        efactor = concept['srs_efactor']
        error_count = concept['error_count']

        # Get current time in UTC
        now_utc_precise = datetime.now(timezone.utc)
        # Floor to the beginning of the day for consistent due date calculation relative to 'today'
        today_utc = now_utc_precise.replace(hour=0, minute=0, second=0, microsecond=0)

        # 1. Update E-Factor based on quality
        # SM-2 formula: EF' = EF + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
        # Ensure quality is within bounds for calculation robustness
        q = max(0, min(5, quality))
        new_efactor = efactor + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
        if new_efactor < MIN_EFACTOR:
            new_efactor = MIN_EFACTOR

        # 2. Calculate new interval and update error count based on quality
        new_error_count = error_count
        if q < 3: # Answer incorrect or hard (quality 0, 1, 2)
            # Reset interval to initial
            new_interval = INITIAL_INTERVAL
            # Increment error count
            new_error_count += 1
            # Optional: Reset E-factor on failure? SM-2 doesn't, but some variations do.
            # Keep the calculated new_efactor unless it's below minimum.
        else: # Answer correct (quality 3, 4, 5)
            # Calculate interval based on current interval and new E-factor
            if interval <= INITIAL_INTERVAL: # First review or review after failure
                 # Use a fixed step for the first successful review
                 new_interval = FIRST_CORRECT_INTERVAL
            else:
                # Core SM-2 interval formula: I(n) = I(n-1) * EF'
                # Round the result to the nearest integer day
                new_interval = round(interval * new_efactor)
                # Ensure interval is at least 1 day
                if new_interval < 1: new_interval = 1

            # Optional: Apply a maximum interval cap (e.g., 10 years)
            # MAX_INTERVAL = 365 * 10
            # if new_interval > MAX_INTERVAL: new_interval = MAX_INTERVAL

            # Optional: Reset error count on success? Let's keep accumulating.
            # new_error_count = 0

        # 3. Calculate the new due date (UTC) based on today + new interval
        # Due date is calculated from 'today', so reviews on the same day don't push the due date further if interval is 1
        new_due_date_dt = today_utc + timedelta(days=new_interval)
        # Store in a consistent format (SQLite typically stores TEXT for dates)
        new_due_date_str = new_due_date_dt.strftime('%Y-%m-%d %H:%M:%S')

        # 4. Record the time of this review precisely
        last_reviewed_date_str = now_utc_precise.strftime('%Y-%m-%d %H:%M:%S')

        # 5. Update the database within a transaction
        with db:
            db.execute(
                """
                UPDATE concepts
                SET srs_interval = ?,
                    srs_efactor = ?,
                    srs_due_date = ?,
                    last_reviewed_date = ?,
                    error_count = ?
                WHERE id = ?
                """,
                (new_interval, new_efactor, new_due_date_str, last_reviewed_date_str, new_error_count, concept_id)
            )
        current_app.logger.info(f"SRS Updated for Concept ID {concept_id}: Quality={quality}, Old(I:{interval}, EF:{efactor:.2f}), New(I:{new_interval}, EF:{new_efactor:.2f}, Due:{new_due_date_str}), Errors={new_error_count}")
        return True

    except sqlite3.Error as e:
        # db context manager handles rollback if 'with db:' is used
        current_app.logger.error(f"Database error updating SRS for Concept ID {concept_id}: {e}", exc_info=True)
        return False
    except Exception as e:
        # Catch any other unexpected errors
        current_app.logger.error(f"Unexpected error updating SRS for Concept ID {concept_id}: {e}", exc_info=True)
        return False


def get_due_concepts(limit=10, mode='due'):
    """
    获取待复习概念列表，包含完整详情 (优化 N+1 查询)。
    mode: 'due' (到期), 'hardest' (按错误次数 > 0).
    Returns a list of dictionaries, each representing a concept with its details.
    """
    db = get_db()
    now_str_utc = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    concepts_raw = []
    params = []

    # Base query to select concept fields
    base_query = """
        SELECT c.id, c.term, c.phonetic, c.etymology, c.synonyms, c.audio_url, c.error_count,
               c.srs_interval, c.srs_efactor, c.srs_due_date, c.last_reviewed_date
        FROM concepts c
    """
    order_by_clause = ""
    where_clause = ""

    # --- Determine query based on mode ---
    if mode == 'due':
        where_clause = " WHERE c.srs_due_date <= ? "
        # Show earliest due first, then perhaps those with more errors among those due today
        order_by_clause = " ORDER BY c.srs_due_date ASC, c.error_count DESC "
        params = [now_str_utc, limit]
        current_app.logger.info(f"Fetching concepts due on or before: {now_str_utc}, Limit: {limit}")
    elif mode == 'hardest':
        # Fetch concepts with at least one error, ordered by errors descending, then soonest due
        where_clause = " WHERE c.error_count > 0 "
        order_by_clause = " ORDER BY c.error_count DESC, c.srs_due_date ASC "
        params = [limit]
        current_app.logger.info(f"Fetching hardest concepts (error_count > 0), Limit: {limit}")
    else: # Default to 'due' if mode is unrecognized
        where_clause = " WHERE c.srs_due_date <= ? "
        order_by_clause = " ORDER BY c.srs_due_date ASC, c.error_count DESC "
        params = [now_str_utc, limit]
        current_app.logger.warning(f"Unrecognized review mode '{mode}', defaulting to 'due'.")

    # --- Execute Base Query ---
    query = base_query + where_clause + order_by_clause + " LIMIT ?"
    try:
        concepts_raw = db.execute(query, params).fetchall()
        current_app.logger.info(f"Found {len(concepts_raw)} concept base rows for review (mode: {mode}).")
    except sqlite3.Error as e:
        current_app.logger.error(f"Database error fetching concepts (mode: {mode}): {e}", exc_info=True)
        return [] # Return empty list on DB error

    # --- Optimization: Batch fetch details for the selected concepts ---
    detailed_concepts = []
    if concepts_raw:
        concept_ids = [row['id'] for row in concepts_raw]
        meanings_by_concept = collections.defaultdict(list)
        collocations_by_concept = collections.defaultdict(list)

        try:
            # Batch fetch meanings
            if concept_ids:
                placeholders = ','.join('?' * len(concept_ids))
                meanings_query = f"SELECT id, concept_id, part_of_speech, definition FROM meanings WHERE concept_id IN ({placeholders}) ORDER BY concept_id, id"
                meanings_raw = db.execute(meanings_query, concept_ids).fetchall()
                for meaning in meanings_raw:
                    meanings_by_concept[meaning['concept_id']].append(dict(meaning))

                # Batch fetch collocations
                collocations_query = f"SELECT id, concept_id, phrase, example FROM collocations WHERE concept_id IN ({placeholders}) ORDER BY concept_id, id"
                collocations_raw = db.execute(collocations_query, concept_ids).fetchall()
                for collocation in collocations_raw:
                    collocations_by_concept[collocation['concept_id']].append(dict(collocation))

            # Combine base concepts with details
            for concept_row in concepts_raw:
                concept_dict = dict(concept_row)
                concept_id = concept_dict['id']
                concept_dict['meanings'] = meanings_by_concept[concept_id]
                concept_dict['collocations'] = collocations_by_concept[concept_id]
                detailed_concepts.append(concept_dict)

            current_app.logger.debug(f"Fetched and combined full details for {len(detailed_concepts)} concepts using optimized query.")

        except sqlite3.Error as e:
             current_app.logger.error(f"Database error fetching details for concepts (mode: {mode}): {e}", exc_info=True)
             # Return empty list if details fetching fails to prevent partial data issues
             return []

    return detailed_concepts


def count_due_concepts():
    """计算今天或之前到期的复习概念数量。"""
    db = get_db()
    now_str_utc = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    try:
        result = db.execute(
            'SELECT COUNT(id) FROM concepts WHERE srs_due_date <= ?', (now_str_utc,)
        ).fetchone()
        return result[0] if result else 0
    except sqlite3.Error as e:
        current_app.logger.error(f"Error counting due concepts: {e}", exc_info=True)
        return 0

def get_mastery_levels():
    """
    统计不同掌握程度 (基于 SRS 间隔) 的单词数量。
    Returns a dictionary like: {'New': 10, 'Learning': 25, 'Young': 50, 'Mature': 100}
    """
    db = get_db()
    # Define interval boundaries for each level
    # Using explicit ranges to match classify_mastery logic in utils
    levels = {
        'New': 0,       # Interval <= 1 day (includes never reviewed if interval is NULL treated as <= 1)
        'Learning': 0,  # 1 < Interval < 7 days (i.e., 2 to 6)
        'Young': 0,     # 7 <= Interval < 30 days
        'Mature': 0,    # Interval >= 30 days
    }
    try:
        # Use COUNT with CASE for efficiency (single query)
        # COALESCE(srs_interval, 1) treats NULL intervals as 'New'
        query = """
            SELECT
                COUNT(CASE WHEN COALESCE(srs_interval, 1) <= 1 THEN 1 END) as New,
                COUNT(CASE WHEN COALESCE(srs_interval, 1) > 1 AND srs_interval < 7 THEN 1 END) as Learning,
                COUNT(CASE WHEN srs_interval >= 7 AND srs_interval < 30 THEN 1 END) as Young,
                COUNT(CASE WHEN srs_interval >= 30 THEN 1 END) as Mature
            FROM concepts
        """
        result = db.execute(query).fetchone()

        if result:
            # Ensure counts are integers, defaulting to 0 if column is unexpectedly NULL
            levels['New'] = result['New'] or 0
            levels['Learning'] = result['Learning'] or 0
            levels['Young'] = result['Young'] or 0
            levels['Mature'] = result['Mature'] or 0
            current_app.logger.debug(f"Mastery levels calculated: {levels}")
        else:
             current_app.logger.warning("Could not calculate mastery levels, query result was None.")

        return levels
    except (sqlite3.Error, TypeError) as e:
        current_app.logger.error(f"Error calculating mastery levels: {e}", exc_info=True)
        # Return zero counts on error
        return {k: 0 for k in levels}

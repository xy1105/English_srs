# app/practice_routes.py
from flask import (
    Blueprint, flash, g, redirect, render_template, request, url_for, session, current_app
)
from .db import get_db
from .srs import get_due_concepts, update_srs
import sqlite3
from datetime import datetime, timezone, timedelta

bp = Blueprint('practice', __name__)

# SRS Quality mapping
SRS_QUALITY_MAP = {"again": 0, "hard": 2, "good": 4, "easy": 5}

# Constants for session keys (More specific names)
PRACTICE_SESSION_PREFIX = 'practice_'
SESSION_QUEUE_KEY = f'{PRACTICE_SESSION_PREFIX}queue_ids'
SESSION_INDEX_KEY = f'{PRACTICE_SESSION_PREFIX}current_index'
SESSION_STATS_KEY = f'{PRACTICE_SESSION_PREFIX}session_stats'

# --- Helper to clear practice session data ---
def clear_practice_session():
    """Removes all practice-related keys from the session."""
    keys_to_pop = [k for k in session if k.startswith(PRACTICE_SESSION_PREFIX)]
    for key in keys_to_pop:
        session.pop(key, None)
    current_app.logger.info("Cleared practice session data.")

def count_high_error_concepts(threshold=3):
    """Counts concepts with error_count at or above a threshold."""
    db = get_db()
    try:
        result = db.execute(
            'SELECT COUNT(id) FROM concepts WHERE error_count >= ?', (threshold,)
        ).fetchone()
        return result[0] if result else 0
    except sqlite3.Error as e:
        current_app.logger.error(f"Error counting high error concepts: {e}", exc_info=True)
        return 0

@bp.route('/start')
def start_session():
    """
    Starts a new review session (due or hardest).
    Checks if a session is already in progress and redirects if so.
    """
    # --- Check for existing session ---
    if SESSION_QUEUE_KEY in session and SESSION_INDEX_KEY in session:
        current_index = session.get(SESSION_INDEX_KEY, 0)
        queue_len = len(session.get(SESSION_QUEUE_KEY, []))
        # Check if the session is genuinely in progress (index < length)
        if current_index < queue_len:
            flash("你当前有一个正在进行的复习会话。请先完成或退出。", "info")
            return redirect(url_for('.session_view')) # Redirect to the current card

    # --- Start a new session ---
    clear_practice_session() # Clear any potentially stale data before starting fresh

    mode = request.args.get('mode', 'due')
    limit_str = request.args.get('limit', '10')
    try:
        limit = int(limit_str)
        if limit <= 0: limit = 10 # Default to 10 if invalid
    except ValueError:
        limit = 10 # Default if conversion fails

    allowed_modes = ['due', 'hardest']
    if mode not in allowed_modes:
        flash(f"无效的复习模式 '{mode}'，已切换到 'due' 模式。", "warning")
        mode = 'due'

    current_app.logger.info(f"Attempting to start practice session (Mode: {mode}, Limit: {limit})")

    # Fetch concepts with full details initially using the SRS function
    due_concepts_details = get_due_concepts(limit=limit, mode=mode)

    if not due_concepts_details:
        # Provide specific feedback based on mode
        if mode == 'due':
             flash(f"太棒了！当前没有到期的单词需要复习。", "success")
        elif mode == 'hardest':
             flash(f"词库中目前没有标记为“难词”的单词 (错误次数 > 0)。", "info")
        else:
            flash(f"当前没有符合条件 '{mode}' 的单词需要复习。", "success")
        return redirect(url_for('main.index'))

    # Store only concept IDs in the session queue
    session[SESSION_QUEUE_KEY] = [c['id'] for c in due_concepts_details]
    session[SESSION_INDEX_KEY] = 0

    # Initialize session statistics
    session[SESSION_STATS_KEY] = {
        'start_time': datetime.now(timezone.utc).isoformat(),
        'total_cards': len(due_concepts_details),
        'correct': 0,
        'incorrect': 0,
        'reviewed_ids': [],
        'mode': mode, # Store the mode for the summary page if needed
        'tag_filter_id': None # Practice doesn't use tag filter currently
    }

    current_app.logger.info(f"Starting practice session with {len(due_concepts_details)} concepts (Mode: {mode}). IDs: {session[SESSION_QUEUE_KEY]}")
    session.modified = True # Explicitly mark session as modified

    # Redirect to the session view to display the first card
    return redirect(url_for('.session_view'))

@bp.route('/session')
def session_view():
    """Displays the current practice card."""
    # --- Validate Session State ---
    required_keys = [SESSION_QUEUE_KEY, SESSION_INDEX_KEY, SESSION_STATS_KEY]
    if not all(key in session for key in required_keys):
        flash("复习会话无效或已过期，请重新开始。", "warning")
        current_app.logger.warning("Practice session_view called with invalid/missing session keys.")
        clear_practice_session()
        return redirect(url_for('main.index'))

    current_index = session[SESSION_INDEX_KEY]
    queue = session[SESSION_QUEUE_KEY]
    total_in_session = len(queue)

    # Check if session was already completed
    if current_index >= total_in_session:
        flash("该复习会话已完成。", "info")
        # Ensure summary can be accessed even if user navigates back
        return redirect(url_for('.session_summary'))

    # --- Load Current Card Details ---
    concept_id = queue[current_index]
    try:
        db = get_db()
        # Fetch core concept data
        concept_raw = db.execute(
             'SELECT id, term, phonetic, etymology, synonyms, audio_url, error_count FROM concepts WHERE id = ?',
             (concept_id,)
         ).fetchone()

        if not concept_raw:
             current_app.logger.error(f"Could not find concept details in DB for queued ID: {concept_id}. Skipping card.")
             flash(f"无法加载单词 (ID: {concept_id})，将跳过此卡片。", "warning")
             # Advance index and try next card
             session[SESSION_INDEX_KEY] = current_index + 1
             session.modified = True
             # Update stats? Maybe add a 'skipped' count later if needed
             return redirect(url_for('.session_view')) # Recursive call to show next

        concept = dict(concept_raw)

        # Fetch associated meanings
        meanings = db.execute(
            'SELECT id, part_of_speech, definition FROM meanings WHERE concept_id = ? ORDER BY id',
            (concept_id,)
        ).fetchall()
        concept['meanings'] = [dict(m) for m in meanings]

        # Fetch associated collocations
        collocations = db.execute(
            'SELECT id, phrase, example FROM collocations WHERE concept_id = ? ORDER BY id',
            (concept_id,)
        ).fetchall()
        concept['collocations'] = [dict(coll) for coll in collocations]

        # Render the practice page with the concept's details
        return render_template(
            'practice_session.html',
            concept=concept,
            current_progress=current_index + 1, # Display index is 1-based
            total_in_session=total_in_session,
            quality_map=SRS_QUALITY_MAP
        )
    except sqlite3.Error as e:
        current_app.logger.error(f"Database error fetching concept for practice (ID: {concept_id}): {e}", exc_info=True)
        flash("加载单词时发生数据库错误，会话中止。", "danger")
        clear_practice_session()
        return redirect(url_for('main.index'))
    except Exception as e: # Catch any other unexpected errors
         current_app.logger.error(f"Unexpected error fetching concept for practice (ID: {concept_id}): {e}", exc_info=True)
         flash("加载单词时发生未知错误，会话中止。", "danger")
         clear_practice_session()
         return redirect(url_for('main.index'))

@bp.route('/submit', methods=('POST',))
def submit_review():
    """Processes user's review quality for the current card."""
    # --- Validate Session State ---
    required_keys = [SESSION_QUEUE_KEY, SESSION_INDEX_KEY, SESSION_STATS_KEY]
    if not all(key in session for key in required_keys):
        flash("复习会话无效或已过期，请重新开始。", "warning")
        current_app.logger.warning("Submit review called with invalid/missing session keys.")
        clear_practice_session()
        return redirect(url_for('main.index')) # Redirect to dashboard

    current_index = session[SESSION_INDEX_KEY]
    queue = session[SESSION_QUEUE_KEY]
    stats = session[SESSION_STATS_KEY]

    # Check if session was already completed (e.g., user navigates back)
    if current_index >= len(queue):
        flash("该复习会话已完成。", "info")
        # Redirect to summary if already done, stats should still be there until summary is viewed
        return redirect(url_for('.session_summary'))

    # --- Get Data from Request and Session ---
    try:
        concept_id = queue[current_index]
        quality_str = request.form.get('quality')
    except IndexError:
         flash("复习会话索引错误，请重新开始。", "danger")
         current_app.logger.error(f"IndexError accessing practice queue. Index: {current_index}, Queue size: {len(queue)}")
         clear_practice_session()
         return redirect(url_for('main.index'))

    # --- Validate Input ---
    if quality_str not in SRS_QUALITY_MAP:
        flash("提交了无效的评价等级。", "danger")
        current_app.logger.warning(f"Invalid quality string received: {quality_str} for concept ID {concept_id}")
        # Stay on the same card instead of ending session
        return redirect(url_for('.session_view'))

    # --- Process the Review ---
    quality_val = SRS_QUALITY_MAP[quality_str]
    current_app.logger.info(f"Submitting review for Concept ID {concept_id} with quality '{quality_str}' ({quality_val})")

    # Update SRS data in the database
    success = update_srs(concept_id, quality_val)
    if not success:
        # update_srs logs the error internally
        flash("更新复习状态时发生错误，该卡片可能未正确更新。", "danger")
        # Continue to next card even if DB update failed for this one
        pass

    # --- Update Session Statistics ---
    if quality_val < 3: # Again (0) or Hard (2) count as incorrect for simple stats
        stats['incorrect'] += 1
    else: # Good (4) or Easy (5) count as correct
        stats['correct'] += 1
    if concept_id not in stats['reviewed_ids']: # Track unique IDs reviewed in this session
        stats['reviewed_ids'].append(concept_id)
    session[SESSION_STATS_KEY] = stats # Save updated stats back to session

    # --- Advance to Next Card ---
    session[SESSION_INDEX_KEY] = current_index + 1
    next_index = session[SESSION_INDEX_KEY]
    current_app.logger.debug(f"Advanced practice index to: {next_index}")
    session.modified = True # Ensure session is saved

    # --- Check if Session is Finished ---
    if next_index >= len(queue):
        # Session finished
        current_app.logger.info(f"Practice session finished. Preparing redirect to summary. Stats: {stats}")
        # Redirect to summary page (summary route will save history and clear session)
        return redirect(url_for('.session_summary'))
    else:
        # Redirect to the session view to load the next card
         return redirect(url_for('.session_view'))

@bp.route('/summary')
def session_summary():
    """Displays the summary, saves history, and cleans up session."""
    # Check if stats exist in session, retrieve them
    if SESSION_STATS_KEY not in session:
        flash("没有找到最近的复习总结信息。", "warning")
        return redirect(url_for('main.index'))

    stats = session.get(SESSION_STATS_KEY, {})
    reviewed_ids = stats.get('reviewed_ids', [])
    start_time_iso = stats.get('start_time')
    end_time_dt = datetime.now(timezone.utc)
    duration_str = "计算出错"
    duration_seconds = 0
    accuracy = 0

    # Calculate duration
    if start_time_iso:
        try:
            # Ensure timezone info is handled correctly
            if not start_time_iso.endswith('Z') and '+' not in start_time_iso:
                 start_time_iso += 'Z' # Assume UTC if no timezone provided
            start_dt = datetime.fromisoformat(start_time_iso.replace('Z', '+00:00'))
            duration = end_time_dt - start_dt
            duration_seconds = max(0, int(duration.total_seconds()))
            minutes = duration_seconds // 60
            seconds = duration_seconds % 60
            duration_str = f"{minutes} 分 {seconds} 秒"
        except (ValueError, TypeError) as e:
            current_app.logger.warning(f"Could not parse session start time for duration: {start_time_iso}. Error: {e}")
            duration_str = "计算出错"

    # Calculate Accuracy
    total_reviewed = len(reviewed_ids) # Or use total_cards? Use reviewed_ids for actual number seen
    correct = stats.get('correct', 0)
    if total_reviewed > 0:
        accuracy = round((correct / total_reviewed) * 100, 1)

    # --- Save to History Database ---
    db = get_db()
    try:
        with db:
            db.execute("""
                INSERT INTO session_history
                    (session_type, mode, tag_filter_id, start_time, end_time, duration_seconds,
                     total_items, correct_count, incorrect_count, skipped_count, accuracy)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                'practice',
                stats.get('mode'),
                stats.get('tag_filter_id'), # Should be None for practice
                start_time_iso,
                end_time_dt.isoformat(),
                duration_seconds,
                total_reviewed, # Use actual reviewed count
                stats.get('correct', 0),
                stats.get('incorrect', 0),
                0, # Practice doesn't skip currently
                accuracy
            ))
        current_app.logger.info(f"Saved practice session history. Mode: {stats.get('mode')}, Total: {total_reviewed}, Correct: {correct}, Accuracy: {accuracy}%")
    except sqlite3.Error as e:
        current_app.logger.error(f"Database error saving practice session history: {e}", exc_info=True)
        flash("保存本次复习记录时出错。", "warning")
    except Exception as e:
        current_app.logger.error(f"Unexpected error saving practice session history: {e}", exc_info=True)
        flash("保存本次复习记录时发生未知错误。", "warning")

    # Fetch terms for reviewed concepts (optional, display purposes)
    reviewed_concepts_terms = []
    if reviewed_ids:
         try:
             placeholders = ','.join('?' * len(reviewed_ids))
             query = f"SELECT id, term FROM concepts WHERE id IN ({placeholders})"
             reviewed_concepts_raw = db.execute(query, reviewed_ids).fetchall()
             reviewed_concepts_terms = [dict(row) for row in reviewed_concepts_raw]
         except sqlite3.Error as e:
             current_app.logger.error(f"Error fetching terms for reviewed concepts in summary: {e}", exc_info=True)
             flash("加载已复习单词列表时出错。", "warning")

    # --- Clean up session data AFTER retrieving and saving necessary info ---
    clear_practice_session()

    return render_template(
        'practice_summary.html',
        stats=stats,
        duration=duration_str,
        accuracy=accuracy, # Pass accuracy
        total_reviewed=total_reviewed, # Pass total reviewed count
        reviewed_concepts=reviewed_concepts_terms
    )

@bp.route('/quit', methods=['POST']) # Use POST to prevent accidental quits via GET
def quit_session():
    """Ends the current practice session prematurely."""
    # Check if a session actually exists
    if SESSION_QUEUE_KEY not in session:
        flash("没有正在进行的复习会话可以退出。", "info")
    else:
        clear_practice_session()
        flash("复习会话已退出。", "success")
        current_app.logger.info("User quit practice session.")
    return redirect(url_for('main.index'))


@bp.route('/wrong_list')
def wrong_concepts():
    """Shows a list of concepts with high error counts."""
    db = get_db()
    wrong_concepts_list = []
    # Define threshold for "high error count" - maybe make this configurable later?
    error_threshold = current_app.config.get('WRONG_LIST_ERROR_THRESHOLD', 1) # Default to 1 or more errors
    limit = current_app.config.get('WRONG_LIST_LIMIT', 50) # Limit the list size

    try:
        wrong_concepts_list = db.execute(
            """
            SELECT id, term, phonetic, error_count, last_reviewed_date, srs_interval, srs_due_date
            FROM concepts
            WHERE error_count >= ?
            ORDER BY error_count DESC, last_reviewed_date DESC NULLS LAST -- Show never reviewed last among same error count
            LIMIT ?
            """, (error_threshold, limit)
        ).fetchall()
        current_app.logger.info(f"Fetched {len(wrong_concepts_list)} concepts for wrong list (threshold: {error_threshold}, limit: {limit}).")
    except sqlite3.Error as e:
        current_app.logger.error(f"Error fetching wrong concepts: {e}", exc_info=True)
        flash("加载易错词列表失败。", "danger")

    return render_template('wrong_concepts.html', concepts=wrong_concepts_list)

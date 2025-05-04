# app/test_routes.py
from flask import (
    Blueprint, flash, redirect, render_template, request, url_for, session, current_app, abort, jsonify
)
from .db import get_db
# Import utils needed
from .utils import blank_out_term, get_all_tags, parse_datetime_utc, now_utc # Added parse_datetime_utc, now_utc
import sqlite3
import random
from datetime import datetime, timezone, timedelta

bp = Blueprint('test', __name__)

# Session keys - Prefixed for clarity and to avoid potential collisions
TEST_SESSION_PREFIX = 'test_'
TEST_MAIN_MODE = f'{TEST_SESSION_PREFIX}main_mode'
TEST_SUB_MODE = f'{TEST_SESSION_PREFIX}sub_mode'
TEST_QUANTITY = f'{TEST_SESSION_PREFIX}quantity'
TEST_QUEUE = f'{TEST_SESSION_PREFIX}queue_ids'
TEST_INDEX = f'{TEST_SESSION_PREFIX}current_index'
TEST_STATS = f'{TEST_SESSION_PREFIX}stats'
TEST_TAG_FILTER = f'{TEST_SESSION_PREFIX}tag_filter_id' # Store ID for consistency
TEST_LIST_CONCEPTS = f'{TEST_SESSION_PREFIX}list_concepts' # For Mode 3

PLACEHOLDER = "____" # Placeholder for blanking

# --- Helper to clear test session data ---
def clear_test_session():
    """Removes all test-related keys from the session."""
    keys_to_pop = [k for k in session if k.startswith(TEST_SESSION_PREFIX)]
    for key in keys_to_pop:
        session.pop(key, None)
    current_app.logger.info("Cleared test session data.")

# --- Route to get concept counts for tag filtering (AJAX) ---
@bp.route('/api/count_by_tag')
def count_by_tag_api():
    """API endpoint to get concept counts, optionally filtered by tag."""
    tag_id_str = request.args.get('tag_id')
    db = get_db()
    counts = {'all': 0}
    tags_with_counts = []

    try:
        # Get total count
        total_row = db.execute("SELECT COUNT(id) FROM concepts").fetchone()
        counts['all'] = total_row[0] if total_row else 0

        # Get counts per tag
        tag_counts_raw = db.execute("""
            SELECT t.id, t.name, COUNT(ct.concept_id) as concept_count
            FROM tags t
            JOIN concept_tags ct ON t.id = ct.tag_id
            GROUP BY t.id, t.name
            ORDER BY t.name COLLATE NOCASE
        """).fetchall()
        tags_with_counts = [dict(row) for row in tag_counts_raw]
        counts['tags'] = tags_with_counts

        return jsonify(counts)

    except sqlite3.Error as e:
        current_app.logger.error(f"API Error fetching concept counts by tag: {e}", exc_info=True)
        return jsonify({"error": "无法获取标签统计数据"}), 500

# --- Setup Route ---
@bp.route('/setup', methods=('GET', 'POST'))
def setup():
    # --- Check for existing session ---
    if TEST_QUEUE in session and TEST_INDEX in session:
        current_index = session.get(TEST_INDEX, 0)
        queue_len = len(session.get(TEST_QUEUE, [])) if TEST_MAIN_MODE in session and session[TEST_MAIN_MODE] != 3 else 0 # Mode 3 uses different logic
        total_len_mode3 = len(session.get(TEST_LIST_CONCEPTS, [])) if session.get(TEST_MAIN_MODE) == 3 else 0

        # Check if the session is genuinely in progress
        is_mode3_in_progress = session.get(TEST_MAIN_MODE) == 3 and total_len_mode3 > 0 and current_index == 0 # Mode 3 is single page
        is_mode1_2_in_progress = session.get(TEST_MAIN_MODE) != 3 and current_index < queue_len

        if is_mode1_2_in_progress or is_mode3_in_progress:
            flash("你当前有一个正在进行的测试会话。请先完成或退出。", "info")
            return redirect(url_for('.session_view'))

    # --- Proceed with setup if no active session ---
    clear_test_session() # Ensure clean state

    db = get_db()
    all_tags = get_all_tags()
    total_concepts = 0

    try:
        total_concepts_row = db.execute('SELECT COUNT(id) FROM concepts').fetchone()
        total_concepts = total_concepts_row[0] if total_concepts_row else 0
    except (sqlite3.Error, TypeError) as e:
        current_app.logger.warning(f"Could not fetch total concept count for setup page: {e}")
        total_concepts = 0 # Assume 0 on error

    if request.method == 'POST':
        try:
            # --- Get and Validate Form Data ---
            main_mode = int(request.form.get('test_mode_main', '1')) # 1, 2, or 3
            sub_mode = None # For Mode 2 or Mode 3 sub-options
            tag_filter_id = request.form.get('tag_filter') # Can be empty string ""

            try:
                quantity = int(request.form.get('quantity', 10))
                if quantity <= 0:
                    flash("测试数量必须大于 0。", "danger")
                    return render_template('test_setup.html', total_concepts=total_concepts, all_tags=all_tags)
            except ValueError:
                 flash("输入的测试数量无效。", "danger")
                 return render_template('test_setup.html', total_concepts=total_concepts, all_tags=all_tags)

            # Validate sub-modes based on main mode
            if main_mode == 2:
                sub_mode = request.form.get('test_mode_sub_2') # 'meaning', 'phrase', or 'mixed'
                if not sub_mode or sub_mode not in ['meaning', 'phrase', 'mixed']:
                    flash("请为模式二选择一个有效的具体测试内容。", "warning")
                    return render_template('test_setup.html', total_concepts=total_concepts, all_tags=all_tags)
            elif main_mode == 3:
                sub_mode = request.form.get('test_mode_sub_3') # 'blank_term' or 'blank_definition'
                if not sub_mode or sub_mode not in ['blank_term', 'blank_definition']:
                    flash("请为模式三选择一个有效的具体测试内容 (挖空类型)。", "warning")
                    return render_template('test_setup.html', total_concepts=total_concepts, all_tags=all_tags)

            # --- Determine Available Concepts Based on Filter ---
            count_sql = "SELECT COUNT(DISTINCT c.id) FROM concepts c"
            count_joins = ""
            count_params = []
            tag_filter_name_for_msg = "词库中"
            selected_tag_name_for_log = "所有"
            tag_filter_id_int = None

            if tag_filter_id:
                try:
                    tag_filter_id_int = int(tag_filter_id)
                    count_joins += " JOIN concept_tags ct ON c.id = ct.concept_id"
                    count_sql += count_joins + " WHERE ct.tag_id = ?"
                    count_params.append(tag_filter_id_int)
                    # Find tag name for messages/logging
                    tag_info = next((t for t in all_tags if t['id'] == tag_filter_id_int), None)
                    if tag_info:
                        tag_filter_name_for_msg = f"标签 '{tag_info['name']}' 下"
                        selected_tag_name_for_log = tag_info['name']
                    else:
                         tag_filter_name_for_msg = f"选定标签 (ID: {tag_filter_id_int}) 下"
                         selected_tag_name_for_log = f"ID {tag_filter_id_int}"
                except ValueError:
                     flash("无效的标签过滤器 ID。", "danger")
                     return render_template('test_setup.html', total_concepts=total_concepts, all_tags=all_tags)

            try:
                 available_concepts_count = db.execute(count_sql, count_params).fetchone()[0] or 0
            except (sqlite3.Error, TypeError) as e:
                current_app.logger.error(f"Error counting concepts for tag filter {tag_filter_id_int}: {e}", exc_info=True)
                flash(f"无法统计 {tag_filter_name_for_msg} 的单词数。", "warning")
                available_concepts_count = 0 # Assume none available on error

            if available_concepts_count == 0:
                 flash(f"{tag_filter_name_for_msg}没有单词可供测试。", "info")
                 return render_template('test_setup.html', total_concepts=total_concepts, all_tags=all_tags)

            if quantity > available_concepts_count:
                 flash(f"请求数量 ({quantity}) 超过了 {tag_filter_name_for_msg} 的单词总数 ({available_concepts_count})。将测试所有 {available_concepts_count} 个单词。", "warning")
                 quantity = available_concepts_count # Adjust quantity to available max

            # --- Fetch Concepts/IDs Based on Mode ---
            concept_ids = []
            list_concepts_details = [] # For Mode 3

            fetch_sql_base = "SELECT DISTINCT c.id, c.term, c.phonetic, c.audio_url FROM concepts c" # Select base fields needed by all modes
            fetch_joins = ""
            fetch_where_clause = " WHERE 1=1 " # Start where clause
            fetch_params = []

            if tag_filter_id_int is not None:
                fetch_joins += " JOIN concept_tags ct ON c.id = ct.concept_id"
                fetch_where_clause += " AND ct.tag_id = ?"
                fetch_params.append(tag_filter_id_int)

            # Construct full SQL
            fetch_sql = fetch_sql_base + fetch_joins + fetch_where_clause

            # Add ordering and limit
            fetch_sql += " ORDER BY RANDOM() LIMIT ?"
            fetch_params.append(quantity)

            try:
                # Fetch the concept data (IDs and basic info)
                concepts_rows = db.execute(fetch_sql, fetch_params).fetchall()
                if not concepts_rows:
                    flash(f"{tag_filter_name_for_msg}没有单词可供测试 (随机查询返回为空)。", "info")
                    return redirect(url_for('.setup'))

                # Store IDs for Mode 1 & 2, store full details for Mode 3
                concept_ids = [row['id'] for row in concepts_rows]

                if main_mode == 3:
                    # Fetch full details (meanings) for list mode concepts
                    full_details_map = {}
                    if concept_ids:
                         placeholders = ','.join('?' * len(concept_ids))
                         meanings_query = f"SELECT concept_id, part_of_speech, definition FROM meanings WHERE concept_id IN ({placeholders}) ORDER BY concept_id, id"
                         meanings_raw = db.execute(meanings_query, concept_ids).fetchall()
                         for m in meanings_raw:
                             cid = m['concept_id']
                             if cid not in full_details_map: full_details_map[cid] = []
                             full_details_map[cid].append(dict(m))

                    # Combine base info with meanings
                    for row in concepts_rows:
                        concept_dict = dict(row)
                        concept_dict['meanings'] = full_details_map.get(row['id'], [])
                        list_concepts_details.append(concept_dict)

            except sqlite3.Error as e:
                 current_app.logger.error(f"Database error fetching random concepts with filter: {e}", exc_info=True)
                 flash("随机抽取单词时发生数据库错误。", "danger")
                 return redirect(url_for('.setup'))

            # --- Initialize Session ---
            # clear_test_session() is already called at the beginning
            session[TEST_MAIN_MODE] = main_mode
            session[TEST_SUB_MODE] = sub_mode
            session[TEST_TAG_FILTER] = tag_filter_id_int # Store the ID (or None)

            # Set quantity and queue/list based on mode
            if main_mode == 3:
                session[TEST_QUANTITY] = len(list_concepts_details)
                session[TEST_LIST_CONCEPTS] = list_concepts_details
                session[TEST_INDEX] = 0 # Mode 3 is always index 0 (single page view)
                session[TEST_QUEUE] = [] # Not used for mode 3
                log_ids_or_count = f"{len(list_concepts_details)} concepts"
            else:
                session[TEST_QUANTITY] = len(concept_ids)
                session[TEST_QUEUE] = concept_ids
                session[TEST_INDEX] = 0
                session[TEST_LIST_CONCEPTS] = [] # Not used for mode 1/2
                log_ids_or_count = f"IDs: {concept_ids}"

            session[TEST_STATS] = {
                'correct': 0, 'incorrect': 0, 'skipped': 0,
                'total': session[TEST_QUANTITY],
                'start_time': datetime.now(timezone.utc).isoformat()
                }

            current_app.logger.info(f"Starting test: Mode={main_mode}, SubMode={sub_mode}, Quantity={session[TEST_QUANTITY]}, Tag='{selected_tag_name_for_log}'. {log_ids_or_count}")
            session.modified = True # Explicitly mark session as modified
            return redirect(url_for('.session_view')) # Redirect to the first question/list

        except ValueError as e: # Catch potential int conversion errors
            flash(f"输入参数无效: {e}", "danger")
            current_app.logger.error(f"ValueError during test setup: {e}", exc_info=True)
        except Exception as e:
            current_app.logger.error(f"Error processing test setup form: {e}", exc_info=True)
            flash("设置测试时发生未知错误。", "danger")

    # GET request or POST error: Render setup page
    return render_template('test_setup.html', total_concepts=total_concepts, all_tags=all_tags)

@bp.route('/session')
def session_view():
    """Displays the current test question or list."""
    # --- Validate Session State ---
    required_keys = [TEST_MAIN_MODE, TEST_STATS, TEST_QUANTITY] # Basic keys needed for all modes
    if not all(key in session for key in required_keys):
        flash("测试会话无效或已过期，请重新开始设置。", "info")
        clear_test_session()
        return redirect(url_for('.setup'))

    # --- Get Session Data ---
    main_mode = session[TEST_MAIN_MODE]
    sub_mode = session.get(TEST_SUB_MODE) # Could be None
    stats = session[TEST_STATS]
    total_in_session = session[TEST_QUANTITY]

    # === Handle Mode 3 (List Recall) ===
    if main_mode == 3:
        list_concepts = session.get(TEST_LIST_CONCEPTS)
        current_index = session.get(TEST_INDEX, 0) # Should always be 0 for mode 3 summary access

        if not list_concepts: # Check if list data exists
             flash("列表测试数据丢失，请重新开始设置。", "danger")
             current_app.logger.error("Test session view (Mode 3) called without list_concepts data in session.")
             clear_test_session()
             return redirect(url_for('.setup'))

        # Check completion (for Mode 3, completion means going to summary)
        # If user navigates back from summary, stats might exist but list might be cleared.
        # For now, just display the list again if they navigate back.

        return render_template(
            'test_session.html',
            concepts_list=list_concepts, # Pass the list of concepts
            current_progress=1, # Mode 3 is like one big item
            total_in_session=1, # Mode 3 is like one big item
            test_mode=main_mode,
            current_test_type=sub_mode, # e.g., 'blank_term' or 'blank_definition'
            placeholder=PLACEHOLDER,
            phrase_data=None, # Not used in Mode 3
            meanings_for_prompt=None # Not used in Mode 3 prompt
        )

    # === Handle Mode 1 & 2 (Card by Card) ===
    else:
        queue = session.get(TEST_QUEUE)
        current_index = session.get(TEST_INDEX)

        # Validate queue and index for Mode 1/2
        if queue is None or current_index is None:
            flash("测试会话队列数据丢失，请重新开始设置。", "danger")
            current_app.logger.error("Test session view (Mode 1/2) called without queue/index data.")
            clear_test_session()
            return redirect(url_for('.setup'))

        # --- Check if Test Finished ---
        if current_index >= total_in_session:
            current_app.logger.info("Test session index reached end, redirecting to summary.")
            return redirect(url_for('.summary'))

        # --- Get Current Concept ID and Fetch Data ---
        try:
            concept_id = queue[current_index]
        except IndexError:
             current_app.logger.error(f"Test session IndexError: Index {current_index} out of bounds for queue size {len(queue)}.")
             flash("测试队列索引错误，请重新开始测试。", "danger")
             clear_test_session()
             return redirect(url_for('.setup'))

        db = get_db()
        concept = None
        phrase_data = None
        current_test_type = None # 'meaning' or 'phrase' for Mode 2
        meanings_for_prompt = [] # Store meanings needed for Mode 2 phrase prompt

        try:
            # Fetch core concept data needed for all modes
            concept_raw = db.execute(
                 'SELECT id, term, phonetic, etymology, synonyms, audio_url FROM concepts WHERE id = ?',
                 (concept_id,)
             ).fetchone()

            if not concept_raw:
                 current_app.logger.error(f"Test session: Could not find concept details for ID: {concept_id}. Skipping.")
                 flash(f"无法加载单词 (ID: {concept_id})，已跳过此题。", "warning")
                 # Skip this question: Increment index, update stats, redirect to next
                 stats['skipped'] += 1
                 session[TEST_STATS] = stats
                 session[TEST_INDEX] = current_index + 1
                 session.modified = True
                 return redirect(url_for('.session_view'))

            concept = dict(concept_raw)

            # Fetch associated data (meanings, collocations) - needed for answer display
            meanings_raw = db.execute('SELECT id, concept_id, part_of_speech, definition FROM meanings WHERE concept_id = ? ORDER BY id', (concept_id,)).fetchall()
            concept['meanings'] = [dict(m) for m in meanings_raw]

            collocations_raw = db.execute('SELECT id, concept_id, phrase, example FROM collocations WHERE concept_id = ? ORDER BY id', (concept_id,)).fetchall()
            concept['collocations'] = [dict(c) for c in collocations_raw]

            # --- Determine Specific Test Logic for Mode 2 ---
            if main_mode == 2:
                possible_types_based_on_data = []
                if concept['meanings']: possible_types_based_on_data.append('meaning')
                if concept['collocations']: possible_types_based_on_data.append('phrase')

                # Determine which test type to use based on sub_mode and available data
                if sub_mode == 'meaning' and 'meaning' in possible_types_based_on_data:
                    current_test_type = 'meaning'
                elif sub_mode == 'phrase' and 'phrase' in possible_types_based_on_data:
                    current_test_type = 'phrase'
                elif sub_mode == 'mixed':
                    if possible_types_based_on_data: # If any type is possible
                         # Choose randomly for variety if mixed
                         current_test_type = random.choice(possible_types_based_on_data)
                         current_app.logger.debug(f"Concept {concept_id}: Mode 2 Mixed - Chose '{current_test_type}'.")
                    else: # No data for either type
                         current_app.logger.warning(f"Test Mode 2 (Mixed): Concept {concept_id} has no meanings or collocations. Falling back to Mode 1 view.")
                         # Fallback logic: Treat as Mode 1 for display, but still log as Mode 2?
                         # For simplicity, we'll show the Mode 1 view (recall)
                         pass # main_mode remains 2, but current_test_type is None
                else: # Requested sub_mode data is missing
                    current_app.logger.warning(f"Test Mode 2 (Sub:{sub_mode}): Concept {concept_id} lacks required data ({sub_mode}). Falling back to Mode 1 view.")
                    # Fallback to Mode 1 view (recall)
                    pass # main_mode remains 2, but current_test_type is None

            # --- Prepare Data Specific to the Test Type (Mode 2) ---
            if current_test_type == 'phrase':
                 # We already checked concept['collocations'] exists and is not empty
                 chosen_collocation = random.choice(concept['collocations'])
                 blanked_phrase = blank_out_term(chosen_collocation['phrase'], concept['term'], PLACEHOLDER)
                 blanked_example = blank_out_term(chosen_collocation['example'], concept['term'], PLACEHOLDER) if chosen_collocation['example'] else None

                 # Provide meanings as the prompt for phrase test
                 meanings_for_prompt = concept['meanings']

                 phrase_data = {
                     'original_phrase': chosen_collocation['phrase'],
                     'original_example': chosen_collocation['example'],
                     'blanked_phrase': blanked_phrase,
                     'blanked_example': blanked_example,
                     'correct_answer': concept['term'] # The term is the answer to fill
                 }
                 # Log if blanking didn't work as expected
                 if blanked_phrase == chosen_collocation['phrase'] and PLACEHOLDER not in blanked_phrase:
                      current_app.logger.warning(f"Blanking term '{concept['term']}' in phrase '{chosen_collocation['phrase']}' did not insert placeholder.")

            elif current_test_type == 'meaning':
                 # Prompt is the term/phonetic, user needs to input meaning
                 pass # No extra data prep needed here

            # else: Mode 1 or Mode 2 fallback - Prompt is term/phonetic, user recalls

        except sqlite3.Error as e:
            current_app.logger.error(f"Database error fetching details for test concept (ID: {concept_id}): {e}", exc_info=True)
            flash("加载测试题目时发生数据库错误。", "danger")
            clear_test_session()
            return redirect(url_for('.setup'))
        except Exception as e:
            current_app.logger.error(f"Unexpected error preparing test question (ID: {concept_id}): {e}", exc_info=True)
            flash("加载测试题目时发生未知错误。", "danger")
            clear_test_session()
            return redirect(url_for('.setup'))

        # --- Render the Session Page for Mode 1/2 ---
        return render_template(
            'test_session.html',
            concept=concept, # Full concept details for answer display
            current_progress=current_index + 1,
            total_in_session=total_in_session,
            test_mode=main_mode,
            current_test_type=current_test_type, # 'meaning', 'phrase', or None
            phrase_data=phrase_data, # Data for phrase blanking test
            placeholder=PLACEHOLDER, # Placeholder string for template use
            meanings_for_prompt=meanings_for_prompt, # Pass meanings needed for phrase prompt
            concepts_list=None # Not used in Mode 1/2
        )

@bp.route('/submit', methods=('POST',))
def submit_test():
    """Processes the self-judged result (correct/incorrect) for the current question or list."""
    # --- Validate Session State ---
    required_keys = [TEST_MAIN_MODE, TEST_STATS, TEST_QUANTITY, TEST_INDEX]
    if not all(key in session for key in required_keys):
        flash("测试会话无效或已结束，无法提交结果。", "warning")
        clear_test_session()
        return redirect(url_for('.setup'))

    main_mode = session[TEST_MAIN_MODE]
    stats = session[TEST_STATS]
    current_index = session[TEST_INDEX] # For Mode 1/2 progress

    # --- Process Submission ---
    result = request.form.get('result') # 'correct' or 'incorrect'

    # --- Handle Mode 3 (List Recall) Submission ---
    if main_mode == 3:
        # Mode 3 submits result for the whole list at once
        # We expect 'total_correct' and 'total_incorrect' from the form, submitted by JS
        try:
             total_correct = int(request.form.get('total_correct', 0))
             total_incorrect = int(request.form.get('total_incorrect', 0))
             stats['correct'] = total_correct
             stats['incorrect'] = total_incorrect
             # Mode 3 doesn't really have a concept of 'skipped' in the same way
             stats['skipped'] = 0
             session[TEST_STATS] = stats
             session[TEST_INDEX] = 1 # Mark as completed for summary check
             session.modified = True
             current_app.logger.info(f"Test Mode 3 submitted. Correct: {total_correct}, Incorrect: {total_incorrect}")
             return redirect(url_for('.summary'))
        except ValueError:
             flash("提交的列表测试结果无效。", "danger")
             return redirect(url_for('.session_view')) # Stay on the list view

    # --- Handle Mode 1 & 2 Submission ---
    else:
        queue = session.get(TEST_QUEUE)
        total_in_session = session[TEST_QUANTITY]

        # Check completion again (e.g., user clicks back after finishing)
        if not queue or current_index >= total_in_session:
             current_app.logger.warning("Submit called on already completed test session (Mode 1/2).")
             return redirect(url_for('.summary'))

        if result == 'correct':
            stats['correct'] += 1
        elif result == 'incorrect':
            stats['incorrect'] += 1
        else:
            flash("提交了无效的结果值。", "warning")
            return redirect(url_for('.session_view')) # Stay on the same question

        session[TEST_STATS] = stats # Save updated stats
        session[TEST_INDEX] = current_index + 1 # Advance index
        session.modified = True # Ensure session changes are saved

        current_app.logger.debug(f"Test question {current_index + 1} submitted as '{result}'. Advancing to index {session[TEST_INDEX]}.")

        # Redirect to the next question or summary if finished
        return redirect(url_for('.session_view'))


@bp.route('/summary')
def summary():
    """Displays the summary of the completed test session and saves history."""
    # --- Validate Session State ---
    required_keys = [TEST_STATS, TEST_MAIN_MODE, TEST_SUB_MODE, TEST_TAG_FILTER]
    if not all(key in session for key in required_keys):
        flash("没有找到测试总结信息，请先开始一个测试。", "warning")
        clear_test_session()
        return redirect(url_for('.setup'))

    # --- Retrieve Session Data ---
    stats = session.get(TEST_STATS, {})
    main_mode = session[TEST_MAIN_MODE]
    sub_mode = session.get(TEST_SUB_MODE)
    tag_filter_id = session.get(TEST_TAG_FILTER) # ID or None
    tag_filter_name = None
    mode_description = f"模式 {main_mode}" # Default description

    # --- Generate Mode Description ---
    if main_mode == 1:
        mode_description = "模式一: 看词回忆"
    elif main_mode == 2:
        mode_map = {'meaning': '单词释义', 'phrase': '搭配填空', 'mixed': '混合'}
        mode_description = f"模式二: {mode_map.get(sub_mode, '未知')}"
    elif main_mode == 3:
        mode_map = {'blank_term': '列表回忆 (填单词)', 'blank_definition': '列表回忆 (填释义)'}
        mode_description = f"模式三: {mode_map.get(sub_mode, '未知')}"

    # --- Fetch Tag Name if Filter Was Used ---
    db = get_db()
    if tag_filter_id:
         try:
             tag_row = db.execute("SELECT name FROM tags WHERE id = ?", (tag_filter_id,)).fetchone()
             if tag_row:
                 tag_filter_name = tag_row['name']
             else:
                 current_app.logger.warning(f"Could not find tag name for filtered ID {tag_filter_id} in summary.")
                 tag_filter_name = f"标签 ID {tag_filter_id}" # Fallback display
         except sqlite3.Error as e:
             current_app.logger.error(f"Database error fetching tag name for summary (ID: {tag_filter_id}): {e}")
             tag_filter_name = f"标签 ID {tag_filter_id} (查询出错)"

    # --- Calculate Duration ---
    start_time_iso = stats.get('start_time')
    end_time_dt = datetime.now(timezone.utc)
    duration_str = "计算出错"
    duration_seconds = 0
    if start_time_iso:
        try:
            if not start_time_iso.endswith('Z') and '+' not in start_time_iso:
                start_time_iso += 'Z'
            start_dt = datetime.fromisoformat(start_time_iso.replace('Z', '+00:00'))
            duration = end_time_dt - start_dt
            duration_seconds = max(0, int(duration.total_seconds()))
            minutes = duration_seconds // 60
            seconds = duration_seconds % 60
            duration_str = f"{minutes} 分 {seconds} 秒"
        except (ValueError, TypeError) as e:
            current_app.logger.warning(f"Could not parse session start time for duration: {start_time_iso}. Error: {e}")

    # --- Calculate Accuracy ---
    total = stats.get('total', 0)
    correct = stats.get('correct', 0)
    accuracy = round((correct / total) * 100, 1) if total > 0 else 0

    # --- Save to History Database ---
    try:
        with db:
            db.execute("""
                INSERT INTO session_history
                    (session_type, mode, tag_filter_id, start_time, end_time, duration_seconds,
                     total_items, correct_count, incorrect_count, skipped_count, accuracy)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                'test',
                f"{main_mode}_{sub_mode}" if sub_mode else str(main_mode), # Combine modes for storage
                tag_filter_id,
                start_time_iso,
                end_time_dt.isoformat(),
                duration_seconds,
                total,
                correct,
                stats.get('incorrect', 0),
                stats.get('skipped', 0),
                accuracy
            ))
        current_app.logger.info(f"Saved test session history. Mode: {main_mode}-{sub_mode}, Tag: {tag_filter_id}, Total: {total}, Correct: {correct}, Accuracy: {accuracy}%")
    except sqlite3.Error as e:
        current_app.logger.error(f"Database error saving test session history: {e}", exc_info=True)
        flash("保存本次测试记录时出错。", "warning")
    except Exception as e:
        current_app.logger.error(f"Unexpected error saving test session history: {e}", exc_info=True)
        flash("保存本次测试记录时发生未知错误。", "warning")

    # --- Clean Up Session ---
    # IMPORTANT: Clear session AFTER retrieving and saving all needed data
    clear_test_session()

    # --- Render Summary Page ---
    return render_template(
        'test_summary.html',
        stats=stats,
        duration=duration_str,
        accuracy=accuracy,
        tag_filter_name=tag_filter_name, # Pass name (or fallback) to template
        mode_description=mode_description # Pass descriptive mode string
    )

@bp.route('/quit', methods=['POST']) # Use POST
def quit_session():
    """Ends the current test session prematurely."""
    if not any(key.startswith(TEST_SESSION_PREFIX) for key in session):
         flash("没有正在进行的测试会话可以退出。", "info")
    else:
        clear_test_session()
        flash("测试会话已退出。", "success")
        current_app.logger.info("User quit test session.")
    return redirect(url_for('main.index'))
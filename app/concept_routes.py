# app/concept_routes.py
from flask import (
    Blueprint, flash, g, redirect, render_template, request, url_for, current_app, abort, Response, stream_with_context, jsonify
)
from werkzeug.utils import secure_filename
from .db import get_db
# CORRECT: Import classify_mastery from utils, ensure other utils are imported
from .utils import (export_concepts_to_csv, import_concepts_from_csv,
                    get_tags_for_concept, get_or_create_tag_ids, update_concept_tags, get_all_tags,
                    allowed_file, classify_mastery, parse_datetime_utc, format_datetime_local, format_due_date_relative, # Ensure datetime utils are imported if needed here
                    now_utc) # Added now_utc
from datetime import datetime, timezone # Keep timezone if needed separately
import sqlite3
import os
import math

bp = Blueprint('concept', __name__)
ITEMS_PER_PAGE = 15 # Items per page
COMMON_POS = ['n.', 'v.', 'adj.', 'adv.', 'prep.', 'pron.', 'conj.', 'phr.', 'interj.', 'num.', 'art.'] # Expanded list

# --- Helper: 获取 Concept 完整详情 (用于展开视图) ---
def get_concept_details(concept_id):
    """获取单个 Concept 及其关联的 Meanings, Collocations, 和 Tags"""
    db = get_db()
    concept = db.execute(
        'SELECT id, term, phonetic, etymology, synonyms, audio_url, error_count, srs_interval, srs_efactor, srs_due_date, last_reviewed_date FROM concepts WHERE id = ?',
        (concept_id,)
    ).fetchone()

    if concept is None:
        return None

    meanings = db.execute(
        'SELECT id, part_of_speech, definition FROM meanings WHERE concept_id = ? ORDER BY id',
        (concept_id,)
    ).fetchall()

    collocations = db.execute(
        'SELECT id, phrase, example FROM collocations WHERE concept_id = ? ORDER BY id',
        (concept_id,)
    ).fetchall()

    tags = get_tags_for_concept(concept_id) # Get tags using utility function

    # Convert concept Row to dict and add nested lists
    concept_dict = dict(concept)
    concept_dict['meanings'] = [dict(m) for m in meanings]
    concept_dict['collocations'] = [dict(c) for c in collocations]
    concept_dict['tags'] = tags # List of tag dicts
    concept_dict['tags_str'] = ', '.join([t['name'] for t in tags]) # Comma-separated string for display/edit

    # Add derived properties for easier template use
    concept_dict['mastery'] = classify_mastery(concept_dict['srs_interval'])
    concept_dict['is_due'] = concept_dict.get('srs_due_date') and parse_datetime_utc(concept_dict['srs_due_date']) <= now_utc()

    return concept_dict


# --- 主管理路由 ---
@bp.route('/manage')
def manage_concepts():
    """管理单词和搭配的页面"""
    db = get_db()
    # --- 获取请求参数 ---
    view = request.args.get('view', 'concepts', type=str)
    search_query = request.args.get('q', '', type=str).strip()
    tag_filter = request.args.get('tag', '', type=str).strip()
    pos_filter = request.args.get('pos', '', type=str).strip()
    page = request.args.get('page', 1, type=int)
    if page < 1: page = 1

    all_tags = get_all_tags() # Fetch all tags for the filter dropdown
    items = []
    total_items = 0
    total_pages = 1

    # --- 构建通用过滤条件 (始终基于 Concept 表 'c') ---
    filter_joins = ""
    filter_where_clauses = []
    filter_params = []

    # Add filters based on request arguments
    if tag_filter:
        # Join concept_tags and tags table if not already joined
        if "concept_tags ct" not in filter_joins: filter_joins += " JOIN concept_tags ct ON c.id = ct.concept_id"
        if "tags t" not in filter_joins: filter_joins += " JOIN tags t ON ct.tag_id = t.id"
        filter_where_clauses.append("lower(t.name) = lower(?)") # Case-insensitive tag filter
        filter_params.append(tag_filter)

    if pos_filter:
         # Join meanings table if not already joined
        if "meanings m" not in filter_joins: filter_joins += " LEFT JOIN meanings m ON c.id = m.concept_id"
        # Use LIKE for prefixes (e.g., 'n.' matches 'n.', 'n. pl.', etc.)
        filter_where_clauses.append("m.part_of_speech LIKE ?")
        filter_params.append(pos_filter + '%')

    # --- 根据视图应用特定逻辑 ---
    offset = (page - 1) * ITEMS_PER_PAGE
    view_params = list(filter_params) # Copy base params
    view_where = list(filter_where_clauses) # Copy base clauses

    try:
        if view == 'collocations':
            # Query for collocations, joining concepts for filtering and display
            # Use DISTINCT on co.id for count, and select DISTINCT rows for data
            select_count_base = "SELECT COUNT(DISTINCT co.id) FROM collocations co JOIN concepts c ON co.concept_id = c.id "
            select_data_base = "SELECT DISTINCT co.id, co.phrase, co.example, co.concept_id, c.term as concept_term, c.phonetic as concept_phonetic FROM collocations co JOIN concepts c ON co.concept_id = c.id "
            view_joins = filter_joins # Use the common joins related to concepts 'c'

            if search_query:
                 like_query = f"%{search_query}%"
                 # Search collocation phrase, example, OR the concept term itself
                 view_where.append("(co.phrase LIKE ? OR co.example LIKE ? OR lower(c.term) LIKE lower(?))")
                 view_params.extend([like_query, like_query, like_query])

            where_sql = " WHERE " + " AND ".join(view_where) if view_where else ""
            count_sql = select_count_base + view_joins + where_sql
            total_items = db.execute(count_sql, view_params).fetchone()[0] or 0

            data_sql = select_data_base + view_joins + where_sql + " ORDER BY co.phrase COLLATE NOCASE ASC LIMIT ? OFFSET ?"
            params_with_pagination = view_params + [ITEMS_PER_PAGE, offset]
            items_raw = db.execute(data_sql, params_with_pagination).fetchall()
            items = [dict(row) for row in items_raw]
            current_app.logger.info(f"Fetched {len(items)} collocations for view '{view}' page {page}.")

        else: # Default to 'concepts' view
            view = 'concepts'
            select_count_base = "SELECT COUNT(DISTINCT c.id) FROM concepts c "
            # Select core fields for the main list + counts needed for the row display
            # Pre-calculate counts using subqueries for efficiency
            select_data_base = """
                SELECT DISTINCT c.id, c.term, c.phonetic, c.error_count, c.srs_interval, c.srs_due_date, c.last_reviewed_date,
                       (SELECT COUNT(m.id) FROM meanings m WHERE m.concept_id = c.id) as meaning_count,
                       (SELECT COUNT(co.id) FROM collocations co WHERE co.concept_id = c.id) as collocation_count
                FROM concepts c
            """
            view_joins = filter_joins # Use common joins related to concepts 'c'

            if search_query:
                like_query = f"%{search_query}%"
                # Search concept term, etymology, synonyms for concept view (case-insensitive)
                view_where.append("(lower(c.term) LIKE lower(?) OR lower(c.etymology) LIKE lower(?) OR lower(c.synonyms) LIKE lower(?))")
                view_params.extend([like_query, like_query, like_query])

            where_sql = " WHERE " + " AND ".join(view_where) if view_where else ""
            count_sql = select_count_base + view_joins + where_sql
            total_items = db.execute(count_sql, view_params).fetchone()[0] or 0

            # Fetch the IDs and counts for the current page first
            data_sql = select_data_base + view_joins + where_sql + " ORDER BY c.term COLLATE NOCASE ASC LIMIT ? OFFSET ?"
            params_with_pagination = view_params + [ITEMS_PER_PAGE, offset]
            concepts_basic_info = db.execute(data_sql, params_with_pagination).fetchall()

            # Now, fetch full details ONLY for the concepts on the current page
            items = []
            if concepts_basic_info:
                concept_ids_on_page = [row['id'] for row in concepts_basic_info]
                # Create a map for quick lookup of counts
                counts_map = {row['id']: {'meaning_count': row['meaning_count'], 'collocation_count': row['collocation_count']} for row in concepts_basic_info}

                # Fetch full details for these IDs using the optimized helper
                # Assuming get_concept_details fetches meanings/collocations efficiently (if not, optimize it)
                # For now, calling it per concept. If performance is an issue, batch fetch details.
                for concept_id in concept_ids_on_page:
                    concept_details = get_concept_details(concept_id)
                    if concept_details:
                        # Merge pre-calculated counts
                        concept_details.update(counts_map.get(concept_id, {}))
                        items.append(concept_details)
                    else:
                        current_app.logger.warning(f"Could not fetch full details for concept ID {concept_id} in manage list.")

            current_app.logger.info(f"Fetched details for {len(items)} concepts for view '{view}' page {page}.")

    except sqlite3.Error as db_err:
         current_app.logger.error(f"Database error in manage_concepts (view: {view}): {db_err}", exc_info=True)
         flash("加载列表时发生数据库错误。", "danger")
         items = []
         total_items = 0
    except Exception as e:
        current_app.logger.error(f"Unexpected error in manage_concepts (view: {view}): {e}", exc_info=True)
        flash("加载列表时发生未知错误。", "danger")
        items = []
        total_items = 0

    # --- 计算分页 ---
    total_pages = math.ceil(total_items / ITEMS_PER_PAGE) if total_items > 0 else 1
    # Handle cases where page number might be out of bounds after filtering
    if page > total_pages and total_pages > 0: page = total_pages

    # --- 准备传递给模板的参数 ---
    pagination_params = {k: v for k, v in request.args.items() if k != 'page'}
    pagination_params['view'] = view # Ensure view is part of pagination links

    # Context processors inject utility functions (like classify_mastery, format_datetime_local)
    template_context = {
        'items': items,
        'item_type': view,
        'total_items': total_items,
        'search_query': search_query,
        'all_tags': all_tags, # Pass for filter dropdown
        'selected_tag': tag_filter,
        'common_pos': COMMON_POS, # Pass for filter dropdown
        'selected_pos': pos_filter,
        'current_page': page,
        'total_pages': total_pages,
        'pagination_endpoint': 'concept.manage_concepts', # Endpoint name for url_for
        'pagination_params': pagination_params,
    }

    return render_template('manage_concepts.html', **template_context)


@bp.route('/add', methods=('GET', 'POST'))
def add_concept():
    concept_data_on_error = None # Store submitted data if validation fails
    all_tags = get_all_tags() # Get tags for the tag input datalist

    if request.method == 'POST':
        # --- Extract Form Data ---
        term = request.form.get('term', '').strip()
        phonetic = request.form.get('phonetic', '').strip()
        etymology = request.form.get('etymology', '').strip()
        synonyms = request.form.get('synonyms', '').strip()
        audio_url = request.form.get('audio_url', '').strip()
        tags_str = request.form.get('tags', '').strip() # Comma-separated tags

        # Extract dynamic meanings
        meanings_data = []
        i = 0
        while True:
            pos_key = f'meanings[{i}][part_of_speech]'
            def_key = f'meanings[{i}][definition]'
            # Check if either field for this index exists in the form submission
            if pos_key in request.form or def_key in request.form:
                 pos = request.form.get(pos_key, '').strip()
                 definition = request.form.get(def_key, '').strip()
                 # Only add if both part_of_speech and definition are provided and not empty
                 if pos and definition:
                     meanings_data.append({'part_of_speech': pos, 'definition': definition})
                 elif pos or definition: # Warn if only one part is filled
                      flash(f"第 {i+1} 个含义的词性和定义必须同时填写。", "warning")
                      # Optionally set error flag here if needed
                 i += 1
            else:
                 break # No more meaning fields found for this index

        # Extract dynamic collocations
        collocations_data = []
        j = 0
        while True:
            phrase_key = f'collocations[{j}][phrase]'
            example_key = f'collocations[{j}][example]'
            # Check if phrase field exists (example is optional)
            if phrase_key in request.form:
                 phrase = request.form.get(phrase_key, '').strip()
                 example = request.form.get(example_key, '').strip()
                 # Only add if phrase is provided
                 if phrase:
                     collocations_data.append({'phrase': phrase, 'example': example})
                 j += 1
            else:
                break # No more collocation fields found

        # --- Validation ---
        error = None
        if not term:
            error = '核心概念 (Term) 不能为空。'
        # Add more validation if needed (e.g., URL format)

        # --- Process Data if Valid ---
        if error is None:
            db = get_db()
            # Set initial SRS values for a new concept
            initial_due_date = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
            initial_interval = 1 # Start with 1 day interval
            initial_efactor = 2.5 # Standard starting E-Factor

            try:
                with db: # Use context manager for automatic commit/rollback
                    cursor = db.cursor()
                    # Insert the main concept
                    cursor.execute(
                        """INSERT INTO concepts (term, phonetic, etymology, synonyms, audio_url, srs_due_date, srs_interval, srs_efactor, error_count, last_reviewed_date)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, NULL)""",
                        (term, phonetic, etymology, synonyms, audio_url, initial_due_date, initial_interval, initial_efactor)
                    )
                    concept_id = cursor.lastrowid
                    current_app.logger.info(f"Inserted concept '{term}' with ID {concept_id}.")

                    # Handle Tags: Get or create tag IDs and link them
                    tag_ids = get_or_create_tag_ids(tags_str)
                    if tag_ids:
                        if not update_concept_tags(concept_id, tag_ids):
                            # This function logs errors internally
                            raise sqlite3.Error("添加概念时更新标签失败。")

                    # Insert Meanings if any
                    if meanings_data:
                        meanings_values = [(concept_id, m['part_of_speech'], m['definition']) for m in meanings_data]
                        cursor.executemany('INSERT INTO meanings (concept_id, part_of_speech, definition) VALUES (?, ?, ?)', meanings_values)
                        current_app.logger.debug(f"Inserted {len(meanings_values)} meanings for concept ID {concept_id}.")

                    # Insert Collocations if any
                    if collocations_data:
                        collocations_values = [(concept_id, c['phrase'], c['example']) for c in collocations_data]
                        cursor.executemany('INSERT INTO collocations (concept_id, phrase, example) VALUES (?, ?, ?)', collocations_values)
                        current_app.logger.debug(f"Inserted {len(collocations_values)} collocations for concept ID {concept_id}.")

                flash(f'概念 "{term}" 添加成功!', 'success')
                # Redirect to manage list, default view 'concepts'
                return redirect(url_for('concept.manage_concepts', view='concepts'))

            except sqlite3.IntegrityError:
                # Check if it's the UNIQUE constraint on 'term'
                existing = db.execute("SELECT id FROM concepts WHERE lower(term) = lower(?)", (term,)).fetchone()
                if existing:
                     error = f'核心概念 "{term}" 已存在 (ID: {existing["id"]})。请使用其他名称。'
                else:
                     error = f'添加概念时发生数据库完整性错误: {e}' # Generic message for other integrity issues
                current_app.logger.warning(f"IntegrityError adding concept '{term}': {error}", exc_info=True)
            except sqlite3.Error as e:
                error = f'添加概念时发生数据库错误: {e}'
                current_app.logger.error(f"Database error adding concept '{term}': {e}", exc_info=True)
            except Exception as e:
                error = f'添加概念时发生未知错误: {e}'
                current_app.logger.error(f"Unexpected error adding concept '{term}': {e}", exc_info=True)

        # --- Handle Errors ---
        if error:
            flash(error, 'danger')
            # Store submitted data to re-populate the form
            concept_data_on_error = {
                'term': term, 'phonetic': phonetic, 'etymology': etymology,
                'synonyms': synonyms, 'audio_url': audio_url, 'tags_str': tags_str,
                'meanings_on_error': meanings_data, # Pass back submitted meanings
                'collocations_on_error': collocations_data # Pass back submitted collocations
            }
            # Need to re-fetch all tags for the template
            all_tags = get_all_tags()

    # Render form for GET request or if POST had errors
    return render_template(
        'add_edit_concept.html',
        concept=None, # Indicate this is the 'add' mode
        concept_data_on_error=concept_data_on_error,
        all_tags=all_tags, # Pass tags for the datalist suggestion
        is_edit_error=False # Explicitly set for clarity
    )


@bp.route('/edit/<int:concept_id>', methods=('GET', 'POST'))
def edit_concept(concept_id):
    all_tags = get_all_tags() # Get tags for tag input datalist

    if request.method == 'POST':
        # --- Extract Form Data ---
        term = request.form.get('term', '').strip()
        phonetic = request.form.get('phonetic', '').strip()
        etymology = request.form.get('etymology', '').strip()
        synonyms = request.form.get('synonyms', '').strip()
        audio_url = request.form.get('audio_url', '').strip()
        tags_str = request.form.get('tags', '').strip()

        # Get original view/page parameters for redirecting back
        origin_view = request.form.get('origin_view', 'concepts')
        try:
            origin_page = int(request.form.get('origin_page', 1))
            if origin_page < 1: origin_page = 1
        except ValueError:
             origin_page = 1
        origin_search = request.form.get('origin_search', '')
        origin_tag = request.form.get('origin_tag', '')
        origin_pos = request.form.get('origin_pos', '')

        # Extract dynamic meanings (same logic as add)
        meanings_data = []
        i = 0
        while True:
            pos_key = f'meanings[{i}][part_of_speech]'; def_key = f'meanings[{i}][definition]'
            if pos_key in request.form or def_key in request.form:
                pos = request.form.get(pos_key, '').strip(); definition = request.form.get(def_key, '').strip()
                if pos and definition: meanings_data.append({'part_of_speech': pos, 'definition': definition})
                elif pos or definition: flash(f"第 {i+1} 个含义的词性和定义必须同时填写。", "warning")
                i += 1
            else: break

        # Extract dynamic collocations (same logic as add)
        collocations_data = []
        j = 0
        while True:
            phrase_key = f'collocations[{j}][phrase]'; example_key = f'collocations[{j}][example]'
            if phrase_key in request.form:
                 phrase = request.form.get(phrase_key, '').strip(); example = request.form.get(example_key, '').strip()
                 if phrase: collocations_data.append({'phrase': phrase, 'example': example})
                 j += 1
            else: break

        # --- Validation ---
        error = None
        if not term:
            error = '核心概念 (Term) 不能为空。'

        # --- Process Data if Valid ---
        if error is None:
            db = get_db()
            try:
                with db:
                    cursor = db.cursor()
                    # Update core concept fields
                    cursor.execute(
                        """UPDATE concepts SET term = ?, phonetic = ?, etymology = ?, synonyms = ?, audio_url = ?
                           WHERE id = ?""",
                        (term, phonetic, etymology, synonyms, audio_url, concept_id)
                    )
                    current_app.logger.debug(f"Updated core fields for concept ID {concept_id}.")

                    # Update tags
                    tag_ids = get_or_create_tag_ids(tags_str)
                    if not update_concept_tags(concept_id, tag_ids):
                         raise sqlite3.Error("编辑概念时更新标签失败。")

                    # Update meanings: Delete existing and insert submitted ones
                    cursor.execute('DELETE FROM meanings WHERE concept_id = ?', (concept_id,))
                    if meanings_data:
                        meanings_values = [(concept_id, m['part_of_speech'], m['definition']) for m in meanings_data]
                        cursor.executemany('INSERT INTO meanings (concept_id, part_of_speech, definition) VALUES (?, ?, ?)', meanings_values)
                        current_app.logger.debug(f"Updated {len(meanings_values)} meanings for concept ID {concept_id}.")

                    # Update collocations: Delete existing and insert submitted ones
                    cursor.execute('DELETE FROM collocations WHERE concept_id = ?', (concept_id,))
                    if collocations_data:
                        collocations_values = [(concept_id, c['phrase'], c['example']) for c in collocations_data]
                        cursor.executemany('INSERT INTO collocations (concept_id, phrase, example) VALUES (?, ?, ?)', collocations_values)
                        current_app.logger.debug(f"Updated {len(collocations_values)} collocations for concept ID {concept_id}.")

                flash(f'概念 "{term}" 更新成功!', 'success')
                # Redirect back to the manage list with original filters/page
                redirect_url = url_for('concept.manage_concepts', view=origin_view, page=origin_page, q=origin_search, tag=origin_tag, pos=origin_pos)
                return redirect(redirect_url)

            except sqlite3.IntegrityError as e:
                # Check if the conflict is due to the term uniqueness constraint with ANOTHER concept
                existing = db.execute("SELECT id FROM concepts WHERE lower(term) = lower(?) AND id != ?", (term, concept_id)).fetchone()
                if existing:
                    error = f'更新失败：核心概念 "{term}" 与另一个已存在的单词 (ID: {existing["id"]}) 重复。'
                else: # Should not happen if constraint is just on term uniqueness, but handle just in case
                    error = f'数据库完整性错误: {e}'
                current_app.logger.warning(f"IntegrityError editing concept ID {concept_id} ('{term}'): {error}", exc_info=True)
            except sqlite3.Error as e:
                error = f'更新概念时发生数据库错误: {e}'
                current_app.logger.error(f"Database error editing concept ID {concept_id} ('{term}'): {e}", exc_info=True)
            except Exception as e:
                error = f'更新概念时发生未知错误: {e}'
                current_app.logger.error(f"Unexpected error editing concept ID {concept_id} ('{term}'): {e}", exc_info=True)

        # --- Handle Errors ---
        if error:
            flash(error, 'danger')
            # Re-populate form with submitted data on error
            # We need to reconstruct a dict similar to what get_concept_details returns
            concept_details_on_error = {
                'id': concept_id, 'term': term, 'phonetic': phonetic, 'etymology': etymology,
                'synonyms': synonyms, 'audio_url': audio_url, 'tags_str': tags_str,
                'meanings': meanings_data, # Use submitted data
                'collocations': collocations_data, # Use submitted data
                # Pass back origin parameters to hidden fields
                'origin_view': origin_view, 'origin_page': origin_page,
                'origin_search': origin_search, 'origin_tag': origin_tag, 'origin_pos': origin_pos,
                 # Add other fields from original concept if needed for display (like srs info)
                 # Fetching again might be simpler if needed
                 'srs_interval': request.form.get('srs_interval'), # Assuming these aren't editable but needed
                 'srs_due_date': request.form.get('srs_due_date'),
                 'error_count': request.form.get('error_count'),
                 'last_reviewed_date': request.form.get('last_reviewed_date')
            }
            # Simulate derived properties needed by the template
            concept_details_on_error['mastery'] = classify_mastery(concept_details_on_error.get('srs_interval'))
            concept_details_on_error['is_due'] = concept_details_on_error.get('srs_due_date') and parse_datetime_utc(concept_details_on_error['srs_due_date']) <= now_utc()
            concept_details_on_error['tags'] = [{'name': t.strip()} for t in tags_str.split(',') if t.strip()] # Approximate tags list

            # Need all tags again for the datalist
            all_tags = get_all_tags()
            # Pass a flag to the template to indicate it's an edit error state
            return render_template(
                'add_edit_concept.html',
                concept=concept_details_on_error, # Pass the reconstructed dict
                all_tags=all_tags,
                is_edit_error=True # Flag for template logic
                )

    # --- GET Request ---
    concept_details = get_concept_details(concept_id)
    if concept_details is None:
        abort(404, f"Concept with ID {concept_id} not found.")

    # Add origin parameters from request args to the concept dict for the hidden fields
    concept_details['origin_view'] = request.args.get('view', 'concepts')
    concept_details['origin_page'] = request.args.get('page', 1, type=int)
    concept_details['origin_search'] = request.args.get('q', '')
    concept_details['origin_tag'] = request.args.get('tag', '')
    concept_details['origin_pos'] = request.args.get('pos', '')

    return render_template(
        'add_edit_concept.html',
        concept=concept_details,
        all_tags=all_tags, # Pass tags for datalist
        is_edit_error=False
        )


@bp.route('/delete/<int:concept_id>', methods=('POST',))
def delete_concept(concept_id):
    db = get_db()
    # Get origin parameters from form for redirect
    origin_view = request.form.get('origin_view', 'concepts')
    try: origin_page = int(request.form.get('origin_page', 1))
    except ValueError: origin_page = 1
    origin_search = request.form.get('origin_search', '')
    origin_tag = request.form.get('origin_tag', '')
    origin_pos = request.form.get('origin_pos', '')

    # Get term for flash message before deleting
    concept = db.execute('SELECT term FROM concepts WHERE id = ?', (concept_id,)).fetchone()

    if concept is None:
        flash(f'尝试删除的概念 ID {concept_id} 不存在。', 'warning')
    else:
        term = concept['term']
        try:
            with db: # Transaction ensures all related data is deleted or none is
                # Cascade delete should handle meanings, collocations, concept_tags automatically due to schema definition
                # Delete the concept itself
                rows_deleted = db.execute('DELETE FROM concepts WHERE id = ?', (concept_id,)).rowcount
            if rows_deleted > 0:
                 flash(f'概念 "{term}" (ID: {concept_id}) 及其关联数据已成功删除。', 'success')
                 current_app.logger.info(f"Successfully deleted concept ID {concept_id} ('{term}'). Rows deleted: {rows_deleted}")
            else:
                 # Should not happen if concept existed, but good to check
                 flash(f'尝试删除概念 "{term}" 时未找到记录 (ID: {concept_id})。', 'warning')
                 current_app.logger.warning(f"Attempted to delete concept ID {concept_id} ('{term}'), but no rows were affected.")
        except sqlite3.Error as e:
            flash(f'删除概念 "{term}" 时发生数据库错误: {e}', 'danger')
            current_app.logger.error(f"Error deleting concept ID {concept_id} ('{term}'): {e}", exc_info=True)

    # Redirect back to the manage list with original parameters
    redirect_url = url_for('concept.manage_concepts', view=origin_view, page=origin_page, q=origin_search, tag=origin_tag, pos=origin_pos)
    return redirect(redirect_url)


@bp.route('/export')
def export_csv():
    """Exports all concepts to a CSV file download."""
    try:
        csv_data_string = export_concepts_to_csv() # Use utility function
        if csv_data_string is None:
            # Error flash message is handled within export_concepts_to_csv
            return redirect(url_for('concept.manage_concepts'))

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"concepts_export_{timestamp}.csv"
        # Return response with CSV data and correct headers for download
        return Response(
            csv_data_string, # Already UTF-8 encoded string with BOM from util
            mimetype="text/csv; charset=utf-8",
            headers={"Content-disposition": f"attachment; filename=\"{filename}\""}
        )
    except Exception as e:
        current_app.logger.error(f"Error generating CSV export response: {e}", exc_info=True)
        flash("生成 CSV 导出文件时出错。", "danger")
        return redirect(url_for('concept.manage_concepts'))


@bp.route('/import', methods=('GET', 'POST'))
def import_csv():
    """Handles CSV file upload and import process."""
    if request.method == 'POST':
        # Check if the post request has the file part
        if 'csvfile' not in request.files:
            flash('未发现文件部分', 'warning')
            return redirect(request.url)
        file = request.files['csvfile']
        # If the user does not select a file, the browser submits an empty file without a filename.
        if file.filename == '':
            flash('未选择任何文件', 'warning')
            return redirect(request.url)

        # Use utility function to check allowed extensions
        if file and allowed_file(file.filename, {'csv'}):
            try:
                content_bytes = file.read() # Read file content as bytes
                # Use utility function for import logic
                imported_count, errors = import_concepts_from_csv(content_bytes)

                # Display summary messages (already flashed within the function)
                # Redirect to manage page regardless of errors to see results/remaining items
                return redirect(url_for('concept.manage_concepts', view='concepts'))
            except Exception as e:
                # Catch unexpected errors during file processing
                flash(f"处理 CSV 文件时发生意外错误: {e}", "danger")
                current_app.logger.error(f"Unexpected error processing CSV upload '{file.filename}': {e}", exc_info=True)
                return redirect(request.url)
        else:
            flash(f"只允许上传 CSV 文件 (.csv)。检测到文件类型: {file.filename.rsplit('.', 1)[-1] if '.' in file.filename else '无扩展名'}", 'danger')
            return redirect(request.url)

    # GET request: show the upload form
    return render_template('import_concepts.html')

# app/history_routes.py
from flask import (
    Blueprint, flash, redirect, render_template, request, url_for, current_app
)
from .db import get_db
from .utils import get_all_tags, format_datetime_local # Import necessary utils
import sqlite3
import math

bp = Blueprint('history', __name__, url_prefix='/history')
ITEMS_PER_PAGE = 20 # Number of history records per page

@bp.route('/')
def view_history():
    """Displays the session history page with pagination and filtering."""
    db = get_db()
    page = request.args.get('page', 1, type=int)
    if page < 1: page = 1

    # Filters (add more as needed: date range, type, mode)
    session_type_filter = request.args.get('type', '', type=str).strip() # 'practice' or 'test'
    tag_filter_id = request.args.get('tag', '', type=str).strip() # Tag ID

    base_query = """
        SELECT h.id, h.session_type, h.mode, h.start_time, h.duration_seconds,
               h.total_items, h.correct_count, h.incorrect_count, h.skipped_count, h.accuracy,
               t.name as tag_name
        FROM session_history h
        LEFT JOIN tags t ON h.tag_filter_id = t.id
    """
    count_query = "SELECT COUNT(h.id) FROM session_history h LEFT JOIN tags t ON h.tag_filter_id = t.id"
    filters = []
    params = []

    # Apply filters
    if session_type_filter:
        if session_type_filter in ['practice', 'test']:
             filters.append("h.session_type = ?")
             params.append(session_type_filter)
        else:
             flash("无效的会话类型过滤器。", "warning")
             session_type_filter = '' # Clear invalid filter

    if tag_filter_id:
        try:
             tag_id_int = int(tag_filter_id)
             filters.append("h.tag_filter_id = ?")
             params.append(tag_id_int)
        except ValueError:
             flash("无效的标签过滤器ID。", "warning")
             tag_filter_id = '' # Clear invalid filter

    # Construct WHERE clause
    where_clause = ""
    if filters:
        where_clause = " WHERE " + " AND ".join(filters)

    # Get total items count with filters
    try:
        total_items_row = db.execute(count_query + where_clause, params).fetchone()
        total_items = total_items_row[0] if total_items_row else 0
    except sqlite3.Error as e:
        current_app.logger.error(f"Error counting history items: {e}", exc_info=True)
        flash("无法获取历史记录总数。", "danger")
        total_items = 0

    # Calculate pagination
    total_pages = math.ceil(total_items / ITEMS_PER_PAGE) if total_items > 0 else 1
    if page > total_pages and total_pages > 0: page = total_pages
    offset = (page - 1) * ITEMS_PER_PAGE

    # Fetch history items for the current page
    history_items = []
    try:
        query = base_query + where_clause + " ORDER BY h.start_time DESC LIMIT ? OFFSET ?"
        params_with_pagination = params + [ITEMS_PER_PAGE, offset]
        history_raw = db.execute(query, params_with_pagination).fetchall()
        history_items = [dict(row) for row in history_raw]
        current_app.logger.info(f"Fetched {len(history_items)} history items for page {page}.")
    except sqlite3.Error as e:
        current_app.logger.error(f"Error fetching history items: {e}", exc_info=True)
        flash("加载历史记录时发生数据库错误。", "danger")

    all_tags = get_all_tags() # For the filter dropdown

    # Prepare pagination context
    pagination_params = {k: v for k, v in request.args.items() if k != 'page'}

    return render_template('history.html',
                           history_items=history_items,
                           current_page=page,
                           total_pages=total_pages,
                           total_items=total_items,
                           pagination_endpoint='history.view_history',
                           pagination_params=pagination_params,
                           all_tags=all_tags,
                           selected_type=session_type_filter,
                           selected_tag_id=tag_filter_id)

# app/wander_routes.py
from flask import (
    Blueprint, flash, redirect, render_template, request, url_for, current_app, session
)
from .db import get_db
# Reuse the get_concept_details function from concept_routes
from .concept_routes import get_concept_details
from .utils import get_all_tags # Import get_all_tags
import sqlite3
import random

bp = Blueprint('wander', __name__)

# --- Helper: Get Random Concept ID with Optional Tag Filter ---
def get_random_concept_id(tag_id=None):
    """获取一个随机 Concept 的 ID, 可选按标签过滤。 Returns ID or None."""
    db = get_db()
    query = "SELECT id FROM concepts c"
    params = []
    joins = ""

    if tag_id:
        try:
            tag_id_int = int(tag_id)
            joins += " JOIN concept_tags ct ON c.id = ct.concept_id"
            query += joins + " WHERE ct.tag_id = ?"
            params.append(tag_id_int)
            current_app.logger.debug(f"Wander: Filtering concepts by tag ID: {tag_id_int}")
        except ValueError:
            current_app.logger.warning(f"Wander: Invalid tag_id '{tag_id}' provided. Ignoring filter.")
            tag_id = None # Ignore invalid tag_id

    query += " ORDER BY RANDOM() LIMIT 1"

    try:
        result = db.execute(query, params).fetchone()
        if result:
            return result['id']
        else:
            msg = f"Wander: No concepts found" + (f" for tag ID {tag_id}" if tag_id else "") + "."
            current_app.logger.warning(msg)
            return None
    except sqlite3.Error as e:
        current_app.logger.error(f"Wander: Error fetching random concept ID (Tag ID: {tag_id}): {e}", exc_info=True)
        return None

# --- Helper: Get Random Collocation with Optional Tag Filter ---
def get_random_collocation_with_concept(tag_id=None):
    """获取一个随机 Collocation 及其关联的 Concept 信息, 可选按标签过滤。 Returns dict or None."""
    db = get_db()
    query = """
        SELECT co.id as collocation_id, co.phrase, co.example, co.concept_id,
               c.term, c.phonetic, c.audio_url
        FROM collocations co
        JOIN concepts c ON co.concept_id = c.id
    """
    params = []
    joins = "" # For filtering based on concept's tag

    if tag_id:
        try:
            tag_id_int = int(tag_id)
            # Need to join concept_tags to filter based on the concept's tag
            joins += " JOIN concept_tags ct ON c.id = ct.concept_id"
            query += joins + " WHERE ct.tag_id = ?"
            params.append(tag_id_int)
            current_app.logger.debug(f"Wander: Filtering collocations by concept tag ID: {tag_id_int}")
        except ValueError:
            current_app.logger.warning(f"Wander: Invalid tag_id '{tag_id}' provided for collocation filter. Ignoring filter.")
            tag_id = None # Ignore invalid tag_id

    query += " ORDER BY RANDOM() LIMIT 1"

    try:
        collocation_data = db.execute(query, params).fetchone()
        if collocation_data:
            return dict(collocation_data)
        else:
            msg = f"Wander: No collocations found" + (f" for concepts with tag ID {tag_id}" if tag_id else "") + "."
            current_app.logger.warning(msg)
            return None
    except sqlite3.Error as e:
        current_app.logger.error(f"Wander: Error fetching random collocation (Tag ID: {tag_id}): {e}", exc_info=True)
        return None

# --- Wander Setup Route ---
@bp.route('/setup', methods=['GET', 'POST'])
def setup():
    """Page to select wander mode and optional tag filter."""
    if request.method == 'POST':
        mode = request.form.get('wander_mode', 'concept') # 'concept' or 'collocation'
        tag_id = request.form.get('tag_filter') # Can be empty string ""
        tag_id_int = None

        if tag_id:
             try:
                 tag_id_int = int(tag_id)
             except ValueError:
                 flash("选择了无效的标签。", "warning")
                 tag_id_int = None # Reset if invalid

        # Redirect to the display route with parameters
        return redirect(url_for('.display', mode=mode, tag_id=tag_id_int))

    # GET request: Show the setup form
    all_tags = get_all_tags()
    db = get_db()
    total_concepts = db.execute("SELECT COUNT(id) FROM concepts").fetchone()[0] or 0
    total_collocations = db.execute("SELECT COUNT(id) FROM collocations").fetchone()[0] or 0

    return render_template('wander_setup.html',
                           all_tags=all_tags,
                           total_concepts=total_concepts,
                           total_collocations=total_collocations)


# --- Wander Display Route ---
@bp.route('/display')
def display():
    """Displays a random concept or collocation based on mode and filter."""
    mode = request.args.get('mode', 'concept')
    tag_id = request.args.get('tag_id') # Keep as string or None initially
    item_data = None
    tag_name = None # To display selected tag name

    if tag_id:
        try:
            tag_id_int = int(tag_id)
            db = get_db()
            tag_row = db.execute("SELECT name FROM tags WHERE id = ?", (tag_id_int,)).fetchone()
            if tag_row:
                tag_name = tag_row['name']
            else:
                 flash(f"未找到 ID 为 {tag_id} 的标签。", "warning")
                 tag_id = None # Clear invalid tag_id
        except (ValueError, sqlite3.Error):
             flash("无效的标签过滤器。", "warning")
             tag_id = None # Clear invalid tag_id

    current_app.logger.info(f"Wander display requested. Mode: {mode}, Tag ID: {tag_id}")

    # Fetch random item based on mode and validated tag_id
    if mode == 'concept':
        concept_id = get_random_concept_id(tag_id=tag_id)
        if concept_id:
            try:
                item_data = get_concept_details(concept_id)
                if item_data is None:
                     raise ValueError(f"get_concept_details returned None for ID {concept_id}")
            except Exception as e:
                flash(f"加载随机单词详情时出错: {e}", "danger")
                current_app.logger.error(f"Wander: Error loading concept details for ID {concept_id}: {e}", exc_info=True)
                return redirect(url_for('.setup')) # Redirect to setup on error
        else:
             flash(f"在 " + (f"标签 '{tag_name}' 下" if tag_name else "词库中") + " 没有找到单词。", "warning")
             return redirect(url_for('.setup'))

    elif mode == 'collocation':
        item_data = get_random_collocation_with_concept(tag_id=tag_id)
        if item_data is None:
            flash(f"在 " + (f"标签 '{tag_name}' 下" if tag_name else "词库中") + " 没有找到固定搭配。", "warning")
            return redirect(url_for('.setup'))

    else:
        flash("无效的漫游模式。", "danger")
        return redirect(url_for('.setup'))

    # If item_data was successfully fetched
    current_app.logger.info(f"Wander Mode: Displaying random {mode} (Tag: {tag_name or 'All'}). Item: {item_data.get('term') or item_data.get('phrase')}")
    return render_template('wander_display.html',
                           item=item_data,
                           mode=mode,
                           tag_id=tag_id, # Pass tag_id for the 'Next' button
                           tag_name=tag_name # Pass tag_name for display
                           )

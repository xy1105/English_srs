# app/main_routes.py
from flask import (
    Blueprint, flash, g, redirect, render_template, request, url_for, current_app, jsonify
)
from .db import get_db
from .srs import count_due_concepts, get_mastery_levels
from .practice_routes import count_high_error_concepts, SESSION_QUEUE_KEY as PRACTICE_SESSION_QUEUE_KEY # Import practice session key
from .test_routes import TEST_QUEUE as TEST_SESSION_QUEUE_KEY, TEST_LIST_CONCEPTS as TEST_SESSION_LIST_KEY # Import test session keys
from .utils import count_total_collocations
import sqlite3
from flask import session # Import session

bp = Blueprint('main', __name__)

@bp.route('/')
def index():
    """主页/仪表盘"""
    db = get_db()
    total_concepts = 0
    due_count = 0
    high_error_count = 0
    mastery_levels = {'New': 0, 'Learning': 0, 'Young': 0, 'Mature': 0} # Default values
    total_collocations = 0 # Initialize
    session_active_type = None # To indicate if a practice or test session is ongoing

    try:
        # Get total concepts count
        total_concepts_row = db.execute('SELECT COUNT(id) FROM concepts').fetchone()
        total_concepts = total_concepts_row[0] if total_concepts_row else 0

        # Get other stats using dedicated functions
        due_count = count_due_concepts()
        # CORRECTED: Use threshold=1 to match the wrong_list page default
        high_error_count = count_high_error_concepts(threshold=1)
        mastery_levels = get_mastery_levels()
        total_collocations = count_total_collocations() # Use function from utils

        # Check for active sessions using constants imported from routes
        if PRACTICE_SESSION_QUEUE_KEY in session:
            session_active_type = 'practice'
        elif TEST_SESSION_QUEUE_KEY in session or TEST_SESSION_LIST_KEY in session:
             # Check both list and queue keys for test mode 3 and 1/2 respectively
            session_active_type = 'test'

        current_app.logger.info(f"Dashboard stats: TotalConcepts={total_concepts}, Due={due_count}, HighError(>=1)={high_error_count}, Collocations={total_collocations}, Mastery={mastery_levels}, ActiveSession={session_active_type}")

    except (sqlite3.Error, TypeError) as e:
        current_app.logger.error(f"Error fetching dashboard stats: {e}", exc_info=True)
        flash("无法加载仪表盘统计数据。", "danger")
        # Ensure defaults are used if error occurs
        mastery_levels = {'New': 0, 'Learning': 0, 'Young': 0, 'Mature': 0}
        total_collocations = 0
        high_error_count = 0 # Reset count on error
        session_active_type = None # Assume no active session on error

    return render_template(
        'index.html',
        total_concepts=total_concepts,
        due_count=due_count,
        high_error_count=high_error_count,
        mastery_levels=mastery_levels,
        total_collocations=total_collocations,
        session_active_type=session_active_type
    )

# API endpoint for chart data
@bp.route('/api/mastery-data')
def mastery_data_api():
    """Provides mastery level data for charts."""
    try:
        levels = get_mastery_levels()
        if not levels: # Handle case where get_mastery_levels might return None or empty on error
            current_app.logger.warning("get_mastery_levels returned empty or None, providing default chart data.")
            levels = {'New': 0, 'Learning': 0, 'Young': 0, 'Mature': 0}

        # Prepare data in a format Chart.js understands
        labels = ['New', 'Learning', 'Young', 'Mature']
        data_values = [levels.get(label, 0) for label in labels]

        chart_data = {
            'labels': labels,
            'datasets': [{
                'label': '单词掌握程度',
                'data': data_values,
                'backgroundColor': [ # Consistent colors
                    'rgba(220, 53, 69, 0.7)',  # New (Red) - Bootstrap Danger
                    'rgba(255, 193, 7, 0.7)', # Learning (Yellow) - Bootstrap Warning
                    'rgba(25, 135, 84, 0.7)', # Young (Green) - Bootstrap Success
                    'rgba(13, 110, 253, 0.7)', # Mature (Blue) - Bootstrap Primary
                ],
                'borderColor': [
                    'rgba(220, 53, 69, 1)',
                    'rgba(255, 193, 7, 1)',
                    'rgba(25, 135, 84, 1)',
                    'rgba(13, 110, 253, 1)',
                ],
                'borderWidth': 1
            }]
        }
        return jsonify(chart_data)
    except Exception as e:
         current_app.logger.error(f"Error generating mastery data API: {e}", exc_info=True)
         return jsonify({"error": "无法获取掌握程度数据"}), 500
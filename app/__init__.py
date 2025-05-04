# app/__init__.py
import os
from flask import Flask, render_template, request, session, g # <--- IMPORT g HERE
from . import db
from . import utils # Ensure utils is imported
import logging
from logging.handlers import RotatingFileHandler
import sys # Import sys for console encoding check
from datetime import datetime, timedelta, timezone

# Import utility functions needed in context processors or globally
from .utils import (format_datetime_local, format_due_date_relative,
                    parse_datetime_utc, classify_mastery, now_utc)

# Import route blueprints to access their session keys in before_request
from . import practice_routes
from . import test_routes


def create_app(test_config=None):
    """应用工厂函数"""
    app = Flask(__name__, instance_relative_config=True)

    # --- Configuration ---
    app.config.from_mapping(
        SECRET_KEY='dev', # !! CHANGE THIS IN PRODUCTION !!
        DATABASE=os.path.join(app.instance_path, 'english_srs.sqlite'),
        # Log configuration
        LOG_FILE=os.path.join(app.instance_path, 'app.log'),
        LOG_LEVEL=logging.DEBUG if os.environ.get('FLASK_DEBUG') == '1' else logging.INFO,
        LOG_MAX_BYTES=1024 * 1024 * 5, # 5 MB
        LOG_BACKUP_COUNT=3,
        # Session configuration (consider alternatives like Flask-Session for production)
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax', # Good default for security
        # PERMANENT_SESSION_LIFETIME = timedelta(days=7) # Example: make session persistent
    )

    if test_config is None:
        # Load the instance config, if it exists, when not testing
        app.config.from_pyfile('config.py', silent=True)
        # Load environment variables (e.g., from .flaskenv or system)
        app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', app.config['SECRET_KEY'])
        # Optionally load other env vars here
    else:
        # Load the test config if passed in
        app.config.from_mapping(test_config)

    # --- Ensure instance folder exists ---
    try:
        os.makedirs(app.instance_path, exist_ok=True) # exist_ok=True prevents error if exists
    except OSError as e:
         app.logger.error(f"CRITICAL: Could not create instance folder at {app.instance_path}: {e}")
         raise # Raise error if instance folder is needed and cannot be created

    # --- Logging Setup ---
    log_format = '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
    log_level = app.config['LOG_LEVEL']
    formatter = logging.Formatter(log_format)
    stream_handler_exists = any(isinstance(h, logging.StreamHandler) for h in app.logger.handlers)

    # Always add stream handler (console)
    if not stream_handler_exists:
        stream_handler = logging.StreamHandler(sys.stderr)
        try:
             if hasattr(stream_handler.stream, 'reconfigure'): # Python 3.7+
                 try: stream_handler.stream.reconfigure(encoding='utf-8')
                 except Exception: pass
             elif hasattr(stream_handler, 'setEncoding'): # Older method
                 try: stream_handler.setEncoding('utf-8')
                 except Exception: pass
        except Exception as e:
             app.logger.warning(f"Could not set UTF-8 encoding for console handler: {e}")

        stream_handler.setFormatter(formatter)
        stream_handler.setLevel(log_level)
        app.logger.addHandler(stream_handler)

    # Add file handler only if not in debug/testing and LOG_FILE is set
    if not app.debug and not app.testing and app.config.get('LOG_FILE'):
        try:
            file_handler = RotatingFileHandler(
                app.config['LOG_FILE'],
                maxBytes=app.config['LOG_MAX_BYTES'],
                backupCount=app.config['LOG_BACKUP_COUNT'],
                encoding='utf-8'
            )
            file_handler.setFormatter(formatter)
            file_handler.setLevel(log_level)
            app.logger.addHandler(file_handler)
            app.logger.info(f"Logging to file: {app.config['LOG_FILE']}")
        except Exception as e:
             app.logger.error(f"Failed to set up file logger at {app.config['LOG_FILE']}: {e}")

    # Set the overall level for the Flask logger
    app.logger.setLevel(log_level)
    app.logger.info(f"Application starting up. Log level: {logging.getLevelName(log_level)}")

    # --- Initialize Extensions ---
    db.init_app(app)
    # e.g., Session(app)

    # --- Register Blueprints ---
    # Need to import blueprints *after* app is created if they use app context,
    # but they are already imported above for accessing session keys. This is okay.
    from . import main_routes
    app.register_blueprint(main_routes.bp)
    from . import concept_routes
    app.register_blueprint(concept_routes.bp, url_prefix='/concepts')
    # Note: practice_routes and test_routes already imported at top
    app.register_blueprint(practice_routes.bp, url_prefix='/practice')
    app.register_blueprint(test_routes.bp, url_prefix='/test')
    from . import wander_routes
    app.register_blueprint(wander_routes.bp, url_prefix='/wander')
    from . import history_routes # Register new history blueprint
    app.register_blueprint(history_routes.bp) # Using url_prefix='/history' set in blueprint file
    app.logger.info("Registered all blueprints.")

    # --- Context Processors ---
    @app.context_processor
    def inject_utilities():
        # Pass utility functions to all templates
        return dict(
            classify_mastery=classify_mastery,
            format_datetime_local=format_datetime_local,
            format_due_date_relative=format_due_date_relative,
            parse_datetime_utc=parse_datetime_utc,
            now_utc=now_utc,
            timedelta=timedelta
        )
    app.logger.info("Registered context processors.")

    # --- Request Hooks ---
    @app.before_request
    def check_active_session():
        """Check for active sessions and store type in g"""
        # Check if g exists for the current request context
        if g:
             g.active_session_type = None # Initialize on g
             # Use imported blueprint modules to access session key constants safely
             if practice_routes.SESSION_QUEUE_KEY in session:
                 g.active_session_type = 'practice'
             # Check both list and queue keys for test mode 3 and 1/2 respectively
             elif test_routes.TEST_LIST_CONCEPTS in session or test_routes.TEST_QUEUE in session:
                  g.active_session_type = 'test'
        else:
            # This case should generally not happen during a normal request lifecycle
            # where before_request is called, but good to log if it does.
            app.logger.warning("Flask 'g' object not available in before_request hook.")


    # --- Error Handlers ---
    @app.errorhandler(404)
    def page_not_found(e):
        app.logger.warning(f"404 Not Found: {request.url} (Referrer: {request.referrer})", exc_info=e)
        return render_template('404.html', error=e), 404

    @app.errorhandler(500)
    def internal_server_error(e):
        original_exception = getattr(e, 'original_exception', e)
        app.logger.error(f"500 Internal Server Error: {original_exception} for URL {request.url}", exc_info=True)
        return render_template('500.html', error=e), 500

    @app.errorhandler(Exception) # Catch other unexpected errors
    def handle_exception(e):
        app.logger.error(f"Unhandled Exception: {e} for URL {request.url}", exc_info=True)
        # Optionally rollback database session if using SQLAlchemy or similar
        # db.session.rollback()
        return render_template('500.html', error="发生了意外错误"), 500

    app.logger.info("Flask application instance created successfully.")
    return app
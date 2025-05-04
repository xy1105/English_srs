import sqlite3
import click
from flask import current_app, g
from flask.cli import with_appcontext
import os

DATABASE_CONFIG_KEY = 'DATABASE'

def get_db():
    """获取当前请求的数据库连接。如果不存在，则创建新连接。"""
    if 'db' not in g:
        db_path = current_app.config[DATABASE_CONFIG_KEY]
        # 确保 instance 文件夹存在
        instance_path = current_app.instance_path
        if not os.path.exists(instance_path):
            try:
                os.makedirs(instance_path)
                current_app.logger.info(f"Created instance folder at {instance_path}")
            except OSError as e:
                current_app.logger.error(f"Error creating instance folder: {e}")
                raise # Rethrow the exception if folder creation fails

        current_app.logger.debug(f"Connecting to database at: {db_path}")
        try:
            g.db = sqlite3.connect(
                db_path,
                detect_types=sqlite3.PARSE_DECLTYPES
            )
            # Enable Foreign Key support if not enabled by default (recommended)
            g.db.execute("PRAGMA foreign_keys = ON;")
            g.db.row_factory = sqlite3.Row # 让查询结果可以像字典一样访问列
            current_app.logger.debug("Database connection established (Foreign Keys ON).")
        except sqlite3.Error as e:
            current_app.logger.error(f"Database connection error: {e}")
            raise # Propagate the error

    return g.db

def close_db(e=None):
    """关闭数据库连接。"""
    db = g.pop('db', None)
    if db is not None:
        db.close()
        current_app.logger.debug("Database connection closed.")

def init_db():
    """初始化数据库：读取 schema.sql 文件并执行。"""
    db = get_db()
    # Correct path assuming db.py is in the app package root
    schema_path = os.path.join(os.path.dirname(__file__), 'schema.sql')
    current_app.logger.info(f"Initializing database schema from: {schema_path}")
    try:
        # Correct way to open resource relative to the application's root path
        # or relative to the blueprint if using app_context.
        # Since db.py is likely at the app level, open_resource might need schema path relative to app root.
        # Let's assume schema.sql is next to db.py for simplicity here.
        # Using current_app.open_resource assumes schema.sql is in the application package root (where __init__.py is)
        # Or we use the constructed path directly
        # with current_app.open_resource('schema.sql') as f: # If schema.sql is at app root level
        with open(schema_path, 'r', encoding='utf-8') as f: # Use direct path if schema.sql is next to db.py
            schema_script = f.read()
            # Execute script potentially containing multiple statements
            db.executescript(schema_script)
        current_app.logger.info("Database schema initialized successfully.")
    except FileNotFoundError:
         current_app.logger.error(f"Schema file not found at {schema_path}")
         raise # Re-raise to make the command fail clearly
    except sqlite3.Error as e:
        current_app.logger.error(f"Error initializing database schema: {e}")
        raise

@click.command('init-db')
@with_appcontext
def init_db_command():
    """CLI 命令：flask init-db，用于清空并创建新的数据库表。"""
    click.echo("WARNING: This will delete existing data and reinitialize the database.")
    if click.confirm("Do you want to continue?"):
        click.echo("Initializing the database...")
        try:
            init_db()
            click.echo("Database initialized.")
        except Exception as e:
            click.echo(f"Failed to initialize database: {e}", err=True)
            current_app.logger.error(f"Exception during init-db: {e}", exc_info=True) # Log full traceback
    else:
        click.echo("Database initialization cancelled.")


def init_app(app):
    """在 Flask 应用实例上注册数据库相关的函数。"""
    # 确保 instance 文件夹路径配置正确
    if not app.config.get(DATABASE_CONFIG_KEY):
         # 默认数据库路径设置在 instance 文件夹下
        app.config[DATABASE_CONFIG_KEY] = os.path.join(app.instance_path, 'english_srs.sqlite')
        app.logger.info(f"Database path set to default: {app.config[DATABASE_CONFIG_KEY]}")
    else:
         app.logger.info(f"Database path loaded from config: {app.config[DATABASE_CONFIG_KEY]}")

    # 注册 teardown 函数，在每个请求结束后关闭数据库连接
    app.teardown_appcontext(close_db)
    # 添加 init-db 命令到 flask 命令组
    app.cli.add_command(init_db_command)
    app.logger.info("Database functions registered with the app.")
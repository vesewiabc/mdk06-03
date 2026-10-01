"""Flask-расширения, инициализируются в create_app()."""
from flask_wtf.csrf import CSRFProtect

csrf = CSRFProtect()
from replyradar.api.app import app
from replyradar.config import get_settings
from replyradar.logging import configure_logging

configure_logging(get_settings().log)

__all__ = ["app"]

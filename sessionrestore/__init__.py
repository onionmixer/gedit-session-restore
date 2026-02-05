import os
import gettext

import gi
gi.require_version("Gedit", "3.0")
gi.require_version("Gtk", "3.0")

_locale_dir = os.path.join(os.path.dirname(__file__), "locale")
try:
    _translations = gettext.translation("sessionrestore", _locale_dir)
    _ = _translations.gettext
except FileNotFoundError:
    _ = lambda s: s

from .appactivatable import SessionRestoreAppActivatable
from .windowactivatable import SessionRestoreWindowActivatable

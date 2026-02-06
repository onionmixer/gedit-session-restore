# Session Restore — gedit Plugin

Save and restore all open tabs (including unsaved text) across gedit sessions.

## Features

| Feature | Description |
|---------|-------------|
| Saved file tab restore | Reopen files by URI with cursor position |
| **Unsaved text preserve** | Save the actual text content of untitled tabs to a temp directory and restore on next launch |
| Tab order restore | Tabs are restored in the same order |
| Modified file preserve | Optionally save unsaved modifications of already-saved files (off by default) |
| Per-tab idle snapshot | Optionally auto-snapshot each tab after idle timeout for crash recovery (off by default) |
| Multi-window support | All windows' tabs are merged into a single session |
| i18n | English (default) + Korean |

## Comparison with gedit-restore-tabs

| Feature | gedit-restore-tabs | **Session Restore** |
|---------|-------------------|---------------------|
| Saved file tab restore | URI only | URI + cursor position |
| Unsaved text preserve | **No** | **Yes** |
| Tab order restore | No | Yes |
| Modified file preserve | No | Yes (optional) |
| Per-tab idle snapshot | No | Yes (optional) |
| Multi-window support | No | Yes |
| i18n | No | Yes (en, ko) |

## Requirements

- gedit 41+ (API 3.0, python3 loader)
- Python 3

## Installation

```bash
# Clone the repository
git clone https://github.com/onionmixer/gedit-session-restore.git
cd gedit-session-restore

# Create the plugin directory if it doesn't exist
mkdir -p ~/.local/share/gedit/plugins

# Create symlinks
ln -sf "$(pwd)/sessionrestore.plugin" ~/.local/share/gedit/plugins/sessionrestore.plugin
ln -sf "$(pwd)/sessionrestore"        ~/.local/share/gedit/plugins/sessionrestore
```

Then open gedit, go to **Preferences > Plugins**, and enable **Session Restore**.

### Uninstall

```bash
rm ~/.local/share/gedit/plugins/sessionrestore.plugin
rm ~/.local/share/gedit/plugins/sessionrestore
rm -rf ~/.config/gedit/tmp   # Remove session data (optional)
```

## Settings

Open the plugin preferences dialog from **Preferences > Plugins > Session Restore > Preferences**.

| Setting | Default | Description |
|---------|---------|-------------|
| Preserve unsaved modifications of saved files | OFF | When ON, saves modified content of already-saved files to temp storage |
| Per-tab auto snapshot (crash recovery) | OFF | When ON, snapshots each tab after an idle period |
| Idle time before saving | 2.0 sec | How long to wait after last keystroke before auto-snapshot (0.5–10 sec) |

Settings are stored in `~/.config/gedit/tmp/sessionrestore_settings.json`.

## How It Works

### Session Save

The session is saved automatically on every meaningful change:

| Event | Save behavior |
|-------|---------------|
| Tab added | Immediate save |
| Tab removed / active tab changed | Debounced save (500ms) |
| Text changed | Debounced save (500ms) |
| Window close (`delete-event`) | Immediate save |

Session data is stored in:
```
~/.config/gedit/tmp/
├── session.json          # Tab metadata (URIs, cursor positions, types)
└── unsaved/              # Actual text content of unsaved tabs
    ├── tab_0001.txt
    └── ...
```

### Session Restore

On startup, the plugin restores the previous session:

1. Loads `session.json`
2. Restores each tab by type:
   - `file` — opens via `create_tab_from_location()`
   - `unsaved` — creates a blank tab and inserts saved text
   - `file_modified` — opens the file, waits for async load, then replaces content
3. Removes the default empty tab
4. Restores active tab and cursor positions
5. Waits a 2-second settle period before allowing new saves

### Tab Types

| Type | Condition | What is saved |
|------|-----------|---------------|
| `file` | Saved file, no modifications | URI + cursor position |
| `unsaved` | Never saved to disk (non-empty) | Full text content + cursor position |
| `file_modified` | Saved file with unsaved edits (`preserve_modifications=ON`) | URI + full text content + cursor position |

### Safety Mechanisms

- **Atomic writes**: Session and settings files are written via tmp + `os.replace()` to prevent corruption
- **Restore fallback**: If the window `show` signal is missed, an idle callback ensures restore still runs
- **Close protection**: A `_closing` flag prevents tab-removal signals from overwriting the session during shutdown
- **Session preservation**: If restore was never attempted (e.g., plugin load failure), the previous session is not overwritten on close
- **Size limit**: Unsaved text larger than 5 MB is skipped to prevent excessive disk/memory usage

## Internationalization (i18n)

The plugin UI supports multiple languages via `gettext`.

- **English**: default (source strings)
- **Korean (ko)**: included translation

Translations are in `sessionrestore/locale/<lang>/LC_MESSAGES/sessionrestore.po`.

### Adding a New Language

```bash
mkdir -p sessionrestore/locale/<lang>/LC_MESSAGES
# Create .po file (use ko/LC_MESSAGES/sessionrestore.po as template), then compile:
msgfmt sessionrestore/locale/<lang>/LC_MESSAGES/sessionrestore.po \
    -o sessionrestore/locale/<lang>/LC_MESSAGES/sessionrestore.mo
```

## File Structure

```
gedit-session-restore/
├── sessionrestore.plugin          # Plugin metadata (i18n: en, ko)
├── sessionrestore/
│   ├── __init__.py                # gettext init + exports
│   ├── appactivatable.py          # App-level init + settings UI (PeasGtk.Configurable)
│   ├── windowactivatable.py       # Window-level tab tracking, save/restore
│   ├── sessionmanager.py          # Session data serialization/deserialization
│   ├── settings.py                # Plugin settings (JSON-based)
│   └── locale/
│       └── ko/LC_MESSAGES/
│           ├── sessionrestore.po  # Korean translation source
│           └── sessionrestore.mo  # Compiled translation
├── DEVPLAN_gedit_plugin_session_restore.md
├── README.md
└── LICENSE
```

## Debugging

Run gedit from a terminal to see plugin log messages:

```bash
gedit --new-window 2>&1
```

Log lines are prefixed with `[SessionRestore]`:
```
[SessionRestore] do_activate (window visible: False, restored: False)
[SessionRestore] restoring 3 tabs
[SessionRestore] restore complete (3 tabs)
[SessionRestore] session saved (3 tabs)
[SessionRestore] delete-event (restore_attempted=True)
```

## References

- [gedit-restore-tabs](https://github.com/Quartz64/gedit-restore-tabs) — Existing plugin that restores saved file tabs by URI only. Session Restore was designed to address its limitations.
- [gedit Plugin Development — Python](https://wiki.gnome.org/Apps/Gedit/PythonPluginHowTo)
- [Gedit API Reference (3.0)](https://lazka.github.io/pgi-docs/Gedit-3.0/)

## License

This project is licensed under the **GNU General Public License v3.0**. See [LICENSE](LICENSE) for details.

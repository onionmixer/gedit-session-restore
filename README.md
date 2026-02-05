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
| i18n | English (default) + Korean |

## Comparison with gedit-restore-tabs

[gedit-restore-tabs](https://github.com/Quartz64/gedit-restore-tabs) restores only saved file tabs by URI. **Session Restore** goes further by preserving the actual text content of unsaved (untitled) tabs, modified file contents, cursor positions, and tab order.

## Requirements

- gedit 41+ (API 3.0, python3 loader)
- Python 3
- `gettext` (stdlib, for i18n)

## Installation

```bash
# Clone the repository
git clone https://github.com/onionmixer/gedit-session-restore.git

# Create symlinks to the gedit plugin directory
ln -s "$(pwd)/gedit-session-restore/sessionrestore.plugin" \
      ~/.local/share/gedit/plugins/sessionrestore.plugin
ln -s "$(pwd)/gedit-session-restore/sessionrestore" \
      ~/.local/share/gedit/plugins/sessionrestore
```

Then open gedit, go to **Preferences > Plugins**, and enable **Session Restore**.

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

- **On tab add**: immediate save
- **On tab remove / active tab change**: debounced save (500ms)
- **On text change**: debounced save (500ms)
- **On window close (`delete-event`)**: immediate save
- **On Ctrl+Q**: relies on last debounced save (Ctrl+Q bypasses `delete-event` in gedit)

Session data is stored in:
```
~/.config/gedit/tmp/
├── session.json          # Tab metadata (URIs, cursor positions, types)
└── unsaved/              # Actual text content of unsaved tabs
    ├── tab_0001.txt
    ├── tab_0002.txt
    └── ...
```

### Session Restore

On startup, the plugin waits for the window `show` signal, then:

1. Loads `session.json`
2. Restores each tab by type:
   - `file` — opens via `create_tab_from_location()`
   - `unsaved` — creates a blank tab and inserts saved text
   - `file_modified` — opens the file, waits for async load, then replaces content
3. Removes the default empty tab
4. Restores active tab and cursor positions
5. Keeps a 2-second settle period to prevent post-restore signals from overwriting the session

### Tab Types

| Type | Condition | What is saved |
|------|-----------|---------------|
| `file` | Saved file, no modifications | URI + cursor position |
| `unsaved` | Never saved to disk | Full text content + cursor position |
| `file_modified` | Saved file with unsaved edits (requires `preserve_modifications=ON`) | URI + full text content + cursor position |

## Internationalization (i18n)

The plugin UI supports multiple languages via `gettext`.

- **English**: default (source strings)
- **Korean (ko)**: included translation

Translations are in `sessionrestore/locale/<lang>/LC_MESSAGES/sessionrestore.po`.

### Adding a New Language

```bash
# Create the locale directory
mkdir -p sessionrestore/locale/<lang>/LC_MESSAGES

# Create the .po file with translations (use sessionrestore.po as template)
# Then compile:
msgfmt sessionrestore/locale/<lang>/LC_MESSAGES/sessionrestore.po \
    -o sessionrestore/locale/<lang>/LC_MESSAGES/sessionrestore.mo
```

## File Structure

```
gedit-session-restore/
├── sessionrestore.plugin          # Plugin metadata
├── sessionrestore/
│   ├── __init__.py                # gettext init + exports
│   ├── appactivatable.py          # App-level init + settings UI
│   ├── windowactivatable.py       # Window-level tab tracking, save/restore
│   ├── sessionmanager.py          # Session data serialization/deserialization
│   ├── settings.py                # Plugin settings (JSON-based)
│   └── locale/
│       └── ko/
│           └── LC_MESSAGES/
│               ├── sessionrestore.po   # Korean translation source
│               └── sessionrestore.mo   # Compiled translation
├── DEVPLAN_gedit_plugin_instance_save.md
├── README.md
└── LICENSE
```

## References

- [gedit-restore-tabs](https://github.com/Quartz64/gedit-restore-tabs) — Existing gedit plugin for restoring saved file tabs (URI only). Session Restore was designed to address its limitations, particularly the lack of unsaved text preservation.
- [gedit Plugin Development — Python](https://wiki.gnome.org/Apps/Gedit/PythonPluginHowTo)
- [Gedit API Reference (3.0)](https://lazka.github.io/pgi-docs/Gedit-3.0/)

## License

This project is licensed under the **GNU General Public License v3.0**. See [LICENSE](LICENSE) for details.

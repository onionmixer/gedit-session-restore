import gi
gi.require_version("Gedit", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("PeasGtk", "1.0")

from gi.repository import GObject, Gedit, Gtk, PeasGtk

from . import _
from .settings import Settings


class SessionRestoreAppActivatable(GObject.Object, Gedit.AppActivatable,
                                   PeasGtk.Configurable):
    """앱 레벨 초기화 + 설정 UI.

    복수 윈도우 시 중복 복원 방지 플래그 관리 및
    PeasGtk.Configurable 기반 플러그인 설정 다이얼로그 제공.
    """

    __gtype_name__ = "SessionRestoreAppActivatable"
    app = GObject.Property(type=Gedit.App)

    _restored = False  # 클래스 변수: 세션 복원이 이미 수행되었는지

    def __init__(self):
        GObject.Object.__init__(self)

    def do_activate(self):
        SessionRestoreAppActivatable._restored = False

    def do_deactivate(self):
        pass

    @classmethod
    def is_restored(cls):
        return cls._restored

    @classmethod
    def mark_restored(cls):
        cls._restored = True

    # ------------------------------------------------------------------
    # PeasGtk.Configurable — 설정 다이얼로그
    # ------------------------------------------------------------------

    def do_create_configure_widget(self):
        settings = Settings()

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_border_width(12)

        # --- preserve_modifications ---
        chk_preserve = Gtk.CheckButton(
            label=_("Also preserve unsaved modifications of saved files"))
        chk_preserve.set_active(settings.get("preserve_modifications"))
        chk_preserve.connect(
            "toggled",
            lambda w: settings.set("preserve_modifications", w.get_active()))
        box.pack_start(chk_preserve, False, False, 0)

        # --- auto_snapshot_enabled ---
        chk_snapshot = Gtk.CheckButton(
            label=_("Enable per-tab auto snapshot (crash recovery)"))
        chk_snapshot.set_active(settings.get("auto_snapshot_enabled"))
        box.pack_start(chk_snapshot, False, False, 0)

        # --- auto_snapshot_idle_seconds (indented row) ---
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hbox.set_margin_start(24)

        lbl = Gtk.Label(label=_("Idle time before saving:"))
        hbox.pack_start(lbl, False, False, 0)

        adj = Gtk.Adjustment(
            value=settings.get("auto_snapshot_idle_seconds"),
            lower=0.5, upper=10.0,
            step_increment=0.5, page_increment=1.0)
        spin = Gtk.SpinButton(adjustment=adj, digits=1)
        spin.set_sensitive(settings.get("auto_snapshot_enabled"))
        spin.connect(
            "value-changed",
            lambda w: settings.set("auto_snapshot_idle_seconds", w.get_value()))
        hbox.pack_start(spin, False, False, 0)

        lbl_unit = Gtk.Label(label=_("sec"))
        hbox.pack_start(lbl_unit, False, False, 0)

        box.pack_start(hbox, False, False, 0)

        # snapshot 체크박스 토글 → spin 민감도 + 설정 저장
        def on_snapshot_toggled(widget):
            active = widget.get_active()
            settings.set("auto_snapshot_enabled", active)
            spin.set_sensitive(active)

        chk_snapshot.connect("toggled", on_snapshot_toggled)

        box.show_all()
        return box

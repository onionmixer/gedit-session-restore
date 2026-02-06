import gi
gi.require_version("Gedit", "3.0")
gi.require_version("Gtk", "3.0")

from gi.repository import GObject, GLib, Gedit, Gio, Gtk

from .sessionmanager import SessionManager
from .settings import Settings
from .appactivatable import SessionRestoreAppActivatable

# 텍스트 변경 후 세션 저장까지 대기 시간 (ms)
_DEBOUNCE_MS = 500

# 미저장 텍스트 최대 크기 (bytes). 초과 시 저장 건너뜀.
_MAX_UNSAVED_BYTES = 5 * 1024 * 1024  # 5 MB


class SessionRestoreWindowActivatable(GObject.Object, Gedit.WindowActivatable):
    """윈도우 단위 탭 추적, 세션 저장/복원."""

    __gtype_name__ = "SessionRestoreWindowActivatable"
    window = GObject.Property(type=Gedit.Window)

    def __init__(self):
        GObject.Object.__init__(self)
        self._handlers = []
        self._session = SessionManager()
        self._settings = Settings()
        self._show_handler = None
        self._debounce_id = None
        self._doc_handlers = {}  # doc → handler_id
        self._restoring = False  # 복원 중 저장 방지 플래그
        self._closing = False  # 윈도우 종료 중 플래그 (Phase 9-2)
        self._restore_attempted = False  # 복원 시도 여부 (Phase 9-3)
        self._restore_settle_id = None  # 복원 후 안정화 타이머
        self._restore_fallback_id = None  # show 미수신 fallback 타이머 (Phase 9-1)
        self._pending_modifications = {}  # tab → (handler_id, content, line, col)
        self._tab_idle_timers = {}  # doc → GLib source id (per-tab idle snapshot)

    def do_activate(self):
        print("[SessionRestore] do_activate (window visible: %s, restored: %s)"
              % (self.window.get_visible(),
                 SessionRestoreAppActivatable.is_restored()))
        self._session.ensure_dirs()

        # 아직 세션이 복원되지 않은 경우, 복원 전까지 저장을 차단한다.
        # (기본 빈 탭의 tab-added 시그널이 세션을 덮어쓰는 것을 방지)
        if not SessionRestoreAppActivatable.is_restored():
            self._restoring = True

        h = self.window.connect("tab-added", self._on_tab_added)
        self._handlers.append(h)
        h = self.window.connect("tab-removed", self._on_tab_removed)
        self._handlers.append(h)
        h = self.window.connect("active-tab-changed", self._on_tabs_changed)
        self._handlers.append(h)
        h = self.window.connect("delete-event", self._on_window_delete_event)
        self._handlers.append(h)

        self._show_handler = self.window.connect("show", self._on_window_show)

        # Phase 9-1: show 시그널 미수신 fallback
        # do_activate() 시점에 윈도우가 이미 표시된 상태이면
        # show 시그널이 다시 발생하지 않으므로 idle 콜백으로 복원을 트리거한다.
        if not SessionRestoreAppActivatable.is_restored():
            self._restore_fallback_id = GLib.idle_add(
                self._check_restore_needed)

        # 이미 열려있는 탭의 document changed 시그널 연결
        for doc in self.window.get_documents():
            self._connect_doc(doc)

    def do_deactivate(self):
        print("[SessionRestore] do_deactivate")
        self._cancel_restore_fallback()
        self._cancel_restore_settle()
        self._cancel_debounce()
        self._cancel_all_tab_idle_timers()
        for tab, (hid, _, _, _) in list(self._pending_modifications.items()):
            try:
                tab.disconnect(hid)
            except Exception:
                pass
        self._pending_modifications.clear()
        for doc, hid in list(self._doc_handlers.items()):
            try:
                doc.disconnect(hid)
            except Exception:
                pass
        self._doc_handlers.clear()
        if self._show_handler is not None:
            try:
                self.window.disconnect(self._show_handler)
            except Exception:
                pass
            self._show_handler = None
        for h in self._handlers:
            self.window.disconnect(h)
        self._handlers.clear()

    def do_update_state(self):
        pass

    # ------------------------------------------------------------------
    # document changed 시그널 관리
    # ------------------------------------------------------------------

    def _connect_doc(self, doc):
        if doc not in self._doc_handlers:
            hid = doc.connect("changed", self._on_document_changed)
            self._doc_handlers[doc] = hid

    def _disconnect_doc(self, doc):
        hid = self._doc_handlers.pop(doc, None)
        if hid is not None:
            try:
                doc.disconnect(hid)
            except Exception:
                pass
        self._cancel_tab_idle_timer(doc)

    # ------------------------------------------------------------------
    # 디바운스
    # ------------------------------------------------------------------

    def _cancel_debounce(self):
        if self._debounce_id is not None:
            GLib.source_remove(self._debounce_id)
            self._debounce_id = None

    def _cancel_restore_settle(self):
        if self._restore_settle_id is not None:
            GLib.source_remove(self._restore_settle_id)
            self._restore_settle_id = None

    def _cancel_restore_fallback(self):
        if self._restore_fallback_id is not None:
            GLib.source_remove(self._restore_fallback_id)
            self._restore_fallback_id = None

    def _schedule_save(self):
        """디바운스: 연속 이벤트를 병합하여 _DEBOUNCE_MS 후 저장."""
        self._cancel_debounce()
        self._debounce_id = GLib.timeout_add(_DEBOUNCE_MS, self._debounce_save)

    def _debounce_save(self):
        self._debounce_id = None
        self._save_session()
        return False

    # ------------------------------------------------------------------
    # 탭별 Idle 스냅샷 (auto_snapshot_enabled=ON 시)
    # ------------------------------------------------------------------

    def _cancel_tab_idle_timer(self, doc):
        timer_id = self._tab_idle_timers.pop(doc, None)
        if timer_id is not None:
            GLib.source_remove(timer_id)

    def _cancel_all_tab_idle_timers(self):
        for timer_id in self._tab_idle_timers.values():
            GLib.source_remove(timer_id)
        self._tab_idle_timers.clear()

    def _reset_tab_idle_timer(self, doc):
        """해당 문서의 idle 타이머를 리셋한다.
        idle_seconds 후 추가 입력이 없으면 세션을 저장한다.
        """
        self._cancel_tab_idle_timer(doc)
        idle_ms = int(self._settings.get("auto_snapshot_idle_seconds") * 1000)
        timer_id = GLib.timeout_add(idle_ms, self._on_tab_idle, doc)
        self._tab_idle_timers[doc] = timer_id

    def _on_tab_idle(self, doc):
        """탭 idle 시간 경과: 세션 저장 (비정상 종료 대비)."""
        self._tab_idle_timers.pop(doc, None)
        self._save_session()
        return False

    # ------------------------------------------------------------------
    # 세션 저장
    # ------------------------------------------------------------------

    def _collect_tabs_data(self):
        """모든 윈도우의 탭 정보를 수집한다.

        복수 윈도우가 열려있는 경우 모든 윈도우의 탭을 합산하여
        세션 데이터를 구성한다. 활성 탭은 현재 윈도우 기준.

        Returns:
            (tabs_data list, active_tab_index int)
        """
        tabs_data = []
        active_tab = self.window.get_active_tab()
        active_tab_index = 0
        unsaved_counter = 0

        # 모든 윈도우에서 탭 수집 (복수 윈도우 세션 보존)
        app = Gedit.App.get_default()
        all_documents = []
        for win in app.get_windows():
            all_documents.extend(win.get_documents())

        for i, doc in enumerate(all_documents):
            tab = Gedit.Tab.get_from_document(doc)
            if tab == active_tab:
                active_tab_index = i

            location = doc.get_file().get_location()

            # 커서 위치
            insert_mark = doc.get_insert()
            cursor_iter = doc.get_iter_at_mark(insert_mark)
            cursor_line = cursor_iter.get_line()
            cursor_column = cursor_iter.get_line_offset()

            # 언어 ID
            lang = doc.get_language()
            language_id = lang.get_id() if lang else None

            if location is not None:
                uri = location.get_uri()

                if doc.get_modified() and self._settings.get("preserve_modifications"):
                    text = self._extract_text(doc)
                    text_bytes = len(text.encode("utf-8", errors="replace"))
                    if text_bytes > _MAX_UNSAVED_BYTES:
                        print("[SessionRestore] file_modified tab too large (%d bytes), saving as file: %s"
                              % (text_bytes, uri))
                        tabs_data.append({
                            "type": "file",
                            "uri": uri,
                            "cursor_line": cursor_line,
                            "cursor_column": cursor_column,
                            "language_id": language_id,
                        })
                    else:
                        unsaved_counter += 1
                        tmp_file = "tab_%04d.txt" % unsaved_counter
                        self._session.save_unsaved_content(tmp_file, text)
                        tabs_data.append({
                            "type": "file_modified",
                            "uri": uri,
                            "tmp_file": tmp_file,
                            "cursor_line": cursor_line,
                            "cursor_column": cursor_column,
                            "language_id": language_id,
                        })
                else:
                    tabs_data.append({
                        "type": "file",
                        "uri": uri,
                        "cursor_line": cursor_line,
                        "cursor_column": cursor_column,
                        "language_id": language_id,
                    })
            else:
                # Phase 9-4: 빈 unsaved 탭은 세션에 포함하지 않음
                text = self._extract_text(doc)
                if not text:
                    continue
                text_bytes = len(text.encode("utf-8", errors="replace"))
                if text_bytes > _MAX_UNSAVED_BYTES:
                    print("[SessionRestore] unsaved tab too large (%d bytes), skipping: %s"
                          % (text_bytes, doc.get_short_name_for_display()))
                    continue
                unsaved_counter += 1
                tmp_file = "tab_%04d.txt" % unsaved_counter
                self._session.save_unsaved_content(tmp_file, text)
                tabs_data.append({
                    "type": "unsaved",
                    "tmp_file": tmp_file,
                    "title": doc.get_short_name_for_display(),
                    "cursor_line": cursor_line,
                    "cursor_column": cursor_column,
                    "language_id": language_id,
                })

        return tabs_data, active_tab_index

    def _extract_text(self, doc):
        """GtkTextBuffer 에서 전체 텍스트를 추출한다."""
        start = doc.get_start_iter()
        end = doc.get_end_iter()
        return doc.get_text(start, end, True)

    def _save_session(self):
        """모든 윈도우의 세션을 저장한다.
        탭이 없거나 복원 중이면 저장하지 않는다.
        """
        if self._restoring:
            return
        if self._closing:
            return
        app = Gedit.App.get_default()
        has_documents = any(win.get_documents() for win in app.get_windows())
        if not has_documents:
            return
        try:
            self._session.cleanup_unsaved()
            tabs_data, active_tab_index = self._collect_tabs_data()
            self._session.save_session(tabs_data, active_tab_index)
            print("[SessionRestore] session saved (%d tabs)" % len(tabs_data))
        except Exception as e:
            print("[SessionRestore] save error: %s" % e)

    # ------------------------------------------------------------------
    # 시그널 핸들러
    # ------------------------------------------------------------------

    def _on_tab_added(self, window, tab, data=None):
        """탭 추가 시: document changed 시그널 연결 + 즉시 세션 저장."""
        self._connect_doc(tab.get_document())
        if not self._closing:
            self._cancel_debounce()
            self._save_session()

    def _on_tab_removed(self, window, tab, data=None):
        """탭 제거 시: document changed 시그널 해제 + 디바운스 저장.
        종료 중(_closing)이면 저장을 스킵하여 delete-event의
        마지막 좋은 세이브를 보호한다.
        """
        self._disconnect_doc(tab.get_document())
        if not self._closing:
            self._schedule_save()

    def _on_tabs_changed(self, window, *args):
        """활성 탭 전환 시: 디바운스 저장.
        종료 중이면 스킵.
        """
        if not self._closing:
            self._schedule_save()

    def _on_document_changed(self, doc, data=None):
        """document 텍스트 변경 시: 디바운스 후 세션 저장.
        auto_snapshot 활성화 시 탭별 idle 타이머도 관리한다.
        종료 중이면 스킵.
        """
        if self._closing:
            return
        self._schedule_save()
        if self._settings.get("auto_snapshot_enabled"):
            self._reset_tab_idle_timer(doc)

    def _on_window_delete_event(self, window, event, data=None):
        """윈도우 닫기 직전: 즉시 세션 저장.

        Phase 9-2: _closing 플래그로 이후 tab-removed 등의 디바운스 저장을 차단.
        Phase 9-3: 복원이 시도된 적 없으면 이전 세션을 보호한다.
        """
        print("[SessionRestore] delete-event (restore_attempted=%s)"
              % self._restore_attempted)
        self._cancel_restore_fallback()
        self._cancel_restore_settle()
        self._cancel_debounce()
        self._cancel_all_tab_idle_timers()

        if self._restore_attempted:
            # 정상 흐름: 복원이 시도된 후이므로 현재 상태를 저장한다.
            self._restoring = False
            self._save_session()
        else:
            # 복원이 시도되지 않음 — 이전 세션을 덮어쓰지 않는다.
            print("[SessionRestore] restore never attempted, preserving existing session")

        # _closing을 save 이후에 설정하여 위의 _save_session()은 정상 실행되고,
        # 이후 tab-removed 등의 디바운스 저장은 차단된다.
        self._closing = True
        return False

    def _on_window_show(self, window, data=None):
        """최초 윈도우 표시: 첫 번째 윈도우인 경우만 세션 복원."""
        if self._show_handler is not None:
            self.window.disconnect(self._show_handler)
            self._show_handler = None

        if SessionRestoreAppActivatable.is_restored():
            # 다른 윈도우가 이미 복원 완료 — 이 윈도우는 저장 허용
            self._restoring = False
            self._cancel_restore_fallback()
            return

        SessionRestoreAppActivatable.mark_restored()
        self._cancel_restore_fallback()
        # _restoring은 do_activate에서 이미 True 설정됨.
        # UI 초기화 완료 후 복원하기 위해 idle 콜백 사용.
        GLib.idle_add(self._restore_session)

    # ------------------------------------------------------------------
    # Phase 9-1: show 시그널 미수신 fallback
    # ------------------------------------------------------------------

    def _check_restore_needed(self):
        """show 시그널이 이미 발생한 경우 복원을 트리거하는 fallback.

        do_activate() 시점에 윈도우가 이미 표시(visible)된 상태이면
        show 시그널이 다시 발생하지 않으므로, idle 콜백에서 복원을 시도한다.
        """
        self._restore_fallback_id = None

        # 이미 복원 완료됨 (show 핸들러가 먼저 실행된 경우)
        if SessionRestoreAppActivatable.is_restored():
            self._restoring = False
            return False

        # show 핸들러가 아직 실행되지 않음 — 직접 복원 트리거
        print("[SessionRestore] restore fallback triggered"
              " (show signal was missed)")

        if self._show_handler is not None:
            try:
                self.window.disconnect(self._show_handler)
            except Exception:
                pass
            self._show_handler = None

        SessionRestoreAppActivatable.mark_restored()
        self._restore_session()
        return False  # idle 1회 실행

    # ------------------------------------------------------------------
    # 세션 복원
    # ------------------------------------------------------------------

    def _restore_session(self):
        """session.json 에서 탭을 복원한다.
        GLib.idle_add 콜백으로도 사용되므로 False 를 반환한다.
        """
        self._restore_attempted = True

        session = self._session.load_session()
        if not session:
            print("[SessionRestore] no session to restore")
            self._restoring = False
            return False

        tabs = session.get("tabs", [])
        if not tabs:
            self._restoring = False
            return False

        print("[SessionRestore] restoring %d tabs" % len(tabs))

        try:
            # gedit 기본 빈 탭 기억 (나중에 제거)
            default_tab = self._get_default_empty_tab()

            restored_tabs = []
            for tab_data in tabs:
                tab = self._restore_tab(tab_data)
                if tab is not None:
                    restored_tabs.append((tab, tab_data))

            # 기본 빈 탭 제거
            if default_tab is not None and restored_tabs:
                self.window.close_tab(default_tab)

            # 활성 탭 복원
            active_index = session.get("active_tab_index", 0)
            if 0 <= active_index < len(restored_tabs):
                self.window.set_active_tab(restored_tabs[active_index][0])

            # 복원된 탭들의 document changed 시그널 연결
            for tab, _ in restored_tabs:
                self._connect_doc(tab.get_document())

            print("[SessionRestore] restore complete (%d tabs)" % len(restored_tabs))
        except Exception as e:
            print("[SessionRestore] restore error: %s" % e)
            self._restoring = False
            return False

        # 복원 직후 스케줄된 디바운스 취소 (비동기 로딩 중 저장 방지)
        self._cancel_debounce()
        # _restoring = True 를 유지한 채 안정화 대기 (2초)
        # 비동기 파일 로딩이 완료된 후 깨끗한 세션 저장을 수행한다.
        self._restore_settle_id = GLib.timeout_add(2000, self._on_restore_settled)

        return False  # idle_add 1회 실행

    def _on_restore_settled(self):
        """복원 후 안정화 완료: _restoring 해제하고 세션을 깨끗하게 저장."""
        self._restore_settle_id = None
        self._restoring = False
        self._cancel_debounce()
        self._save_session()
        return False

    def _get_default_empty_tab(self):
        """gedit 시작 시 자동 생성된 빈 탭을 찾는다.
        문서가 1개, 위치 없음, 수정 없음, 텍스트 비어있음이면 기본 탭.
        """
        docs = self.window.get_documents()
        if len(docs) != 1:
            return None
        doc = docs[0]
        if doc.get_file().get_location() is not None:
            return None
        if doc.get_modified():
            return None
        text = self._extract_text(doc)
        if text:
            return None
        return Gedit.Tab.get_from_document(doc)

    def _restore_tab(self, tab_data):
        """tab_data 딕셔너리로부터 하나의 탭을 복원한다.

        Returns:
            복원된 Gedit.Tab 또는 실패 시 None.
        """
        tab_type = tab_data.get("type")

        if tab_type == "file":
            return self._restore_file_tab(tab_data)
        elif tab_type == "file_modified":
            return self._restore_file_modified_tab(tab_data)
        elif tab_type == "unsaved":
            return self._restore_unsaved_tab(tab_data)
        return None

    def _restore_file_tab(self, tab_data):
        """정식 파일 탭 복원: URI로 파일을 연다."""
        uri = tab_data.get("uri")
        if not uri:
            return None

        location = Gio.file_new_for_uri(uri)
        if not location.query_exists():
            print("[SessionRestore] file not found, skipping: %s" % uri)
            return None

        line = tab_data.get("cursor_line", 0)
        column = tab_data.get("cursor_column", 0)

        tab = self.window.create_tab_from_location(
            location, None, line + 1, column + 1, False, True
        )
        return tab

    def _restore_file_modified_tab(self, tab_data):
        """수정된 파일 탭 복원: 파일을 열고 로딩 완료 후 수정 내용을 덮어쓴다."""
        tab = self._restore_file_tab(tab_data)
        if tab is None:
            return None

        tmp_file = tab_data.get("tmp_file")
        if not tmp_file:
            return tab

        content = self._session.load_unsaved_content(tmp_file)
        if content is None:
            return tab

        line = tab_data.get("cursor_line", 0)
        column = tab_data.get("cursor_column", 0)

        # 이미 로딩 완료된 경우 즉시 적용
        if tab.get_state() == Gedit.TabState.STATE_NORMAL:
            self._apply_modified_content(tab, content, line, column)
        else:
            # 로딩 완료 대기
            hid = tab.connect("notify::state", self._on_file_loaded_for_modify)
            self._pending_modifications[tab] = (hid, content, line, column)

        return tab

    def _on_file_loaded_for_modify(self, tab, pspec):
        """파일 로딩 완료 시 수정 텍스트 적용."""
        if tab.get_state() != Gedit.TabState.STATE_NORMAL:
            return

        entry = self._pending_modifications.pop(tab, None)
        if entry is None:
            return

        hid, content, line, column = entry
        tab.disconnect(hid)
        self._apply_modified_content(tab, content, line, column)

    def _apply_modified_content(self, tab, content, line=0, column=0):
        """탭의 문서 텍스트를 수정된 내용으로 교체."""
        doc = tab.get_document()
        doc.begin_user_action()
        doc.set_text(content, -1)
        doc.end_user_action()

        try:
            it = doc.get_iter_at_line_offset(line, column)
            doc.place_cursor(it)
        except Exception:
            pass

        # 원본 파일과 다르므로 modified 플래그 설정
        doc.set_modified(True)

    def _restore_unsaved_tab(self, tab_data):
        """미저장 텍스트 탭 복원: 빈 탭 생성 후 텍스트 삽입."""
        tmp_file = tab_data.get("tmp_file")
        if not tmp_file:
            return None

        content = self._session.load_unsaved_content(tmp_file)
        if content is None:
            return None

        tab = self.window.create_tab(True)
        doc = tab.get_document()

        doc.begin_user_action()
        doc.set_text(content, -1)
        doc.end_user_action()

        # 커서 위치 복원
        line = tab_data.get("cursor_line", 0)
        column = tab_data.get("cursor_column", 0)
        try:
            it = doc.get_iter_at_line_offset(line, column)
            doc.place_cursor(it)
        except Exception:
            pass

        # 복원 직후 modified 플래그 해제 (사용자가 수정한 것이 아니므로)
        doc.set_modified(False)

        return tab

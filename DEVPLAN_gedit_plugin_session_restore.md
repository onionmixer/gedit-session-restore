# DEVPLAN: gedit Session Restore Plugin

## 1. 프로젝트 개요

**플러그인명**: Session Restore
**목적**: gedit 종료 시 열려 있던 모든 탭의 상태를 보존하고, 재시작 시 동일한 상태로 복원한다.
**gedit 버전**: 41.0 (Gedit API 3.0, Loader=python3)
**기본 저장 디렉터리**: `~/.config/gedit/tmp/`
**리포지토리**: https://github.com/onionmixer/gedit-session-restore

### 핵심 동작 원칙

> **이 플러그인은 "파일을 자동 저장(auto-save to disk)" 하는 기능이 아니다.**
>
> - **미저장 텍스트** (파일로 저장한 적 없는 탭) → 텍스트 내용을 tmp에 보존/복원 **(핵심 기능)**
> - **이미 저장된 파일** → URI만 기억하고 재시작 시 해당 파일을 reload
> - **저장된 파일의 미저장 수정 보존** → 설정으로 on/off 가능 (기본 OFF)
> - **탭별 Idle 스냅샷** (입력 후 일정 시간 멈추면 해당 탭만 저장) → 설정으로 on/off 가능 (기본 OFF)

### 기존 플러그인과의 차별점

| 기능 | gedit-restore-tabs | **Session Restore (본 프로젝트)** |
|------|--------------------|---------------------------------|
| 저장된 파일 탭 복원 | O (URI만 저장) | O (URI + 커서 위치) |
| 미저장 텍스트 보존 | **X** | **O (텍스트 내용 자체를 저장)** |
| 탭 순서 복원 | X | O |
| 수정된 파일 내용 보존 | X | O (설정으로 on/off) |
| 탭별 Idle 스냅샷 | X | O (설정으로 on/off) |
| 다국어 지원 (i18n) | X | O (English + 한국어) |

---

## 2. 기술 아키텍처

### 2.1 파일 구조

```
gedit-session-restore/
├── sessionrestore.plugin              # 플러그인 메타데이터 (i18n: en, ko)
├── sessionrestore/                    # Python 패키지
│   ├── __init__.py                    # gettext 초기화 + AppActivatable/WindowActivatable export
│   ├── appactivatable.py             # App 레벨 (복원 플래그 관리 + PeasGtk 설정 UI)
│   ├── windowactivatable.py          # Window 레벨 (탭 추적, 세션 저장/복원)
│   ├── sessionmanager.py             # 세션 데이터 직렬화/역직렬화 로직
│   ├── settings.py                   # 플러그인 설정 관리 (JSON 파일 기반)
│   └── locale/
│       └── ko/
│           └── LC_MESSAGES/
│               ├── sessionrestore.po  # 한국어 번역 소스
│               └── sessionrestore.mo  # 컴파일된 번역
├── DEVPLAN_gedit_plugin_session_restore.md
├── README.md
└── LICENSE
```

### 2.2 저장 디렉터리 구조

```
~/.config/gedit/tmp/
├── session.json                       # 세션 메타데이터
├── sessionrestore_settings.json       # 플러그인 설정
└── unsaved/                           # 미저장 텍스트 내용 보관
    ├── tab_0001.txt
    ├── tab_0002.txt
    └── ...
```

### 2.3 session.json 스키마

```json
{
  "version": 1,
  "saved_at": "2026-02-05T19:30:00",
  "active_tab_index": 2,
  "tabs": [
    {
      "type": "file",
      "uri": "file:///home/user/document.py",
      "cursor_line": 42,
      "cursor_column": 10,
      "language_id": "python3"
    },
    {
      "type": "unsaved",
      "tmp_file": "tab_0002.txt",
      "title": "Untitled Document 3",
      "cursor_line": 1,
      "cursor_column": 0,
      "language_id": null
    },
    {
      "type": "file_modified",
      "uri": "file:///home/user/notes.txt",
      "tmp_file": "tab_0003.txt",
      "cursor_line": 15,
      "cursor_column": 5,
      "language_id": "text"
    }
  ]
}
```

**탭 유형**:
- `"file"`: 정식 파일, 수정 없음 → URI만 기록, 재시작 시 파일 reload **(항상 동작)**
- `"unsaved"`: 파일로 저장한 적 없는 새 텍스트 → 텍스트 내용을 tmp 파일에 보존 **(핵심 기능, 항상 동작)**
- `"file_modified"`: 정식 파일이지만 미저장 수정 있음 → URI + 수정된 텍스트를 tmp에 보존 **(설정 `preserve_modifications` = ON 일 때만)**
  - 설정 OFF (기본값): `is_modified()`인 파일 탭은 `type="file"`로 처리 (URI만 저장, 수정 내용 버림)

### 2.4 플러그인 설정 항목

| 설정 키 | 타입 | 기본값 | 설명 |
|---------|------|--------|------|
| `preserve_modifications` | bool | `False` | 이미 저장된 파일의 미저장 수정 내용도 tmp에 보존할지 여부 |
| `auto_snapshot_enabled` | bool | `False` | 탭별 idle 감지 스냅샷 on/off |
| `auto_snapshot_idle_seconds` | float | `2.0` | 마지막 입력 이후 스냅샷까지 대기 시간 (초) |

설정은 `~/.config/gedit/tmp/sessionrestore_settings.json` 에 JSON으로 저장한다.
(GSettings/dconf 대신 단순 JSON 파일 사용 — GSchema 등록 없이 독립 동작 가능)

### 2.5 세션 저장 트리거 및 디바운스

| 이벤트 | 저장 방식 |
|--------|----------|
| `tab-added` | 즉시 저장 |
| `tab-removed` | 디바운스 저장 (500ms) |
| `active-tab-changed` | 디바운스 저장 (500ms) |
| `document changed` (텍스트 변경) | 디바운스 저장 (500ms) |
| `delete-event` (윈도우 닫기) | 즉시 저장 (디바운스/타이머 취소 후) |

- 디바운스(`_DEBOUNCE_MS = 500`): 연속 이벤트를 병합하여 불필요한 저장 횟수를 줄임
- 미저장 텍스트 최대 크기 제한: `_MAX_UNSAVED_BYTES = 5MB` 초과 시 저장 건너뜀

### 2.6 탭별 Idle 스냅샷 동작 원리 (`auto_snapshot_enabled=ON` 시)

```
[사용자가 탭에서 텍스트 입력/삭제]
    │
    ▼
document 'changed' 시그널 발생
    │
    ▼
해당 문서의 기존 idle 타이머가 있으면 취소 (reset)
    │
    ▼
GLib.timeout_add(idle_ms, _on_tab_idle, doc)  ← 새 타이머 등록
    │
    ... idle_seconds 간 추가 입력 없음 ...
    │
    ▼
_on_tab_idle(doc) 호출 → _save_session()으로 전체 세션 저장
```

- 비정상 종료 시에도 최근 idle_seconds 이내의 입력만 손실
- `auto_snapshot_enabled=OFF` (기본값)이면 이 메커니즘 전체가 비활성화

### 2.7 복원 안정화 메커니즘

```
[세션 복원 완료]
    │
    ▼
_restoring = True 유지 (저장 차단)
    │
    ▼
GLib.timeout_add(2000ms, _on_restore_settled)
    │
    ... 2초 대기 (비동기 파일 로딩 완료) ...
    │
    ▼
_on_restore_settled() → _restoring = False, 깨끗한 세션 저장
```

- 복원 중 tab-added/document-changed 시그널로 인한 세션 덮어쓰기 방지
- 비동기 파일 로딩이 완료된 후 깨끗한 상태로 세션 저장

---

## 3. 핵심 클래스 설계 (구현 완료)

### 3.1 Settings (settings.py)

플러그인 설정 관리. JSON 파일 기반으로 GSettings 없이 독립 동작.

```python
class Settings:
    """플러그인 설정 로드/저장."""

    BASE_DIR = os.path.expanduser("~/.config/gedit/tmp")
    SETTINGS_FILE = os.path.join(BASE_DIR, "sessionrestore_settings.json")

    DEFAULTS = {
        "preserve_modifications": False,
        "auto_snapshot_enabled": False,
        "auto_snapshot_idle_seconds": 2.0,
    }

    def __init__(self)        # DEFAULTS 복사 후 load() 호출
    def load(self) -> None     # 파일에서 설정 읽기, 손상 시 기본값 유지
    def save(self) -> None     # 설정을 파일에 원자적 기록 (tmp → replace)
    def get(self, key: str)    # 설정값 반환
    def set(self, key: str, value) -> None  # 설정값 변경 후 즉시 save
```

### 3.2 SessionManager (sessionmanager.py)

세션 데이터 관리 전담 클래스. 파일 I/O와 직렬화 로직을 분리한다.

```python
class SessionManager:
    """세션 저장/로드를 담당하는 유틸리티 클래스"""

    BASE_DIR = os.path.expanduser("~/.config/gedit/tmp")
    SESSION_FILE = os.path.join(BASE_DIR, "session.json")
    UNSAVED_DIR = os.path.join(BASE_DIR, "unsaved")

    def ensure_dirs(self) -> None
        """저장 디렉터리 존재 확인 및 생성"""

    def save_session(self, tabs_data: list, active_tab_index: int) -> None
        """세션 데이터를 session.json에 원자적 기록 (tmp → os.replace)"""

    def load_session(self) -> dict | None
        """session.json 로드, 없거나 손상 시 None 반환"""

    def save_unsaved_content(self, filename: str, content: str) -> None
        """미저장 텍스트를 tmp 파일에 기록"""

    def load_unsaved_content(self, filename: str) -> str | None
        """tmp 파일에서 텍스트 읽기 (errors="replace" 인코딩 안전 처리)"""

    def cleanup_unsaved(self) -> None
        """unsaved/ 디렉터리를 삭제 후 재생성 (shutil.rmtree)"""
```

### 3.3 SessionRestoreWindowActivatable (windowactivatable.py)

gedit 윈도우 단위의 탭 추적 및 세션 저장/복원 핵심 로직.

```python
class SessionRestoreWindowActivatable(GObject.Object, Gedit.WindowActivatable):
    __gtype_name__ = "SessionRestoreWindowActivatable"
    window = GObject.Property(type=Gedit.Window)

    # === 인스턴스 변수 ===
    _handlers: list          # 윈도우 시그널 핸들러 ID 목록
    _session: SessionManager
    _settings: Settings
    _show_handler: int       # window 'show' 시그널 핸들러 (1회용)
    _debounce_id: int        # 디바운스 타이머 ID
    _doc_handlers: dict      # doc → changed 시그널 handler_id
    _restoring: bool         # 복원 중 저장 방지 플래그
    _restore_settle_id: int  # 복원 후 안정화 타이머 ID
    _pending_modifications: dict  # tab → (handler_id, content, line, col)
    _tab_idle_timers: dict   # doc → GLib source id (per-tab idle)

    # === 시그널 연결 ===
    def do_activate(self)
        """플러그인 활성화 시:
        - ensure_dirs()
        - 복원 전 _restoring = True 설정 (세션 덮어쓰기 방지)
        - window 'tab-added', 'tab-removed', 'active-tab-changed', 'delete-event' 연결
        - window 'show' 연결 (최초 표시 시 세션 복원)
        - 이미 열려있는 탭의 document changed 시그널 연결
        """

    def do_deactivate(self)
        """플러그인 비활성화 시:
        - 안정화 타이머, 디바운스 타이머, 탭별 idle 타이머 모두 취소
        - pending_modifications 시그널 해제
        - document changed 시그널 해제
        - 윈도우 시그널 핸들러 해제
        """

    # === document changed 시그널 관리 ===
    def _connect_doc(self, doc)
    def _disconnect_doc(self, doc)

    # === 디바운스 ===
    def _cancel_debounce(self)
    def _cancel_restore_settle(self)
    def _schedule_save(self)
    def _debounce_save(self)

    # === 탭별 Idle 스냅샷 ===
    def _cancel_tab_idle_timer(self, doc)
    def _cancel_all_tab_idle_timers(self)
    def _reset_tab_idle_timer(self, doc)
    def _on_tab_idle(self, doc) -> bool

    # === 세션 저장 ===
    def _collect_tabs_data(self) -> tuple[list, int]
        """모든 윈도우(Gedit.App.get_windows())의 탭 정보를 합산 수집.
        - location 없음 → type="unsaved", 텍스트 저장 (항상)
        - location 있음 + 수정 없음 → type="file", URI만 기록 (항상)
        - location 있음 + 수정 있음:
          - preserve_modifications=ON  → type="file_modified", URI + 텍스트 저장
          - preserve_modifications=OFF → type="file", URI만 기록
        - _MAX_UNSAVED_BYTES(5MB) 초과 시 unsaved는 건너뜀, file_modified는 file로 강등
        - 커서 위치(line, column), language_id 추출
        """

    def _extract_text(self, doc) -> str
    def _save_session(self) -> None
        """_restoring 중이거나 탭이 없으면 저장하지 않음."""

    # === 세션 복원 ===
    def _restore_session(self) -> bool
        """session.json에서 탭을 복원. GLib.idle_add 콜백.
        1. 기본 빈 탭 기억
        2. 각 탭 복원 (_restore_tab)
        3. 기본 빈 탭 제거
        4. 활성 탭 인덱스 복원
        5. document changed 시그널 연결
        6. 2초 안정화 타이머 시작
        """

    def _on_restore_settled(self) -> bool
    def _get_default_empty_tab(self)
    def _restore_tab(self, tab_data)
    def _restore_file_tab(self, tab_data)
        """URI로 파일 열기. 파일 부재 시 건너뛰기."""
    def _restore_file_modified_tab(self, tab_data)
        """파일 열기 후 비동기 로딩 완료 대기 → 수정 텍스트 적용."""
    def _on_file_loaded_for_modify(self, tab, pspec)
    def _apply_modified_content(self, tab, content, line, column)
    def _restore_unsaved_tab(self, tab_data)
        """빈 탭 생성 → 텍스트 삽입 → modified=False 설정."""

    # === 시그널 핸들러 ===
    def _on_tab_added(self, window, tab)       # 즉시 저장
    def _on_tab_removed(self, window, tab)     # 디바운스 저장
    def _on_tabs_changed(self, window, *args)  # 디바운스 저장
    def _on_document_changed(self, doc)        # 디바운스 저장 + auto_snapshot 타이머
    def _on_window_delete_event(self, window, event)  # 즉시 저장
    def _on_window_show(self, window)          # 첫 윈도우만 복원
```

### 3.4 SessionRestoreAppActivatable (appactivatable.py)

앱 레벨 초기화 + 설정 UI. PeasGtk.Configurable 기반 플러그인 설정 다이얼로그 제공.

```python
class SessionRestoreAppActivatable(GObject.Object, Gedit.AppActivatable,
                                   PeasGtk.Configurable):
    __gtype_name__ = "SessionRestoreAppActivatable"
    app = GObject.Property(type=Gedit.App)

    _restored = False  # 클래스 변수: 복수 윈도우 중복 복원 방지

    def do_activate(self)       # _restored = False 초기화
    def do_deactivate(self)     # pass

    @classmethod
    def is_restored(cls)        # 복원 완료 여부 확인
    @classmethod
    def mark_restored(cls)      # 복원 완료 표시

    def do_create_configure_widget(self) -> Gtk.Widget
        """설정 다이얼로그 위젯 생성:
        - preserve_modifications 체크박스 (기본 OFF)
        - auto_snapshot_enabled 체크박스 (기본 OFF)
        - auto_snapshot_idle_seconds 스핀버튼 (0.5~10초, 기본 2초)
          - auto_snapshot_enabled=ON일 때만 활성화
        """
```

---

## 4. 동작 흐름

### 4.1 세션 저장 흐름 (gedit 종료 시)

```
[사용자가 gedit 종료]
    │
    ▼
window 'delete-event' 시그널 발생
    │
    ▼
_on_window_delete_event() 호출
    ├── _restoring = False (안정화 중이라도 강제 저장)
    ├── 디바운스 타이머 취소
    ├── 탭별 idle 타이머 모두 취소
    │
    ▼
_save_session()
    ├── _restoring 체크 → False이므로 진행
    ├── 탭 존재 여부 체크 (모든 윈도우)
    │
    ▼
_collect_tabs_data()
    ├── Gedit.App.get_windows() 로 모든 윈도우의 탭 수집
    ├── 각 탭에 대해:
    │   ├── document.get_file().get_location() 확인
    │   ├── location 없음 → type="unsaved", 텍스트 저장 (5MB 제한)
    │   ├── location 있음 + 수정 없음 → type="file", URI 기록
    │   └── location 있음 + 수정 있음:
    │       ├── [preserve_modifications=ON]  → type="file_modified" (5MB 제한)
    │       └── [preserve_modifications=OFF] → type="file", URI만 기록
    │
    ▼
SessionManager.cleanup_unsaved()  ← 이전 tmp 파일 삭제 (rmtree)
SessionManager.save_session()     ← session.json 원자적 기록
SessionManager.save_unsaved_content() × N  ← 미저장 텍스트 기록
```

### 4.2 세션 저장 흐름 (실시간 — 탭 추가/제거/변경 시)

```
[탭 추가 / 탭 제거 / 활성 탭 전환 / 텍스트 변경]
    │
    ├── tab-added → _connect_doc() + 즉시 _save_session()
    ├── tab-removed → _disconnect_doc() + _schedule_save() (500ms 디바운스)
    ├── active-tab-changed → _schedule_save() (500ms 디바운스)
    └── document changed → _schedule_save() (500ms 디바운스)
                           + auto_snapshot ON이면 탭별 idle 타이머 리셋
```

### 4.3 세션 복원 흐름 (gedit 시작 시)

```
[gedit 시작]
    │
    ▼
do_activate()
    ├── _restoring = True (세션 덮어쓰기 방지)
    ├── 시그널 연결
    │
    ▼
window 'show' 시그널 발생
    │
    ▼
_on_window_show() 호출
    ├── show 핸들러 해제 (1회용)
    ├── SessionRestoreAppActivatable.is_restored() 확인
    │   ├── True → 다른 윈도우가 이미 복원 → _restoring = False, 종료
    │   └── False → mark_restored(), GLib.idle_add(_restore_session)
    │
    ▼
_restore_session() (idle 콜백)
    │
    ├── SessionManager.load_session()
    │   ├── None → 복원 없이 종료
    │
    ▼
    ├── 기본 빈 탭 기억 (_get_default_empty_tab)
    │
    ├── 각 탭 데이터에 대해 _restore_tab():
    │   ├── type="file":
    │   │   └── Gio.file_new_for_uri(uri) → query_exists() → create_tab_from_location()
    │   │
    │   ├── type="unsaved":
    │   │   ├── window.create_tab(True)
    │   │   ├── load_unsaved_content(tmp_file)
    │   │   ├── doc.set_text(content)
    │   │   └── doc.set_modified(False)
    │   │
    │   └── type="file_modified":
    │       ├── _restore_file_tab() 로 파일 열기
    │       ├── tab.get_state() == STATE_NORMAL?
    │       │   ├── Yes → 즉시 _apply_modified_content()
    │       │   └── No → tab 'notify::state' 시그널 연결 → 로딩 완료 대기
    │       └── _apply_modified_content():
    │           ├── doc.begin_user_action() / set_text() / end_user_action()
    │           ├── place_cursor(line, column)
    │           └── doc.set_modified(True)
    │
    ├── 기본 빈 탭 제거
    ├── 활성 탭 인덱스 복원
    ├── 복원된 탭의 document changed 시그널 연결
    │
    ▼
2초 안정화 대기 (_restoring = True 유지)
    │
    ▼
_on_restore_settled()
    ├── _restoring = False
    └── _save_session() (깨끗한 세션 저장)
```

---

## 5. 개발 단계

### Phase 1: 프로젝트 기반 구축 — **완료**
- [x] 디렉터리 구조 생성 (`sessionrestore/` 패키지)
- [x] `sessionrestore.plugin` 메타데이터 파일 작성 (i18n: en, ko)
- [x] `__init__.py` 에 gettext 초기화 + import/export 설정
- [x] `~/.config/gedit/tmp/` 및 `unsaved/` 디렉터리 자동 생성 로직
- [x] gedit 플러그인 목록에서 활성화 확인

### Phase 2: 세션 저장 구현 — **완료**
- [x] `SessionManager` 클래스 구현
  - [x] `ensure_dirs()`, `cleanup_unsaved()` (shutil.rmtree 기반)
  - [x] `save_session()` (원자적 쓰기: tmp → os.replace)
  - [x] `save_unsaved_content()`
- [x] `WindowActivatable._collect_tabs_data()` 구현
  - [x] 미저장 탭 텍스트 추출 (GtkTextBuffer → str)
  - [x] 파일 탭 URI 수집
  - [x] 커서 위치 (line, column) 수집
  - [x] language_id 수집
  - [x] 활성 탭 인덱스 수집
  - [x] 복수 윈도우 합산 수집 (`Gedit.App.get_windows()`)
  - [x] 대용량 텍스트 보호 (`_MAX_UNSAVED_BYTES = 5MB`)
- [x] `window delete-event` 시그널 연결 및 저장 트리거
- [x] 실시간 세션 저장 (tab-added 즉시, tab-removed/changed 디바운스 500ms)
- [x] document 'changed' 시그널 연결 → 텍스트 변경 시 디바운스 저장

### Phase 3: 세션 복원 구현 — **완료**
- [x] `SessionManager.load_session()`, `load_unsaved_content()` 구현
  - [x] JSON 파싱 실패 시 None 반환 (안전한 fallback)
  - [x] 인코딩 안전 처리 (`errors="replace"`)
- [x] `WindowActivatable._restore_session()` 구현
  - [x] `type="file"` 복원: `create_tab_from_location()` 으로 파일 reload
  - [x] `type="unsaved"` 복원: 빈 탭 생성 → 텍스트 삽입 → `modified=False`
  - [x] `type="file_modified"` 복원: 파일 열기 → 비동기 로딩 대기 → 수정 텍스트 적용
  - [x] 기본 빈 탭 ('Untitled Document') 자동 제거
  - [x] 활성 탭 및 커서 위치 복원
- [x] `window show` 시그널 연결 → `GLib.idle_add` 으로 복원 트리거
- [x] 첫 번째 윈도우 판별 (AppActivatable 클래스 변수 `_restored`)
- [x] 복원 중 저장 방지 (`_restoring` 플래그)
- [x] 복원 후 2초 안정화 대기 (`_on_restore_settled`)

### Phase 4: 플러그인 설정 UI 및 옵션 구현 — **완료**
- [x] `Settings` 클래스 구현 (JSON 파일 기반 load/save, 원자적 쓰기)
- [x] `PeasGtk.Configurable` 기반 설정 다이얼로그 UI
  - [x] `preserve_modifications` 체크박스 (기본 OFF)
  - [x] `auto_snapshot_enabled` 체크박스 (기본 OFF)
  - [x] `auto_snapshot_idle_seconds` 스핀버튼 (0.5~10초, 기본 2초)
    - `auto_snapshot_enabled=ON` 일 때만 활성화
- [x] `_collect_tabs_data()` 에 `preserve_modifications` 설정 반영
- [x] `_restore_session()` 에 `type="file_modified"` 복원 로직 구현
  - [x] 파일 열기 → `notify::state` 시그널로 비동기 로딩 완료 대기 → 수정 텍스트 덮어쓰기

### Phase 5: 탭별 Idle 스냅샷 구현 — **완료**
- [x] document 'changed' 시그널 연결 → idle 타이머 (재)등록
- [x] `GLib.timeout_add(idle_ms, ...)` 기반 탭별 개별 타이머
  - 텍스트 변경 시 기존 타이머 취소 (`GLib.source_remove`) + 새 타이머 등록
  - idle_seconds 후 추가 입력 없으면 `_save_session()` 호출
- [x] `do_deactivate()` 에서 모든 탭의 idle 타이머 정리
- [x] `auto_snapshot_enabled` 설정에 따라 동적 활성화/비활성화

### Phase 6: 다국어 지원 (i18n) — **완료**
- [x] `gettext` 기반 번역 프레임워크 (`__init__.py`)
- [x] `.plugin` 파일 Name/Description i18n (en, ko)
- [x] 설정 UI 문자열 번역
- [x] 한국어(ko) 번역: `sessionrestore/locale/ko/LC_MESSAGES/sessionrestore.po/.mo`

### Phase 7: 엣지 케이스 및 안정성 — **완료**
- [x] 파일이 삭제된 경우의 복원 처리 (`query_exists()` → 건너뛰기)
- [x] 대용량 텍스트 보호 (`_MAX_UNSAVED_BYTES = 5MB`)
- [x] session.json 파싱 실패 시 안전한 fallback (None 반환)
- [x] 인코딩 처리 (UTF-8 기본, `errors="replace"`)
- [x] 복수 gedit 윈도우 합산 세션 저장 (`Gedit.App.get_windows()`)
- [x] `file_modified` 탭 복원 시 비동기 파일 로딩 완료 대기 (`notify::state`)
- [x] 복원 중 세션 덮어쓰기 방지 (`_restoring` 플래그)
- [x] 원자적 파일 쓰기 (`.tmp` → `os.replace`)
- [x] 설정 파일 손상 시 DEFAULTS fallback

### Phase 9: 세션 저장/복원 안정성 개선 — **완료**
- [x] 9-1. 복원 트리거 이중화 (`GLib.idle_add` fallback으로 `show` 미수신 보완)
- [x] 9-2. `_closing` 플래그 추가 (종료 시 `_on_tab_removed` 디바운스 저장 차단)
- [x] 9-3. 복원 미실행 시 세션 보호 (`_restore_attempted` 플래그로 이전 세션 덮어쓰기 방지)
- [x] 9-4. 빈 unsaved 탭 필터링 (`_collect_tabs_data()`에서 빈 텍스트 탭 제외)
- [x] 9-5. 디버깅 로그 강화 (주요 분기점에 상태 로그 추가)

### Phase 8: 테스트 및 배포 — **완료**
- [ ] 수동 테스트 시나리오:
  - [ ] 미저장 텍스트만 있는 상태 → 종료 → 재시작 → 복원 확인
  - [ ] 정식 파일만 있는 상태 → 종료 → 재시작 → reload 확인
  - [ ] 파일 + 미저장 텍스트 혼합 → 종료 → 재시작 → 전체 복원 확인
  - [ ] `preserve_modifications=OFF` → 수정된 파일 탭 → 종료 → 재시작 → 파일 원본으로 reload 확인
  - [ ] `preserve_modifications=ON` → 수정된 파일 탭 → 종료 → 재시작 → 수정 내용 유지 확인
  - [ ] `auto_snapshot_enabled=ON` → 미저장 탭에 입력 → idle 대기 → `unsaved/` 파일 갱신 확인
  - [ ] `auto_snapshot_enabled=ON` → gedit 비정상 종료(kill) → 재시작 → 최근 스냅샷으로 복원 확인
  - [ ] `auto_snapshot_enabled=ON` → 빠르게 연속 입력 → 타이머 리셋 → 입력 중에는 저장 안 됨 확인
  - [ ] 설정 다이얼로그에서 옵션 토글 후 동작 변경 확인
  - [ ] 복수 윈도우 → 종료 → 재시작 → 모든 탭 복원 확인
  - [ ] 5MB 초과 미저장 텍스트 → 저장 건너뛰기 확인
- [x] 심볼릭 링크를 통한 편리한 개발 환경 구성
- [x] README.md 작성 (설치/사용법/구조/설정)
- [x] LICENSE (GPL v3.0) 포함
- [x] GitHub 릴리즈

---

## 6. 핵심 gedit API 참조

### 사용할 주요 API

| API | 용도 |
|-----|------|
| `Gedit.WindowActivatable` | 윈도우 레벨 플러그인 인터페이스 |
| `Gedit.AppActivatable` | 앱 레벨 플러그인 인터페이스 |
| `PeasGtk.Configurable` | 설정 다이얼로그 인터페이스 |
| `Gedit.App.get_default().get_windows()` | 모든 윈도우 리스트 |
| `window.get_documents()` | 모든 열린 문서 리스트 |
| `window.get_active_tab()` | 현재 활성 탭 |
| `window.create_tab(jump_to)` | 빈 새 탭 생성 |
| `window.create_tab_from_location(location, encoding, line, column, create, jump_to)` | 파일로부터 탭 생성 |
| `window.close_tab(tab)` | 탭 닫기 |
| `window.set_active_tab(tab)` | 활성 탭 설정 |
| `Gedit.Tab.get_from_document(doc)` | 문서에서 탭 가져오기 |
| `tab.get_state()` | 탭 상태 (`STATE_NORMAL` 등) |
| `tab.get_document()` | 탭에서 문서 가져오기 |
| `document.get_file().get_location()` | 문서의 Gio.File 위치 (None이면 미저장) |
| `document.is_modified()` / `set_modified()` | 수정 여부 확인/설정 |
| `document.get_language()` | 구문 강조 언어 |
| `document.get_short_name_for_display()` | 표시용 짧은 이름 |
| `Gio.file_new_for_uri(uri)` | URI → Gio.File 변환 |
| `location.query_exists()` | 파일 존재 여부 확인 |
| `GLib.idle_add()` | UI 초기화 완료 후 콜백 |
| `GLib.timeout_add()` | 지연 타이머 |
| `GLib.source_remove()` | 타이머 취소 |

### GtkTextBuffer에서 텍스트 추출

```python
doc = tab.get_document()
start_iter = doc.get_start_iter()
end_iter = doc.get_end_iter()
text = doc.get_text(start_iter, end_iter, True)  # include_hidden_chars=True
```

### 커서 위치 추출

```python
insert_mark = doc.get_insert()
cursor_iter = doc.get_iter_at_mark(insert_mark)
line = cursor_iter.get_line()
column = cursor_iter.get_line_offset()
```

---

## 7. 개발 환경 설정

### 플러그인 개발 경로

```bash
# 프로젝트 소스 디렉터리
/mnt/USERS/onion/DATA_ORIGN/Workspace/gedit_plugin_session_restore/

# gedit 플러그인 설치 위치 (심볼릭 링크로 연결)
~/.local/share/gedit/plugins/sessionrestore.plugin
~/.local/share/gedit/plugins/sessionrestore/   → 프로젝트 소스 링크

# 세션 데이터 저장 위치
~/.config/gedit/tmp/session.json
~/.config/gedit/tmp/sessionrestore_settings.json
~/.config/gedit/tmp/unsaved/
```

### 개발 시 디버깅 방법

```bash
# gedit를 터미널에서 실행하여 print 로그 확인
gedit --new-window 2>&1

# 플러그인 로그 접두사: [SessionRestore]
# 주요 로그 메시지:
#   [SessionRestore] do_activate
#   [SessionRestore] session saved (N tabs)
#   [SessionRestore] restoring N tabs
#   [SessionRestore] restore complete (N tabs)
#   [SessionRestore] no session to restore
#   [SessionRestore] file not found, skipping: <uri>
#   [SessionRestore] unsaved tab too large (N bytes), skipping: <name>
#   [SessionRestore] delete-event
```

---

## 8. 의존성

| 패키지 | 용도 |
|--------|------|
| `gi.repository.Gedit` (3.0) | gedit 플러그인 API |
| `gi.repository.GObject` | GObject 기반 클래스 |
| `gi.repository.GLib` | 타이머 (timeout_add, idle_add, source_remove) |
| `gi.repository.Gio` | 파일 I/O, URI 처리 |
| `gi.repository.Gtk` (3.0) | TextBuffer 접근, 설정 UI 위젯 |
| `gi.repository.PeasGtk` (1.0) | 설정 다이얼로그 인터페이스 |
| `json` (stdlib) | session.json / settings.json 직렬화 |
| `os`, `shutil`, `datetime` (stdlib) | 파일 시스템, 타임스탬프 |
| `gettext` (stdlib) | 다국어 지원 (i18n) |

---

## 9. 리스크 및 주의사항

1. **`file_modified` 복원의 비동기 문제** (`preserve_modifications=ON` 시): `create_tab_from_location()` 이후 파일 로딩이 비동기적으로 진행됨. → `tab.connect("notify::state", ...)` 로 `STATE_NORMAL` 대기하여 해결. 이미 로딩 완료 시 즉시 적용.

2. **복수 윈도우 세션 관리**: `Gedit.App.get_default().get_windows()` 로 모든 윈도우의 탭을 합산 저장. 마지막으로 닫히는 윈도우가 전체 세션을 저장함.

3. **대용량 텍스트**: `_MAX_UNSAVED_BYTES = 5MB` 제한. 초과 시 unsaved 탭은 건너뛰고, file_modified 탭은 file로 강등.

4. **경쟁 상태** (`auto_snapshot_enabled=ON` 시): 탭 idle 스냅샷과 `delete-event` 전체 세션 저장이 동시에 실행될 가능성. `delete-event` 에서 모든 idle 타이머를 취소하여 방지.

5. **복원 중 세션 덮어쓰기**: `_restoring` 플래그로 복원 중 발생하는 tab-added/document-changed 시그널이 세션을 덮어쓰는 것을 방지. 2초 안정화 대기 후 해제.

6. **gedit 버전 호환**: gedit 41.0 (현재 설치 버전) 기준 개발. `Gedit.TabState.STATE_NORMAL` 등 API 호환성 주의.

7. **설정 파일 손상**: `sessionrestore_settings.json` / `session.json` 손상 시 기본값(DEFAULTS) 또는 None으로 fallback하여 안전 동작 보장. 원자적 쓰기(tmp → os.replace)로 쓰기 중 손상 방지.

8. **Ctrl+Q 종료**: gedit에서 Ctrl+Q는 `delete-event`를 거치지 않을 수 있음. 실시간 디바운스 저장(500ms)으로 대부분의 상태가 이미 저장되어 있으므로 데이터 손실 최소화.

---

## 10. 버그 분석: 기존 파일 탭 세션 복원 실패

### 10.1 증상

1. gedit를 구동하고 이미 존재하는 여러 개의 text 파일을 연다
2. 내용 수정은 하지 않는다
3. X 버튼으로 gedit를 종료한다
4. gedit를 다시 시작하면 아무 파일도 열리지 않은 기본 상태가 된다

### 10.2 원인 분석

코드 흐름을 추적한 결과, 다음 3가지 연쇄 문제가 식별되었다.

#### 문제 A: `show` 시그널 미수신 가능성 (복원 트리거 누락)

```
[gedit 시작]
    │
    ▼
gedit이 윈도우 생성 + gtk_widget_show() 호출  ← show 시그널 발생
    │
    ▼
libpeas가 플러그인 활성화 → do_activate() 호출
    ├── self.window.connect("show", _on_window_show)  ← 이미 show 발생 후!
    │
    ▼
show 시그널이 다시 발생하지 않음
    │
    ▼
_on_window_show() 호출 안 됨
    │
    ▼
_restore_session() 실행 안 됨
    │
    ▼
_restoring = True 고정 (영원히 해제 안 됨)
```

`do_activate()` 시점에 윈도우가 이미 표시(visible)된 상태라면, `show` 시그널은 이미
발생한 후이므로 핸들러가 영원히 호출되지 않는다. 이 경우:

- `_restore_session()`이 실행되지 않아 이전 세션이 복원되지 않음
- `_restoring = True`가 해제되지 않아 **모든 실시간 저장이 차단됨**

#### 문제 B: `_restoring = True` 상태에서 실시간 저장 차단

```python
def _save_session(self):
    if self._restoring:    # ← _restoring이 True로 고정되면
        return              #    모든 저장이 영원히 차단됨
```

`show` 시그널이 미수신되면 `_restoring`이 영원히 True이므로:
- `_on_tab_added()` → `_save_session()` → 차단 (저장 안 됨)
- `_on_document_changed()` → `_schedule_save()` → `_save_session()` → 차단
- 사용자가 파일을 열고 편집해도 세션이 전혀 저장되지 않음

**유일한 저장 기회는 `_on_window_delete_event()`** 에서 `_restoring = False` 설정 후 저장.

#### 문제 C: 종료 시 이전 세션 덮어쓰기

`show` 미수신 시나리오에서의 세션 파일 상태 변화:

```
[Run 1: 최초 실행]
1. gedit 시작 → _restoring = True (show 미수신, 복원 안 됨)
2. 파일 A, B, C 열기 → _save_session() 차단 (저장 안 됨)
3. X 버튼 종료:
   _on_window_delete_event():
     _restoring = False
     _save_session() → session.json = [A, B, C]  ✓ 저장됨

[Run 2: 두 번째 실행]
1. gedit 시작 → _restoring = True (show 미수신, 복원 안 됨)
2. 사용자에게 보이는 것: 빈 gedit (기본 탭만 존재)
   → session.json에는 [A, B, C]가 있지만 복원되지 않았음
3. 사용자가 빈 상태로 종료:
   _on_window_delete_event():
     _restoring = False
     _save_session() → session.json = [빈 탭]  ✗ 덮어쓰기!

[Run 3: 세 번째 실행]
1. session.json에는 [빈 탭]만 남아있음
2. 복원해도 의미 없는 빈 탭만 복원됨
```

#### 문제 D: 윈도우 종료 시 `_on_tab_removed` 디바운스 저장

`delete-event` 이후 윈도우 파괴 과정에서 탭이 하나씩 제거된다:

```
[delete-event] → _save_session() → session.json = [A, B, C]  ✓
    │
    ▼
[탭 C 제거] → _on_tab_removed() → _schedule_save() (500ms 디바운스)
[탭 B 제거] → _on_tab_removed() → _schedule_save() (디바운스 리셋)
[탭 A 제거] → _on_tab_removed() → _schedule_save() (디바운스 리셋)
    │
    ▼
[do_deactivate()] → _cancel_debounce()  ← 디바운스 취소
```

현재는 `do_deactivate()`가 디바운스를 취소하므로 대부분 안전하지만,
타이밍에 따라 디바운스가 먼저 실행되면 불완전한 세션으로 덮어쓸 수 있다.
명시적 `_closing` 플래그가 없으므로 보장이 없음.

#### 문제 E: 빈 unsaved 탭이 세션에 포함됨

gedit 기본 생성 빈 탭(Untitled Document)도 `type="unsaved"` (빈 텍스트)로
세션에 저장된다. 복원 시 불필요한 빈 탭이 생성됨.

### 10.3 영향 범위

| 시나리오 | 저장 | 복원 | 영향 |
|----------|------|------|------|
| show 정상 수신 + 파일 탭 종료 | O | O | 정상 동작 |
| show 미수신 + 파일 탭 종료 | △ (delete-event에서만) | X | **세션 복원 실패** |
| show 미수신 + 빈 상태 종료 | O (빈 세션) | X | **이전 세션 덮어쓰기** |
| show 정상 + 탭 제거 중 디바운스 실행 | △ (불완전) | O | 불완전 세션 저장 |

---

## 11. 개선 계획 (Phase 9)

### Phase 9: 세션 저장/복원 안정성 개선

#### 9-1. 복원 트리거 이중화 (문제 A 해결)

**현재**: `show` 시그널에만 의존 → 미수신 시 복원 불가

**개선**: `do_activate()`에서 `GLib.idle_add` fallback 추가

```python
def do_activate(self):
    ...
    # 기존: show 핸들러만 연결
    self._show_handler = self.window.connect("show", self._on_window_show)

    # 추가: fallback — show 미수신 시 idle 콜백으로 복원 트리거
    if not SessionRestoreAppActivatable.is_restored():
        self._restore_fallback_id = GLib.idle_add(self._check_restore_needed)

def _check_restore_needed(self):
    """show 시그널이 이미 발생한 경우 복원을 트리거하는 fallback."""
    self._restore_fallback_id = None

    # 이미 복원 완료 (show 핸들러가 먼저 실행됨)
    if SessionRestoreAppActivatable.is_restored():
        return False

    # show 핸들러가 아직 실행 안 됨 — 직접 복원 트리거
    if self._show_handler is not None:
        self.window.disconnect(self._show_handler)
        self._show_handler = None

    SessionRestoreAppActivatable.mark_restored()
    self._restore_session()
    return False  # idle 1회 실행
```

- [x] `_on_window_show()` 기존 로직 유지 (정상 경로)
- [ ] `_check_restore_needed()` fallback 추가 (show 미수신 보완)
- [ ] `do_deactivate()` 에서 fallback 타이머 정리 추가

#### 9-2. `_closing` 플래그 추가 (문제 D 해결)

**현재**: 종료 과정에서 `_on_tab_removed` 디바운스가 세션을 덮어쓸 수 있음

**개선**: `_on_window_delete_event()`에서 `_closing = True` 설정,
이후 모든 저장 트리거에서 `_closing` 체크

```python
def __init__(self):
    ...
    self._closing = False

def _on_window_delete_event(self, window, event, data=None):
    self._closing = True        # ← 추가: 종료 모드 진입
    self._cancel_restore_settle()
    self._restoring = False
    self._cancel_debounce()
    self._cancel_all_tab_idle_timers()
    self._save_session()
    return False

def _on_tab_removed(self, window, tab, data=None):
    self._disconnect_doc(tab.get_document())
    if not self._closing:        # ← 추가: 종료 중이면 저장 스킵
        self._schedule_save()

def _on_tabs_changed(self, window, *args):
    if not self._closing:        # ← 추가
        self._schedule_save()

def _on_document_changed(self, doc, data=None):
    if not self._closing:        # ← 추가
        self._schedule_save()
        if self._settings.get("auto_snapshot_enabled"):
            self._reset_tab_idle_timer(doc)
```

- [ ] `_closing` 인스턴스 변수 추가
- [ ] `_on_window_delete_event()` 에서 `_closing = True` 설정
- [ ] `_on_tab_removed()`, `_on_tabs_changed()`, `_on_document_changed()` 에서 `_closing` 체크

#### 9-3. 복원 미실행 시 세션 보호 (문제 B, C 해결)

**현재**: 복원이 안 된 상태에서 종료 시 빈 세션으로 이전 세션을 덮어씀

**개선**: 복원이 시도된 적 없으면 `delete-event`에서도 세션을 덮어쓰지 않음

```python
def __init__(self):
    ...
    self._restore_attempted = False  # 복원이 시도되었는지 여부

def _restore_session(self):
    self._restore_attempted = True
    ...

def _on_window_delete_event(self, window, event, data=None):
    self._closing = True
    self._cancel_restore_settle()
    self._cancel_debounce()
    self._cancel_all_tab_idle_timers()

    if self._restore_attempted:
        # 복원이 시도된 후에만 세션 저장 (정상 흐름)
        self._restoring = False
        self._save_session()
    else:
        # 복원이 시도되지 않은 경우 — 이전 세션 보호
        print("[SessionRestore] restore never attempted, preserving existing session")

    return False
```

- [ ] `_restore_attempted` 인스턴스 변수 추가
- [ ] `_restore_session()` 진입 시 `True` 설정
- [ ] `_on_window_delete_event()` 에서 `_restore_attempted` 체크

#### 9-4. 빈 unsaved 탭 필터링 (문제 E 해결)

**현재**: 빈 텍스트의 미저장 탭도 세션에 포함됨

**개선**: `_collect_tabs_data()`에서 빈 unsaved 탭 제외

```python
# _collect_tabs_data() 내 unsaved 분기:
else:
    text = self._extract_text(doc)
    if not text:
        continue  # ← 추가: 빈 unsaved 탭은 세션에 포함하지 않음
    ...
```

- [ ] `_collect_tabs_data()` unsaved 분기에서 빈 텍스트 탭 스킵

#### 9-5. 디버깅 로그 강화

주요 분기점에 로그를 추가하여 문제 재현 시 진단을 용이하게 한다.

```python
# do_activate()
print("[SessionRestore] do_activate (window visible: %s, restored: %s)"
      % (self.window.get_visible(), SessionRestoreAppActivatable.is_restored()))

# _check_restore_needed() fallback
print("[SessionRestore] restore fallback triggered (show signal was missed)")

# _save_session()
print("[SessionRestore] _save_session (restoring=%s, closing=%s, restore_attempted=%s)"
      % (self._restoring, self._closing, self._restore_attempted))

# _on_window_delete_event()
print("[SessionRestore] delete-event (restore_attempted=%s)" % self._restore_attempted)
```

- [ ] `do_activate()` 에 윈도우 visible 상태 로그 추가
- [ ] `_check_restore_needed()` 에 fallback 트리거 로그
- [ ] `_save_session()` 에 상태 플래그 로그
- [ ] `_on_window_delete_event()` 에 restore_attempted 로그

### 구현 우선순위

| 순서 | 항목 | 효과 | 난이도 |
|------|------|------|--------|
| 1 | 9-1. 복원 트리거 이중화 | 핵심 — show 미수신 문제 해결 | 낮음 |
| 2 | 9-3. 복원 미실행 시 세션 보호 | 핵심 — 이전 세션 덮어쓰기 방지 | 낮음 |
| 3 | 9-2. `_closing` 플래그 | 안전장치 — 종료 시 디바운스 방지 | 낮음 |
| 4 | 9-4. 빈 unsaved 탭 필터링 | 개선 — 불필요한 빈 탭 제거 | 낮음 |
| 5 | 9-5. 디버깅 로그 강화 | 진단 — 향후 문제 추적 용이 | 낮음 |

# DEVPLAN: gedit Instance Save Plugin

## 1. 프로젝트 개요

**플러그인명**: Instance Save
**목적**: gedit 종료 시 열려 있던 모든 탭의 상태를 보존하고, 재시작 시 동일한 상태로 복원한다.
**gedit 버전**: 41.0 (Gedit API 3.0, Loader=python3)
**기본 저장 디렉터리**: `~/.config/gedit/tmp/`

### 핵심 동작 원칙

> **이 플러그인은 "파일을 자동 저장(auto-save to disk)" 하는 기능이 아니다.**
>
> - **미저장 텍스트** (파일로 저장한 적 없는 탭) → 텍스트 내용을 tmp에 보존/복원 **(핵심 기능)**
> - **이미 저장된 파일** → URI만 기억하고 재시작 시 해당 파일을 reload
> - **저장된 파일의 미저장 수정 보존** → 설정으로 on/off 가능 (기본 OFF)
> - **탭별 Idle 스냅샷** (입력 2초 멈추면 해당 탭만 저장) → 설정으로 on/off 가능 (기본 OFF)

### 기존 플러그인과의 차별점

| 기능 | gedit-restore-tabs | **Instance Save (본 프로젝트)** |
|------|--------------------|---------------------------------|
| 저장된 파일 탭 복원 | O (URI만 저장) | O (URI + 커서 위치) |
| 미저장 텍스트 보존 | **X** | **O (텍스트 내용 자체를 저장)** |
| 탭 순서 복원 | X | O |
| 수정된 파일 내용 보존 | X | O (설정으로 on/off) |
| 탭별 Idle 스냅샷 (입력 2초 후) | X | O (설정으로 on/off) |

---

## 2. 기술 아키텍처

### 2.1 파일 구조

```
~/.local/share/gedit/plugins/
├── instancesave.plugin              # 플러그인 메타데이터
└── instancesave/                    # Python 패키지
    ├── __init__.py                  # AppActivatable + WindowActivatable export
    ├── appactivatable.py            # App 레벨 (한 번만 초기화)
    ├── windowactivatable.py         # Window 레벨 (탭 추적, 세션 저장/복원)
    ├── sessionmanager.py            # 세션 데이터 직렬화/역직렬화 로직
    └── settings.py                  # 플러그인 설정 관리 (on/off 옵션)
```

### 2.2 저장 디렉터리 구조

```
~/.config/gedit/tmp/
├── session.json                     # 세션 메타데이터
└── unsaved/                         # 미저장 텍스트 내용 보관
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

설정은 `~/.config/gedit/tmp/instancesave_settings.json` 에 JSON으로 저장한다.
(GSettings/dconf 대신 단순 JSON 파일 사용 — GSchema 등록 없이 독립 동작 가능)

### 2.5 탭별 Idle 스냅샷 동작 원리 (`auto_snapshot_enabled=ON` 시)

```
[사용자가 탭에서 텍스트 입력/삭제]
    │
    ▼
document 'changed' 시그널 발생
    │
    ▼
해당 탭의 기존 idle 타이머가 있으면 취소 (reset)
    │
    ▼
GLib.timeout_add(2000ms, _on_tab_idle, tab)  ← 새 타이머 등록
    │
    ... 2초간 추가 입력 없음 ...
    │
    ▼
_on_tab_idle(tab) 호출
    │
    ├── 미저장 탭 → unsaved/ 에 해당 탭 텍스트만 갱신
    ├── 수정된 파일 탭 (preserve_modifications=ON) → unsaved/ 에 해당 탭 텍스트만 갱신
    └── session.json 의 해당 탭 항목도 갱신
```

- **전체 세션을 통째로 저장하지 않고, 변경이 발생한 탭의 텍스트만 개별 갱신**
- 비정상 종료 시에도 최근 2초 이내의 입력만 손실
- `auto_snapshot_enabled=OFF` (기본값)이면 이 메커니즘 전체가 비활성화되고, gedit 정상 종료 시에만 세션 저장

---

## 3. 핵심 클래스 설계

### 3.1 Settings (settings.py)

플러그인 설정 관리. JSON 파일 기반으로 GSettings 없이 독립 동작.

```python
class Settings:
    """플러그인 설정 로드/저장."""

    SETTINGS_FILE = os.path.join(SessionManager.BASE_DIR, "instancesave_settings.json")

    DEFAULTS = {
        "preserve_modifications": False,   # 저장된 파일의 미저장 수정 보존 여부
        "auto_snapshot_enabled": False,    # 탭별 idle 스냅샷 on/off
        "auto_snapshot_idle_seconds": 2.0, # 마지막 입력 후 스냅샷 대기 시간 (초)
    }

    def load(self) -> dict
    def save(self, data: dict) -> None
    def get(self, key: str) -> any
    def set(self, key: str, value: any) -> None
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
        """세션 데이터를 session.json + unsaved/ 에 기록"""

    def load_session(self) -> dict | None
        """session.json 로드, 없으면 None 반환"""

    def save_unsaved_content(self, filename: str, content: str) -> None
        """미저장 텍스트를 tmp 파일에 기록"""

    def load_unsaved_content(self, filename: str) -> str | None
        """tmp 파일에서 텍스트 읽기"""

    def cleanup_unsaved(self) -> None
        """unsaved/ 디렉터리 내 이전 세션 파일 정리"""
```

### 3.3 WindowActivatable (windowactivatable.py)

gedit 윈도우 단위의 탭 추적 및 세션 저장/복원 핵심 로직.

```python
class InstanceSaveWindowActivatable(GObject.Object, Gedit.WindowActivatable):
    __gtype_name__ = "InstanceSaveWindowActivatable"
    window = GObject.Property(type=Gedit.Window)

    # === 시그널 연결 ===
    def do_activate(self)
        """플러그인 활성화 시:
        - window 'delete-event' 연결 (종료 직전 세션 저장)
        - window 'show' 연결 (최초 표시 시 세션 복원)
        - window 'tab-added' / 'tab-removed' 연결 (탭별 idle 감지 등록/해제)
        - Settings 로드
        """

    def do_deactivate(self)
        """플러그인 비활성화 시:
        - 시그널 핸들러 해제
        - 모든 탭의 idle 타이머 제거
        """

    # === 세션 저장 ===
    def _collect_tabs_data(self) -> tuple[list, int]
        """현재 윈도우의 모든 탭 정보 수집:
        - document.get_file().get_location() 으로 파일 존재 여부 확인
        - location 없음 → type="unsaved", 텍스트 저장 (항상)
        - location 있음 + 수정 없음 → type="file", URI만 기록 (항상)
        - location 있음 + 수정 있음:
          - preserve_modifications=ON  → type="file_modified", URI + 텍스트 저장
          - preserve_modifications=OFF → type="file", URI만 기록 (수정 내용 버림)
        - 커서 위치(line, column) 추출
        - 활성 탭 인덱스 기록
        반환: (tabs_data_list, active_tab_index)
        """

    def _save_session(self) -> None
        """_collect_tabs_data() 결과를 SessionManager를 통해 저장"""

    # === 세션 복원 ===
    def _restore_session(self) -> None
        """SessionManager에서 세션 로드 후 탭 복원:
        - 'file' 타입: window.create_tab_from_location() 으로 파일 reload
        - 'unsaved' 타입: 빈 탭 생성 후 텍스트 삽입
        - 'file_modified' 타입: 파일 열기 후 수정된 내용으로 교체
        - 활성 탭 인덱스 복원
        """

    # === 탭별 Idle 스냅샷 (auto_snapshot_enabled=ON 시) ===
    def _connect_tab_signals(self, tab) -> None
        """탭 추가 시: document 'changed' 시그널에 _on_document_changed 연결"""

    def _disconnect_tab_signals(self, tab) -> None
        """탭 제거 시: 시그널 해제 + idle 타이머 취소"""

    def _on_document_changed(self, document) -> None
        """document 텍스트 변경 시:
        - 해당 탭의 기존 idle 타이머가 있으면 GLib.source_remove()
        - GLib.timeout_add(idle_ms, _on_tab_idle, tab) 으로 새 타이머 등록
        """

    def _on_tab_idle(self, tab) -> bool
        """idle_seconds 경과 후 호출:
        - 해당 탭의 텍스트만 unsaved/ 에 갱신 저장
        - session.json 도 갱신
        - return False (타이머 1회 실행)
        """

    # === 시그널 핸들러 ===
    def _on_window_delete_event(self, window, event) -> bool
        """윈도우 닫기 직전: _save_session() 호출"""

    def _on_window_show(self, window) -> None
        """최초 윈도우 표시: 첫 번째 윈도우인 경우만 _restore_session()"""

    def _on_tab_added(self, window, tab) -> None
        """탭 추가 시: _connect_tab_signals(tab)"""

    def _on_tab_removed(self, window, tab) -> None
        """탭 제거 시: _disconnect_tab_signals(tab)"""
```

### 3.4 AppActivatable (appactivatable.py)

앱 레벨 초기화. 복수 윈도우 시 중복 복원 방지 플래그 관리.

```python
class InstanceSaveAppActivatable(GObject.Object, Gedit.AppActivatable):
    __gtype_name__ = "InstanceSaveAppActivatable"
    app = GObject.Property(type=Gedit.App)

    def do_activate(self)
        """앱 시작 시: 복원 완료 플래그 초기화"""

    def do_deactivate(self)
        """앱 종료 시: 정리"""
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
    │
    ▼
_collect_tabs_data()
    ├── 각 탭에 대해:
    │   ├── document.get_file().get_location() 확인
    │   ├── location 없음 → type="unsaved", 텍스트 저장 (항상)
    │   ├── location 있음 + 수정 없음 → type="file", URI 기록 (항상)
    │   └── location 있음 + 수정 있음:
    │       ├── [preserve_modifications=ON]  → type="file_modified", URI + 텍스트 저장
    │       └── [preserve_modifications=OFF] → type="file", URI만 기록 (수정 내용 버림)
    │
    ▼
SessionManager.cleanup_unsaved()  ← 이전 tmp 파일 삭제
SessionManager.save_session()     ← session.json 기록
SessionManager.save_unsaved_content() × N  ← 미저장 텍스트 기록
```

### 4.2 세션 복원 흐름 (gedit 시작 시)

```
[gedit 시작]
    │
    ▼
window 'show' 시그널 발생
    │
    ▼
_on_window_show() 호출
    │
    ├── 첫 번째 윈도우가 아닌 경우 → 무시
    │
    ▼
SessionManager.load_session()
    │
    ├── session.json 없음 → 복원 없이 종료
    │
    ▼
각 탭 데이터에 대해:
    ├── type="file":
    │   └── window.create_tab_from_location(uri)
    │       → 파일이 존재하면 열기, 없으면 건너뛰기
    │
    ├── type="unsaved":
    │   ├── window.create_tab(True)
    │   ├── SessionManager.load_unsaved_content(tmp_file)
    │   └── document.set_text(content)
    │
    └── type="file_modified":
        ├── window.create_tab_from_location(uri)
        ├── 파일 로드 완료 대기 (loaded 시그널)
        ├── SessionManager.load_unsaved_content(tmp_file)
        └── document.set_text(modified_content)
    │
    ▼
기본 생성된 빈 'Untitled Document' 탭 제거
활성 탭 인덱스 복원
```

---

## 5. 개발 단계

### Phase 1: 프로젝트 기반 구축
- [ ] 디렉터리 구조 생성 (`instancesave/` 패키지)
- [ ] `instancesave.plugin` 메타데이터 파일 작성
- [ ] `__init__.py` 에 기본 import/export 설정
- [ ] `~/.config/gedit/tmp/` 및 `unsaved/` 디렉터리 자동 생성 로직
- [ ] gedit 플러그인 목록에서 활성화 확인 (빈 껍데기 상태)

### Phase 2: 세션 저장 구현
- [ ] `SessionManager` 클래스 구현
  - [ ] `ensure_dirs()`, `cleanup_unsaved()`
  - [ ] `save_session()`, `save_unsaved_content()`
- [ ] `WindowActivatable._collect_tabs_data()` 구현
  - [ ] 미저장 탭 텍스트 추출 (GtkTextBuffer → str) — 핵심
  - [ ] 파일 탭 URI 수집
  - [ ] 커서 위치 (line, column) 수집
  - [ ] 활성 탭 인덱스 수집
- [ ] `window delete-event` 시그널 연결 및 저장 트리거
- [ ] 저장된 `session.json` 및 `unsaved/` 파일 내용 수동 검증

### Phase 3: 세션 복원 구현
- [ ] `SessionManager.load_session()`, `load_unsaved_content()` 구현
- [ ] `WindowActivatable._restore_session()` 구현
  - [ ] `type="file"` 복원: `create_tab_from_location()` 으로 파일 reload
  - [ ] `type="unsaved"` 복원: 빈 탭 생성 → 텍스트 삽입
  - [ ] 기본 빈 탭 ('Untitled Document') 자동 제거
  - [ ] 활성 탭 및 커서 위치 복원
- [ ] `window show` 시그널 연결 및 복원 트리거
- [ ] 첫 번째 윈도우 판별 로직 (`Gedit.App.get_default().get_windows()`)

### Phase 4: 플러그인 설정 UI 및 옵션 구현
- [ ] `Settings` 클래스 구현 (JSON 파일 기반 설정 load/save)
- [ ] `PeasGtk.Configurable` 기반 설정 다이얼로그 UI
  - [ ] `preserve_modifications` 체크박스 (기본 OFF)
    - ON: 저장된 파일의 미저장 수정 내용도 tmp에 보존
    - OFF: 저장된 파일은 URI만 기억, 수정 내용 버림
  - [ ] `auto_snapshot_enabled` 체크박스 (기본 OFF)
    - ON: 탭별 입력 idle 감지 후 스냅샷 (비정상 종료 대비)
    - OFF: gedit 정상 종료 시에만 세션 저장
  - [ ] `auto_snapshot_idle_seconds` 스핀버튼 (0.5~10초, 기본 2초)
    - `auto_snapshot_enabled=ON` 일 때만 활성화
- [ ] `_collect_tabs_data()` 에 `preserve_modifications` 설정 반영
- [ ] `_restore_session()` 에 `type="file_modified"` 복원 로직 추가
  - [ ] 파일 열기 → 비동기 로딩 완료 대기 → 수정 텍스트 덮어쓰기

### Phase 5: 탭별 Idle 스냅샷 구현 (`auto_snapshot_enabled=ON` 시)
- [ ] `window 'tab-added'` / `'tab-removed'` 시그널 연결
- [ ] 각 탭의 `document 'changed'` 시그널 연결 → idle 타이머 (재)등록
- [ ] `GLib.timeout_add(idle_ms, ...)` 기반 탭별 개별 타이머
  - 텍스트 변경 시 기존 타이머 취소 (`GLib.source_remove`) + 새 타이머 등록
  - idle_seconds (기본 2초) 동안 추가 입력 없으면 해당 탭만 스냅샷
- [ ] `_on_tab_idle()`: 해당 탭의 텍스트만 `unsaved/`에 갱신 + `session.json` 갱신
- [ ] `do_deactivate()` 에서 모든 탭의 idle 타이머 정리
- [ ] 설정 변경 시 시그널 연결 동적 시작/중지

### Phase 6: 엣지 케이스 및 안정성
- [ ] 파일이 삭제된 경우의 복원 처리 (file 타입인데 파일 부재 시 → 건너뛰기)
- [ ] 매우 큰 텍스트의 저장/복원 처리 (메모리/성능)
- [ ] session.json 파싱 실패 시 안전한 fallback
- [ ] 인코딩 처리 (UTF-8 기본, 원본 인코딩 보존 시도)
- [ ] 복수 gedit 윈도우 동시 운영 시 세션 충돌 방지
- [ ] `file_modified` 탭 복원 시 비동기 파일 로딩 완료 대기 처리

### Phase 7: 테스트 및 배포
- [ ] 수동 테스트 시나리오:
  - [ ] 미저장 텍스트만 있는 상태 → 종료 → 재시작 → 복원 확인
  - [ ] 정식 파일만 있는 상태 → 종료 → 재시작 → reload 확인
  - [ ] 파일 + 미저장 텍스트 혼합 → 종료 → 재시작 → 전체 복원 확인
  - [ ] `preserve_modifications=OFF` → 수정된 파일 탭 → 종료 → 재시작 → 파일 원본으로 reload 확인
  - [ ] `preserve_modifications=ON` → 수정된 파일 탭 → 종료 → 재시작 → 수정 내용 유지 확인
  - [ ] `auto_snapshot_enabled=ON` → 미저장 탭에 입력 → 2초 대기 → `unsaved/` 파일 갱신 확인
  - [ ] `auto_snapshot_enabled=ON` → gedit 비정상 종료(kill) → 재시작 → 최근 스냅샷으로 복원 확인
  - [ ] `auto_snapshot_enabled=ON` → 빠르게 연속 입력 → 타이머 리셋 → 입력 중에는 저장 안 됨 확인
  - [ ] 설정 다이얼로그에서 옵션 토글 후 동작 변경 확인
- [ ] 심볼릭 링크를 통한 편리한 개발 환경 구성
- [ ] 설치 스크립트 또는 README 작성

---

## 6. 핵심 gedit API 참조

### 사용할 주요 API

| API | 용도 |
|-----|------|
| `Gedit.WindowActivatable` | 윈도우 레벨 플러그인 인터페이스 |
| `Gedit.AppActivatable` | 앱 레벨 플러그인 인터페이스 |
| `window.get_documents()` | 모든 열린 문서 리스트 |
| `window.get_active_tab()` | 현재 활성 탭 |
| `window.create_tab(jump_to)` | 빈 새 탭 생성 |
| `window.create_tab_from_location(location, encoding, line, column, create)` | 파일로부터 탭 생성 |
| `window.close_tab(tab)` | 탭 닫기 |
| `window.set_active_tab(tab)` | 활성 탭 설정 |
| `document.get_file().get_location()` | 문서의 Gio.File 위치 (None이면 미저장) |
| `document.is_modified()` | 수정 여부 확인 |
| `document.get_language()` | 구문 강조 언어 |
| `tab.get_document()` | 탭에서 문서 가져오기 |
| `tab.get_state()` | 탭 상태 (로딩 중 등) |
| `Gio.file_new_for_uri(uri)` | URI → Gio.File 변환 |
| `GLib.timeout_add_seconds()` | 주기적 타이머 |

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
/mnt/USERS/onion/DATA_ORIGN/Workspace/gedit_instance_save/

# gedit 플러그인 설치 위치 (심볼릭 링크로 연결)
~/.local/share/gedit/plugins/instancesave.plugin
~/.local/share/gedit/plugins/instancesave/   → 프로젝트 소스 링크

# 세션 데이터 저장 위치
~/.config/gedit/tmp/session.json
~/.config/gedit/tmp/unsaved/
```

### 개발 시 디버깅 방법

```bash
# gedit를 터미널에서 실행하여 print/로그 확인
gedit --new-window 2>&1

# 또는 GLib 로깅 사용
# 코드 내: GLib.log_default_handler("InstanceSave", GLib.LogLevelFlags.LEVEL_DEBUG, msg)
```

---

## 8. 의존성

| 패키지 | 용도 |
|--------|------|
| `gi.repository.Gedit` (3.0) | gedit 플러그인 API |
| `gi.repository.GObject` | GObject 기반 클래스 |
| `gi.repository.GLib` | 타이머, 파일 유틸리티 |
| `gi.repository.Gio` | 파일 I/O, URI 처리 |
| `gi.repository.Gtk` (3.0) | TextBuffer 접근 |
| `json` (stdlib) | session.json 직렬화 |
| `os`, `datetime` (stdlib) | 파일 시스템, 타임스탬프 |

---

## 9. 리스크 및 주의사항

1. **`file_modified` 복원의 비동기 문제** (`preserve_modifications=ON` 시): `create_tab_from_location()` 이후 파일 로딩이 비동기적으로 진행됨. 로딩 완료 전에 `set_text()`를 호출하면 실패할 수 있음. → `tab`의 `loaded` 시그널 또는 `tab.get_state()` 폴링으로 해결. 이 복잡성은 `preserve_modifications` 설정이 OFF (기본값)이면 발생하지 않음.

2. **복수 윈도우 세션 관리**: gedit은 단일 프로세스로 여러 윈도우를 관리함. 마지막으로 닫히는 윈도우의 세션이 저장되므로, 복수 윈도우 환경에서는 모든 윈도우의 세션을 합산 저장하는 방안 검토 필요.

3. **대용량 텍스트**: 미저장 탭에 매우 큰 텍스트가 있는 경우 tmp 파일 저장 시 디스크/메모리 부담. 텍스트 크기 상한 고려.

4. **경쟁 상태** (`auto_snapshot_enabled=ON` 시): 탭 idle 스냅샷과 `delete-event` 전체 세션 저장이 동시에 실행될 가능성. 저장 로직에 간단한 잠금 또는 플래그로 방지. `auto_snapshot_enabled=OFF` (기본값)이면 발생하지 않음.

5. **gedit 버전 호환**: 일부 API(`tab.load_file` 등)가 gedit 버전에 따라 다를 수 있음. gedit 41.0 (현재 설치 버전)을 기준으로 개발하되, deprecated API 주의.

6. **설정 파일 손상**: `instancesave_settings.json`이 손상될 경우 기본값(DEFAULTS)으로 fallback하여 안전 동작 보장.

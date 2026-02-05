import os
import json
import shutil
from datetime import datetime


class SessionManager:
    """세션 데이터(session.json + unsaved/ 텍스트 파일) 저장/로드 담당."""

    BASE_DIR = os.path.expanduser("~/.config/gedit/tmp")
    SESSION_FILE = os.path.join(BASE_DIR, "session.json")
    UNSAVED_DIR = os.path.join(BASE_DIR, "unsaved")

    def ensure_dirs(self):
        """저장 디렉터리가 없으면 생성한다."""
        os.makedirs(self.BASE_DIR, exist_ok=True)
        os.makedirs(self.UNSAVED_DIR, exist_ok=True)

    def cleanup_unsaved(self):
        """unsaved/ 디렉터리 내 이전 세션 파일을 모두 삭제한다."""
        if os.path.isdir(self.UNSAVED_DIR):
            shutil.rmtree(self.UNSAVED_DIR)
        os.makedirs(self.UNSAVED_DIR, exist_ok=True)

    def save_session(self, tabs_data, active_tab_index):
        """세션 메타데이터를 session.json 에 기록한다.

        Args:
            tabs_data: 탭 정보 딕셔너리 리스트.
            active_tab_index: 활성 탭의 인덱스.
        """
        self.ensure_dirs()
        session = {
            "version": 1,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "active_tab_index": active_tab_index,
            "tabs": tabs_data,
        }
        tmp_path = self.SESSION_FILE + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(session, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, self.SESSION_FILE)

    def load_session(self):
        """session.json 을 로드하여 딕셔너리로 반환한다.

        Returns:
            세션 딕셔너리 또는 파일이 없으면 None.
        """
        if not os.path.isfile(self.SESSION_FILE):
            return None
        try:
            with open(self.SESSION_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

    def save_unsaved_content(self, filename, content):
        """미저장 텍스트를 unsaved/ 디렉터리에 기록한다.

        Args:
            filename: 저장할 파일명 (예: 'tab_0001.txt').
            content: 텍스트 내용.
        """
        self.ensure_dirs()
        filepath = os.path.join(self.UNSAVED_DIR, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

    def load_unsaved_content(self, filename):
        """unsaved/ 디렉터리에서 텍스트를 읽어 반환한다.

        Args:
            filename: 읽을 파일명.

        Returns:
            텍스트 문자열 또는 파일이 없으면 None.
        """
        filepath = os.path.join(self.UNSAVED_DIR, filename)
        if not os.path.isfile(filepath):
            return None
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
        except OSError:
            return None

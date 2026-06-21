import json
import os
import threading
import uuid
from datetime import datetime

from constants import DATA_DIR, DATA_FILES, DEFAULT_CONFIG, Role


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def gen_id(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class Storage:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._file_lock = threading.RLock()
            cls._instance._cache = {}
            cls._instance._seeded = False
        return cls._instance

    def _path(self, name):
        return os.path.join(DATA_DIR, DATA_FILES[name])

    def read(self, name):
        with self._file_lock:
            if name in self._cache:
                return self._cache[name]
            path = self._path(name)
            if not os.path.exists(path):
                self._cache[name] = []
                return []
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, ValueError):
                data = []
            if name == "config":
                data = data or {}
            self._cache[name] = data
            return data

    def write(self, name, data):
        with self._file_lock:
            self._cache[name] = data
            path = self._path(name)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    def insert(self, name, record):
        with self._file_lock:
            data = self.read(name)
            stored = dict(record)
            data.append(stored)
            self.write(name, data)
            return dict(stored)

    def update(self, name, record_id, patch):
        with self._file_lock:
            data = self.read(name)
            for rec in data:
                if rec.get("id") == record_id:
                    rec.update(patch)
                    rec["updated_at"] = now_iso()
                    self.write(name, data)
                    return rec
            return None

    def find(self, name, record_id):
        for rec in self.read(name):
            if rec.get("id") == record_id:
                return dict(rec)
        return None

    def find_one(self, name, predicate):
        for rec in self.read(name):
            if predicate(rec):
                return dict(rec)
        return None

    def find_all(self, name, predicate=None):
        if predicate is None:
            return [dict(r) for r in self.read(name)]
        return [dict(r) for r in self.read(name) if predicate(r)]

    def seed_defaults(self):
        if self._seeded:
            return
        self._seeded = True
        if not self.read("config"):
            self.write("config", dict(DEFAULT_CONFIG))

        if not self.read("users"):
            admin = {
                "id": gen_id("u"),
                "username": "admin",
                "password": "admin123",
                "role": Role.ADMIN,
                "name": "系统管理员",
                "business_line_id": None,
                "seat_group_id": None,
                "created_at": now_iso(),
            }
            inspector = {
                "id": gen_id("u"),
                "username": "inspector",
                "password": "inspector123",
                "role": Role.INSPECTOR,
                "name": "质检员A",
                "business_line_id": None,
                "seat_group_id": None,
                "created_at": now_iso(),
            }
            lead = {
                "id": gen_id("u"),
                "username": "leader",
                "password": "leader123",
                "role": Role.TEAM_LEAD,
                "name": "客服组长A",
                "business_line_id": None,
                "seat_group_id": None,
                "created_at": now_iso(),
            }
            self.write("users", [admin, inspector, lead])

        if not self.read("business_lines"):
            self.write("business_lines", [
                {
                    "id": gen_id("bl"),
                    "name": "售前咨询",
                    "responsible_person": "李经理",
                    "created_at": now_iso(),
                },
            ])

        if not self.read("scoring_tables"):
            self.write("scoring_tables", [
                {
                    "id": gen_id("st"),
                    "name": "通用质检评分表",
                    "business_line_id": None,
                    "total_score": 100,
                    "items": [
                        {"id": "si_open", "name": "开场白规范", "max_score": 10},
                        {"id": "si_attitude", "name": "服务态度", "max_score": 20},
                        {"id": "si_solve", "name": "问题解决能力", "max_score": 30},
                        {"id": "si_lang", "name": "服务用语规范", "max_score": 20},
                        {"id": "si_close", "name": "结束语规范", "max_score": 10},
                        {"id": "si_process", "name": "流程合规", "max_score": 10},
                    ],
                    "created_at": now_iso(),
                },
            ])


storage = Storage()

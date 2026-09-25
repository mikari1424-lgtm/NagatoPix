#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NagatoPix - A Powerful Pixiv App
Pixiv 应用
"""

import asyncio
import json
import webbrowser
import threading
import time
import queue
import subprocess
import tempfile
import os
import re
import socket
import sys
import locale
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs
import logging

import requests
import aiohttp
from aiohttp import web
from bs4 import BeautifulSoup
from pixivpy3 import AppPixivAPI

try:
    import tomllib
except ImportError:
    import tomli as tomllib

from i18n import t, meta, set_language, get_language


VERSION = "1.2.0"


# ============================================================
# Path helpers / 路径工具
# ============================================================
def get_resource_path(relative: str) -> Path:
    if getattr(sys, 'frozen', False):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).parent
    return base / relative


def get_app_dir() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).parent


CONFIG_FILE = get_app_dir() / "config.toml"
LEGACY_CONFIG_FILE = get_app_dir() / "pixiv_client_config.json"
ACCOUNTS_FILE = get_app_dir() / "accounts.json"
SESSION_FILE = get_app_dir() / "session.json"
LEGACY_QUEUE_FILE = get_app_dir() / "queue.json"
HISTORY_FILE = get_app_dir() / "history.json"
LOG_DIR = get_app_dir() / "logs"
LOG_DIR.mkdir(exist_ok=True)
HISTORY_MAX = 2000

_logger: Optional[logging.Logger] = None


# ============================================================
# Logging / 日志
# ============================================================
def setup_logging():
    global _logger
    startup = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_file = LOG_DIR / f"nagato-{startup}.log"

    logger = logging.getLogger('nagato')
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    logger.propagate = False

    fh = logging.FileHandler(log_file, encoding='utf-8')
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        '[%(asctime)s] [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    logger.addHandler(fh)

    try:
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.INFO)
        ch.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))
        logger.addHandler(ch)
    except Exception:
        pass

    _logger = logger


def write_log(msg, level='info'):
    global _logger
    if _logger is None:
        print(f"[{level.upper()}] {msg}")
        return
    fn = getattr(_logger, level, _logger.info)
    fn(msg)


# ============================================================
# Language / 语言
# ============================================================
def detect_system_language() -> str:
    try:
        loc = locale.getdefaultlocale()[0] or 'en'
    except Exception:
        return 'en'
    return 'zh-CN' if loc.lower().startswith('zh') else 'en'


def peek_language() -> str:
    try:
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, 'rb') as f:
                cfg = tomllib.load(f)
            lang = cfg.get('language', 'auto')
            if lang in ('zh-CN', 'en'):
                return lang
        elif LEGACY_CONFIG_FILE.exists():
            with open(LEGACY_CONFIG_FILE, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            lang = cfg.get('language', 'auto')
            if lang in ('zh-CN', 'en'):
                return lang
    except Exception:
        pass
    return detect_system_language()


# ============================================================
# Config / 配置
# ============================================================
class ConfigManager:
    DEFAULT_CONFIG = {
        "refresh_token": "",
        "download_dir": str(Path.home() / "Pictures" / "Pixiv"),
        "proxy": "",
        "language": "auto",
        "theme": "dark",
        "download_mode": "normal",
        "download_delay": 0.5,
        "api_request_delay": 0.3,
        "max_results": 30,
        "rate_limit_retry_delay": 150.0,
        "max_retries": 3,
        "parallel_workers": 3,
    }

    VALIDATORS = {
        'download_delay':         ('float', 0.0, 60.0),
        'api_request_delay':      ('float', 0.0, 60.0),
        'max_results':            ('int',   1,   500),
        'rate_limit_retry_delay': ('float', 1.0, 3600.0),
        'max_retries':            ('int',   1,   100),
        'parallel_workers':       ('int',   1,   8),
    }

    def __init__(self):
        self.config = self._load_or_init()

    def _load_or_init(self) -> dict:
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, 'rb') as f:
                    cfg = tomllib.load(f)
                write_log(t('config_loaded', path=str(CONFIG_FILE)), 'info')
                merged = self._merge_defaults(cfg)
                validated, errors = self._validate(merged)
                for key, val, default, err in errors:
                    write_log(t('config_invalid', key=key, value=val,
                                default=default, error=err), 'warn')
                self.config = validated
                if errors:
                    self.save()
                write_log(t('config_validated'), 'info')
                return self.config
            except Exception as e:
                write_log(t('config_load_failed', error=str(e)), 'warn')
                self.config = self.DEFAULT_CONFIG.copy()
                self.save()
                return self.config

        if LEGACY_CONFIG_FILE.exists():
            try:
                with open(LEGACY_CONFIG_FILE, 'r', encoding='utf-8') as f:
                    old = json.load(f)
                merged = self._merge_defaults(old)
                for k in ("exiftool_path", "username", "password", "api_language"):
                    merged.pop(k, None)
                validated, errors = self._validate(merged)
                self.config = validated
                self.save()
                write_log(t('config_migrated', path=str(CONFIG_FILE)), 'info')
                return self.config
            except Exception as e:
                write_log(t('config_load_failed', error=str(e)), 'warn')

        self.config = self.DEFAULT_CONFIG.copy()
        self.save()
        write_log(t('config_created', path=str(CONFIG_FILE)), 'info')
        return self.config

    def _merge_defaults(self, cfg: dict) -> dict:
        merged = self.DEFAULT_CONFIG.copy()
        for k, v in cfg.items():
            if k in merged:
                merged[k] = v
        return merged

    def _validate(self, cfg: dict):
        errors = []
        result = dict(cfg)
        for key, (typ, lo, hi) in self.VALIDATORS.items():
            if key not in result:
                continue
            try:
                v = result[key]
                if typ == 'int':
                    if isinstance(v, str):
                        v = int(v)
                    if isinstance(v, bool) or not isinstance(v, int):
                        raise ValueError('not an integer')
                else:
                    if isinstance(v, str):
                        v = float(v)
                    if isinstance(v, bool) or not isinstance(v, (int, float)):
                        raise ValueError('not a number')
                    v = float(v)
                if v < lo or v > hi:
                    raise ValueError(f'out of range [{lo}, {hi}]')
                result[key] = v
            except (ValueError, TypeError) as e:
                default = self.DEFAULT_CONFIG[key]
                errors.append((key, cfg[key], default, str(e)))
                result[key] = default

        for key in ('refresh_token', 'download_dir', 'proxy'):
            if key in result and not isinstance(result[key], str):
                errors.append((key, result[key], self.DEFAULT_CONFIG[key], 'not a string'))
                result[key] = self.DEFAULT_CONFIG[key]

        if result.get('language') not in ('auto', 'zh-CN', 'en'):
            result['language'] = 'auto'
        if result.get('theme') not in ('dark', 'light'):
            result['theme'] = 'dark'
        if result.get('download_mode') not in ('normal', 'high'):
            result['download_mode'] = 'normal'

        return result, errors

    def _to_toml(self, cfg: dict) -> str:
        lines = []
        for k, v in cfg.items():
            if isinstance(v, str):
                esc = v.replace('\\', '\\\\').replace('"', '\\"')
                lines.append(f'{k} = "{esc}"')
            elif isinstance(v, bool):
                lines.append(f'{k} = {"true" if v else "false"}')
            elif isinstance(v, int):
                lines.append(f'{k} = {v}')
            elif isinstance(v, float):
                lines.append(f'{k} = {v}')
        return "\n".join(lines) + "\n"

    def save(self):
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                f.write(self._to_toml(self.config))
        except Exception as e:
            write_log(t('config_save_failed', error=str(e)), 'error')

    def get(self, key, default=None):
        return self.config.get(key, default)

    def set(self, key, value):
        self.config[key] = value
        self.save()

    def effective_language(self) -> str:
        lang = self.config.get("language", "auto")
        if lang == "auto":
            return detect_system_language()
        return lang if lang in ('zh-CN', 'en') else 'en'


# ============================================================
# Accounts / 账户
# ============================================================
class AccountsManager:
    """Multi-account storage / 多账号存储"""

    def __init__(self, config):
        self.config = config
        self.data = self._load()
        self._lock = threading.Lock()
        self._ensure_migration()

    def _load(self) -> dict:
        if ACCOUNTS_FILE.exists():
            try:
                with open(ACCOUNTS_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                # Old format (single account) / 旧格式
                if 'accounts' not in data:
                    return {
                        'current_index': 0,
                        'accounts': [{
                            'refresh_token': self.config.get('refresh_token', ''),
                            'profile': data.get('profile', {}),
                            'following': data.get('following', []),
                            'bookmarks': data.get('bookmarks', []),
                        }]
                    }
                return data
            except Exception as e:
                write_log(f"accounts.json load failed: {e}", 'warn')
        return {'current_index': 0, 'accounts': []}

    def _ensure_migration(self):
        """Migrate from config.toml if no accounts exist / 从 config 迁移"""
        if not self.data['accounts']:
            rt = self.config.get('refresh_token', '')
            if rt:
                self.data['accounts'].append({
                    'refresh_token': rt,
                    'profile': {},
                    'following': [],
                    'bookmarks': [],
                })
                self.data['current_index'] = 0
                self.save()
                write_log("Migrated refresh_token from config.toml", 'info')
        else:
            idx = self.data.get('current_index', 0)
            if 0 <= idx < len(self.data['accounts']):
                cur_rt = self.data['accounts'][idx].get('refresh_token', '')
                if cur_rt and cur_rt != self.config.get('refresh_token'):
                    self.config.set('refresh_token', cur_rt)

    def save(self):
        try:
            with open(ACCOUNTS_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            write_log(f"accounts.json save failed: {e}", 'error')

    def list_accounts(self) -> list:
        out = []
        for i, acc in enumerate(self.data['accounts']):
            p = acc.get('profile', {})
            out.append({
                'index': i,
                'id': p.get('id'),
                'name': p.get('name', ''),
                'account': p.get('account', ''),
                'avatar': p.get('avatar', ''),
                'is_current': i == self.data.get('current_index', 0),
            })
        return out

    def get_current(self):
        idx = self.data.get('current_index', 0)
        if 0 <= idx < len(self.data['accounts']):
            return self.data['accounts'][idx]
        return None

    def get_current_profile(self) -> dict:
        cur = self.get_current()
        return cur.get('profile', {}) if cur else {}

    def set_current_profile(self, profile: dict):
        idx = self.data.get('current_index', 0)
        if 0 <= idx < len(self.data['accounts']):
            self.data['accounts'][idx]['profile'] = profile
            self.save()

    def set_current_following(self, items: list):
        idx = self.data.get('current_index', 0)
        if 0 <= idx < len(self.data['accounts']):
            self.data['accounts'][idx]['following'] = items
            self.save()

    def get_current_following(self) -> list:
        cur = self.get_current()
        return cur.get('following', []) if cur else []

    def set_current_bookmarks(self, items: list):
        idx = self.data.get('current_index', 0)
        if 0 <= idx < len(self.data['accounts']):
            self.data['accounts'][idx]['bookmarks'] = items
            self.save()

    def get_current_bookmarks(self) -> list:
        cur = self.get_current()
        return cur.get('bookmarks', []) if cur else []

    def add_account(self, refresh_token: str) -> int:
        for i, acc in enumerate(self.data['accounts']):
            if acc.get('refresh_token') == refresh_token:
                self.data['current_index'] = i
                self.config.set('refresh_token', refresh_token)
                self.save()
                return i
        self.data['accounts'].append({
            'refresh_token': refresh_token,
            'profile': {},
            'following': [],
            'bookmarks': [],
        })
        self.data['current_index'] = len(self.data['accounts']) - 1
        self.config.set('refresh_token', refresh_token)
        self.save()
        return self.data['current_index']

    def switch_account(self, index: int) -> bool:
        if 0 <= index < len(self.data['accounts']):
            self.data['current_index'] = index
            rt = self.data['accounts'][index].get('refresh_token', '')
            self.config.set('refresh_token', rt)
            self.save()
            return True
        return False

    def remove_account(self, index: int) -> bool:
        if 0 <= index < len(self.data['accounts']):
            self.data['accounts'].pop(index)
            if not self.data['accounts']:
                self.data['current_index'] = 0
            else:
                self.data['current_index'] = min(
                    self.data.get('current_index', 0),
                    len(self.data['accounts']) - 1
                )
                cur_rt = self.data['accounts'][self.data['current_index']].get('refresh_token', '')
                self.config.set('refresh_token', cur_rt)
            self.save()
            return True
        return False

# ============================================================
# Session / 会话（合并 queue.json）
# ============================================================
class SessionManager:
    """session.json: queue + UI state / 队列 + UI 状态"""

    def __init__(self):
        self.data = self._load()
        self._lock = threading.Lock()

    def _load(self) -> dict:
        # 优先从新 session.json 加载
        if SESSION_FILE.exists():
            try:
                with open(SESSION_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                write_log(f"session.json load failed: {e}", 'warn')
        # 回退：从旧 queue.json 迁移
        if LEGACY_QUEUE_FILE.exists():
            try:
                with open(LEGACY_QUEUE_FILE, 'r', encoding='utf-8') as f:
                    old = json.load(f)
                session = {
                    'queue': old,
                    'ui_state': {},
                }
                # 迁移后删除旧文件
                LEGACY_QUEUE_FILE.unlink()
                write_log("Migrated queue.json to session.json", 'info')
                return session
            except Exception as e:
                write_log(f"queue.json migrate failed: {e}", 'warn')
        return {'queue': {'current_tasks': [], 'failed_tasks': []}, 'ui_state': {}}

    def save(self):
        with self._lock:
            try:
                with open(SESSION_FILE, 'w', encoding='utf-8') as f:
                    json.dump(self.data, f, indent=2, ensure_ascii=False)
            except Exception as e:
                write_log(f"session.json save failed: {e}", 'error')

    def get_queue(self) -> dict:
        return self.data.get('queue', {'current_tasks': [], 'failed_tasks': []})

    def set_queue(self, queue_data: dict):
        self.data['queue'] = queue_data
        self.save()

    def get_ui_state(self) -> dict:
        return self.data.get('ui_state', {})

    def set_ui_state(self, state: dict):
        self.data['ui_state'] = state
        self.save()

    def clear_queue(self):
        self.data['queue'] = {'current_tasks': [], 'failed_tasks': []}
        self.save()


# ============================================================
# ExifTool probe
# ============================================================
def get_exiftool_version(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    try:
        r = subprocess.run([str(path), "-ver"],
                           capture_output=True, text=True,
                           encoding='utf-8', errors='ignore', timeout=5)
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception as e:
        write_log(t('exiftool_version_error', error=str(e)), 'warn')
    return None


# ============================================================
# Console minimize
# ============================================================
def minimize_console_window() -> bool:
    if sys.platform != 'win32' or not getattr(sys, 'frozen', False):
        return False
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 6)
            return True
    except Exception:
        pass
    return False


# ============================================================
# History
# ============================================================
_history_lock = threading.Lock()


def load_history():
    if not HISTORY_FILE.exists():
        return []
    try:
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        write_log(t('history_load_failed', error=str(e)), 'error')
        return []


def append_history(entry):
    with _history_lock:
        history = load_history()
        pid = entry.get('id')
        for h in history[:100]:
            if h.get('id') == pid:
                return
        history.insert(0, entry)
        if len(history) > HISTORY_MAX:
            history = history[:HISTORY_MAX]
        try:
            with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
                json.dump(history, f, indent=2, ensure_ascii=False)
        except Exception as e:
            write_log(t('history_save_failed', error=str(e)), 'error')


def format_date(s):
    if not s:
        return ''
    return s.replace('T', ' ')[:19]


# ============================================================
# Latency
# ============================================================
def measure_latency_sync(config):
    proxy = config.get("proxy") or None
    proxies = {"http": proxy, "https": proxy} if proxy else None
    url = "https://www.cloudflare.com/cdn-cgi/trace"
    try:
        t0 = time.time()
        with requests.get(url, timeout=5, proxies=proxies,
                          stream=True, headers={"User-Agent": "Mozilla/5.0"}) as r:
            for _ in r.iter_content(512):
                break
        return int((time.time() - t0) * 1000)
    except Exception as e:
        write_log(t('latency_failed', error=str(e)), 'warn')
        return None


# ============================================================
# Rate limiter
# ============================================================
class RateLimiter:
    def __init__(self):
        self.lock = threading.Lock()
        self.cond = threading.Condition(self.lock)
        self.limited = False
        self.until = 0.0
        self.on_limited = None

    def wait_if_limited(self):
        with self.cond:
            while self.limited:
                rem = self.until - time.time()
                if rem > 0:
                    self.cond.wait(timeout=rem)
                else:
                    self.limited = False
                    self.cond.notify_all()
                    break

    def set_limited(self, delay):
        with self.cond:
            self.limited = True
            self.until = time.time() + delay
            self.cond.notify_all()
        if self.on_limited:
            try:
                self.on_limited(delay)
            except Exception:
                pass


# ============================================================
# Pixiv API
# ============================================================
class PixivAPI:
    def __init__(self, config, rate_limiter):
        self.config = config
        self.rate_limiter = rate_limiter
        self.api = None
        self.logged_in = False
        self._lock = threading.Lock()

    def login(self):
        if self.api is None:
            self.api = AppPixivAPI()
            proxy = self.config.get("proxy")
            if proxy:
                self.api.set_proxy(proxy)
        rt = self.config.get("refresh_token")
        if not rt:
            write_log(t('no_token'), 'error')
            self.logged_in = False
            return False
        try:
            self.api.auth(refresh_token=rt)
            self.logged_in = True
            write_log(t('login_success'), 'info')
            return True
        except Exception as e:
            write_log(t('login_failed', error=str(e)), 'error')
            self.logged_in = False
            if self.api:
                self.api.access_token = None
            return False

    def ensure_login(self):
        if not self.logged_in:
            with self._lock:
                if not self.logged_in:
                    self.login()

    def _call_with_retry(self, func, *args, **kwargs):
        max_retries = int(self.config.get("max_retries", 3))
        delay = float(self.config.get("rate_limit_retry_delay", 150))
        for attempt in range(max_retries + 1):
            self.rate_limiter.wait_if_limited()
            try:
                result = func(*args, **kwargs)
                if isinstance(result, dict) and 'error' in result:
                    emsg = str(result['error']).lower()
                    if 'rate limit' in emsg or '429' in emsg:
                        self.rate_limiter.set_limited(delay)
                        write_log(t('rate_limited', delay=delay), 'warn')
                        continue
                return result
            except Exception as e:
                emsg = str(e).lower()
                if 'rate limit' in emsg or '429' in emsg:
                    self.rate_limiter.set_limited(delay)
                    write_log(t('rate_limited', delay=delay), 'warn')
                    continue
                raise
        raise Exception(t('api_retry_exhausted'))

    def get_illust_detail(self, iid):
        self.ensure_login()
        return self._call_with_retry(self.api.illust_detail, iid).get("illust", {})

    def search_illust(self, word, target='exact_match_for_tags', sort='date_desc',
                      offset=0, duration=None, start_date=None, end_date=None):
        self.ensure_login()
        kwargs = {'search_target': target, 'sort': sort, 'offset': offset}
        if start_date and end_date:
            kwargs['start_date'] = start_date
            kwargs['end_date'] = end_date
        elif duration:
            kwargs['duration'] = duration
        return self._call_with_retry(self.api.search_illust, word, **kwargs)

    def get_ranking(self, mode='day', date=None, offset=0):
        self.ensure_login()
        return self._call_with_retry(self.api.illust_ranking, mode, date=date, offset=offset)

    def search_users(self, word, offset=0):
        self.ensure_login()
        return self._call_with_retry(self.api.search_user, word, offset=offset)

    def get_user_detail(self, uid):
        self.ensure_login()
        return self._call_with_retry(self.api.user_detail, uid)

    def get_user_illusts(self, uid, offset=0):
        self.ensure_login()
        return self._call_with_retry(self.api.user_illusts, uid, offset=offset)

    def get_illust_recommended(self, **kwargs):
        self.ensure_login()
        return self._call_with_retry(self.api.illust_recommended, **kwargs)

    def get_illust_follow(self, restrict='all', offset=0):
        self.ensure_login()
        return self._call_with_retry(self.api.illust_follow,
                                     restrict=restrict, offset=offset)

    def get_user_bookmarks(self, uid, restrict='public', offset=0):
        self.ensure_login()
        return self._call_with_retry(self.api.user_bookmarks_illust, uid,
                                     restrict=restrict, offset=offset)

    def follow_user(self, uid, restrict='public'):
        self.ensure_login()
        return self._call_with_retry(self.api.user_follow_add, uid, restrict=restrict)

    def unfollow_user(self, uid):
        self.ensure_login()
        return self._call_with_retry(self.api.user_follow_del, uid)

    def download_image(self, url, path, headers=None):
        if headers is None:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                              "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
                "Referer": "https://www.pixiv.net/",
            }
        try:
            r = requests.get(url, headers=headers, stream=True, timeout=30)
            if r.status_code == 200:
                with open(path, 'wb') as f:
                    for chunk in r.iter_content(1024):
                        f.write(chunk)
                return True
            write_log(t('download_failed', url=f"HTTP {r.status_code}"), 'warn')
            return False
        except Exception as e:
            write_log(t('download_failed', url=str(e)), 'error')
            return False

    def illust_bookmark_add(self, iid, restrict='public'):
        self.ensure_login()
        return self._call_with_retry(self.api.illust_bookmark_add, iid, restrict=restrict)

    def illust_bookmark_delete(self, iid):
        self.ensure_login()
        return self._call_with_retry(self.api.illust_bookmark_delete, iid)


# ============================================================
# ExifTool wrapper
# ============================================================
def _exiftool_cstr(s: str) -> str:
    return (s.replace("\\", "\\\\")
             .replace("\r\n", "\\n")
             .replace("\n", "\\n")
             .replace("\r", "\\n")
             .replace("\t", "\\t"))


class ExifToolWrapper:
    def __init__(self, path):
        self.exiftool_path = Path(path)
        if not self.exiftool_path.exists():
            write_log(t('exiftool_not_found', path=str(self.exiftool_path)), 'warn')

    def write_metadata(self, image_path, metadata, ignore_minor=False, export_json=False):
        if not self.exiftool_path.exists():
            return False, None

        json_path = None
        if export_json:
            json_path = image_path.with_suffix('.json')
            try:
                with open(json_path, 'w', encoding='utf-8') as jf:
                    json.dump(metadata, jf, indent=2, ensure_ascii=False)
            except Exception as e:
                write_log(t('exiftool_json_failed', error=str(e)), 'error')
                json_path = None

        args_file = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                                             suffix='.args', delete=False) as f:
                args_file = f.name
                f.write("#[CSTR]-charset=UTF8\n")
                f.write("#[CSTR]-charset=filename=UTF8\n")
                if ignore_minor:
                    f.write("-m\n")
                f.write("-overwrite_original\n")
                for tag, value in metadata.items():
                    if value is None:
                        continue
                    if isinstance(value, list):
                        for it in value:
                            if it == "":
                                continue
                            raw = str(it).strip()
                            if not raw:
                                continue
                            escaped = _exiftool_cstr(raw)
                            f.write(f"#[CSTR]-{tag}={escaped}\n")
                    else:
                        raw = str(value).strip()
                        if not raw:
                            continue
                        escaped = _exiftool_cstr(raw)
                        f.write(f"#[CSTR]-{tag}={escaped}\n")
                f.write(str(image_path.absolute()) + "\n")
        except Exception as e:
            write_log(t('exiftool_args_failed', error=str(e)), 'error')
            return False, json_path

        cmd = [str(self.exiftool_path), "-@", args_file]
        for attempt in range(2):
            try:
                r = subprocess.run(cmd, capture_output=True, text=True,
                                   encoding='utf-8', errors='ignore', timeout=60)
                if r.returncode == 0:
                    return True, json_path
                write_log(t('exiftool_failed', code=r.returncode,
                            stderr=r.stderr.strip()), 'warn')
                if attempt == 0:
                    time.sleep(0.5)
                else:
                    return False, json_path
            except Exception as e:
                write_log(t('exiftool_exception', error=str(e)), 'error')
                if attempt == 0:
                    time.sleep(0.5)
                else:
                    return False, json_path
            finally:
                if args_file and os.path.exists(args_file):
                    try:
                        os.unlink(args_file)
                    except Exception:
                        pass
        return False, json_path


# ============================================================
# Download worker
# ============================================================
class DownloadWorker:
    def __init__(self, config, session: SessionManager):
        self.config = config
        self.session = session
        self.rate_limiter = RateLimiter()
        self.api = PixivAPI(config, self.rate_limiter)
        self.exiftool = ExifToolWrapper(str(get_resource_path("plugins/ExifTool.exe")))
        self.download_dir = Path(config.get("download_dir"))
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.url_queue = queue.Queue()
        self.workers = []
        self.is_running = False
        self.should_stop = False
        self._active_threads = 0
        self._threads_lock = threading.Lock()
        self.failed_items = []
        self.failed_lock = threading.Lock()
        self.processed_count = 0
        self.status_callback = None

    def set_status_callback(self, cb):
        self.status_callback = cb

    def _emit(self, msg, level='info'):
        write_log(msg, level)
        if self.status_callback:
            self.status_callback(msg, level)

    def _current_workers(self) -> int:
        mode = self.config.get("download_mode", "normal")
        if mode == "normal":
            return 1
        return max(1, min(8, int(self.config.get("parallel_workers", 3))))

    def _save_queue(self):
        try:
            with self.url_queue.mutex:
                items = list(self.url_queue.queue)
            current_tasks = []
            for item in items:
                if isinstance(item, tuple):
                    # retry tuple: (url, img_path, metadata, True)
                    current_tasks.append(item[0])
                elif isinstance(item, dict):
                    current_tasks.append(item)
                else:
                    current_tasks.append(item)
            with self.failed_lock:
                failed_tasks = [
                    {"pid": pid,
                     "img_path": str(img_path) if img_path else None,
                     "metadata": meta or {}}
                    for pid, img_path, meta in self.failed_items
                ]
            self.session.set_queue({
                'current_tasks': current_tasks,
                'failed_tasks': failed_tasks,
            })
            return True
        except Exception as e:
            write_log(t('queue_save_failed', error=str(e)), 'error')
            return False

    def add_items(self, items: list):
        """
        items: list of {url: str, metadata?: dict}
        / 列表项：{url, metadata?}
        """
        n = 0
        for it in items:
            if isinstance(it, str):
                it = {'url': it}
            if not isinstance(it, dict) or not it.get('url'):
                continue
            self.url_queue.put(it)
            n += 1
        if n > 0:
            self._emit(t('enqueued_n', n=n), 'info')
            self._save_queue()
            if not self.is_running:
                self.start()
        return n

    def get_queue_length(self):
        return self.url_queue.qsize()

    def start(self):
        if self.is_running:
            return False
        if self.url_queue.empty():
            self._emit(t('queue_empty'), 'warn')
            return False
        self.should_stop = False
        self.is_running = True
        self._active_threads = 0
        n = self._current_workers()
        for _ in range(n):
            th = threading.Thread(target=self._worker_loop, daemon=True)
            th.start()
            self.workers.append(th)
        self._emit(t('workers_started', n=n), 'info')
        return True

    def stop(self):
        self.should_stop = True
        self._emit(t('stopping_queue'), 'info')

    def clear_queue(self):
        if self.is_running:
            self._emit(t('cannot_clear_running'), 'warn')
            return 0
        n = self.url_queue.qsize()
        while not self.url_queue.empty():
            try:
                self.url_queue.get_nowait()
            except queue.Empty:
                break
        self._emit(t('queue_cleared', n=n), 'info')
        self._save_queue()
        return n

    def retry_failed(self):
        if self.is_running:
            self._emit(t('cannot_retry_running'), 'warn')
            return 0
        with self.failed_lock:
            if not self.failed_items:
                self._emit(t('no_failed_tasks'), 'info')
                return 0
            n = len(self.failed_items)
            for pid, img_path, meta_d in self.failed_items:
                url = f"https://www.pixiv.net/artworks/{pid}"
                self.url_queue.put((url, img_path, meta_d, True))
            self.failed_items.clear()
        self._emit(t('requeued_failed', n=n), 'info')
        self.start()
        return n

    def get_failed_count(self):
        with self.failed_lock:
            return len(self.failed_items)

    def _worker_loop(self):
        with self._threads_lock:
            self._active_threads += 1
        self.api.ensure_login()
        while not self.should_stop:
            try:
                item = self.url_queue.get(timeout=1)
            except queue.Empty:
                break
            if isinstance(item, tuple) and len(item) == 4:
                # Retry tuple
                url, img_path, meta_d, _ = item
                self._emit(t('task_retry', url=url), 'info')
                ok, _ = self.exiftool.write_metadata(img_path, meta_d,
                                                     ignore_minor=True, export_json=True)
                if ok:
                    self._emit(t('retry_success', url=url), 'info')
                else:
                    self._emit(t('retry_failed', url=url), 'error')
                    with self.failed_lock:
                        pid = self._parse_url(url)[1]
                        self.failed_items.append((pid, img_path, meta_d))
            else:
                # Dict item: {url, metadata?}
                url = item.get('url')
                cached = item.get('metadata')
                self._emit(t('processing', url=url,
                             remaining=self.url_queue.qsize()), 'info')
                ok, pid, img_path, meta_d = self._process_url(url, cached_meta=cached)
                if ok:
                    self._emit(t('task_success', url=url), 'info')
                else:
                    self._emit(t('task_failed', url=url), 'error')
                    if img_path and meta_d:
                        with self.failed_lock:
                            self.failed_items.append((pid, img_path, meta_d))
            self.processed_count += 1
            self._save_queue()
            time.sleep(float(self.config.get("download_delay", 0.5)))
            self.url_queue.task_done()
        with self._threads_lock:
            self._active_threads -= 1
            if self._active_threads == 0:
                self.is_running = False
                self.should_stop = False
                has_remaining = not self.url_queue.empty()
                has_failed = self.get_failed_count() > 0
                if not has_remaining and not has_failed:
                    self.session.set_queue({'current_tasks': [], 'failed_tasks': []})
                    write_log(t('queue_finished_empty'), 'info')
                else:
                    self._save_queue()
                    write_log(t('queue_finished_partial',
                                pending=self.url_queue.qsize(),
                                failed=self.get_failed_count()), 'info')
                self._emit(t('workers_stopped'), 'info')
                if has_remaining and not self.should_stop:
                    self.start()

    def _process_url(self, url, cached_meta=None):
        try:
            typ, iid = self._parse_url(url)
        except ValueError:
            write_log(t('invalid_url', url=url), 'error')
            return False, None, None, None
        return self._process_illust(iid, cached_meta=cached_meta)

    def _parse_url(self, url):
        m = re.search(r'/artworks/(\d+)', url)
        if m:
            return 'illust', int(m.group(1))
        if url.isdigit():
            return 'illust', int(url)
        raise ValueError(url)

    def _process_illust(self, iid, cached_meta=None):
        # Reuse cached illust metadata if available / 若有缓存元数据则复用
        if cached_meta and cached_meta.get('illust'):
            info = cached_meta['illust']
            write_log(f"Using cached metadata for {iid}", 'info')
        else:
            info = self.api.get_illust_detail(iid)
        if not info:
            write_log(t('illust_fetch_failed', id=iid), 'warn')
            return False, iid, None, None
        if not info.get('visible', False):
            write_log(t('illust_invisible', id=iid), 'warn')
            return False, iid, None, None

        title = info.get('title', '')
        author = info.get('user', {}).get('name', '')
        author_id = info.get('user', {}).get('id')
        create_date = info.get('create_date', '')
        caption = info.get('caption', '')
        tags = info.get('tags', [])
        x_restrict = info.get('x_restrict', 0)
        ai_type = info.get('illust_ai_type', 0)
        page_count = info.get('page_count', 1)
        single = info.get('meta_single_page', {})
        pages = info.get('meta_pages', [])
        restr_attrs = info.get('restriction_attributes', [])

        tag_names = [x.get('name', '') for x in tags]
        trans_names = [x.get('translated_name', '') for x in tags]
        tag_strs = []
        for i, n in enumerate(tag_names):
            tr = trans_names[i] if i < len(trans_names) else ''
            tag_strs.append(f"{n}({tr})" if tr else n)

        pri = []
        if ai_type == 2:
            pri.append(meta('ai_generated'))
        if x_restrict == 1:
            pri.append("R-18")
        elif x_restrict == 2:
            pri.append("R-18G")
        if restr_attrs:
            pri.append("R-15")
        final_tags = pri + tag_strs

        cap = self._clean_caption(caption)
        desc = f"{meta('source_url')}: https://www.pixiv.net/artworks/{iid}"
        if cap:
            desc += f"\n{meta('description')}: {cap}"

        metadata = {
            "XMP-dc:title": title, "EXIF:ImageDescription": title, "EXIF:XPTitle": title,
            "XMP-dc:creator": author, "EXIF:Artist": author, "EXIF:XPAuthor": author,
            "XMP-dc:subject": final_tags, "EXIF:XPKeywords": ",".join(final_tags),
            "XMP:CreateDate": create_date, "XMP:MetadataDate": create_date,
            "EXIF:DateTimeOriginal": create_date, "EXIF:CreateDate": create_date,
            "EXIF:ModifyDate": create_date,
            "XMP-dc:description": desc,
            "EXIF:XPComment": f"{meta('source_url')}: https://www.pixiv.net/artworks/{iid}",
        }

        urls = []
        if page_count == 1:
            u = single.get('original_image_url')
            if u:
                urls.append(u)
        else:
            for p in pages:
                im = p.get('image_urls', {})
                u = im.get('original') or im.get('large') or im.get('medium')
                if u:
                    urls.append(u)
        if not urls:
            write_log(t('no_image_url', id=iid), 'warn')
            return False, iid, None, metadata

        saved = []
        for u in urls:
            base = u.split('?')[0]
            fname = os.path.basename(base)
            if not fname:
                ext = os.path.splitext(base)[1] or '.jpg'
                fname = f"{iid}{ext}" if page_count == 1 else f"{iid}_p{urls.index(u)+1}{ext}"
            sp = self.download_dir / fname
            if sp.exists():
                write_log(t('file_exists', path=str(sp)), 'info')
                saved.append(sp)
                continue
            write_log(t('downloading', url=u, path=str(sp)), 'info')
            if self.api.download_image(u, sp):
                write_log(t('download_done', path=str(sp)), 'info')
                ok, _ = self.exiftool.write_metadata(sp, metadata,
                                                     ignore_minor=False, export_json=False)
                if ok:
                    saved.append(sp)
                else:
                    write_log(t('metadata_failed', path=str(sp)), 'warn')
                    return False, iid, sp, metadata
            else:
                return False, iid, None, metadata

        restr_str = ""
        if x_restrict == 1:
            restr_str = "R-18"
        elif x_restrict == 2:
            restr_str = "R-18G"
        elif restr_attrs:
            restr_str = "R-15"
        append_history({
            'id': iid, 'title': title, 'page_count': page_count,
            'author': author, 'author_id': author_id,
            'tags': final_tags,
            'ai_generated': ai_type == 2,
            'sensitive': x_restrict > 0 or bool(restr_attrs),
            'restriction': restr_str,
            'publish_time': format_date(create_date),
            'downloaded_at': int(time.time()),
        })
        return True, iid, (saved[0] if saved else None), metadata

    def _clean_caption(self, caption):
        if not caption:
            return ""
        caption = re.sub(r'<br\s*/?>', '\n', caption, flags=re.IGNORECASE)
        caption = re.sub(r'<[^>]+>', '', caption)
        lines = caption.split('\n')
        cleaned = []
        for line in lines:
            line = re.sub(r'[ \t]+', ' ', line).strip()
            if line:
                cleaned.append(line)
        return '\n'.join(cleaned)


# ============================================================
# WebSocket bridge
# ============================================================
class WebBridge:
    def __init__(self, config, accounts: AccountsManager, session: SessionManager):
        self.config = config
        self.accounts = accounts
        self.session = session
        self.loop = None
        self.clients = set()
        self.clients_lock = threading.Lock()
        self.worker = DownloadWorker(config, session)
        self.worker.set_status_callback(self.on_worker_status)
        self.worker.rate_limiter.on_limited = self._on_rate_limited

    def set_loop(self, loop):
        self.loop = loop

    def on_worker_status(self, msg, level='info'):
        self.broadcast(self._queue_status_payload())

    def _queue_status_payload(self):
        return {
            'type': 'queue_status',
            'queue': self.worker.get_queue_length(),
            'failed': self.worker.get_failed_count(),
            'processed': self.worker.processed_count,
            'running': self.worker.is_running,
            'stopping': self.worker.should_stop and self.worker.is_running,
            'mode': self.config.get('download_mode', 'normal'),
            'workers': self.worker._current_workers(),
        }

    def _on_rate_limited(self, delay):
        self.broadcast({'type': 'rate_limited', 'delay': int(delay)})

    async def register(self, ws):
        with self.clients_lock:
            self.clients.add(ws)

    async def unregister(self, ws):
        with self.clients_lock:
            self.clients.discard(ws)

    def broadcast(self, msg):
        if self.loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._broadcast(msg), self.loop)

    async def _broadcast(self, msg):
        with self.clients_lock:
            clients = list(self.clients)
        if not clients:
            return
        data = json.dumps(msg, ensure_ascii=False)
        await asyncio.gather(*[ws.send_str(data) for ws in clients],
                             return_exceptions=True)


# ============================================================
# Formatters
# ============================================================
def _slim_illust(info: dict) -> dict:
    """Keep only fields needed by downloader / 精简 illust，仅保留下载所需字段"""
    if not isinstance(info, dict):
        return {}
    user = info.get('user', {}) or {}
    return {
        'id': info.get('id'),
        'title': info.get('title', ''),
        'user': {
            'id': user.get('id'),
            'name': user.get('name', ''),
        },
        'create_date': info.get('create_date', ''),
        'caption': info.get('caption', ''),
        'tags': info.get('tags', []),
        'x_restrict': info.get('x_restrict', 0),
        'illust_ai_type': info.get('illust_ai_type', 0),
        'page_count': info.get('page_count', 1),
        'meta_single_page': info.get('meta_single_page', {}),
        'meta_pages': info.get('meta_pages', []),
        'restriction_attributes': info.get('restriction_attributes', []),
        'visible': info.get('visible', True),
        'type': info.get('type', 'illust'),
    }

def format_item(it):
    pid = it.get('id')
    user = it.get('user', {}) or {}
    avatar = (user.get('profile_image_urls', {}) or {}).get('medium', '')

    ai_type = it.get('illust_ai_type', 0)
    x_restrict = it.get('x_restrict', 0)
    restr_attrs = it.get('restriction_attributes', [])
    if x_restrict == 1:
        restriction = "R-18"
    elif x_restrict == 2:
        restriction = "R-18G"
    elif restr_attrs:
        restriction = "R-15"
    else:
        restriction = ""

    tags_out = []
    for x in it.get('tags', []):
        name = x.get('name', '') or ''
        trans = x.get('translated_name', '') or ''
        tags_out.append(f"{name}({trans})" if trans else name)

    return {
        'id': pid,
        'title': it.get('title', ''),
        'author': user.get('name', ''),
        'author_id': user.get('id'),
        'author_account': user.get('account', ''),
        'author_avatar': avatar,
        'views': it.get('total_view', 0) or 0,
        'bookmarks': it.get('total_bookmarks', 0) or 0,
        'is_bookmarked': bool(it.get('is_bookmarked', False)),
        'tags': tags_out,
        'ai_generated': ai_type == 2,
        'sensitive': x_restrict > 0 or bool(restr_attrs),
        'restriction': restriction,
        'is_new': False,
        'date': format_date(it.get('create_date', '') or ''),
        'type': it.get('type', 'illust'),
        'page_count': it.get('page_count', 1) or 1,
    }

def format_user(u):
    return {'id': u.get('id'), 'name': u.get('name', ''),
            'account': u.get('account', ''), 'is_followed': u.get('is_followed', False)}


def format_user_detail(data, extra=None):
    user = data.get('user', {})
    profile = data.get('profile', {})
    result = {
        'id': user.get('id'), 'name': user.get('name', ''),
        'account': user.get('account', ''), 'comment': user.get('comment', ''),
        'is_followed': user.get('is_followed', False),
        'avatar': user.get('profile_image_urls', {}).get('medium', ''),
        'region': profile.get('region', ''),
        'country_code': profile.get('country_code', ''),
        'gender': profile.get('gender', ''),
        'birth_day': profile.get('birth_day', ''),
        'webpage': profile.get('webpage'),
        'twitter_account': profile.get('twitter_account', ''),
        'total_follow_users': profile.get('total_follow_users', 0),
        'total_illusts': profile.get('total_illusts', 0),
        'total_manga': profile.get('total_manga', 0),
        'total_novels': profile.get('total_novels', 0),
        'total_illust_bookmarks_public': profile.get('total_illust_bookmarks_public', 0),
        'is_premium': profile.get('is_premium', False),
        'is_accept_request': None,
        'background_image_url': profile.get('background_image_url'),
        'profile_publicity': data.get('profile_publicity', {}),
        'workspace': data.get('workspace', {}),
    }
    if extra:
        result.update(extra)
    return result


def parse_bookmark_html(html):
    urls = []
    try:
        soup = BeautifulSoup(html, 'html.parser')
        for a in soup.find_all('a', href=True):
            href = a['href']
            if re.search(r'/artworks/\d+', href):
                if href.startswith('/'):
                    href = 'https://www.pixiv.net' + href
                urls.append(href)
    except Exception as e:
        write_log(t('bookmark_parse_failed', error=str(e)), 'error')
    return list(set(urls))


# ============================================================
# Command handler
# ============================================================
async def handle_command(bridge, cmd, ws):
    c = cmd.get('cmd')

    if c == 'login':
        rt = cmd.get('refresh_token', '').strip()
        if not rt:
            await ws.send_str(json.dumps({'type': 'login_result',
                                          'success': False,
                                          'msg': 'Refresh token is required'}))
            return
        bridge.config.set('refresh_token', rt)
        loop = asyncio.get_event_loop()

        def do_login():
            bridge.worker.api.logged_in = False
            bridge.worker.api.api = None
            return bridge.worker.api.login()

        ok = await loop.run_in_executor(None, do_login)
        await ws.send_str(json.dumps({'type': 'login_result', 'success': ok,
                                      'msg': 'Login succeeded' if ok
                                             else 'Login failed, check your refresh token'}))

    elif c == 'set_language':
        lang = cmd.get('lang', '')
        if lang in ('zh-CN', 'en'):
            bridge.config.set('language', lang)
            set_language(lang)
            write_log(t('language_loaded', lang=lang), 'info')
            await ws.send_str(json.dumps({'type': 'language_set', 'lang': lang}))

    elif c == 'set_theme':
        theme = cmd.get('theme', 'dark')
        if theme in ('dark', 'light'):
            bridge.config.set('theme', theme)
            await ws.send_str(json.dumps({'type': 'theme_set', 'theme': theme}))

    elif c == 'save_ui_state':
        state = cmd.get('state', {})
        bridge.session.set_ui_state(state)
        await ws.send_str(json.dumps({'type': 'ui_state_saved'}))

    elif c == 'add_items':
        items = cmd.get('items', [])
        n = bridge.worker.add_items(items)
        await ws.send_str(json.dumps(bridge._queue_status_payload()))
        await ws.send_str(json.dumps({'type': 'items_added', 'count': n}))

    elif c == 'add_urls':
        # 向后兼容：转换为 items
        urls = cmd.get('urls', [])
        items = [{'url': u} for u in urls]
        n = bridge.worker.add_items(items)
        await ws.send_str(json.dumps(bridge._queue_status_payload()))

    elif c == 'start_queue':
        ok = bridge.worker.start()
        await ws.send_str(json.dumps({'type': 'success' if ok else 'error',
                                      'msg': 'Queue started' if ok else 'Cannot start queue'}))

    elif c == 'stop_queue':
        bridge.worker.stop()
        await ws.send_str(json.dumps({'type': 'success', 'msg': 'Stopping queue...'}))

    elif c == 'clear_queue':
        n = bridge.worker.clear_queue()
        await ws.send_str(json.dumps({'type': 'success', 'msg': f'Cleared {n} task(s)'}))

    elif c == 'retry_failed':
        n = bridge.worker.retry_failed()
        if n == 0:
            await ws.send_str(json.dumps({'type': 'error', 'msg': 'No failed tasks'}))

    elif c == 'search':
        tag = cmd.get('tag', '')
        sort = cmd.get('sort', 'date_desc')
        target = cmd.get('target', 'exact_match_for_tags')
        duration = cmd.get('duration', '') or None
        start_date = cmd.get('start_date', '') or None
        end_date = cmd.get('end_date', '') or None
        pages = max(1, min(200, int(cmd.get('pages', 1))))
        start_page = max(1, int(cmd.get('start_page', 1)))
        filters = cmd.get('filters', {'illust': True, 'manga': True})
        loop = asyncio.get_event_loop()

        if start_date and end_date:
            date_re = re.compile(r'^\d{4}-\d{2}-\d{2}$')
            if not date_re.match(start_date) or not date_re.match(end_date):
                await ws.send_str(json.dumps({'type': 'error',
                                              'msg': 'Invalid date format'}))
                return
            if start_date > end_date:
                await ws.send_str(json.dumps({'type': 'error',
                                              'msg': 'Start date must be <= end date'}))
                return
            duration = None

        def do_search():
            results = []
            api = PixivAPI(bridge.config, bridge.worker.rate_limiter)
            api.ensure_login()
            for i in range(pages):
                page = start_page + i
                offset = (page - 1) * 30
                bridge.broadcast({'type': 'search_progress',
                                  'current': i + 1, 'total': pages, 'page': page})
                try:
                    resp = api.search_illust(tag, target=target, sort=sort,
                                             offset=offset, duration=duration,
                                             start_date=start_date, end_date=end_date)
                except Exception as e:
                    write_log(t('search_page_failed', page=page, error=str(e)), 'error')
                    break
                items = resp.get('illusts', [])
                if not items:
                    break
                results.extend(items)
                if len(items) < 30:
                    break
                time.sleep(float(bridge.config.get('api_request_delay', 0.3)))
            filtered = []
            for it in results:
                ty = it.get('type', '')
                if ty == 'illust' and filters.get('illust'):
                    filtered.append(it)
                elif ty == 'manga' and filters.get('manga'):
                    filtered.append(it)
            return filtered

        results = await loop.run_in_executor(None, do_search)
        # 保留原始 illust 数据供下载复用
        formatted = []
        for it in results:
            f = format_item(it)
            f['_slim_illust'] = _slim_illust(it)
            formatted.append(f)
        await ws.send_str(json.dumps({'type': 'search_result',
                                      'items': formatted,
                                      'start_page': start_page, 'pages': pages},
                                     ensure_ascii=False))

    elif c == 'ranking':
        mode = cmd.get('mode', 'day')
        limit = 480
        loop = asyncio.get_event_loop()

        write_log(f"ranking requested: mode={mode}", 'info')

        def do_ranking():
            api = PixivAPI(bridge.config, bridge.worker.rate_limiter)
            api.ensure_login()
            delay = float(bridge.config.get('api_request_delay', 0.3))

            # --- Today ---
            write_log(f"ranking: fetching today ({mode})", 'info')
            today = []
            today_ids = set()
            today_date = None
            offset = 0
            while len(today) < limit:
                bridge.broadcast({'type': 'ranking_progress',
                                  'phase': 'today', 'count': len(today)})
                try:
                    resp = api.get_ranking(mode, offset=offset)
                except Exception as e:
                    write_log(f"ranking today failed at offset={offset}: {e}", 'error')
                    break
                items = resp.get('illusts', []) or []
                if not items:
                    write_log(f"ranking today: empty at offset={offset}, stop", 'info')
                    break

                # 从 next_url 解析真实日期（首次拿到时记录）
                if today_date is None:
                    nxt = resp.get('next_url')
                    if nxt:
                        try:
                            parsed = urlparse(nxt)
                            params = parse_qs(parsed.query)
                            d = params.get('date', [None])[0]
                            if d:
                                today_date = d
                        except Exception:
                            pass

                for it in items:
                    pid = it.get('id')
                    if pid is not None and pid not in today_ids:
                        today_ids.add(pid)
                        today.append(it)

                offset += 30
                if len(today) >= limit:
                    break
                if not resp.get('next_url'):
                    write_log(f"ranking today: no next_url at offset={offset}, stop", 'info')
                    break
                time.sleep(delay)
            today = today[:limit]
            write_log(f"ranking today: got {len(today)} items (date={today_date})", 'info')

            # 计算 yesterday_date：优先使用 today 的请求日期 - 1 天
            if today_date:
                try:
                    base_dt = datetime.strptime(today_date, '%Y-%m-%d')
                except ValueError:
                    base_dt = datetime.now()
            else:
                base_dt = datetime.now()
            yesterday_date = (base_dt - timedelta(days=1)).strftime('%Y-%m-%d')

            # --- Yesterday ---
            write_log(f"ranking: fetching yesterday ({mode}, date={yesterday_date})", 'info')
            yesterday_ids = set()
            offset = 0
            y_iterations = 0
            max_y_iterations = 20
            while offset < limit and y_iterations < max_y_iterations:
                y_iterations += 1
                bridge.broadcast({'type': 'ranking_progress',
                                  'phase': 'yesterday', 'count': len(yesterday_ids)})
                try:
                    resp = api.get_ranking(mode, date=yesterday_date, offset=offset)
                except Exception as e:
                    write_log(f"ranking yesterday failed at offset={offset}: {e}", 'error')
                    break
                items = resp.get('illusts', []) or []
                if not items:
                    write_log(f"ranking yesterday: empty at offset={offset}, stop", 'info')
                    break
                for it in items:
                    pid = it.get('id')
                    if pid is not None:
                        yesterday_ids.add(pid)
                offset += 30
                if not resp.get('next_url'):
                    write_log(f"ranking yesterday: no next_url at offset={offset}, stop", 'info')
                    break
                time.sleep(delay)
            write_log(f"ranking yesterday: got {len(yesterday_ids)} unique ids", 'info')

            # 标记新作
            yesterday_available = len(yesterday_ids) > 0
            new_count = 0
            for it in today:
                if yesterday_available:
                    is_new = it.get('id') not in yesterday_ids
                else:
                    is_new = False
                it['_is_new'] = is_new
                if is_new:
                    new_count += 1

            return today, len(today_ids), len(yesterday_ids), new_count

        try:
            results, today_count, y_count, new_count = await loop.run_in_executor(
                None, do_ranking)
        except Exception as e:
            write_log(f"ranking executor failed: {e}", 'error')
            await ws.send_str(json.dumps({'type': 'error',
                                          'msg': f'Ranking failed: {e}'}))
            return

        write_log(f"ranking done: today={today_count}, yesterday={y_count}, new={new_count}", 'info')
        formatted = []
        for it in results:
            f = format_item(it)
            f['is_new'] = bool(it.get('_is_new'))
            f['_slim_illust'] = _slim_illust(it)
            formatted.append(f)
        await ws.send_str(json.dumps({
            'type': 'ranking_result',
            'items': formatted,
            'stats': {
                'today': today_count,
                'yesterday': y_count,
                'new': new_count,
            }
        }, ensure_ascii=False))
    
    elif c == 'parse_bookmark':
        urls = parse_bookmark_html(cmd.get('html', ''))
        await ws.send_str(json.dumps({'type': 'bookmark_parsed', 'urls': urls}))

    elif c == 'search_users':
        word = cmd.get('word', '')
        offset = int(cmd.get('offset', 0))
        loop = asyncio.get_event_loop()

        def do_users():
            api = PixivAPI(bridge.config, bridge.worker.rate_limiter)
            api.ensure_login()
            return api.search_users(word, offset=offset)

        try:
            resp = await loop.run_in_executor(None, do_users)
        except Exception as e:
            await ws.send_str(json.dumps({'type': 'error',
                                          'msg': f'User search failed: {e}'}))
            return
        previews = resp.get('user_previews', [])
        users = [format_user(p.get('user', {})) for p in previews]
        await ws.send_str(json.dumps({'type': 'user_search_result', 'items': users}))

    elif c == 'user_detail':
        uid = int(cmd.get('uid'))
        loop = asyncio.get_event_loop()

        def do_user():
            api = PixivAPI(bridge.config, bridge.worker.rate_limiter)
            api.ensure_login()
            detail = api.get_user_detail(uid)
            if not detail:
                return None, [], None
            bridge.broadcast({'type': 'user_detail_phase', 'phase': 'detail',
                              'user': format_user_detail(detail)})
            all_illusts = []
            offset = 0
            page = 1
            delay = float(bridge.config.get('api_request_delay', 0.3))
            while True:
                bridge.broadcast({'type': 'user_detail_phase', 'phase': 'illusts',
                                  'page': page, 'count': len(all_illusts)})
                try:
                    resp = api.get_user_illusts(uid, offset=offset)
                except Exception as e:
                    write_log(t('user_illusts_failed', error=str(e)), 'error')
                    break
                items = resp.get('illusts', [])
                if not items:
                    break
                all_illusts.extend(items)
                if len(items) < 30:
                    break
                if not resp.get('next_url'):
                    break
                offset += 30
                page += 1
                time.sleep(delay)
            is_accept = None
            if all_illusts:
                is_accept = all_illusts[0].get('user', {}).get('is_accept_request')
            return detail, all_illusts, is_accept

        try:
            detail, all_illusts, is_accept = await loop.run_in_executor(None, do_user)
        except Exception as e:
            await ws.send_str(json.dumps({'type': 'error',
                                          'msg': f'User detail failed: {e}'}))
            return
        if not detail:
            await ws.send_str(json.dumps({'type': 'error',
                                          'msg': 'User not found or inaccessible'}))
            return
        user_info = format_user_detail(detail, extra={'is_accept_request': is_accept})
        items = []
        for it in all_illusts:
            f = format_item(it)
            f['_slim_illust'] = _slim_illust(it)
            items.append(f)
        await ws.send_str(json.dumps({'type': 'user_detail_result',
                                      'user': user_info, 'items': items},
                                     ensure_ascii=False))

    elif c == 'follow_user':
        uid = int(cmd.get('uid'))
        action = cmd.get('action', 'follow')  # follow / unfollow
        loop = asyncio.get_event_loop()

        def do_follow():
            api = PixivAPI(bridge.config, bridge.worker.rate_limiter)
            api.ensure_login()
            if action == 'follow':
                return api.follow_user(uid)
            else:
                return api.unfollow_user(uid)

        try:
            await loop.run_in_executor(None, do_follow)
            await ws.send_str(json.dumps({'type': 'follow_user_result',
                                          'uid': uid, 'action': action,
                                          'success': True}))
        except Exception as e:
            await ws.send_str(json.dumps({'type': 'error',
                                          'msg': f'Follow failed: {e}'}))

    elif c == 'recommend':
        mode = cmd.get('mode', 'auto')
        limit = min(max(1, int(cmd.get('limit', 60))), 120)
        loop = asyncio.get_event_loop()
        kwargs = {}
        if mode == 'queue':
            with bridge.worker.url_queue.mutex:
                items = list(bridge.worker.url_queue.queue)
            seeds = []
            for it in items[:30]:
                url = it.get('url') if isinstance(it, dict) else (
                    it[0] if isinstance(it, tuple) else it)
                try:
                    _, pid = bridge.worker._parse_url(url)
                    seeds.append(pid)
                except Exception:
                    continue
            if seeds:
                kwargs['bookmark_illust_ids'] = seeds
        elif mode == 'history':
            history = load_history()
            seeds = [h['id'] for h in history[:30] if h.get('id')]
            if seeds:
                kwargs['bookmark_illust_ids'] = seeds
        elif mode == 'work':
            try:
                pid = int(cmd.get('pid', 0))
            except Exception:
                pid = 0
            if pid <= 0:
                await ws.send_str(json.dumps({'type': 'error', 'msg': 'Invalid PID'}))
                return
            kwargs['bookmark_illust_ids'] = [pid]
        elif mode == 'advanced':
            adv = cmd.get('params', {})
            if adv.get('bookmark_illust_ids'):
                v = adv['bookmark_illust_ids']
                if isinstance(v, str):
                    v = [int(s.strip()) for s in v.split(',') if s.strip().isdigit()]
                kwargs['bookmark_illust_ids'] = v[:30]
            if adv.get('viewed'):
                v = adv['viewed']
                if isinstance(v, str):
                    v = [int(s.strip()) for s in v.split(',') if s.strip().isdigit()]
                kwargs['viewed'] = v[:30]
            if 'include_ranking_illusts' in adv:
                kwargs['include_ranking_illusts'] = bool(adv['include_ranking_illusts'])
            if 'include_privacy_policy' in adv:
                kwargs['include_privacy_policy'] = bool(adv['include_privacy_policy'])

        def do_rec():
            api = PixivAPI(bridge.config, bridge.worker.rate_limiter)
            api.ensure_login()
            results = []
            offset = 0
            delay = float(bridge.config.get('api_request_delay', 0.3))
            while len(results) < limit:
                try:
                    resp = api.get_illust_recommended(offset=offset, **kwargs)
                except Exception as e:
                    write_log(t('recommend_failed', error=str(e)), 'error')
                    break
                items = resp.get('illusts', [])
                if not items:
                    break
                results.extend(items)
                if len(results) >= limit:
                    break
                if not resp.get('next_url'):
                    break
                offset += 30
                time.sleep(delay)
            return results[:limit]

        results = await loop.run_in_executor(None, do_rec)
        formatted = []
        for it in results:
            f = format_item(it)
            f['_slim_illust'] = _slim_illust(it)
            formatted.append(f)
        await ws.send_str(json.dumps({'type': 'recommend_result',
                                      'items': formatted, 'mode': mode},
                                     ensure_ascii=False))

    elif c == 'follow_new':
        offset = int(cmd.get('offset', 0))
        restrict = cmd.get('restrict', 'all')
        if restrict not in ('all', 'public', 'private'):
            restrict = 'all'
        batch_size = 300
        loop = asyncio.get_event_loop()

        write_log(f"follow_new requested: offset={offset}, restrict={restrict}", 'info')

        def do_follow():
            api = PixivAPI(bridge.config, bridge.worker.rate_limiter)
            api.ensure_login()
            results = []
            seen_ids = set()
            cur_offset = offset
            delay = float(bridge.config.get('api_request_delay', 0.3))
            max_iterations = 40
            iterations = 0

            while len(results) < batch_size and iterations < max_iterations:
                iterations += 1
                bridge.broadcast({'type': 'follow_progress', 'count': len(results)})
                write_log(f"follow_new: fetching offset={cur_offset}", 'info')

                try:
                    resp = api.get_illust_follow(restrict=restrict, offset=cur_offset)
                except Exception as e:
                    write_log(f"follow_new failed at offset={cur_offset}: {e}", 'error')
                    break

                items = resp.get('illusts', []) or []
                write_log(f"follow_new: offset={cur_offset} returned {len(items)} items", 'info')

                if not items:
                    write_log("follow_new: empty page, stop", 'info')
                    return results, False

                new_items = [it for it in items if it.get('id') not in seen_ids]
                if not new_items:
                    write_log(f"follow_new: no new items at offset={cur_offset}, stop", 'info')
                    return results, False

                for it in new_items:
                    seen_ids.add(it.get('id'))
                results.extend(new_items)

                next_url = resp.get('next_url')
                if not next_url:
                    write_log("follow_new: no next_url, stop", 'info')
                    return results[:batch_size], False

                new_offset = None
                try:
                    parsed = urlparse(next_url)
                    params = parse_qs(parsed.query)
                    v = params.get('offset', [None])[0]
                    if v is not None:
                        new_offset = int(v)
                except (ValueError, TypeError):
                    pass

                if new_offset is None or new_offset <= cur_offset:
                    write_log(f"follow_new: offset did not advance ({cur_offset} -> {new_offset}), stop",
                              'info')
                    return results[:batch_size], False

                cur_offset = new_offset

                if len(results) >= batch_size:
                    return results[:batch_size], True
                time.sleep(delay)

            write_log(f"follow_new: loop end, {len(results)} items after {iterations} iterations", 'info')
            return results[:batch_size], False

        try:
            items, has_more = await loop.run_in_executor(None, do_follow)
        except Exception as e:
            write_log(f"follow_new executor failed: {e}", 'error')
            await ws.send_str(json.dumps({'type': 'error',
                                          'msg': f'Follow new failed: {e}'}))
            return

        write_log(f"follow_new done: {len(items)} items, has_more={has_more}", 'info')
        formatted = []
        for it in items:
            f = format_item(it)
            f['_slim_illust'] = _slim_illust(it)
            formatted.append(f)
        await ws.send_str(json.dumps({'type': 'follow_new_result',
                                      'items': formatted,
                                      'offset': offset,
                                      'batch_size': batch_size,
                                      'has_more': has_more},
                                     ensure_ascii=False))        
    # -------- Accounts --------
    elif c in ('get_account', 'refresh_account'):
        force = (c == 'refresh_account')
        loop = asyncio.get_event_loop()
        cached = bridge.accounts.get_current_profile()

        if not force and cached and cached.get('id'):
            await ws.send_str(json.dumps({
                'type': 'account_result',
                'profile': cached,
                'bookmarks': bridge.accounts.get_current_bookmarks(),
            }, ensure_ascii=False))
            return

        def do_account():
            api = PixivAPI(bridge.config, bridge.worker.rate_limiter)
            api.ensure_login()
            try:
                uid = api.api.user_id
            except Exception:
                return None
            try:
                detail = api.get_user_detail(uid)
            except Exception as e:
                write_log(f"Account detail fetch failed: {e}", 'warn')
                return None
            user = detail.get('user', {})
            prof = detail.get('profile', {})
            return {
                'id': user.get('id'),
                'name': user.get('name', ''),
                'account': user.get('account', ''),
                'avatar': user.get('profile_image_urls', {}).get('medium', ''),
                'comment': user.get('comment', ''),
                'total_follow_users': prof.get('total_follow_users', 0),
                'total_illusts': prof.get('total_illusts', 0),
                'total_manga': prof.get('total_manga', 0),
                'total_illust_bookmarks_public':
                    prof.get('total_illust_bookmarks_public', 0),
                'region': prof.get('region', ''),
                'background_image_url': prof.get('background_image_url'),
                'is_premium': prof.get('is_premium', False),
            }

        profile = await loop.run_in_executor(None, do_account)
        if profile:
            bridge.accounts.set_current_profile(profile)
        else:
            profile = cached or {}
        await ws.send_str(json.dumps({
            'type': 'account_result',
            'profile': profile,
            'bookmarks': bridge.accounts.get_current_bookmarks(),
        }, ensure_ascii=False))

    elif c == 'list_accounts':
        await ws.send_str(json.dumps({
            'type': 'account_list',
            'accounts': bridge.accounts.list_accounts(),
            'current_index': bridge.accounts.data.get('current_index', 0),
        }, ensure_ascii=False))

    elif c == 'add_account':
        rt = cmd.get('refresh_token', '').strip()
        if not rt:
            await ws.send_str(json.dumps({'type': 'error',
                                          'msg': 'Refresh token is required'}))
            return
        loop = asyncio.get_event_loop()

        def do_validate():
            test = AppPixivAPI()
            proxy = bridge.config.get('proxy')
            if proxy:
                test.set_proxy(proxy)
            try:
                test.auth(refresh_token=rt)
                uid = test.user_id
                detail = test.user_detail(uid)
                user = detail.get('user', {})
                prof = detail.get('profile', {})
                return True, {
                    'id': user.get('id'),
                    'name': user.get('name', ''),
                    'account': user.get('account', ''),
                    'avatar': user.get('profile_image_urls', {}).get('medium', ''),
                    'comment': user.get('comment', ''),
                    'total_follow_users': prof.get('total_follow_users', 0),
                    'total_illusts': prof.get('total_illusts', 0),
                    'total_manga': prof.get('total_manga', 0),
                    'total_illust_bookmarks_public':
                        prof.get('total_illust_bookmarks_public', 0),
                    'region': prof.get('region', ''),
                    'background_image_url': prof.get('background_image_url'),
                    'is_premium': prof.get('is_premium', False),
                }
            except Exception as e:
                return False, str(e)

        ok, result = await loop.run_in_executor(None, do_validate)
        if not ok:
            await ws.send_str(json.dumps({'type': 'error',
                                          'msg': f'Invalid token: {result}'}))
            return
        idx = bridge.accounts.add_account(rt)
        bridge.accounts.set_current_profile(result)
        # Reset and re-login / 重置并重新登录
        bridge.worker.api.logged_in = False
        bridge.worker.api.api = None
        bridge.worker.api.ensure_login()
        await ws.send_str(json.dumps({'type': 'account_added',
                                      'index': idx, 'profile': result},
                                     ensure_ascii=False))

    elif c == 'switch_account':
        index = int(cmd.get('index', 0))
        if bridge.accounts.switch_account(index):
            bridge.worker.api.logged_in = False
            bridge.worker.api.api = None
            bridge.worker.api.ensure_login()
            await ws.send_str(json.dumps({'type': 'account_switched',
                                          'index': index}))
        else:
            await ws.send_str(json.dumps({'type': 'error',
                                          'msg': 'Invalid index'}))

    elif c == 'remove_account':
        index = int(cmd.get('index', 0))
        if bridge.accounts.remove_account(index):
            bridge.worker.api.logged_in = False
            bridge.worker.api.api = None
            bridge.worker.api.ensure_login()
            await ws.send_str(json.dumps({'type': 'account_removed',
                                          'index': index}))
        else:
            await ws.send_str(json.dumps({'type': 'error',
                                          'msg': 'Invalid index'}))

    elif c == 'load_following':
        loop = asyncio.get_event_loop()

        def do_following():
            api = PixivAPI(bridge.config, bridge.worker.rate_limiter)
            api.ensure_login()
            uid = api.api.user_id
            results = []
            offset = 0
            delay = float(bridge.config.get('api_request_delay', 0.3))
            for _ in range(10):
                try:
                    resp = api._call_with_retry(api.api.user_following, uid, offset=offset)
                except Exception as e:
                    write_log(f"load_following failed: {e}", 'error')
                    break
                previews = resp.get('user_previews', []) or []
                if not previews:
                    break
                for up in previews:
                    u = up.get('user', {})
                    results.append({
                        'id': u.get('id'),
                        'name': u.get('name', ''),
                        'account': u.get('account', ''),
                        'avatar': u.get('profile_image_urls', {}).get('medium', ''),
                        'is_followed': u.get('is_followed', False),
                    })
                offset += 30
                if not resp.get('next_url'):
                    break
                time.sleep(delay)
            return results

        try:
            following = await loop.run_in_executor(None, do_following)
            bridge.accounts.set_current_following(following)
            await ws.send_str(json.dumps({'type': 'following_list',
                                          'items': following}, ensure_ascii=False))
        except Exception as e:
            await ws.send_str(json.dumps({'type': 'error',
                                          'msg': f'Load following failed: {e}'}))

    elif c == 'load_bookmarks':
        loop = asyncio.get_event_loop()

        def do_bookmarks():
            api = PixivAPI(bridge.config, bridge.worker.rate_limiter)
            api.ensure_login()
            uid = api.api.user_id
            results = []
            offset = 0
            delay = float(bridge.config.get('api_request_delay', 0.3))
            for _ in range(10):
                try:
                    resp = api.get_user_bookmarks(uid, restrict='public', offset=offset)
                except Exception as e:
                    write_log(f"load_bookmarks failed: {e}", 'error')
                    break
                items = resp.get('illusts', []) or []
                if not items:
                    break
                for it in items:
                    f = format_item(it)
                    f['_slim_illust'] = _slim_illust(it)
                    results.append(f)
                offset += 30
                if not resp.get('next_url'):
                    break
                time.sleep(delay)
            return results

        try:
            bookmarks = await loop.run_in_executor(None, do_bookmarks)
            bridge.accounts.set_current_bookmarks(bookmarks)
            await ws.send_str(json.dumps({'type': 'bookmarks_list',
                                          'items': bookmarks}, ensure_ascii=False))
        except Exception as e:
            await ws.send_str(json.dumps({'type': 'error',
                                          'msg': f'Load bookmarks failed: {e}'}))

    elif c == 'get_config':
        await ws.send_str(json.dumps({'type': 'config', 'data': bridge.config.config}))

    elif c == 'save_config':
        for k, v in cmd.get('data', {}).items():
            bridge.config.set(k, v)
        bridge.worker.download_dir = Path(bridge.config.get('download_dir'))
        await ws.send_str(json.dumps({'type': 'success', 'msg': 'Config saved'}))
        await ws.send_str(json.dumps(bridge._queue_status_payload()))

    elif c == 'set_download_mode':
        mode = cmd.get('mode', 'normal')
        if mode not in ('normal', 'high'):
            mode = 'normal'
        bridge.config.set('download_mode', mode)
        await ws.send_str(json.dumps(bridge._queue_status_payload()))

    elif c == 'test_latency':
        loop = asyncio.get_event_loop()
        latency = await loop.run_in_executor(None, measure_latency_sync, bridge.config)
        if latency is not None:
            await ws.send_str(json.dumps({'type': 'latency_result',
                                          'success': True, 'latency': latency}))
        else:
            await ws.send_str(json.dumps({'type': 'latency_result',
                                          'success': False,
                                          'error': 'Request failed or timed out'}))
    elif c == 'bookmark_toggle':
        iid = int(cmd.get('id', 0))
        action = cmd.get('action', 'add')  # add / delete
        restrict = cmd.get('restrict', 'public')
        if iid <= 0:
            await ws.send_str(json.dumps({'type': 'error', 'msg': 'Invalid illust id'}))
            return
        loop = asyncio.get_event_loop()

        def do_toggle():
            api = PixivAPI(bridge.config, bridge.worker.rate_limiter)
            api.ensure_login()
            if action == 'add':
                return api.illust_bookmark_add(iid, restrict=restrict)
            else:
                return api.illust_bookmark_delete(iid)

        try:
            await loop.run_in_executor(None, do_toggle)
            await ws.send_str(json.dumps({
                'type': 'bookmark_result',
                'id': iid,
                'action': action,
                'success': True,
            }))
        except Exception as e:
            write_log(f"Bookmark toggle failed: {e}", 'error')
            await ws.send_str(json.dumps({
                'type': 'bookmark_result',
                'id': iid,
                'action': action,
                'success': False,
                'msg': str(e),
            }))
    else:
        await ws.send_str(json.dumps({'type': 'error',
                                      'msg': f'Unknown command: {c}'}))


# ============================================================
# HTTP handlers
# ============================================================
async def index_handler(request):
    html_path = get_resource_path("webui/index.html")
    if html_path.exists():
        return web.FileResponse(html_path)
    return web.Response(text="index.html not found", status=404)


async def proxy_image_handler(request):
    url = request.query.get('url', '')
    if not url:
        return web.Response(status=400, text='missing url')
    if 'pximg.net' not in url:
        return web.Response(status=403, text='forbidden host')
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Referer": "https://www.pixiv.net/",
    }
    loop = asyncio.get_event_loop()

    def fetch():
        try:
            r = requests.get(url, headers=headers, timeout=15, stream=True)
            if r.status_code != 200:
                return r.status_code, b'', 'text/plain'
            return 200, r.content, r.headers.get('Content-Type', 'image/jpeg')
        except Exception as e:
            write_log(t('proxy_failed', error=str(e)), 'warn')
            return 502, str(e).encode(), 'text/plain'

    status, body, ctype = await loop.run_in_executor(None, fetch)
    return web.Response(body=body, status=status, content_type=ctype)


async def ws_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    bridge = request.app['bridge']
    await bridge.register(ws)
    try:
        init_payload = bridge._queue_status_payload()
        init_payload['type'] = 'init'
        init_payload['config'] = bridge.config.config
        init_payload['ui_state'] = bridge.session.get_ui_state()
        await ws.send_str(json.dumps(init_payload, ensure_ascii=False))

        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    cmd = json.loads(msg.data)
                    await handle_command(bridge, cmd, ws)
                except Exception as e:
                    write_log(t('command_error', error=str(e)), 'error')
                    try:
                        await ws.send_str(json.dumps({'type': 'error',
                                                      'msg': str(e)}))
                    except Exception:
                        pass
            elif msg.type == aiohttp.WSMsgType.ERROR:
                break
    finally:
        await bridge.unregister(ws)
    return ws


def find_free_port(start=8765, end=8865):
    for port in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('127.0.0.1', port))
                return port
            except Exception:
                continue
    return 8765


def load_saved_queue(worker, session: SessionManager):
    queue_data = session.get_queue()
    current = queue_data.get('current_tasks', []) or []
    failed = queue_data.get('failed_tasks', []) or []
    for it in current:
        if isinstance(it, dict):
            worker.url_queue.put(it)
        else:
            worker.url_queue.put({'url': it})
    for item in failed:
        pid = item.get('pid')
        img_path = item.get('img_path')
        meta_d = item.get('metadata') or {}
        if pid and img_path:
            with worker.failed_lock:
                worker.failed_items.append((int(pid), Path(img_path), meta_d))
    if current or failed:
        write_log(t('queue_restored', pending=len(current), failed=len(failed)), 'info')


async def startup_latency_check(bridge):
    loop = asyncio.get_event_loop()
    latency = await loop.run_in_executor(None, measure_latency_sync, bridge.config)
    if latency is not None:
        write_log(t('latency_startup', latency=latency), 'info')
        bridge.broadcast({'type': 'startup_latency', 'latency': latency})


async def main_async(port, config, accounts, session):
    app = web.Application()
    bridge = WebBridge(config, accounts, session)
    bridge.set_loop(asyncio.get_event_loop())

    load_saved_queue(bridge.worker, session)

    app['bridge'] = bridge
    app.router.add_get('/', index_handler)
    app.router.add_get('/ws', ws_handler)
    app.router.add_get('/proxy_image', proxy_image_handler)

    web_dir = get_resource_path("webui")
    if web_dir.exists():
        app.router.add_static('/static/', web_dir)
        icons = web_dir / "static_icons"
        if icons.exists():
            app.router.add_static('/static_icons/', icons)
        ui_icons = web_dir / "ui_icons"
        if ui_icons.exists():
            app.router.add_static('/ui_icons/', ui_icons)

    async def on_shutdown(app):
        try:
            app['bridge'].worker._save_queue()
            write_log(t('server_shutdown'), 'info')
        except Exception as e:
            write_log(t('queue_save_failed', error=str(e)), 'error')
    app.on_shutdown.append(on_shutdown)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', port)
    await site.start()

    url = f"http://127.0.0.1:{port}/"
    write_log(t('server_started', url=url), 'info')

    def open_browser_and_minimize():
        time.sleep(0.8)
        write_log(t('browser_opening'), 'info')
        try:
            webbrowser.open(url)
        except Exception:
            pass
        time.sleep(1.5)
        if minimize_console_window():
            write_log(t('console_minimized'), 'info')

    threading.Thread(target=open_browser_and_minimize, daemon=True).start()
    asyncio.create_task(startup_latency_check(bridge))

    # 若队列中存在已保存的任务，自动启动
    if not bridge.worker.url_queue.empty():
        write_log("Auto-starting queue with restored tasks", 'info')
        bridge.worker.start()

    while True:
        await asyncio.sleep(3600)


def main():
    set_language(peek_language())
    setup_logging()

    write_log(t('starting'), 'info')

    config = ConfigManager()
    final_lang = config.effective_language()
    set_language(final_lang)
    write_log(t('language_loaded', lang=final_lang), 'info')

    accounts = AccountsManager(config)
    session = SessionManager()

    exiftool_path = get_resource_path("plugins/ExifTool.exe")
    version = get_exiftool_version(exiftool_path)
    if version:
        write_log(t('exiftool_found', version=version), 'info')
    else:
        write_log(t('exiftool_not_found', path=str(exiftool_path)), 'warn')

    port = find_free_port()
    try:
        asyncio.run(main_async(port, config, accounts, session))
    except KeyboardInterrupt:
        write_log(t('interrupted'), 'info')


if __name__ == '__main__':
    main()
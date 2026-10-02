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
import zipfile
import shutil
from PIL import Image

import requests
import aiohttp
from aiohttp import web
from bs4 import BeautifulSoup
from pixivpy3 import AppPixivAPI, PixivError
from concurrent.futures import ThreadPoolExecutor

import tomllib

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
    CONFIG_FILE = get_app_dir() / "config.toml"
    LEGACY_CONFIG_FILE = get_app_dir() / "pixiv_client_config.json"

    DEFAULT_CONFIG = {
        'download_dir': str(Path.home() / "Pictures" / "Pixiv"),
        'proxy': '',
        'language': 'auto',
        'theme': 'dark',
        'performance': {
            'download_mode': 'normal',
            'parallel_workers': 0,
            'download_delay': 0.5,
            'max_retries': 3,
        },
        'api': {
            'request_delay': 0.3,
            'rate_limit_wait': 150.0,
            'max_results': 30,
            'parallel_requests': 1,
            'web_ajax_mode': 'disabled',
        },
    }

    VALIDATORS = {
        'performance.download_delay':   ('float', 0.0, 60.0),
        'performance.parallel_workers': ('int',   0,   64),
        'performance.max_retries':      ('int',   1,   100),
        'api.request_delay':            ('float', 0.0, 60.0),
        'api.rate_limit_wait':          ('float', 1.0, 3600.0),
        'api.max_results':              ('int',   1,   500),
        'api.parallel_requests':        ('int',   1,   8),
    }

    STRING_FIELDS = (
        'download_dir', 'proxy', 'language', 'theme',
    )

    def __init__(self):
        self.config = self._load_or_init()
        self._resolve_auto_workers()

    # ------------------------------------------------------------
    # Load / migrate / init
    # ------------------------------------------------------------
    def _load_or_init(self) -> dict:
        if self.CONFIG_FILE.exists():
            try:
                with open(self.CONFIG_FILE, 'rb') as f:
                    cfg = tomllib.load(f)
                write_log(t('config_loaded', path=str(self.CONFIG_FILE)), 'info')
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
                self.config = self._default_copy()
                self.save()
                return self.config

        if self.LEGACY_CONFIG_FILE.exists():
            try:
                with open(self.LEGACY_CONFIG_FILE, 'r', encoding='utf-8') as f:
                    old = json.load(f)
                merged = self._merge_defaults(old)
                for k in ("exiftool_path", "username", "password", "api_language"):
                    merged.pop(k, None)
                validated, errors = self._validate(merged)
                self.config = validated
                self.save()
                write_log(t('config_migrated', path=str(self.CONFIG_FILE)), 'info')
                return self.config
            except Exception as e:
                write_log(t('config_load_failed', error=str(e)), 'warn')

        self.config = self._default_copy()
        self.save()
        write_log(t('config_created', path=str(self.CONFIG_FILE)), 'info')
        return self.config

    def _default_copy(self) -> dict:
        """Deep copy of default config / 默认配置的深拷贝"""
        return json.loads(json.dumps(self.DEFAULT_CONFIG))

    def _merge_defaults(self, cfg: dict) -> dict:
        result = self._default_copy()
        for k, v in cfg.items():
            if k == 'refresh_token':
                # Migrate below, don't copy / 稍后迁移，不复制
                continue
            if k in ('performance', 'api') and isinstance(v, dict):
                for sk, sv in v.items():
                    result[k][sk] = sv
            elif k in result:
                result[k] = v
        return result

    # ------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------
    def _validate(self, cfg: dict):
        errors = []
        result = json.loads(json.dumps(cfg))

        for path, (typ, lo, hi) in self.VALIDATORS.items():
            keys = path.split('.')
            node = result
            for k in keys[:-1]:
                node = node.get(k, {})
            leaf = keys[-1]
            if leaf not in node:
                continue
            try:
                v = node[leaf]
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
                node[leaf] = v
            except (ValueError, TypeError) as e:
                # Get default / 获取默认值
                dnode = self.DEFAULT_CONFIG
                for k in keys[:-1]:
                    dnode = dnode.get(k, {})
                default = dnode.get(leaf)
                errors.append((path, node.get(leaf), default, str(e)))
                node[leaf] = default

        # String fields / 字符串字段
        for key in self.STRING_FIELDS:
            if key in result and not isinstance(result[key], str):
                errors.append((key, result[key], self.DEFAULT_CONFIG[key], 'not a string'))
                result[key] = self.DEFAULT_CONFIG[key]

        # Enum fields / 枚举字段
        if result.get('language') not in ('auto', 'zh-CN', 'en'):
            result['language'] = 'auto'
        if result.get('theme') not in ('dark', 'light'):
            result['theme'] = 'dark'
        if result.get('performance', {}).get('download_mode') not in ('normal', 'high'):
            result['performance']['download_mode'] = 'normal'
        if result.get('api', {}).get('web_ajax_mode') not in (
            'disabled', 'illust_only', 'illust_user', 'global'
        ):
            result['api']['web_ajax_mode'] = 'disabled'

        return result, errors

    # ------------------------------------------------------------
    # Auto worker detection
    # ------------------------------------------------------------
    def _resolve_auto_workers(self):
        """Auto-detect worker count when parallel_workers == 0"""
        pw = self.config['performance'].get('parallel_workers', 0)
        if pw == 0:
            try:
                import psutil
                logical = psutil.cpu_count(logical=True) or 4
                detected = max(1, min(8, logical // 2))
            except Exception:
                detected = 3
            self.config['performance']['_resolved_workers'] = detected
            write_log(f"Auto worker count: {detected} (logical cores detected)", 'info')
        else:
            self.config['performance']['_resolved_workers'] = pw

    # ------------------------------------------------------------
    # Dotted-path accessors
    # ------------------------------------------------------------
    def get(self, path: str, default=None):
        keys = path.split('.')
        cur = self.config
        for k in keys:
            if isinstance(cur, dict) and k in cur:
                cur = cur[k]
            else:
                return default
        return cur

    def set(self, path: str, value):
        keys = path.split('.')
        cur = self.config
        for k in keys[:-1]:
            if k not in cur or not isinstance(cur[k], dict):
                cur[k] = {}
            cur = cur[k]
        cur[keys[-1]] = value
        self.save()

    # ------------------------------------------------------------
    # Save
    # ------------------------------------------------------------
    def save(self):
        try:
            with open(self.CONFIG_FILE, 'w', encoding='utf-8') as f:
                f.write(self._to_toml(self.config))
        except Exception as e:
            write_log(t('config_save_failed', error=str(e)), 'error')

    def _to_toml(self, cfg: dict) -> str:
        lines = []
        # Flat top-level keys first / 顶层键在前
        for k, v in cfg.items():
            if isinstance(v, dict):
                continue
            if k.startswith('_'):
                continue
            lines.append(self._format_kv(k, v))
        # Then sections / 然后各段
        for section, vals in cfg.items():
            if not isinstance(vals, dict):
                continue
            lines.append('')
            lines.append(f'[{section}]')
            for k, v in vals.items():
                if k.startswith('_'):
                    continue
                lines.append(self._format_kv(k, v))
        return '\n'.join(lines) + '\n'

    def _format_kv(self, k: str, v) -> str:
        if isinstance(v, str):
            esc = v.replace('\\', '\\\\').replace('"', '\\"')
            return f'{k} = "{esc}"'
        if isinstance(v, bool):
            return f'{k} = {"true" if v else "false"}'
        if isinstance(v, (int, float)):
            return f'{k} = {v}'
        return f'# {k} = <unsupported>'

    # ------------------------------------------------------------
    # Language resolution
    # ------------------------------------------------------------
    def effective_language(self) -> str:
        lang = self.config.get('language', 'auto')
        if lang == 'auto':
            return detect_system_language()
        return lang if lang in ('zh-CN', 'en') else 'en'

# ============================================================
# Accounts / 账户
# ============================================================
class AccountsManager:
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
                # Normalize structure / 规范化结构
                if 'accounts' not in data:
                    # Old single-account format / 旧单账号格式
                    data = {
                        'current_index': 0,
                        'accounts': [{
                            'refresh_token': data.get('refresh_token', ''),
                            'profile': data.get('profile', {}),
                            'following': data.get('following', []),
                            'bookmarks': data.get('bookmarks', []),
                        }] if data.get('profile') or data.get('refresh_token') else [],
                        'webapi': {'PHPSESSID': ''},
                    }
                data.setdefault('current_index', 0)
                data.setdefault('accounts', [])
                data.setdefault('webapi', {'PHPSESSID': ''})
                return data
            except Exception as e:
                write_log(f"accounts.json load failed: {e}", 'warn')
        return {
            'current_index': 0,
            'accounts': [],
            'webapi': {'PHPSESSID': ''},
        }

    def _ensure_migration(self):
        """Migrate from config.toml if no accounts / 从 config 迁移"""
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
            # Sync config with the currently-selected account
            idx = self.data.get('current_index', 0)
            if 0 <= idx < len(self.data['accounts']):
                cur_rt = self.data['accounts'][idx].get('refresh_token', '')
                if cur_rt:
                    self.config.config.pop('refresh_token', None)

    def save(self):
        try:
            with open(ACCOUNTS_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            write_log(f"accounts.json save failed: {e}", 'error')

    # ------------------------------------------------------------
    # Current account accessors — defensive / 当前账号访问器
    # ------------------------------------------------------------
    def get_current(self) -> dict:
        """Return the current account dict / 返回当前账号字典"""
        accounts = self.data.get('accounts', [])
        if not accounts:
            return {}
        idx = self.data.get('current_index', 0)
        if not (0 <= idx < len(accounts)):
            idx = 0
            self.data['current_index'] = 0
        return accounts[idx]

    def get_current_refresh_token(self) -> str:
        """Return the current account's refresh_token / 返回当前账号的 RefreshToken"""
        acct = self.get_current()
        return (acct.get('refresh_token') or '').strip()

    def get_current_profile(self) -> dict:
        acct = self.get_current()
        return acct.get('profile', {}) if acct else {}

    def set_current_profile(self, profile: dict):
        acct = self.get_current()
        if not acct:
            return
        acct['profile'] = profile
        self.save()

    def get_current_following(self) -> list:
        acct = self.get_current()
        return acct.get('following', []) if acct else []

    def set_current_following(self, items: list):
        acct = self.get_current()
        if not acct:
            return
        acct['following'] = items
        self.save()

    def get_current_bookmarks(self) -> list:
        acct = self.get_current()
        return acct.get('bookmarks', []) if acct else []

    def set_current_bookmarks(self, items: list):
        acct = self.get_current()
        if not acct:
            return
        acct['bookmarks'] = items
        self.save()

    # ------------------------------------------------------------
    # PHPSESSID / Web Ajax
    # ------------------------------------------------------------
    def get_phpsessid(self) -> str:
        return self.data.get('webapi', {}).get('PHPSESSID', '')

    def set_phpsessid(self, value: str):
        self.data.setdefault('webapi', {})['PHPSESSID'] = value
        self.save()

    # ------------------------------------------------------------
    # Account management / 账号管理
    # ------------------------------------------------------------
    def list_accounts(self) -> list:
        out = []
        for i, acc in enumerate(self.data.get('accounts', [])):
            p = acc.get('profile', {}) or {}
            rt = acc.get('refresh_token', '') or ''
            out.append({
                'index': i,
                'id': p.get('id'),
                'name': p.get('name', ''),
                'account': p.get('account', ''),
                'avatar': p.get('avatar', ''),
                'refresh_token': rt,               # NEW: expose for UI
                'refresh_token_preview': (rt[:8] + '...' + rt[-6:]) if len(rt) > 20 else rt,
                'is_current': i == self.data.get('current_index', 0),
            })
        return out

    def add_account(self, refresh_token: str) -> int:
        refresh_token = refresh_token.strip()
        for i, acc in enumerate(self.data.get('accounts', [])):
            if acc.get('refresh_token') == refresh_token:
                self.data['current_index'] = i
                self.save()
                return i
        self.data.setdefault('accounts', []).append({
            'refresh_token': refresh_token,
            'profile': {},
            'following': [],
            'bookmarks': [],
        })
        self.data['current_index'] = len(self.data['accounts']) - 1
        self.save()
        return self.data['current_index']

    def switch_account(self, index: int) -> bool:
        accounts = self.data.get('accounts', [])
        if 0 <= index < len(accounts):
            self.data['current_index'] = index
            self.save()
            return True
        return False

    def remove_account(self, index: int) -> bool:
        accounts = self.data.get('accounts', [])
        if 0 <= index < len(accounts):
            accounts.pop(index)
            if not accounts:
                self.data['current_index'] = 0
            else:
                self.data['current_index'] = min(
                    self.data.get('current_index', 0),
                    len(accounts) - 1
                )
            self.save()
            return True
        return False

    def get_current_refresh_token(self) -> str:
        cur = self.get_current()
        return cur.get('refresh_token', '') if cur else ''

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

class WebAjaxClient:
    """Pixiv Web Ajax API client / 网页版 API 客户端"""

    BASE = "https://www.pixiv.net/ajax"

    # Mode constants / 模式常量
    MODE_DISABLED     = 'disabled'
    MODE_ILLUST_ONLY  = 'illust_only'
    MODE_ILLUST_USER  = 'illust_user'
    MODE_GLOBAL       = 'global'

    def __init__(self, config, accounts, rate_limiter):
        self.config = config
        self.accounts = accounts
        self.rate_limiter = rate_limiter

    # ------------------------------------------------------------
    # Availability / 可用性
    # ------------------------------------------------------------
    def is_available(self) -> bool:
        if not self.accounts:
            return False
        if not self.accounts.get_phpsessid():
            return False
        mode = self.config.get('api.web_ajax_mode', self.MODE_DISABLED)
        return mode != self.MODE_DISABLED

    def _use_for(self, feature: str) -> bool:
        """
        feature: 'illust' | 'user' | 'list'
        / 判定某功能是否走 Ajax
        """
        if not self.is_available():
            return False
        mode = self.config.get('api.web_ajax_mode', self.MODE_DISABLED)
        if mode == self.MODE_ILLUST_ONLY:
            return feature == 'illust'
        if mode == self.MODE_ILLUST_USER:
            return feature in ('illust', 'user')
        if mode == self.MODE_GLOBAL:
            return True
        return False

    # ------------------------------------------------------------
    # Low-level request / 底层请求
    # ------------------------------------------------------------
    def _headers(self) -> dict:
        return {
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/121.0.0.0 Safari/537.36"),
            "Referer": "https://www.pixiv.net/",
            "Accept": "application/json",
            "Cookie": f"PHPSESSID={self.accounts.get_phpsessid()}",
        }

    def _request(self, path: str, params: dict = None) -> dict:
        self.rate_limiter.wait_if_limited()
        try:
            r = requests.get(f"{self.BASE}/{path}",
                             params=params or {},
                             headers=self._headers(),
                             timeout=15)
            if r.status_code != 200:
                write_log(f"Web Ajax HTTP {r.status_code}: {path}", 'warn')
                return {}
            data = r.json()
            if data.get('error'):
                write_log(f"Web Ajax error: {data.get('message', '')}", 'warn')
                return {}
            return data.get('body', {}) or {}
        except Exception as e:
            write_log(f"Web Ajax failed: {e}", 'warn')
            return {}

    # ------------------------------------------------------------
    # Feature endpoints / 各功能接口
    # ------------------------------------------------------------
    def illust_detail(self, iid: int) -> dict:
        if not self._use_for('illust'):
            return {}
        return self._request(f"illust/{iid}")

    def user_detail(self, uid: int) -> dict:
        if not self._use_for('user'):
            return {}
        return self._request(f"user/{uid}")

    def search_illust(self, word: str, mode: str = 's_tag_full',
                      order: str = 'date_d', offset: int = 0,
                      search_type: str = 'all') -> dict:
        """Note: Web search uses different params / 网页搜索参数不同"""
        if not self._use_for('list'):
            return {}
        # Web 搜索接口: /ajax/search/artworks/{word}
        return self._request(
            f"search/artworks/{word}",
            params={
                'word': word,
                'order': order,
                'mode': 'all',
                's_mode': mode,
                'type': search_type,
                'p': (offset // 60) + 1,    # Web 分页从 1 开始
                'lang': 'zh',
            }
        )

    def ranking(self, mode: str = 'day', page: int = 1) -> dict:
        """Web ranking endpoint / 网页排行榜"""
        if not self._use_for('list'):
            return {}
        return self._request(f"illust/ranking",
                             params={'mode': mode, 'page': page, 'lang': 'zh'})

# ============================================================
# Pixiv API
# ============================================================
class PixivAPI:
    def __init__(self, config, rate_limiter, accounts=None):
        self.config = config
        self.rate_limiter = rate_limiter
        self.accounts = accounts
        self.web_ajax = WebAjaxClient(config, accounts, rate_limiter) if accounts else None
        self.api = None
        self.logged_in = False
        self._lock = threading.Lock()

    def login(self):
        if self.api is None:
            self.api = AppPixivAPI()
            proxy = self.config.get('proxy')
            if proxy:
                self.api.set_proxy(proxy)

        rt = ''
        if self.accounts:
            rt = self.accounts.get_current_refresh_token()

        if not rt:
            # Diagnostic log / 诊断日志
            try:
                accounts_data = self.accounts.data if self.accounts else {}
                n = len(accounts_data.get('accounts', []))
                idx = accounts_data.get('current_index', 0)
                write_log(
                    f"No refresh token available "
                    f"(accounts={n}, current_index={idx})",
                    'error')
            except Exception:
                write_log("No refresh token available", 'error')
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
        # App API baseline / App API 基础数据
        self.ensure_login()
        try:
            app_info = self._call_with_retry(self.api.illust_detail, iid).get("illust", {}) or {}
        except Exception:
            app_info = {}

        # Enrich with Web Ajax if enabled / 若启用 Ajax 则补全
        if self.web_ajax and self.web_ajax._use_for('illust'):
            web = self.web_ajax.illust_detail(iid)
            if web:
                if web.get('description') and not app_info.get('caption'):
                    app_info['caption'] = web['description']
                    write_log(f"Enriched caption from Web Ajax for {iid}", 'info')
                # Fallback for other fields / 其他字段补充
                for src, dst in [
                    ('bookmarkCount', 'total_bookmarks'),
                    ('viewCount', 'total_view'),
                    ('userName', None),
                ]:
                    if dst and not app_info.get(dst):
                        app_info[dst] = web.get(src)

        return app_info

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

    def search_novel(self, word, sort='date_desc', offset=0):
        self.ensure_login()
        return self._call_with_retry(self.api.search_novel, word,
                                     sort=sort, offset=offset)

    def get_ranking(self, mode='day', date=None, offset=0):
        self.ensure_login()
        return self._call_with_retry(self.api.illust_ranking, mode, date=date, offset=offset)

    def search_users(self, word, offset=0):
        self.ensure_login()
        return self._call_with_retry(self.api.search_user, word, offset=offset)

    def get_user_detail(self, uid):
        self.ensure_login()
        try:
            data = self._call_with_retry(self.api.user_detail, uid) or {}
        except Exception:
            data = {}

        if self.web_ajax and self.web_ajax._use_for('user'):
            web = self.web_ajax.user_detail(uid)
            if web:
                user = data.setdefault('user', {})
                if web.get('comment') and not user.get('comment'):
                    user['comment'] = web['comment']
                    write_log(f"Enriched user comment from Web Ajax for {uid}", 'info')

        return data

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

    def _get_executor(self):
        if self._executor is None:
            n = max(1, min(8, int(self.config.get('api.parallel_requests', 1))))
            with self._executor_lock:
                if self._executor is None:
                    self._executor = ThreadPoolExecutor(max_workers=n,
                                                       thread_name_prefix='pixiv-api')
        return self._executor

    def batch_call(self, fn, items, *args, **kwargs):
        """Execute fn(item, *args, **kwargs) for each item in parallel"""
        n = max(1, int(self.config.get('api.parallel_requests', 1)))
        if n == 1:
            return [fn(it, *args, **kwargs) for it in items]
        executor = self._get_executor()
        futures = [executor.submit(fn, it, *args, **kwargs) for it in items]
        return [f.result() for f in futures]

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
                f.write("-m\n")  # Always ignore minor errors / 始终忽略次要错误
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
    def __init__(self, config, session: SessionManager, accounts: AccountsManager):
        self.config = config
        self.session = session
        self.accounts = accounts
        self.rate_limiter = RateLimiter()
        self.api = PixivAPI(config, self.rate_limiter, accounts=accounts)
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
        self._retry_pass = 0                 # NEW: auto-retry counter / 自动重试计数器
        self._max_retry_passes = 3           # NEW: max auto-retry rounds / 最大自动重试轮次

        # Per-item status tracking / 单项状态追踪
        self.items_status = {}          # pid -> {status, title, stage, progress, ts}
        self._items_lock = threading.Lock()
        self._items_max = 300           # keep last N entries / 最多保留 N 项

        self.status_callback = None
        self.items_callback = None      # callback for items updates / 状态更新回调

        self.web_ajax = WebAjaxClient(config, accounts, self.rate_limiter)

    def set_status_callback(self, cb):
        self.status_callback = cb

    def _emit(self, msg, level='info'):
        write_log(msg, level)
        if self.status_callback:
            self.status_callback(msg, level)

    def _update_item_status(self, pid, **fields):
        if pid is None:
            return
        with self._items_lock:
            cur = self.items_status.get(pid, {})
            cur.update(fields)
            cur['ts'] = time.time()
            self.items_status[pid] = cur
            # Trim old finished entries / 裁剪已完成的旧项
            if len(self.items_status) > self._items_max:
                sorted_items = sorted(
                    self.items_status.items(),
                    key=lambda x: x[1].get('ts', 0)
                )
                for k, v in sorted_items:
                    if v.get('status') in ('success', 'failed'):
                        self.items_status.pop(k, None)
                        if len(self.items_status) <= self._items_max:
                            break
        self._emit_items_update()

    def _emit_items_update(self):
        if not self.items_callback:
            return
        with self._items_lock:
            snapshot = [
                {'pid': pid, **info}
                for pid, info in self.items_status.items()
            ]
        # Sort: processing first, then by ts desc / 排序：进行中优先
        snapshot.sort(key=lambda x: (
            0 if x.get('status') == 'processing' else 1,
            -x.get('ts', 0)
        ))
        try:
            self.items_callback(snapshot)
        except Exception:
            pass

    def _current_workers(self) -> int:
        mode = self.config.get('performance.download_mode', 'normal')
        if mode == 'normal':
            return 1
        return max(1, int(self.config.get('performance._resolved_workers', 3)))

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
    def _fetch_illust_detail(self, iid: int, cached_meta=None) -> dict:
        """
        Priority:
        1. Cached metadata (from list results)
        2. App API (fast)
        3. Web Ajax (if enabled + PHPSESSID set) — merged for caption
        """
        if cached_meta and cached_meta.get('illust'):
            info = dict(cached_meta['illust'])
        else:
            info = self.api.get_illust_detail(iid)

        if not info:
            return {}

        # If caption is missing and Web Ajax is available, enrich / 若 caption 为空则补全
        if not info.get('caption') and self.config.get('api.enable_web_ajax', True):
            web = self.web_ajax.illust_detail(iid)
            if web:
                # Web Ajax returns description field / Web 返回 description 字段
                desc = web.get('description', '')
                if desc:
                    info['caption'] = desc
                    write_log(f"Enriched caption from Web Ajax for {iid}", 'info')
                # Also fill in other missing fields / 补充其他字段
                for src_key, dst_key in [
                    ('userName', None),
                    ('userId', None),
                    ('bookmarkCount', 'total_bookmarks'),
                    ('viewCount', 'total_view'),
                    ('likeCount', None),
                ]:
                    if dst_key and not info.get(dst_key):
                        info[dst_key] = web.get(src_key)
        return info

    def add_items(self, items: list):
        if self.processed_count > 0 and self.url_queue.empty() and not self.is_running:
            self.processed_count = 0
            self._retry_pass = 0
            with self._items_lock:
                self.items_status = {}
            self._emit_items_update()

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
        # Clear item statuses for pending items / 清空待处理项状态
        with self._items_lock:
            self.items_status = {
                pid: info for pid, info in self.items_status.items()
                if info.get('status') == 'processing'
            }
        self._emit_items_update()
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

            url = None
            cached = None
            if isinstance(item, tuple) and len(item) == 4:
                # Legacy retry tuple / 旧重试元组（已不主动生成，兼容保留）
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
                url = item.get('url')
                cached = item.get('metadata')
                self._emit(t('processing', url=url,
                             remaining=self.url_queue.qsize()), 'info')
                # Try to extract pid early / 尝试提前解析 pid
                try:
                    _, early_pid = self._parse_url(url)
                except Exception:
                    early_pid = None

                ok, pid, img_path, meta_d = self._process_url(url, cached_meta=cached)
                if ok:
                    self._emit(t('task_success', url=url), 'info')
                else:
                    self._emit(t('task_failed', url=url), 'error')
                    if meta_d:
                        with self.failed_lock:
                            self.failed_items.append((pid, img_path, meta_d))
                    # Ensure status is marked failed / 确保状态标记失败
                    if pid is not None:
                        self._update_item_status(
                            pid, status='failed', stage='error', error='task_failed')

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

                if has_remaining:
                    # New items arrived during shutdown / 关闭期间有新项
                    self._save_queue()
                    self.start()
                elif has_failed and self._retry_pass < self._max_retry_passes:
                    self._retry_pass += 1
                    with self.failed_lock:
                        retry_items = list(self.failed_items)
                        self.failed_items.clear()
                    for pid, img_path, meta_d in retry_items:
                        retry_url = f"https://www.pixiv.net/artworks/{pid}"
                        self.url_queue.put({'url': retry_url})
                        self._update_item_status(
                            pid, status='pending', stage='retry',
                            progress=0, error='')
                    self._emit(
                        f"Auto-retry pass {self._retry_pass}/{self._max_retry_passes}: "
                        f"{len(retry_items)} items", 'warn')
                    self.start()
                else:
                    if not has_remaining and not has_failed:
                        self.session.set_queue({'current_tasks': [],
                                                'failed_tasks': []})
                        self._retry_pass = 0
                        write_log("All tasks completed", 'info')
                    else:
                        self._save_queue()
                        write_log(
                            f"Retries exhausted, {self.get_failed_count()} items still failing",
                            'warn')
                    self._emit(t('workers_stopped'), 'info')

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
        m = re.search(r'/novel/show\.php\?id=(\d+)', url)
        if m:
            return 'novel', int(m.group(1))
        if url.isdigit():
            # Ambiguous — default to illust; caller can override / 默认插画
            return 'illust', int(url)
        raise ValueError(url)

    def _process_url(self, url, cached_meta=None):
        typ, pid = self._parse_url(url)
        if typ == 'illust':
            return self._process_illust(pid, cached_meta=cached_meta)
        elif typ == 'novel':
            return self._process_novel(pid, cached_meta=cached_meta)
        return False, None, None, None

    def _process_illust(self, iid, cached_meta=None):
        info = self._fetch_illust_detail(iid, cached_meta=cached_meta)
        if info and info.get('type') == 'ugoira':
            return self._process_ugoira(iid, cached_meta={'illust': info})

        if cached_meta and cached_meta.get('illust'):
            info = cached_meta['illust']
            write_log(f"Using cached metadata for {iid}", 'info')
        else:
            info = self.api.get_illust_detail(iid)
        if not info:
            write_log(t('illust_fetch_failed', id=iid), 'warn')
            self._update_item_status(iid, status='failed', stage='fetch',
                                     progress=0, error='fetch_failed')
            return False, iid, None, None
        if not info.get('visible', False):
            write_log(t('illust_invisible', id=iid), 'warn')
            self._update_item_status(iid, status='failed', stage='invisible',
                                     progress=0, error='invisible')
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

        # 下载每页 / Download each page
        saved = []
        total = len(urls)
        for idx, u in enumerate(urls):
            base = u.split('?')[0]
            fname = os.path.basename(base)
            if not fname:
                ext = os.path.splitext(base)[1] or '.jpg'
                fname = f"{iid}{ext}" if page_count == 1 else f"{iid}_p{urls.index(u)+1}{ext}"
            sp = self.download_dir / fname
            if sp.exists():
                write_log(t('file_exists', path=str(sp)), 'info')
                saved.append(sp)
                self._update_item_status(
                    iid, stage='downloading',
                    progress=int(5 + (idx + 1) / total * 80))
                continue

            write_log(t('downloading', url=u, path=str(sp)), 'info')
            self._update_item_status(
                iid, stage='downloading',
                progress=int(5 + idx / total * 80))

            if self.api.download_image(u, sp):
                write_log(t('download_done', path=str(sp)), 'info')
                self._update_item_status(
                    iid, stage='writing_meta',
                    progress=int(5 + (idx + 1) / total * 80))

                ok, _ = self.exiftool.write_metadata(sp, metadata,
                                                     ignore_minor=False,
                                                     export_json=False)
                if ok:
                    saved.append(sp)
                else:
                    write_log(t('metadata_failed', path=str(sp)), 'warn')
                    self._update_item_status(
                        iid, status='failed', stage='metadata',
                        progress=100, error='metadata_failed')
                    return False, iid, sp, metadata
            else:
                self._update_item_status(
                    iid, status='failed', stage='download',
                    progress=int(5 + idx / total * 80),
                    error='download_failed')
                return False, iid, None, metadata

        # 完成
        self._update_item_status(iid, status='success', stage='done',
                                 progress=100)

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

    def _process_ugoira(self, iid, cached_meta=None):
        """
        Ugoira download:
        1. Fetch metadata (frames + zip_url)
        2. Download ZIP, extract frames
        3. Compose APNG via PIL
        4. Write metadata via ExifTool
        """
        self._update_item_status(iid, status='processing', stage='fetching',
                                 progress=0, title='')

        # Fetch illust metadata for title/author/tags / 获取作品基础信息
        info = self._fetch_illust_detail(iid, cached_meta=cached_meta)
        if not info:
            self._update_item_status(iid, status='failed', stage='fetch',
                                     error='fetch_failed')
            return False, iid, None, None

        title = info.get('title', '')
        author = info.get('user', {}).get('name', '')
        author_id = info.get('user', {}).get('id')
        create_date = info.get('create_date', '')
        caption = info.get('caption', '')
        tags = info.get('tags', [])
        page_count = info.get('page_count', 1)
        restr_attrs = info.get('restriction_attributes', [])
        ai_type = info.get('illust_ai_type', 0)
        x_restrict = info.get('x_restrict', 0)

        self._update_item_status(iid, title=title, stage='fetching_meta',
                                 progress=10)

        # Fetch ugoira metadata / 获取动图元数据
        try:
            um = self.api.api.ugoira_metadata(iid)
            ugoira = um.get('ugoira_metadata', {})
            zip_url = ugoira.get('zip_urls', {}).get('medium', '')
            frames = ugoira.get('frames', [])
        except Exception as e:
            write_log(f"ugoira_metadata failed: {e}", 'error')
            self._update_item_status(iid, status='failed', stage='meta',
                                     error=str(e))
            return False, iid, None, None

        if not zip_url or not frames:
            self._update_item_status(iid, status='failed', stage='meta',
                                     error='no_frames')
            return False, iid, None, None

        # Download ZIP / 下载 ZIP
        self._update_item_status(iid, stage='downloading_zip', progress=20)
        temp_dir = self.download_dir / "_ugoira_tmp" / str(iid)
        temp_dir.mkdir(parents=True, exist_ok=True)
        zip_path = temp_dir / "frames.zip"

        headers = {
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/121.0.0.0 Safari/537.36"),
            "Referer": "https://www.pixiv.net/",
        }
        try:
            r = requests.get(zip_url, headers=headers, stream=True, timeout=60)
            r.raise_for_status()
            with open(zip_path, 'wb') as f:
                for chunk in r.iter_content(8192):
                    f.write(chunk)
        except Exception as e:
            write_log(f"Ugoira ZIP download failed: {e}", 'error')
            self._update_item_status(iid, status='failed', stage='download',
                                     error='zip_failed')
            return False, iid, None, None

        # Extract frames / 解压序列帧
        self._update_item_status(iid, stage='extracting', progress=40)
        try:
            with zipfile.ZipFile(zip_path, 'r') as z:
                z.extractall(temp_dir)
        except Exception as e:
            write_log(f"Ugoira extraction failed: {e}", 'error')
            self._update_item_status(iid, status='failed', stage='extract',
                                     error=str(e))
            return False, iid, None, None

        # Compose APNG / 合成 APNG
        self._update_item_status(iid, stage='composing', progress=60)
        filename = f"{iid}.png"
        apng_path = self.download_dir / filename

        try:
            frame_files = []
            delays = []
            for fr in frames:
                fname = fr.get('file', '')
                delay = fr.get('delay', 100)
                fpath = temp_dir / fname
                if fpath.exists():
                    frame_files.append(fpath)
                    delays.append(delay)

            if not frame_files:
                raise RuntimeError("no frames extracted")

            images = [Image.open(p).convert('RGBA') for p in frame_files]
            # PIL APNG save / PIL 保存 APNG
            images[0].save(
                apng_path,
                save_all=True,
                append_images=images[1:],
                duration=delays,
                loop=0,
                format='PNG',
                optimize=False,
            )
            for img in images:
                img.close()
        except Exception as e:
            write_log(f"APNG composition failed: {e}", 'error')
            self._update_item_status(iid, status='failed', stage='compose',
                                     error=str(e))
            return False, iid, None, None

        # Cleanup temp / 清理临时目录
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass

        # Write metadata / 写入元数据
        self._update_item_status(iid, stage='writing_meta', progress=85)

        tag_names = [t.get('name', '') for t in tags]
        trans_names = [t.get('translated_name', '') for t in tags]
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
        pri.append("ugoira")
        final_tags = pri + tag_strs

        cap = self._clean_caption(caption)
        desc = f"{meta('source_url')}: https://www.pixiv.net/artworks/{iid}"
        if cap:
            desc += f"\n{meta('description')}: {cap}"

        metadata = {
            "XMP-dc:title": title,
            "EXIF:ImageDescription": title,
            "XMP-dc:creator": author,
            "EXIF:Artist": author,
            "XMP-dc:subject": final_tags,
            "EXIF:XPKeywords": ",".join(final_tags),
            "XMP:CreateDate": create_date,
            "XMP:MetadataDate": create_date,
            "EXIF:DateTimeOriginal": create_date,
            "XMP-dc:description": desc,
            "EXIF:XPComment": f"{meta('source_url')}: https://www.pixiv.net/artworks/{iid}",
            "XMP-dc:type": "ugoira",
        }
        self.exiftool.write_metadata(apng_path, metadata,
                                     ignore_minor=True, export_json=False)

        self._update_item_status(iid, status='success', stage='done', progress=100)

        # History / 历史记录
        append_history({
            'id': iid, 'title': title, 'page_count': 1,
            'author': author, 'author_id': author_id,
            'tags': final_tags,
            'ai_generated': ai_type == 2,
            'sensitive': x_restrict > 0 or bool(restr_attrs),
            'restriction': pri[0] if pri and pri[0].startswith('R-') else '',
            'type': 'ugoira',
            'publish_time': format_date(create_date),
            'downloaded_at': int(time.time()),
        })

        return True, iid, apng_path, metadata

    def _process_novel(self, nid, cached_meta=None):
        """
        Novel download:
        - App API: novel_detail + novel_text (pixivpy 3.7.5+)
        - Output: Markdown with YAML frontmatter
        - Metadata: XMP written via ExifTool to the .md file (or sidecar)
        """
        self._update_item_status(nid, status='processing', stage='fetching',
                                 progress=0, title='')

        info = self.api.get_novel_detail(nid)
        if not info:
            self._update_item_status(nid, status='failed', stage='fetch',
                                     error='fetch_failed')
            return False, nid, None, None

        title = info.get('title', '')
        author = info.get('user', {}).get('name', '')
        author_id = info.get('user', {}).get('id')
        create_date = info.get('create_date', '')
        caption = info.get('caption', '')
        tags = info.get('tags', [])
        tag_names = [t.get('name', '') for t in tags]

        self._update_item_status(nid, title=title, stage='fetching_text',
                                 progress=15)

        # Fetch full text / 获取正文
        try:
            text_resp = self.api.api.novel_text(nid)
            novel_text = text_resp.get('novel_text', '') if text_resp else ''
        except Exception as e:
            write_log(f"novel_text failed: {e}", 'error')
            novel_text = ''
            self._update_item_status(nid, status='failed', stage='text',
                                     error='text_fetch_failed')
            return False, nid, None, None

        self._update_item_status(nid, stage='writing', progress=60)

        # Build Markdown / 生成 Markdown
        safe_title = re.sub(r'[\\/:*?"<>|]', '_', title)[:80]
        filename = f"{nid}_{safe_title}.md"
        save_path = self.download_dir / "novels"
        save_path.mkdir(exist_ok=True)
        md_path = save_path / filename

        frontmatter = {
            'id': nid,
            'title': title,
            'author': author,
            'author_id': author_id,
            'create_date': create_date,
            'tags': tag_names,
            'source': f"https://www.pixiv.net/novel/show.php?id={nid}",
        }

        yaml_lines = ['---']
        for k, v in frontmatter.items():
            if isinstance(v, list):
                yaml_lines.append(f"{k}:")
                for item in v:
                    yaml_lines.append(f"  - {json.dumps(item, ensure_ascii=False)}")
            else:
                yaml_lines.append(f"{k}: {json.dumps(v, ensure_ascii=False)}")
        yaml_lines.append('---')
        yaml_lines.append('')
        yaml_lines.append(f"# {title}")
        yaml_lines.append('')
        if caption:
            yaml_lines.append(self._clean_caption(caption))
            yaml_lines.append('')
        yaml_lines.append(novel_text)

        content = '\n'.join(yaml_lines)
        try:
            md_path.write_text(content, encoding='utf-8')
        except Exception as e:
            write_log(f"Novel write failed: {e}", 'error')
            self._update_item_status(nid, status='failed', stage='write',
                                     error=str(e))
            return False, nid, None, None

        self._update_item_status(nid, stage='writing_meta', progress=85)

        # Write metadata via ExifTool / 写入元数据
        metadata = {
            "XMP-dc:title": title,
            "XMP-dc:creator": author,
            "XMP-dc:subject": tag_names,
            "XMP-dc:description": self._clean_caption(caption) or f"Source: https://www.pixiv.net/novel/show.php?id={nid}",
            "XMP-dc:type": "novel",
            "XMP:CreateDate": create_date,
            "XMP:MetadataDate": create_date,
        }
        ok, _ = self.exiftool.write_metadata(md_path, metadata,
                                             ignore_minor=True, export_json=False)

        self._update_item_status(nid, status='success', stage='done', progress=100)
        return True, nid, md_path, metadata
    
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
        self.worker = DownloadWorker(config, session=session, accounts=accounts)
        self.worker.set_status_callback(self.on_worker_status)
        self.worker.items_callback = self._on_items_update
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

    def _on_items_update(self, snapshot):
        """Broadcast per-item status / 广播单项状态"""
        self.broadcast({'type': 'queue_items', 'items': snapshot})

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

def make_api(bridge) -> PixivAPI:
    """Create a PixivAPI with shared accounts / 创建带 accounts 的 API 实例"""
    return PixivAPI(
        bridge.config,
        bridge.worker.rate_limiter,
        accounts=bridge.accounts,
    )

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
    elif c == 'search':
        tag = cmd.get('tag', '')
        sort = cmd.get('sort', 'date_desc')
        target = cmd.get('target', 'exact_match_for_tags')
        duration = cmd.get('duration', '') or None
        start_date = cmd.get('start_date', '') or None
        end_date = cmd.get('end_date', '') or None
        pages = max(1, min(200, int(cmd.get('pages', 1))))
        start_page = max(1, int(cmd.get('start_page', 1)))
        filters = cmd.get('filters', {
            'illust': True,
            'manga': True,
            'novel': False,
            'ugoira': False,
        })
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
            api = make_api(bridge)
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
                elif ty == 'novel' and filters.get('novel'):
                    filtered.append(it)
                elif ty == 'ugoira' and filters.get('ugoira'):
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
            api = make_api(bridge)
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
            api = make_api(bridge)
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
            api = make_api(bridge)
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
            api = make_api(bridge)
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
            api = make_api(bridge)
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
            api = make_api(bridge)
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
            api = make_api(bridge)
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
            api = make_api(bridge)
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
            api = make_api(bridge)
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
            if k == 'webapi.PHPSESSID':
                bridge.accounts.set_phpsessid(str(v))
            elif k == 'refresh_token':
                # Refresh token now managed by accounts / 由 accounts 管理
                continue
            else:
                bridge.config.set(k, v)
        bridge.config._resolve_auto_workers()
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
            api = make_api(bridge)
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
        # Include current items snapshot / 附带当前项状态快照
        with bridge.worker._items_lock:
            init_payload['items'] = [
                {'pid': pid, **info}
                for pid, info in bridge.worker.items_status.items()
            ]
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
        if pid:
            # img_path may be None for download failures
            # / 下载失败时 img_path 可能为 None
            path_obj = Path(img_path) if img_path else None
            with worker.failed_lock:
                worker.failed_items.append((int(pid), path_obj, meta_d))
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
    @web.middleware
    async def no_cache_middleware(request, handler):
        """Disable caching for static resources / 开发期禁用静态资源缓存"""
        response = await handler(request)
        path = request.path
        if (path.startswith('/static/')
                or path.startswith('/ui_icons/')
                or path.startswith('/static_icons/')
                or path == '/'):
            response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
        return response

    app = web.Application(middlewares=[no_cache_middleware])
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

def migrate_legacy_refresh_token(config: ConfigManager, accounts: AccountsManager):
    """Move refresh_token from config.toml to accounts.json once / 一次性迁移"""
    # 从旧 config 读
    legacy_rt = ''
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, 'rb') as f:
                raw = tomllib.load(f)
            legacy_rt = raw.get('refresh_token', '') or ''
        except Exception:
            pass
    elif LEGACY_CONFIG_FILE.exists():
        try:
            with open(LEGACY_CONFIG_FILE, 'r', encoding='utf-8') as f:
                legacy_rt = json.load(f).get('refresh_token', '') or ''
        except Exception:
            pass

    if legacy_rt and not accounts.data['accounts']:
        accounts.add_account(legacy_rt)
        write_log("Migrated refresh_token from config to accounts.json", 'info')

    # 从 config 中清除
    if config.config.pop('refresh_token', None):
        config.save()

def main():
    set_language(peek_language())
    setup_logging()
    write_log(t('starting'), 'info')

    config = ConfigManager()   # 内部调用 _resolve_auto_workers

    # Log detected workers / 输出检测结果
    workers = config.get('performance._resolved_workers')
    mode = config.get('performance.download_mode')
    write_log(f"Download mode: {mode}, workers: {workers}", 'info')

    final_lang = config.effective_language()
    set_language(final_lang)
    write_log(t('language_loaded', lang=final_lang), 'info')

    accounts = AccountsManager(config)
    migrate_legacy_refresh_token(config, accounts)
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
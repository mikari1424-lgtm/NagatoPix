#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NagatoPix - A Powerful Pixiv App / 一个强大的 Pixiv 应用

- UI 主通道：App API（搜索、排行榜、关注新作、推荐、用户作品、模态框详情）
- 下载主通道：Ajax API（补全 caption / commentHtml）
- 写操作：App API（书签、关注）
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
import logging
import zipfile
import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from urllib.parse import urlparse, parse_qs, unquote, quote

import requests
import aiohttp
from aiohttp import web
from bs4 import BeautifulSoup
from PIL import Image
from pixivpy3 import AppPixivAPI

import tomllib

from i18n import t, meta, set_language


VERSION = "1.3.0"


# ============================================================
# Path / 路径
# ============================================================
def get_resource_path(relative: str) -> Path:
    """Bundled resource path / 打包资源路径"""
    base = Path(sys._MEIPASS) if getattr(sys, 'frozen', False) \
           else Path(__file__).parent
    return base / relative


def get_app_dir() -> Path:
    """Writable app directory / 可写目录"""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).parent


CONFIG_FILE        = get_app_dir() / "config.toml"
LEGACY_CONFIG_FILE = get_app_dir() / "pixiv_client_config.json"
ACCOUNTS_FILE      = get_app_dir() / "accounts.json"
SESSION_FILE       = get_app_dir() / "session.json"
LEGACY_QUEUE_FILE  = get_app_dir() / "queue.json"
HISTORY_FILE       = get_app_dir() / "history.json"
LOG_DIR            = get_app_dir() / "logs"
LOG_DIR.mkdir(exist_ok=True)
HISTORY_MAX = 2000


# ============================================================
# Logging / 日志
# ============================================================
_logger: Optional[logging.Logger] = None


def setup_logging():
    global _logger
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_file = LOG_DIR / f"nagato-{ts}.log"

    logger = logging.getLogger('nagato')
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    logger.propagate = False

    fh = logging.FileHandler(log_file, encoding='utf-8')
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        '[%(asctime)s] [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'))
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
    """Read language from config before logging is ready."""
    try:
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, 'rb') as f:
                lang = tomllib.load(f).get('language', 'auto')
                if lang in ('zh-CN', 'en'):
                    return lang
        elif LEGACY_CONFIG_FILE.exists():
            with open(LEGACY_CONFIG_FILE, 'r', encoding='utf-8') as f:
                lang = json.load(f).get('language', 'auto')
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
        'download_dir': str(Path.home() / "Pictures" / "Pixiv"),
        'proxy': '',
        'language': 'auto',         # auto | zh-CN | en
        'theme': 'dark',            # dark | light
        'ugoira_format': 'gif',
        'performance': {
            'download_mode': 'normal',          # normal | high
            'parallel_workers': 0,              # 0 = auto
            'download_delay': 0.5,
            'max_retries': 3,
            'enable_download_metadata_cache': True,
        },
        'api': {
            'request_delay': 0.3,
            'rate_limit_wait': 150.0,
            'max_results': 30,
            'parallel_requests': 1,
            'web_ajax_mode': 'auto',            # auto | disabled
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

    STRING_FIELDS = ('download_dir', 'proxy', 'language', 'theme', 'ugoira_format')

    def __init__(self):
        self.config = self._load_or_init()
        self._resolve_auto_workers()

    # ---------- Load / validate / save ----------
    def _default_copy(self) -> dict:
        return json.loads(json.dumps(self.DEFAULT_CONFIG))

    def _load_or_init(self) -> dict:
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, 'rb') as f:
                    cfg = tomllib.load(f)
                write_log(t('config_loaded', path=str(CONFIG_FILE)), 'info')
                merged = self._merge_defaults(cfg)
                validated, errors = self._validate(merged)
                for path, val, default, err in errors:
                    write_log(t('config_invalid', key=path, value=val,
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

        if LEGACY_CONFIG_FILE.exists():
            try:
                with open(LEGACY_CONFIG_FILE, 'r', encoding='utf-8') as f:
                    old = json.load(f)
                merged = self._merge_defaults(old)
                for k in ('exiftool_path', 'username', 'password',
                          'api_language', 'refresh_token'):
                    merged.pop(k, None)
                validated, _ = self._validate(merged)
                self.config = validated
                self.save()
                write_log(t('config_migrated', path=str(CONFIG_FILE)), 'info')
                return self.config
            except Exception as e:
                write_log(t('config_load_failed', error=str(e)), 'warn')

        self.config = self._default_copy()
        self.save()
        write_log(t('config_created', path=str(CONFIG_FILE)), 'info')
        return self.config

    def _merge_defaults(self, cfg: dict) -> dict:
        result = self._default_copy()
        for k, v in cfg.items():
            if k in ('performance', 'api') and isinstance(v, dict):
                for sk, sv in v.items():
                    result[k][sk] = sv
            elif k in result:
                result[k] = v
        return result

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
                    v = int(v) if isinstance(v, str) else v
                    if isinstance(v, bool) or not isinstance(v, int):
                        raise ValueError('not an integer')
                else:
                    v = float(v) if isinstance(v, str) else v
                    if isinstance(v, bool) or not isinstance(v, (int, float)):
                        raise ValueError('not a number')
                    v = float(v)
                if not (lo <= v <= hi):
                    raise ValueError(f'out of range [{lo}, {hi}]')
                node[leaf] = v
            except (ValueError, TypeError) as e:
                dnode = self.DEFAULT_CONFIG
                for k in keys[:-1]:
                    dnode = dnode.get(k, {})
                errors.append((path, node.get(leaf), dnode.get(leaf), str(e)))
                node[leaf] = dnode.get(leaf)

        for key in self.STRING_FIELDS:
            if key in result and not isinstance(result[key], str):
                errors.append((key, result[key],
                               self.DEFAULT_CONFIG[key], 'not a string'))
                result[key] = self.DEFAULT_CONFIG[key]

        if result.get('language') not in ('auto', 'zh-CN', 'en'):
            result['language'] = 'auto'
        if result.get('theme') not in ('dark', 'light'):
            result['theme'] = 'dark'
        if result.get('ugoira_format') not in ('gif', 'apng', 'webp'):
            result['ugoira_format'] = 'gif'
        if result['performance'].get('download_mode') not in ('normal', 'high'):
            result['performance']['download_mode'] = 'normal'

        api = result.setdefault('api', {})
        mode = str(api.get('web_ajax_mode', 'auto')).strip().lower()
        if mode not in ('auto', 'disabled'):
            errors.append(('api.web_ajax_mode', mode, 'auto',
                           'invalid choice, resetting to auto'))
            mode = 'auto'
        api['web_ajax_mode'] = mode

        return result, errors

    def _resolve_auto_workers(self):
        pw = self.config['performance'].get('parallel_workers', 0)
        if pw == 0:
            try:
                import psutil
                logical = psutil.cpu_count(logical=True) or 4
                detected = max(1, min(8, logical // 2))
            except Exception:
                detected = 3
            self.config['performance']['_resolved_workers'] = detected
            write_log(f"Auto worker count: {detected}", 'info')
        else:
            self.config['performance']['_resolved_workers'] = pw

    # ---------- Save ----------
    def save(self):
        try:
            self.config.setdefault('api', {}).setdefault('web_ajax_mode', 'auto')
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                f.write(self._to_toml(self.config))
        except Exception as e:
            write_log(t('config_save_failed', error=str(e)), 'error')

    def _to_toml(self, cfg: dict) -> str:
        lines = []
        for k, v in cfg.items():
            if isinstance(v, dict) or k.startswith('_'):
                continue
            lines.append(self._fmt(k, v))
        for section, vals in cfg.items():
            if not isinstance(vals, dict):
                continue
            lines.append('')
            lines.append(f'[{section}]')
            for k, v in vals.items():
                if k.startswith('_'):
                    continue
                lines.append(self._fmt(k, v))
        return '\n'.join(lines) + '\n'

    def _fmt(self, k, v) -> str:
        if isinstance(v, str):
            esc = v.replace('\\', '\\\\').replace('"', '\\"')
            return f'{k} = "{esc}"'
        if isinstance(v, bool):
            return f'{k} = {"true" if v else "false"}'
        if isinstance(v, (int, float)):
            return f'{k} = {v}'
        return f'# {k} = <unsupported>'

    # ---------- Accessors ----------
    def get(self, path: str, default=None):
        cur = self.config
        for k in path.split('.'):
            if isinstance(cur, dict) and k in cur:
                cur = cur[k]
            else:
                return default
        return cur

    def set(self, path: str, value):
        keys = path.split('.')
        cur = self.config
        for k in keys[:-1]:
            cur = cur.setdefault(k, {})
        cur[keys[-1]] = value
        self.save()

    def effective_language(self) -> str:
        lang = self.config.get('language', 'auto')
        if lang == 'auto':
            return detect_system_language()
        return lang if lang in ('zh-CN', 'en') else 'en'


# ============================================================
# Accounts / 账户
# ============================================================
class AccountsManager:
    """
    accounts.json:
    {
      "current_index": 0,
      "accounts": [{
        "refresh_token": "...",
        "phpsessid": "...",
        "profile": {...},
        "following": [...],
        "bookmarks": [...]
      }]
    }
    """

    def __init__(self, config):
        self.config = config
        self.data = self._load()
        self._lock = threading.Lock()
        self._migrate()

    def _load(self) -> dict:
        if ACCOUNTS_FILE.exists():
            try:
                with open(ACCOUNTS_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if 'accounts' not in data:
                    data = {
                        'current_index': 0,
                        'accounts': [{
                            'refresh_token': data.get('refresh_token', ''),
                            'phpsessid': '',
                            'profile': data.get('profile', {}),
                            'following': data.get('following', []),
                            'bookmarks': data.get('bookmarks', []),
                        }] if (data.get('profile') or data.get('refresh_token')) else [],
                    }
                data.setdefault('current_index', 0)
                data.setdefault('accounts', [])
                return data
            except Exception as e:
                write_log(f"accounts.json load failed: {e}", 'warn')
        return {'current_index': 0, 'accounts': []}

    def _migrate(self):
        legacy = self.data.pop('webapi', None)
        dirty = False
        if legacy and isinstance(legacy, dict):
            ps = (legacy.get('PHPSESSID') or '').strip()
            if ps and self.data['accounts']:
                idx = self.data.get('current_index', 0)
                if 0 <= idx < len(self.data['accounts']):
                    if not self.data['accounts'][idx].get('phpsessid'):
                        self.data['accounts'][idx]['phpsessid'] = ps
                        dirty = True
                        write_log("Migrated PHPSESSID to current account", 'info')
        if not self.data['accounts']:
            rt = self.config.get('refresh_token', '')
            if rt:
                self.data['accounts'].append({
                    'refresh_token': rt, 'phpsessid': '',
                    'profile': {}, 'following': [], 'bookmarks': [],
                })
                self.data['current_index'] = 0
                dirty = True
                write_log("Migrated refresh_token from config.toml", 'info')
        if dirty:
            self.save()

    def save(self):
        try:
            with open(ACCOUNTS_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            write_log(f"accounts.json save failed: {e}", 'error')

    # ---------- Current ----------
    def get_current(self) -> dict:
        acc = self.data.get('accounts', [])
        if not acc:
            return {}
        idx = self.data.get('current_index', 0)
        if not (0 <= idx < len(acc)):
            idx = 0
            self.data['current_index'] = 0
        return acc[idx]

    def get_current_refresh_token(self) -> str:
        return (self.get_current().get('refresh_token') or '').strip()

    def get_phpsessid(self) -> str:
        return (self.get_current().get('phpsessid') or '').strip()

    def set_phpsessid(self, value: str):
        acct = self.get_current()
        if acct:
            acct['phpsessid'] = value.strip()
            self.save()

    def get_current_profile(self) -> dict:
        return self.get_current().get('profile', {})

    def set_current_profile(self, profile: dict):
        acct = self.get_current()
        if acct:
            acct['profile'] = profile
            self.save()

    def get_current_following(self) -> list:
        return self.get_current().get('following', [])

    def set_current_following(self, items: list):
        acct = self.get_current()
        if acct:
            acct['following'] = items
            self.save()

    def get_current_bookmarks(self) -> list:
        return self.get_current().get('bookmarks', [])

    def set_current_bookmarks(self, items: list):
        acct = self.get_current()
        if acct:
            acct['bookmarks'] = items
            self.save()

    def get_self_uid(self):
        profile = self.get_current_profile()
        uid = profile.get('id') if profile else None
        return int(uid) if uid else None

    # ---------- Account list ----------
    def list_accounts(self) -> list:
        out = []
        for i, acc in enumerate(self.data.get('accounts', [])):
            p = acc.get('profile', {}) or {}
            rt = acc.get('refresh_token', '') or ''
            ps = acc.get('phpsessid', '') or ''
            out.append({
                'index': i,
                'id': p.get('id'),
                'name': p.get('name', ''),
                'account': p.get('account', ''),
                'avatar': p.get('avatar', ''),
                'refresh_token': rt,
                'refresh_token_preview':
                    (rt[:8] + '...' + rt[-6:]) if len(rt) > 20 else rt,
                'phpsessid': ps,
                'phpsessid_preview':
                    (ps[:8] + '...' + ps[-6:]) if len(ps) > 20 else ps,
                'is_current': i == self.data.get('current_index', 0),
            })
        return out

    def add_account(self, refresh_token: str, phpsessid: str = '') -> int:
        refresh_token = refresh_token.strip()
        phpsessid = phpsessid.strip()
        for i, acc in enumerate(self.data.get('accounts', [])):
            if acc.get('refresh_token') == refresh_token:
                if phpsessid:
                    acc['phpsessid'] = phpsessid
                self.data['current_index'] = i
                self.save()
                return i
        self.data.setdefault('accounts', []).append({
            'refresh_token': refresh_token, 'phpsessid': phpsessid,
            'profile': {}, 'following': [], 'bookmarks': [],
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
                    self.data.get('current_index', 0), len(accounts) - 1)
            self.save()
            return True
        return False


# ============================================================
# Session / 会话
# ============================================================
class SessionManager:
    """session.json: queue + ui_state"""

    def __init__(self):
        self.data = self._load()
        self._lock = threading.Lock()

    def _load(self) -> dict:
        if SESSION_FILE.exists():
            try:
                with open(SESSION_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                write_log(f"session.json load failed: {e}", 'warn')
        if LEGACY_QUEUE_FILE.exists():
            try:
                with open(LEGACY_QUEUE_FILE, 'r', encoding='utf-8') as f:
                    old = json.load(f)
                LEGACY_QUEUE_FILE.unlink()
                write_log("Migrated queue.json to session.json", 'info')
                return {'queue': old, 'ui_state': {}}
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
        return self.data.get('queue',
                             {'current_tasks': [], 'failed_tasks': []})

    def set_queue(self, queue_data: dict):
        self.data['queue'] = queue_data
        self.save()

    def get_ui_state(self) -> dict:
        return self.data.get('ui_state', {})

    def set_ui_state(self, state: dict):
        self.data['ui_state'] = state
        self.save()


# ============================================================
# ExifTool probe / 探测
# ============================================================
def get_exiftool_version(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    try:
        r = subprocess.run([str(path), "-ver"], capture_output=True,
                           text=True, encoding='utf-8', errors='ignore',
                           timeout=5)
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception as e:
        write_log(t('exiftool_version_error', error=str(e)), 'warn')
    return None


# ============================================================
# Console minimize / 控制台最小化
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
# History / 历史
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
# Latency / 延迟探测
# ============================================================
def measure_latency_sync(config):
    proxy = config.get('proxy') or None
    proxies = {'http': proxy, 'https': proxy} if proxy else None
    url = "https://www.cloudflare.com/cdn-cgi/trace"
    try:
        t0 = time.time()
        with requests.get(url, timeout=5, proxies=proxies,
                          stream=True,
                          headers={'User-Agent': 'Mozilla/5.0'}) as r:
            for _ in r.iter_content(512):
                break
        return int((time.time() - t0) * 1000)
    except Exception as e:
        write_log(t('latency_failed', error=str(e)), 'warn')
        return None


# ============================================================
# Rate limiter / 全局限速器
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
# Web Ajax Client / Web Ajax 客户端
# ============================================================
class WebAjaxClient:
    """
    仅用于这些场景：
    1. 下载时补全 caption（App API 会过滤含 URL 的说明）
    2. 用户简介的 commentHtml
    3. 搜索时统计数据+关联标签
    """
    BASE = "https://www.pixiv.net/ajax"
    WWW  = "https://www.pixiv.net"
    UA   = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/121.0.0.0 Safari/537.36")

    def __init__(self, config, accounts, rate_limiter):
        self.config = config
        self.accounts = accounts
        self.rate_limiter = rate_limiter

    # ---------- Availability ----------
    def is_available(self) -> bool:
        if not self.accounts or not self.accounts.get_phpsessid():
            return False
        return self.config.get('api.web_ajax_mode', 'auto') != 'disabled'

    def lang_param(self) -> str:
        return 'zh' if self.config.effective_language() == 'zh-CN' else 'en'

    # ---------- Request ----------
    def _headers(self, referer: str) -> dict:
        lang = self.config.effective_language()
        accept_lang = ('zh-CN,zh;q=0.9,en;q=0.8' if lang == 'zh-CN'
                       else 'en-US,en;q=0.9,ja;q=0.8')
        return {
            'User-Agent': self.UA,
            'Accept': 'application/json',
            'Accept-Language': accept_lang,
            'Referer': referer,
            'Cookie': f"PHPSESSID={self.accounts.get_phpsessid()}",
        }

    def _get(self, path: str, params=None, referer: str = None) -> dict:
        if not self.is_available():
            return {}

        self.rate_limiter.wait_if_limited()
        url = f"{self.BASE}/{path}"

        try:
            r = requests.get(
                url, params=params or {},
                headers=self._headers(referer or f"{self.WWW}/"),
                timeout=20)
        except Exception as e:
            write_log(f"Web Ajax exception [{path}]: {e}", 'warn')
            return {}

        if r.status_code == 429:
            delay = float(self.config.get('api.rate_limit_wait', 150))
            self.rate_limiter.set_limited(delay)
            write_log(f"Web Ajax rate limited, waiting {delay}s", 'warn')
            return {}
        if r.status_code != 200:
            write_log(f"Web Ajax HTTP {r.status_code}: {path}", 'warn')
            return {}
        try:
            data = r.json()
        except Exception:
            write_log(f"Web Ajax non-JSON: {path}", 'warn')
            return {}
        if data.get('error'):
            write_log(f"Web Ajax error [{path}]: {data.get('message', '')}",
                      'warn')
            return {}
        return data.get('body') or {}

    # ---------- Endpoints ----------
    def illust_detail(self, iid: int) -> dict:
        return self._get(f"illust/{iid}",
                         {'lang': self.lang_param()},
                         referer=f"{self.WWW}/artworks/{iid}")

    def illust_pages(self, iid: int) -> list:
        body = self._get(f"illust/{iid}/pages",
                         {'lang': self.lang_param()},
                         referer=f"{self.WWW}/artworks/{iid}")
        return body if isinstance(body, list) else []

    def user_detail(self, uid: int) -> dict:
        return self._get(f"user/{uid}",
                         {'full': 1, 'lang': self.lang_param()},
                         referer=f"{self.WWW}/users/{uid}")

    def search_artworks(self, word, page=1, s_mode='s_tag_full',
                        type_='all', duration=None):
        word_enc = quote(word, safe='')
        params = {
            'p': page,
            's_mode': s_mode,
            'type': type_,
            'lang': self.lang_param(),
        }
        if duration:
            params['duration'] = duration
        body = self._get(
            f"search/artworks/{word_enc}", params,
            referer=f"{self.WWW}/tags/{word_enc}/artworks")
        if isinstance(body, dict) and body:
            write_log(
                f"Ajax search '{word}': total="
                f"{(body.get('illustManga') or {}).get('total')}, "
                f"related={len(body.get('relatedTags') or [])}",
                'info')
        else:
            write_log(f"Ajax search '{word}': empty body", 'warn')
        return body if isinstance(body, dict) else {}


# ============================================================
# Pixiv API / 双通道封装
# ============================================================
class PixivAPI:
    """
    通道约定：
    - UI 主通道（模态框、搜索、排行榜、关注新作、推荐、用户作品）→ App API
    - 用户简介 → Ajax（commentHtml 仅在 Ajax 返回）
    - 下载详情 → Ajax 优先，回退 App
    """

    def __init__(self, config, rate_limiter, accounts=None):
        self.config = config
        self.rate_limiter = rate_limiter
        self.accounts = accounts
        self.web_ajax = (WebAjaxClient(config, accounts, rate_limiter)
                         if accounts else None)
        self.api = None
        self.logged_in = False
        self._lock = threading.Lock()
        self._executor = None
        self._executor_lock = threading.Lock()

        if accounts is None:
            write_log("PixivAPI created without accounts; login will fail",
                      'warn')

    # ---------- Login ----------
    def login(self):
        if self.api is None:
            self.api = AppPixivAPI()
            proxy = self.config.get('proxy')
            if proxy:
                self.api.set_proxy(proxy)

        rt = self.accounts.get_current_refresh_token() if self.accounts else ''
        if not rt:
            write_log("No refresh token in accounts.json", 'error')
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

    # ---------- Retry wrapper ----------
    def _call_with_retry(self, func, *args, **kwargs):
        max_retries = int(self.config.get('performance.max_retries', 3))
        delay = float(self.config.get('api.rate_limit_wait', 150))
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

    # ---------- App API wrappers ----------
    def get_illust_detail(self, iid):
        """UI path / UI 路径"""
        self.ensure_login()
        return self._call_with_retry(
            self.api.illust_detail, iid).get("illust", {})

    def get_illust_detail_ajax(self, iid):
        """Download path — Ajax preferred / 下载路径 — Ajax 优先"""
        if self.web_ajax and self.web_ajax.is_available():
            body = self.web_ajax.illust_detail(iid)
            if body:
                normalized = self._normalize_ajax_illust(body, iid)
                if (normalized.get('page_count') or 1) > 1:
                    pages = self.web_ajax.illust_pages(iid)
                    if pages:
                        normalized['meta_pages'] = self._normalize_ajax_pages(pages)
                        normalized['meta_single_page'] = {}
                write_log(
                    f"illust {iid} via Ajax "
                    f"(likes={normalized.get('total_likes', 0)}, "
                    f"tags={len(normalized.get('tags', []))})", 'info')
                return normalized
            write_log(f"illust {iid}: Ajax empty, using App", 'warn')

        self.ensure_login()
        return self._call_with_retry(
            self.api.illust_detail, iid).get("illust", {})

    def get_ugoira_metadata(self, iid):
        """Fetch ugoira frame metadata (zip url + frame delays)."""
        self.ensure_login()
        try:
            resp = self._call_with_retry(self.api.ugoira_metadata, iid)
        except Exception as e:
            write_log(f"ugoira_metadata {iid} failed: {e}", 'warn')
            return {}
        if not resp:
            return {}
        return resp.get('ugoira_metadata', {}) or {}

    def get_novel_detail(self, nid):
        self.ensure_login()
        return self._call_with_retry(
            self.api.novel_detail, nid).get("novel", {})

    def get_novel_text(self, nid):
        """Fetch full novel text + series navigation."""
        self.ensure_login()
        try:
            resp = self._call_with_retry(self.api.novel_text, nid)
            return resp or {}
        except Exception as e:
            write_log(f"novel_text {nid} failed: {e}", 'warn')
            return {}

    def get_novel_series(self, series_id, last_order=None):
        """Fetch all novels in a series."""
        self.ensure_login()
        kwargs = {}
        if last_order is not None:
            kwargs['last_order'] = last_order
        try:
            resp = self._call_with_retry(
                self.api.novel_series, series_id, **kwargs)
            return resp or {}
        except Exception as e:
            write_log(f"novel_series {series_id} failed: {e}", 'warn')
            return {}

    def search_illust(self, word, target='exact_match_for_tags',
                      sort='date_desc', offset=0, duration=None,
                      start_date=None, end_date=None):
        self.ensure_login()
        kwargs = {'search_target': target, 'sort': sort, 'offset': offset}
        if duration:
            kwargs['duration'] = duration
        if start_date and end_date:
            kwargs['start_date'] = start_date
            kwargs['end_date'] = end_date
        return self._call_with_retry(self.api.search_illust, word, **kwargs)

    def search_novel(self, word, target='exact_match_for_tags',
                     sort='date_desc', offset=0, duration=None,
                     start_date=None, end_date=None):
        self.ensure_login()
        kwargs = {'search_target': target, 'sort': sort, 'offset': offset}
        if duration:
            kwargs['duration'] = duration
        if start_date and end_date:
            kwargs['start_date'] = start_date
            kwargs['end_date'] = end_date
        return self._call_with_retry(self.api.search_novel, word, **kwargs)
    
    def get_ranking(self, mode='day', date=None, offset=0):
        self.ensure_login()
        return self._call_with_retry(
            self.api.illust_ranking, mode, date=date, offset=offset)

    def search_users(self, word, offset=0):
        self.ensure_login()
        return self._call_with_retry(self.api.search_user, word, offset=offset)

    def get_user_detail(self, uid): 
        """
        用户卡片：
        - 基础数据（name / account / 头像 / 统计 / 背景图等）→ App API
        - 简介（commentHtml）→ Ajax API，仅覆盖 comment / comment_parts
        - App API 失败时回退到完整 Ajax 归一化
        """
        self.ensure_login()

        # 1) App API 基础数据
        app_data = {}
        try:
            app_data = self._call_with_retry(self.api.user_detail, uid) or {}
        except Exception as e:
            write_log(f"user {uid} App detail failed: {e}", 'warn')
            app_data = {}

        # 2) Ajax 简介（仅在可用时请求一次）
        ajax_comment = None
        ajax_comment_parts = None
        ajax_body = None
        if self.web_ajax and self.web_ajax.is_available():
            ajax_body = self.web_ajax.user_detail(uid)
            if ajax_body:
                raw_html = ajax_body.get('commentHtml') or ''
                raw_plain = ajax_body.get('comment') or ''
                if raw_html:
                    ajax_comment = self._html_to_text(raw_html)
                    ajax_comment_parts = self._html_to_parts(raw_html)
                elif raw_plain:
                    ajax_comment = raw_plain
                    ajax_comment_parts = [{'type': 'text', 'value': raw_plain}]
                if ajax_comment:
                    write_log(f"user {uid}: comment via Ajax", 'info')
                else:
                    write_log(f"user {uid}: Ajax comment empty", 'info')

        # 3) 合并：App 基础数据 + Ajax 简介
        if app_data:
            if ajax_comment:
                user = app_data.setdefault('user', {})
                user['comment'] = ajax_comment
                user['comment_parts'] = ajax_comment_parts or []
            return app_data

        # 4) App 失败时回退到 Ajax 完整归一化
        if ajax_body:
            write_log(f"user {uid}: App failed, fallback to Ajax", 'warn')
            return self._normalize_ajax_user(ajax_body)

        return {}

    def get_user_illusts(self, uid, offset=0):
        self.ensure_login()
        return self._call_with_retry(self.api.user_illusts, uid, offset=offset)

    def get_illust_recommended(self, **kwargs):
        self.ensure_login()
        return self._call_with_retry(self.api.illust_recommended, **kwargs)

    def get_illust_follow(self, restrict='all', offset=0):
        self.ensure_login()
        return self._call_with_retry(
            self.api.illust_follow, restrict=restrict, offset=offset)

    def get_user_bookmarks(self, uid, restrict='public',
                       max_bookmark_id=None):
        """
        书签分页走游标：max_bookmark_id。
        pixivpy3 的 user_bookmarks_illust 不接受 offset。
        """
        self.ensure_login()
        kwargs = {'restrict': restrict}
        if max_bookmark_id is not None:
            kwargs['max_bookmark_id'] = int(max_bookmark_id)
        return self._call_with_retry(self.api.user_bookmarks_illust, uid, **kwargs)

    def search_artworks_ajax(self, word, page=1, target=None, duration=None):
        if not (self.web_ajax and self.web_ajax.is_available()):
            write_log("Ajax search skipped: Web Ajax unavailable", 'info')
            return {}
        s_mode_map = {
            'partial_match_for_tags': 's_tag',
            'exact_match_for_tags': 's_tag_full',
            'title_and_caption': 's_tc',
        }
        s_mode = s_mode_map.get(target, 's_tag_full')
        try:
            return self.web_ajax.search_artworks(
                word, page=page, s_mode=s_mode, duration=duration)
        except Exception as e:
            write_log(f"Ajax search meta failed: {e}", 'warn')
            return {}

    def follow_user(self, uid, restrict='public'):
        self.ensure_login()
        return self._call_with_retry(
            self.api.user_follow_add, uid, restrict=restrict)

    def unfollow_user(self, uid):
        self.ensure_login()
        return self._call_with_retry(self.api.user_follow_del, uid)

    def download_image(self, url, path, headers=None):
        if headers is None:
            headers = {
                'User-Agent': self.web_ajax.UA if self.web_ajax else
                              'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
                'Referer': 'https://www.pixiv.net/',
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

    # ---------- Parallel executor ----------
    def _get_executor(self):
        if self._executor is None:
            with self._executor_lock:
                if self._executor is None:
                    n = max(1, min(8, int(
                        self.config.get('api.parallel_requests', 1))))
                    self._executor = ThreadPoolExecutor(
                        max_workers=n, thread_name_prefix='pixiv-api')
        return self._executor

    def batch_call(self, fn, items, *args, **kwargs):
        n = max(1, int(self.config.get('api.parallel_requests', 1)))
        if n == 1:
            return [fn(it, *args, **kwargs) for it in items]
        ex = self._get_executor()
        futures = [ex.submit(fn, it, *args, **kwargs) for it in items]
        return [f.result() for f in futures]

    # ============================================================
    # Ajax normalization / Ajax 归一化
    # ============================================================
    def _extract_translation(self, trans_map: dict) -> str:
        if not isinstance(trans_map, dict):
            return ''
        if self.web_ajax:
            lang = self.web_ajax.lang_param()
            if trans_map.get(lang):
                return trans_map[lang]
        for k in ('en', 'zh', 'ja'):
            if trans_map.get(k):
                return trans_map[k]
        for v in trans_map.values():
            if v:
                return v
        return ''

    def _normalize_ajax_illust(self, body: dict, iid: int) -> dict:
        # Tags
        tags_out = []
        for t in (body.get('tags') or {}).get('tags') or []:
            tags_out.append({
                'name': t.get('tag', '') or '',
                'translated_name':
                    self._extract_translation(t.get('translation') or {}),
            })

        # User
        user_id = body.get('userId')
        user = {
            'id': int(user_id) if user_id else None,
            'name': body.get('userName', '') or '',
            'account': body.get('userAccount', '') or '',
            'profile_image_urls': {
                'medium': body.get('profileImageUrl', '') or '',
            },
            'is_followed': False,
            'is_accept_request': None,
        }

        # Type
        type_map = {0: 'illust', 1: 'manga', 2: 'ugoira'}
        type_str = type_map.get(body.get('illustType', 0), 'illust')

        # AI
        ai_type = 2 if body.get('aiType', 0) == 2 else 0

        # Page count
        page_count = body.get('pageCount', 1) or 1
        urls = body.get('urls') or {}
        original_url = urls.get('original', '') or ''
        regular_url = urls.get('regular', '') or ''

        single = {}
        if page_count <= 1 and (original_url or regular_url):
            single = {
                'original_image_url': original_url,
                'large_image_url': regular_url,
            }

        caption_html = (body.get('illustComment')
                        or body.get('description') or '')
        caption_plain = self._html_to_text(caption_html)
        caption_parts = self._html_to_parts(caption_html)

        return {
            'id': int(iid),
            'title': body.get('illustTitle') or body.get('title', ''),
            'caption': caption_plain,
            'caption_parts': caption_parts,
            'create_date': body.get('createDate', '') or '',
            'user': user,
            'tags': tags_out,
            'total_view': body.get('viewCount', 0) or 0,
            'total_bookmarks': body.get('bookmarkCount', 0) or 0,
            'total_likes': body.get('likeCount', 0) or 0,
            'total_comments': body.get('commentCount', 0) or 0,
            'page_count': page_count,
            'width': body.get('width'),
            'height': body.get('height'),
            'illust_ai_type': ai_type,
            'x_restrict': body.get('xRestrict', 0) or 0,
            'type': type_str,
            'visible': True,
            'restriction_attributes': [],
            'meta_single_page': single,
            'meta_pages': [],
            'is_bookmarked': bool(body.get('bookmarkData')),
            'is_masked': body.get('isMasked', False),
            'is_unlisted': body.get('isUnlisted', False),
            '_source': 'ajax-detail',
        }

    def _normalize_ajax_pages(self, pages: list) -> list:
        result = []
        if not isinstance(pages, list):
            return result
        for p in pages:
            u = p.get('urls') or {}
            result.append({
                'image_urls': {
                    'square_medium': u.get('thumb_mini') or u.get('small', ''),
                    'medium': u.get('small', ''),
                    'large': u.get('regular', ''),
                    'original': u.get('original', ''),
                },
                'width': p.get('width'),
                'height': p.get('height'),
            })
        return result

    def _normalize_ajax_user(self, body: dict) -> dict:
        region = body.get('region') or {}
        social = body.get('social') or {}
        twitter = social.get('twitter') or {}

        raw_html = body.get('commentHtml') or ''
        raw_plain = body.get('comment') or ''

        if raw_html:
            comment_plain = self._html_to_text(raw_html)
            comment_parts = self._html_to_parts(raw_html)
        elif raw_plain:
            comment_plain = raw_plain
            comment_parts = [{'type': 'text', 'value': raw_plain}]
        else:
            comment_plain = ''
            comment_parts = []

        user = {
            'id': int(body.get('userId')) if body.get('userId') else None,
            'name': body.get('name', '') or '',
            'account': body.get('account', '') or '',
            'comment': comment_plain,
            'comment_parts': comment_parts,
            'is_followed': body.get('isFollowed', False),
            'profile_image_urls': {
                'medium': body.get('imageBig') or body.get('image', '') or '',
            },
            'is_accept_request': None,
        }

        profile = {
            'webpage': body.get('webpage'),
            'gender': (body.get('gender') or {}).get('name', ''),
            'birth_day': (body.get('birthDay') or {}).get('name', ''),
            'region': region.get('name', '') or '',
            'country_code': region.get('region', '') or '',
            'job': (body.get('job') or {}).get('name', ''),
            'total_follow_users': body.get('following', 0) or 0,
            'total_mypixiv_users': body.get('mypixivCount', 0) or 0,
            'total_illusts': 0,
            'total_manga': 0,
            'total_novels': 0,
            'total_illust_bookmarks_public': 0,
            'background_image_url': body.get('background'),
            'twitter_account': twitter.get('url', '') or '',
            'twitter_url': twitter.get('url', '') or '',
            'is_premium': body.get('premium', False),
        }

        return {
            'user': user,
            'profile': profile,
            'profile_publicity': {},
            'workspace': body.get('workspace') or {},
            '_source': 'ajax',
        }

    # ============================================================
    # HTML utilities / HTML 工具
    # ============================================================
    def _strip_tags_and_entities(self, s: str) -> str:
        if not s:
            return ''
        s = re.sub(r'<[^>]+>', '', s)
        return (s.replace('&nbsp;', ' ')
                 .replace('&amp;', '&')
                 .replace('&lt;', '<')
                 .replace('&gt;', '>')
                 .replace('&quot;', '"')
                 .replace('&#39;', "'")
                 .replace('&apos;', "'"))

    def _resolve_pixiv_url(self, href: str) -> str:
        if not href:
            return ''
        href = href.strip()

        if href.startswith('/jump.php?'):
            try:
                after = href[len('/jump.php?'):]
                target = after.split('&')[0]
                real = unquote(target)
                if real.startswith(('http://', 'https://')):
                    return real
            except Exception:
                pass
            return ''

        if href.startswith('/'):
            return f"https://www.pixiv.net{href}"

        if href.startswith(('http://', 'https://')):
            return href

        return ''

    def _html_to_text(self, html: str) -> str:
        if not html:
            return ''
        text = re.sub(r'<br\s*/?>', '\n', html, flags=re.IGNORECASE)
        text = re.sub(r'</(p|div|li|h[1-6])>', '\n', text, flags=re.IGNORECASE)

        def link_repl(m):
            href = (m.group(1) or '').strip()
            inner = (m.group(2) or '')
            inner_text = self._strip_tags_and_entities(inner)
            if not inner_text:
                return href
            if href and href != inner_text:
                return f"{inner_text} ({href})"
            return inner_text

        text = re.sub(r'<a\s+[^>]*href=["\']([^"\']*)["\'][^>]*>(.*?)</a>',
                      link_repl, text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r'<[^>]+>', '', text)
        text = (text.replace('&nbsp;', ' ')
                    .replace('&amp;', '&')
                    .replace('&lt;', '<')
                    .replace('&gt;', '>')
                    .replace('&quot;', '"')
                    .replace('&#39;', "'")
                    .replace('&apos;', "'"))
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = '\n'.join(line.rstrip() for line in text.split('\n'))
        return text.strip()

    def _html_to_parts(self, html: str) -> list:
        if not html:
            return []
        html = re.sub(r'<br\s*/?>', '\n', html, flags=re.IGNORECASE)
        html = re.sub(r'</(p|div|li|h[1-6])>', '\n', html, flags=re.IGNORECASE)

        link_re = re.compile(
            r'<a\s+[^>]*href=["\']([^"\']*)["\'][^>]*>(.*?)</a>',
            re.IGNORECASE | re.DOTALL)

        parts = []
        pos = 0
        for m in link_re.finditer(html):
            if m.start() > pos:
                text = self._strip_tags_and_entities(html[pos:m.start()])
                if text:
                    parts.append({'type': 'text', 'value': text})

            real_href = self._resolve_pixiv_url(m.group(1) or '')
            link_text = self._strip_tags_and_entities(m.group(2) or '')

            if real_href:
                parts.append({
                    'type': 'link',
                    'text': link_text or real_href,
                    'href': real_href,
                })
            elif link_text:
                parts.append({'type': 'text', 'value': link_text})

            pos = m.end()

        if pos < len(html):
            text = self._strip_tags_and_entities(html[pos:])
            if text:
                parts.append({'type': 'text', 'value': text})

        # Merge adjacent text segments / 合并相邻文本
        merged = []
        for p in parts:
            if (merged and p['type'] == 'text'
                    and merged[-1]['type'] == 'text'):
                merged[-1]['value'] += p['value']
            else:
                merged.append(p)
        return merged


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
            write_log(t('exiftool_not_found', path=str(self.exiftool_path)),
                      'warn')

    def write_metadata(self, image_path, metadata,
                       export_json=False):
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
            with tempfile.NamedTemporaryFile(
                    mode='w', encoding='utf-8',
                    suffix='.args', delete=False) as f:
                args_file = f.name
                f.write("#[CSTR]-charset=UTF8\n")
                f.write("#[CSTR]-charset=filename=UTF8\n")
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
                            f.write(f"#[CSTR]-{tag}={_exiftool_cstr(raw)}\n")
                    else:
                        raw = str(value).strip()
                        if not raw:
                            continue
                        f.write(f"#[CSTR]-{tag}={_exiftool_cstr(raw)}\n")
                f.write(str(image_path.absolute()) + "\n")
        except Exception as e:
            write_log(t('exiftool_args_failed', error=str(e)), 'error')
            return False, json_path

        cmd = [str(self.exiftool_path), "-@", args_file]
        for attempt in range(2):
            try:
                r = subprocess.run(cmd, capture_output=True, text=True,
                                   encoding='utf-8', errors='ignore',
                                   timeout=60)
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
# Download worker / 下载工作器
# ============================================================
class DownloadWorker:
    def __init__(self, config, session: SessionManager, accounts: AccountsManager):
        self.config = config
        self.session = session
        self.accounts = accounts
        self.rate_limiter = RateLimiter()
        self.api = PixivAPI(config, self.rate_limiter, accounts=accounts)
        self.exiftool = ExifToolWrapper(
            str(get_resource_path("plugins/ExifTool.exe")))
        self.download_dir = Path(config.get('download_dir'))
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
        self._retry_pass = 0
        self._max_retry_passes = 3
        self.items_status = {}
        self._items_lock = threading.Lock()
        self._items_max = 300
        self.status_callback = None
        self.items_callback = None

    # ---------- Callbacks ----------
    def set_status_callback(self, cb):
        self.status_callback = cb

    def _emit(self, msg, level='info'):
        write_log(msg, level)
        if self.status_callback:
            self.status_callback(msg, level)

    def _current_workers(self) -> int:
        mode = self.config.get('performance.download_mode', 'normal')
        if mode == 'normal':
            return 1
        return max(1, int(
            self.config.get('performance._resolved_workers', 3)))

    # ---------- Item status tracking ----------
    def _update_item_status(self, pid, **fields):
        if pid is None:
            return
        with self._items_lock:
            cur = self.items_status.get(pid, {})
            cur.update(fields)
            cur['ts'] = time.time()
            self.items_status[pid] = cur
            if len(self.items_status) > self._items_max:
                for k, v in sorted(self.items_status.items(),
                                   key=lambda x: x[1].get('ts', 0)):
                    if v.get('status') in ('success', 'failed'):
                        self.items_status.pop(k, None)
                        if len(self.items_status) <= self._items_max:
                            break
        self._emit_items_update()

    def _emit_items_update(self):
        if not self.items_callback:
            return
        with self._items_lock:
            snapshot = [{'pid': pid, **info}
                        for pid, info in self.items_status.items()]
        snapshot.sort(key=lambda x: (
            0 if x.get('status') == 'processing' else 1,
            -x.get('ts', 0)))
        try:
            self.items_callback(snapshot)
        except Exception:
            pass

    # ---------- Queue persistence ----------
    def _save_queue(self):
        try:
            with self.url_queue.mutex:
                items = list(self.url_queue.queue)
            current = []
            for item in items:
                if isinstance(item, tuple):
                    current.append(item[0])
                elif isinstance(item, dict):
                    current.append(item)
                else:
                    current.append(item)
            with self.failed_lock:
                failed = [
                    {'pid': pid,
                     'img_path': str(p) if p else None,
                     'metadata': m or {}}
                    for pid, p, m in self.failed_items
                ]
            self.session.set_queue({
                'current_tasks': current,
                'failed_tasks': failed,
            })
            return True
        except Exception as e:
            write_log(t('queue_save_failed', error=str(e)), 'error')
            return False

    # ---------- Queue ops ----------
    def add_items(self, items: list) -> int:
        if (self.processed_count > 0
                and self.url_queue.empty() and not self.is_running):
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

    def get_failed_count(self):
        with self.failed_lock:
            return len(self.failed_items)

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
            t_ = threading.Thread(target=self._worker_loop, daemon=True)
            t_.start()
            self.workers.append(t_)
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
        with self._items_lock:
            self.items_status = {
                pid: info for pid, info in self.items_status.items()
                if info.get('status') == 'processing'}
        self._emit_items_update()
        self._emit(t('queue_cleared', n=n), 'info')
        self._save_queue()
        return n

    # ---------- Worker loop ----------
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
                url, img_path, meta_d, _ = item
                self._emit(t('task_retry', url=url), 'info')
                ok, _ = self.exiftool.write_metadata(
                    img_path, meta_d, export_json=True)
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
                ok, pid, img_path, meta_d = self._process_url(
                    url, cached_meta=cached)
                if ok:
                    self._emit(t('task_success', url=url), 'info')
                else:
                    self._emit(t('task_failed', url=url), 'error')
                    if meta_d:
                        with self.failed_lock:
                            self.failed_items.append((pid, img_path, meta_d))

            self.processed_count += 1
            self._save_queue()
            time.sleep(float(
                self.config.get('performance.download_delay', 0.5)))
            self.url_queue.task_done()

        with self._threads_lock:
            self._active_threads -= 1
            if self._active_threads == 0:
                self.is_running = False
                self.should_stop = False
                has_remaining = not self.url_queue.empty()
                has_failed = self.get_failed_count() > 0

                if has_remaining:
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
                        f"Auto-retry pass {self._retry_pass}/"
                        f"{self._max_retry_passes}: {len(retry_items)} items",
                        'warn')
                    self.start()
                else:
                    if not has_failed:
                        self.session.set_queue({'current_tasks': [],
                                                'failed_tasks': []})
                        self._retry_pass = 0
                        write_log("All tasks completed", 'info')
                    else:
                        self._save_queue()
                        write_log(
                            f"Retries exhausted, "
                            f"{self.get_failed_count()} items still failing",
                            'warn')
                    self._emit(t('workers_stopped'), 'info')

    # ---------- URL dispatch ----------
    def _parse_url(self, url):
        m = re.search(r'/artworks/(\d+)', url)
        if m:
            return 'illust', int(m.group(1))
        m = re.search(r'/novel/show\.php\?id=(\d+)', url)
        if m:
            return 'novel', int(m.group(1))
        if url.isdigit():
            return 'illust', int(url)
        raise ValueError(url)

    def _process_url(self, url, cached_meta=None):
        typ, pid = self._parse_url(url)
        if typ == 'illust':
            return self._process_illust(pid, cached_meta=cached_meta)
        return self._process_novel(pid, cached_meta=cached_meta)

    # ---------- Detail fetching ----------
    def _fetch_illust_detail(self, iid: int, cached_meta=None) -> dict:
        use_cache = self.config.get(
            'performance.enable_download_metadata_cache', True)

        if use_cache and cached_meta and cached_meta.get('illust'):
            cached = cached_meta['illust']
            source = str(cached.get('_source', ''))
            has_caption = bool(cached.get('caption'))

            if source == 'ajax-detail' and has_caption:
                write_log(f"illust {iid}: using cached Ajax detail", 'info')
                return cached

            if not has_caption and self.api.web_ajax \
                    and self.api.web_ajax.is_available():
                ajax = self.api.get_illust_detail_ajax(iid)
                if ajax.get('caption'):
                    merged = dict(cached)
                    merged['caption'] = ajax['caption']
                    if ajax.get('tags'):
                        merged['tags'] = ajax['tags']
                    for k in ('total_likes', 'total_comments',
                              'total_bookmarks', 'total_view'):
                        if ajax.get(k):
                            merged[k] = ajax[k]
                    merged['_source'] = 'ajax-detail'
                    write_log(
                        f"illust {iid}: caption enriched via Ajax", 'info')
                    return merged
                write_log(f"illust {iid}: cached (App), no caption", 'info')
                return cached

            if has_caption:
                write_log(f"illust {iid}: using cached metadata", 'info')
                return cached

        return self.api.get_illust_detail_ajax(iid)

    # ---------- Illust ----------
    def _process_illust(self, iid, cached_meta=None):
        self._update_item_status(iid, status='processing',
                                 stage='fetching', progress=0, title='')

        info = self._fetch_illust_detail(iid, cached_meta=cached_meta)
        if not info:
            self._update_item_status(iid, status='failed',
                                     stage='fetch', error='fetch_failed')
            return False, iid, None, None
        if not info.get('visible', False):
            write_log(t('illust_invisible', id=iid), 'warn')
            self._update_item_status(iid, status='failed',
                                     stage='invisible', error='invisible')
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
        single = info.get('meta_single_page', {}) or {}
        pages = info.get('meta_pages', []) or []
        restr_attrs = info.get('restriction_attributes', [])

        self._update_item_status(iid, title=title,
                                 stage='preparing', progress=5)

        # Build tags with priority
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
            "XMP-dc:title": title,
            "EXIF:ImageDescription": title,
            "EXIF:XPTitle": title,
            "XMP-dc:creator": author,
            "EXIF:Artist": author,
            "EXIF:XPAuthor": author,
            "XMP-dc:subject": final_tags,
            "EXIF:XPKeywords": ",".join(final_tags),
            "XMP:CreateDate": create_date,
            "XMP:MetadataDate": create_date,
            "EXIF:DateTimeOriginal": create_date,
            "EXIF:CreateDate": create_date,
            "EXIF:ModifyDate": create_date,
            "XMP-dc:description": desc,
            "EXIF:XPComment":
                f"{meta('source_url')}: "
                f"https://www.pixiv.net/artworks/{iid}",
        }

        # Ugoira → dedicated pipeline
        if info.get('type') == 'ugoira':
            ok, pid, saved_path, meta_d = self._process_ugoira(
                iid, info, metadata)
            if ok:
                # history
                append_history({
                    'id': iid, 'title': title,
                    'page_count': 1,
                    'author': author, 'author_id': author_id,
                    'tags': final_tags,
                    'ai_generated': ai_type == 2,
                    'sensitive': x_restrict > 0 or bool(restr_attrs),
                    'restriction': (
                        "R-18" if x_restrict == 1 else
                        "R-18G" if x_restrict == 2 else
                        "R-15" if restr_attrs else ""),
                    'publish_time': format_date(create_date),
                    'downloaded_at': int(time.time()),
                    'type': 'ugoira',
                })
            return ok, pid, saved_path, meta_d

        # Collect image URLs
        urls_list = []
        if page_count == 1:
            u = (single.get('original_image_url')
                 or single.get('large_image_url'))
            if u:
                urls_list.append(u)
        else:
            for p in pages:
                im = p.get('image_urls', {})
                u = im.get('original') or im.get('large')
                if u:
                    urls_list.append(u)

        if not urls_list:
            write_log(t('no_image_url', id=iid), 'warn')
            self._update_item_status(iid, status='failed',
                                     stage='no_url', error='no_url')
            return False, iid, None, metadata

        # Download each page
        saved = []
        total = len(urls_list)
        for idx, u in enumerate(urls_list):
            base = u.split('?')[0]
            fname = os.path.basename(base)
            if not fname:
                ext = os.path.splitext(base)[1] or '.jpg'
                fname = (f"{iid}{ext}" if page_count == 1
                         else f"{iid}_p{idx+1}{ext}")
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
                ok, _ = self.exiftool.write_metadata(
                    sp, metadata, export_json=False)
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

        self._update_item_status(iid, status='success',
                                 stage='done', progress=100)

        # History
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

    # ---------- Ugoira ----------
    def _process_ugoira(self, iid, info, metadata):
        """
        info: full illust detail (already fetched)
        metadata: exif dict built by _process_illust
        Returns (ok, iid, saved_path, metadata)
        """
        self._update_item_status(iid, stage='ugoira_meta', progress=10)

        meta = self.api.get_ugoira_metadata(iid)
        if not meta:
            write_log(f"ugoira {iid}: no metadata", 'warn')
            self._update_item_status(iid, status='failed',
                                     stage='ugoira_meta',
                                     error='ugoira_meta_failed')
            return False, iid, None, metadata

        zip_urls = meta.get('zip_urls') or {}
        zip_url = (zip_urls.get('medium')
                   or zip_urls.get('original')
                   or next(iter(zip_urls.values()), ''))
        frames = meta.get('frames') or []
        if not zip_url or not frames:
            write_log(f"ugoira {iid}: empty zip url or frames", 'warn')
            self._update_item_status(iid, status='failed',
                                     stage='ugoira_meta',
                                     error='ugoira_meta_empty')
            return False, iid, None, metadata

        fmt = str(self.config.get('ugoira_format', 'gif')).lower()
        if fmt not in ('gif', 'apng', 'webp'):
            fmt = 'gif'
        ext_map = {'gif': '.gif', 'apng': '.png', 'webp': '.webp'}
        ugoira_dir = self.download_dir / "ugoira"
        ugoira_dir.mkdir(parents=True, exist_ok=True)
        out_path = ugoira_dir / f"{iid}_ugoira{ext_map[fmt]}"

        if out_path.exists():
            write_log(t('file_exists', path=str(out_path)), 'info')
            self._update_item_status(iid, status='success',
                                     stage='done', progress=100)
            return True, iid, out_path, metadata

        with tempfile.TemporaryDirectory(prefix=f"ugoira_{iid}_") as tmpdir:
            tmp = Path(tmpdir)
            zip_path = tmp / f"{iid}.zip"

            self._update_item_status(iid, stage='ugoira_download', progress=20)
            if not self.api.download_image(zip_url, zip_path):
                self._update_item_status(iid, status='failed',
                                         stage='ugoira_download',
                                         error='zip_download_failed')
                return False, iid, None, metadata

            self._update_item_status(iid, stage='ugoira_unzip', progress=35)
            try:
                with zipfile.ZipFile(zip_path) as zf:
                    zf.extractall(tmp)
            except Exception as e:
                write_log(f"ugoira {iid}: unzip failed: {e}", 'error')
                self._update_item_status(iid, status='failed',
                                         stage='ugoira_unzip',
                                         error='unzip_failed')
                return False, iid, None, metadata

            self._update_item_status(iid, stage='ugoira_compose', progress=50)
            try:
                durations, images = [], []
                total = len(frames)
                for idx, fr in enumerate(frames):
                    fn = fr.get('file') or ''
                    delay = int(fr.get('delay') or 50)
                    fp = tmp / fn
                    if not fp.exists():
                        # 兜底：按序号找
                        cand = sorted(tmp.glob(f"*{Path(fn).suffix}"))
                        if idx < len(cand):
                            fp = cand[idx]
                        else:
                            continue
                    img = Image.open(fp)
                    img.load()
                    if img.mode not in ('RGB', 'RGBA', 'P'):
                        img = img.convert('RGBA')
                    images.append(img.copy())
                    durations.append(max(20, delay))
                    if total <= 20 or idx % 5 == 0 or idx == total - 1:
                        self._update_item_status(
                            iid, stage='ugoira_compose',
                            progress=int(50 + (idx + 1) / total * 35))

                if not images:
                    write_log(f"ugoira {iid}: no frames loaded", 'warn')
                    self._update_item_status(iid, status='failed',
                                             stage='ugoira_compose',
                                             error='no_frames')
                    return False, iid, None, metadata

                save_kwargs = {
                    'save_all': True,
                    'append_images': images[1:],
                    'duration': durations,
                    'loop': 0,
                }
                if fmt == 'gif':
                    images[0].save(out_path, format='GIF',
                                   disposal=2, **save_kwargs)
                elif fmt == 'apng':
                    images[0].save(out_path, format='PNG', **save_kwargs)
                else:
                    images[0].save(out_path, format='WEBP', **save_kwargs)

                for img in images:
                    img.close()
            except Exception as e:
                write_log(f"ugoira {iid}: compose failed: {e}", 'error')
                self._update_item_status(iid, status='failed',
                                         stage='ugoira_compose',
                                         error='compose_failed')
                return False, iid, None, metadata

        self._update_item_status(iid, stage='writing_meta', progress=90)
        ok, _ = self.exiftool.write_metadata(out_path, metadata,
                                             export_json=False)
        if not ok:
            write_log(t('metadata_failed', path=str(out_path)), 'warn')
            self._update_item_status(iid, status='failed',
                                     stage='metadata',
                                     error='metadata_failed')
            return False, iid, out_path, metadata

        self._update_item_status(iid, status='success',
                                 stage='done', progress=100)
        return True, iid, out_path, metadata

    # ---------- Novel ----------
    def _process_novel(self, nid, cached_meta=None):
        self._update_item_status(nid, status='processing',
                                 stage='fetching', progress=0, title='')

        info = self.api.get_novel_detail(nid)
        if not info:
            self._update_item_status(nid, status='failed',
                                     stage='fetch', error='fetch_failed')
            return False, nid, None, None

        title = info.get('title', '')
        user = info.get('user', {}) or {}
        author = user.get('name', '')
        author_id = user.get('id')
        author_account = user.get('account', '')
        create_date = info.get('create_date', '')
        caption = info.get('caption', '')
        tags = info.get('tags', []) or []
        x_restrict = info.get('x_restrict', 0) or 0
        ai_type = info.get('novel_ai_type', 0) or 0
        total_view = info.get('total_view', 0) or 0
        total_bookmarks = info.get('total_bookmarks', 0) or 0
        text_length = info.get('text_length', 0) or 0
        series = info.get('series') or {}

        # Tag 构建（与 _process_illust 同一套）
        tag_names = []
        trans_names = []
        for x in tags:
            if isinstance(x, dict):
                tag_names.append(x.get('name', '') or '')
                trans_names.append(x.get('translated_name', '') or '')
            elif isinstance(x, str):
                tag_names.append(x)
                trans_names.append('')
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
        final_tags = pri + tag_strs

        self._update_item_status(nid, title=title,
                                 stage='fetching_text', progress=15)

        text_resp = self.api.get_novel_text(nid)
        novel_text = ''
        if text_resp:
            novel_text = (text_resp.get('novel_text', '')
                          or text_resp.get('text', ''))
        if not novel_text:
            write_log(f"novel_text empty for {nid}", 'warn')
            self._update_item_status(nid, status='failed',
                                     stage='text', error='text_fetch_failed')
            return False, nid, None, None

        self._update_item_status(nid, stage='writing', progress=60)

        safe_title = re.sub(r'[\\/:*?"<>|]', '_', title)[:80]
        work_dir = self.download_dir / "novels"
        work_dir.mkdir(exist_ok=True)
        md_path = work_dir / f"{nid}_{safe_title}.md"

        source_url = f"https://www.pixiv.net/novel/show.php?id={nid}"
        clean_cap = self._clean_caption(caption)

        # YAML frontmatter
        frontmatter = {
            'id': nid,
            'title': title,
            'author': author,
            'author_id': author_id,
            'author_account': author_account,
            'create_date': create_date,
            'tags': final_tags,
            'x_restrict': x_restrict,
            'ai_generated': ai_type == 2,
            'total_view': total_view,
            'total_bookmarks': total_bookmarks,
            'text_length': text_length,
            'series_id': series.get('id'),
            'series_title': series.get('title') or '',
            'source': source_url,
        }
        if clean_cap:
            frontmatter['caption'] = clean_cap

        yaml_lines = ['---']
        for k, v in frontmatter.items():
            if v is None:
                continue
            if isinstance(v, list):
                if not v:
                    yaml_lines.append(f"{k}: []")
                    continue
                yaml_lines.append(f"{k}:")
                for item in v:
                    yaml_lines.append(
                        f"  - {json.dumps(item, ensure_ascii=False)}")
            elif isinstance(v, bool):
                yaml_lines.append(f"{k}: {'true' if v else 'false'}")
            elif isinstance(v, (int, float)):
                yaml_lines.append(f"{k}: {v}")
            else:
                yaml_lines.append(
                    f"{k}: {json.dumps(v, ensure_ascii=False)}")
        yaml_lines.append('---')
        yaml_lines.append('')
        yaml_lines.append(f"# {title}")
        yaml_lines.append('')
        if clean_cap:
            yaml_lines.append(clean_cap)
            yaml_lines.append('')
        yaml_lines.append(novel_text)

        try:
            md_path.write_text('\n'.join(yaml_lines), encoding='utf-8')
        except Exception as e:
            write_log(f"Novel write failed: {e}", 'error')
            self._update_item_status(nid, status='failed',
                                     stage='write', error=str(e))
            return False, nid, None, None

        self._update_item_status(nid, stage='writing_meta', progress=85)

        restr_str = ""
        if x_restrict == 1:
            restr_str = "R-18"
        elif x_restrict == 2:
            restr_str = "R-18G"

        self._update_item_status(nid, status='success',
                                 stage='done', progress=100)

        append_history({
            'id': nid, 'title': title, 'page_count': 1,
            'author': author, 'author_id': author_id,
            'tags': final_tags,
            'ai_generated': ai_type == 2,
            'sensitive': x_restrict > 0,
            'restriction': restr_str,
            'publish_time': format_date(create_date),
            'downloaded_at': int(time.time()),
            'type': 'novel',
        })
        return True, nid, md_path, None

    # ---------- Caption cleanup ----------
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
    def __init__(self, config, accounts: AccountsManager,
                 session: SessionManager):
        self.config = config
        self.accounts = accounts
        self.session = session
        self.loop = None
        self.clients = set()
        self.clients_lock = threading.Lock()
        self.worker = DownloadWorker(config, session, accounts)
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
            'mode': self.config.get('performance.download_mode', 'normal'),
            'workers': self.worker._current_workers(),
            'retry_pass': self.worker._retry_pass,
            'max_retry': self.worker._max_retry_passes,
        }

    def _on_items_update(self, snapshot):
        self.broadcast({'type': 'queue_items', 'items': snapshot})

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
        await asyncio.gather(
            *[ws.send_str(data) for ws in clients],
            return_exceptions=True)


# ============================================================
# Formatters / 数据格式化
# ============================================================
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
        'likes': it.get('total_likes', 0) or 0,
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
    return {
        'id': u.get('id'),
        'name': u.get('name', ''),
        'account': u.get('account', ''),
        'is_followed': u.get('is_followed', False),
    }


def format_user_detail(data, extra=None):
    user = data.get('user', {})
    profile = data.get('profile', {})
    result = {
        'id': user.get('id'),
        'name': user.get('name', ''),
        'account': user.get('account', ''),
        'comment': user.get('comment', ''),
        'comment_parts': user.get('comment_parts', []),
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
        'total_illust_bookmarks_public':
            profile.get('total_illust_bookmarks_public', 0),
        'is_premium': profile.get('is_premium', False),
        'is_accept_request': None,
        'background_image_url': profile.get('background_image_url'),
    }
    if extra:
        result.update(extra)
    return result

def format_novel(it):
    user = it.get('user', {}) or {}
    avatar = (user.get('profile_image_urls', {}) or {}).get('medium', '')
    tags_out = []
    for x in it.get('tags', []) or []:
        if isinstance(x, dict):
            name = x.get('name', '') or ''
            trans = x.get('translated_name', '') or ''
            tags_out.append(f"{name}({trans})" if trans else name)
        elif isinstance(x, str):
            tags_out.append(x)
    series = it.get('series') or {}
    return {
        'id': it.get('id'),
        'title': it.get('title', ''),
        'author': user.get('name', ''),
        'author_id': user.get('id'),
        'author_account': user.get('account', ''),
        'author_avatar': avatar,
        'views': it.get('total_view', 0) or 0,
        'bookmarks': it.get('total_bookmarks', 0) or 0,
        'tags': tags_out,
        'date': format_date(it.get('create_date', '') or ''),
        'type': 'novel',
        'text_length': it.get('text_length', 0) or 0,
        'x_restrict': it.get('x_restrict', 0) or 0,
        'ai_type': it.get('novel_ai_type', 0) or 0,
        'series_id': series.get('id'),
        'series_title': series.get('title', '') or '',
        'is_bookmarked': bool(it.get('is_bookmarked')),
    }


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
# Factory / 工厂
# ============================================================
def make_api(bridge) -> PixivAPI:
    return PixivAPI(bridge.config, bridge.worker.rate_limiter,
                    accounts=bridge.accounts)


# ============================================================
# Command handler / 命令处理
# ============================================================
async def handle_command(bridge, cmd, ws):
    c = cmd.get('cmd')

    # ---------- Auth / language / theme ----------
    if c == 'login':
        rt = cmd.get('refresh_token', '').strip()
        if not rt:
            await ws.send_str(json.dumps({
                'type': 'login_result', 'success': False,
                'msg': 'Refresh token is required'}))
            return
        bridge.config.set('refresh_token', rt)
        loop = asyncio.get_event_loop()

        def do_login():
            bridge.worker.api.logged_in = False
            bridge.worker.api.api = None
            return bridge.worker.api.login()

        ok = await loop.run_in_executor(None, do_login)
        await ws.send_str(json.dumps({
            'type': 'login_result', 'success': ok,
            'msg': 'Login succeeded' if ok
                   else 'Login failed, check your refresh token'}))

    elif c == 'set_language':
        lang = cmd.get('lang', '')
        if lang in ('zh-CN', 'en'):
            bridge.config.set('language', lang)
            set_language(lang)
            write_log(t('language_loaded', lang=lang), 'info')
            await ws.send_str(json.dumps(
                {'type': 'language_set', 'lang': lang}))

    elif c == 'set_theme':
        theme = cmd.get('theme', 'dark')
        if theme in ('dark', 'light'):
            bridge.config.set('theme', theme)
            await ws.send_str(json.dumps(
                {'type': 'theme_set', 'theme': theme}))

    elif c == 'save_ui_state':
        bridge.session.set_ui_state(cmd.get('state', {}))
        await ws.send_str(json.dumps({'type': 'ui_state_saved'}))

    # ---------- Queue ----------
    elif c == 'add_items':
        n = bridge.worker.add_items(cmd.get('items', []))
        await ws.send_str(json.dumps(bridge._queue_status_payload()))
        await ws.send_str(json.dumps({'type': 'items_added', 'count': n}))

    elif c == 'start_queue':
        ok = bridge.worker.start()
        await ws.send_str(json.dumps({
            'type': 'success' if ok else 'error',
            'msg': 'Queue started' if ok else 'Cannot start queue'}))

    elif c == 'stop_queue':
        bridge.worker.stop()
        await ws.send_str(json.dumps(
            {'type': 'success', 'msg': 'Stopping queue...'}))

    elif c == 'clear_queue':
        n = bridge.worker.clear_queue()
        await ws.send_str(json.dumps(
            {'type': 'success', 'msg': f'Cleared {n} task(s)'}))

    # ---------- Search ----------
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
            if (not date_re.match(start_date)
                    or not date_re.match(end_date)):
                await ws.send_str(json.dumps(
                    {'type': 'error', 'msg': 'Invalid date format'}))
                return
            if start_date > end_date:
                await ws.send_str(json.dumps(
                    {'type': 'error', 'msg': 'Start date must be <= end'}))
                return
            duration = None

        def do_search():
            api = make_api(bridge)
            api.ensure_login()

            f = filters or {}
            want_illust = bool(f.get('illust', True))
            want_manga = bool(f.get('manga', True))
            want_ugoira = bool(f.get('ugoira', False))
            want_novel = bool(f.get('novel', False))

            write_log(
                f"search '{tag}': filters illust={want_illust} "
                f"manga={want_manga} ugoira={want_ugoira} novel={want_novel}, "
                f"pages={pages} start_page={start_page}",
                'info')

            delay = float(bridge.config.get('api.request_delay', 0.3))

            illust_raw = []
            if want_illust or want_manga or want_ugoira:
                write_log("search: entering App API loop", 'info')
                for i in range(pages):
                    page = start_page + i
                    offset = (page - 1) * 30
                    bridge.broadcast({'type': 'search_progress',
                                      'current': i + 1, 'total': pages,
                                      'page': page})
                    try:
                        resp = api.search_illust(
                            tag, target=target, sort=sort, offset=offset,
                            duration=duration,
                            start_date=start_date, end_date=end_date)
                    except Exception as e:
                        write_log(t('search_page_failed', page=page,
                                    error=str(e)), 'error')
                        break
                    items = resp.get('illusts', []) if resp else []
                    write_log(
                        f"search page {page}: got {len(items)} items",
                        'info')
                    if not items:
                        break
                    illust_raw.extend(items)
                    if len(items) < 30:
                        break
                    time.sleep(delay)
            else:
                write_log("search: App API loop skipped", 'warn')

            novel_raw = []
            if want_novel:
                for i in range(pages):
                    page = start_page + i
                    offset = (page - 1) * 30
                    bridge.broadcast({'type': 'search_progress',
                                      'current': i + 1, 'total': pages,
                                      'page': page, 'kind': 'novel'})
                    try:
                        resp = api.search_novel(
                            tag, target=target, sort=sort, offset=offset,
                            duration=duration,
                            start_date=start_date, end_date=end_date)
                    except Exception as e:
                        write_log(t('search_page_failed', page=page,
                                    error=str(e)), 'error')
                        break
                    items = resp.get('novels', []) if resp else []
                    write_log(
                        f"search novel page {page}: got {len(items)} items",
                        'info')
                    if not items:
                        break
                    novel_raw.extend(items)
                    if len(items) < 30:
                        break
                    time.sleep(delay)

            illust_out = []
            novel_out = []
            for it in illust_raw:
                ty = it.get('type', '')
                if ty == 'illust' and want_illust:
                    illust_out.append(it)
                elif ty == 'manga' and want_manga:
                    illust_out.append(it)
                elif ty == 'ugoira' and want_ugoira:
                    illust_out.append(it)
            for it in novel_raw:
                it.setdefault('type', 'novel')
                novel_out.append(it)

            total = None
            related_tags = []
            ajax_body = api.search_artworks_ajax(
                tag, page=start_page, target=target, duration=duration)
            if ajax_body:
                im = ajax_body.get('illustManga') or {}
                total = im.get('total')
                rt = ajax_body.get('relatedTags') or []
                related_tags = [x for x in rt if isinstance(x, str)]

            write_log(
                f"search done: illust={len(illust_out)} "
                f"novel={len(novel_out)} total={total} "
                f"related={len(related_tags)}",
                'info')
            return illust_out, novel_out, total, related_tags

        try:
            illust_raw, novel_raw, total, related_tags = \
                await loop.run_in_executor(None, do_search)
        except Exception as e:
            write_log(f"search executor failed: {e}", 'error')
            await ws.send_str(json.dumps(
                {'type': 'error', 'msg': f'Search failed: {e}'}))
            return

        write_log("search: building item list", 'info')
        try:
            illust_items = [format_item(it) for it in illust_raw]
            for i, f in enumerate(illust_items):
                f['_slim_illust'] = illust_raw[i]
            novel_items = [format_novel(it) for it in novel_raw]
            for i, f in enumerate(novel_items):
                f['_slim_illust'] = novel_raw[i]
        except Exception as e:
            write_log(f"search: format failed: {e}", 'error')
            await ws.send_str(json.dumps(
                {'type': 'error', 'msg': f'Format failed: {e}'}))
            return
        write_log(
            f"search: built {len(illust_items)} illust + "
            f"{len(novel_items)} novel", 'info')

        payload = {
            'type': 'search_result',
            'items': illust_items,
            'novel_items': novel_items,
            'start_page': start_page, 'pages': pages,
            'tag': tag, 'total': total,
            'related_tags': related_tags,
        }
        try:
            data = json.dumps(payload, ensure_ascii=False)
        except Exception as e:
            write_log(f"search: json.dumps failed: {e}", 'error')
            await ws.send_str(json.dumps(
                {'type': 'error', 'msg': f'JSON failed: {e}'}))
            return
        write_log(f"search: payload {len(data)} bytes, sending", 'info')

        try:
            await asyncio.wait_for(ws.send_str(data), timeout=15.0)
        except asyncio.TimeoutError:
            write_log(
                "search: send_str TIMED OUT — client not consuming WS",
                'error')
            return
        except Exception as e:
            write_log(f"search: send_str failed: {e}", 'error')
            return
        write_log("search: sent", 'info')

        illust_items = [format_item(it) for it in illust_raw]
        for i, f in enumerate(illust_items):
            f['_slim_illust'] = illust_raw[i]
        novel_items = [format_novel(it) for it in novel_raw]
        for i, f in enumerate(novel_items):
            f['_slim_illust'] = novel_raw[i]

        await ws.send_str(json.dumps({
            'type': 'search_result',
            'items': illust_items,
            'novel_items': novel_items,
            'start_page': start_page, 'pages': pages,
            'tag': tag, 'total': total,
            'related_tags': related_tags},
            ensure_ascii=False))

    # ---------- Ranking ----------
    elif c == 'ranking':
        mode = cmd.get('mode', 'day')
        limit = 480
        loop = asyncio.get_event_loop()

        def do_ranking():
            api = make_api(bridge)
            api.ensure_login()
            delay = float(bridge.config.get('api.request_delay', 0.3))

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
                    write_log(t('ranking_failed', error=str(e)), 'error')
                    break
                items = resp.get('illusts', []) or []
                if not items:
                    break
                if today_date is None:
                    nxt = resp.get('next_url')
                    if nxt:
                        try:
                            params = parse_qs(urlparse(nxt).query)
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
                    break
                time.sleep(delay)
            today = today[:limit]

            # yesterday
            if today_date:
                try:
                    base_dt = datetime.strptime(today_date, '%Y-%m-%d')
                except ValueError:
                    base_dt = datetime.now()
            else:
                base_dt = datetime.now()
            yesterday_date = (base_dt - timedelta(days=1)).strftime('%Y-%m-%d')

            yesterday_ids = set()
            offset = 0
            y_iter = 0
            while offset < limit and y_iter < 20:
                y_iter += 1
                bridge.broadcast({'type': 'ranking_progress',
                                  'phase': 'yesterday',
                                  'count': len(yesterday_ids)})
                try:
                    resp = api.get_ranking(mode, date=yesterday_date,
                                           offset=offset)
                except Exception as e:
                    write_log(t('ranking_failed', error=str(e)), 'error')
                    break
                items = resp.get('illusts', []) or []
                if not items:
                    break
                for it in items:
                    pid = it.get('id')
                    if pid is not None:
                        yesterday_ids.add(pid)
                offset += 30
                if not resp.get('next_url'):
                    break
                time.sleep(delay)

            yesterday_avail = len(yesterday_ids) > 0
            new_count = 0
            for it in today:
                is_new = yesterday_avail and it.get('id') not in yesterday_ids
                it['_is_new'] = is_new
                if is_new:
                    new_count += 1

            return today, len(today_ids), len(yesterday_ids), new_count

        try:
            results, today_count, y_count, new_count = \
                await loop.run_in_executor(None, do_ranking)
        except Exception as e:
            write_log(f"ranking executor failed: {e}", 'error')
            await ws.send_str(json.dumps(
                {'type': 'error', 'msg': f'Ranking failed: {e}'}))
            return

        formatted = []
        for it in results:
            f = format_item(it)
            f['is_new'] = bool(it.get('_is_new'))
            f['_slim_illust'] = it
            formatted.append(f)
        await ws.send_str(json.dumps({
            'type': 'ranking_result',
            'items': formatted,
            'stats': {'today': today_count,
                      'yesterday': y_count, 'new': new_count}},
            ensure_ascii=False))

    # ---------- Bookmark HTML parse ----------
    elif c == 'parse_bookmark':
        urls = parse_bookmark_html(cmd.get('html', ''))
        await ws.send_str(json.dumps(
            {'type': 'bookmark_parsed', 'urls': urls}))

    # ---------- User search ----------
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
            await ws.send_str(json.dumps(
                {'type': 'error', 'msg': f'User search failed: {e}'}))
            return
        users = [format_user(p.get('user', {}))
                 for p in resp.get('user_previews', [])]
        await ws.send_str(json.dumps(
            {'type': 'user_search_result', 'items': users}))

    # ---------- User detail ----------
    elif c == 'user_detail':
        uid = int(cmd.get('uid'))
        loop = asyncio.get_event_loop()

        def do_user():
            api = make_api(bridge)
            api.ensure_login()
            detail = api.get_user_detail(uid)
            if not detail:
                return None, [], None
            bridge.broadcast({'type': 'user_detail_phase',
                              'phase': 'detail',
                              'user': format_user_detail(detail)})
            all_illusts = []
            offset = 0
            page = 1
            delay = float(bridge.config.get('api.request_delay', 0.3))
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
                is_accept = all_illusts[0].get('user', {}) \
                    .get('is_accept_request')
            return detail, all_illusts, is_accept

        try:
            detail, all_illusts, is_accept = \
                await loop.run_in_executor(None, do_user)
        except Exception as e:
            await ws.send_str(json.dumps(
                {'type': 'error', 'msg': f'User detail failed: {e}'}))
            return
        if not detail:
            await ws.send_str(json.dumps(
                {'type': 'error',
                 'msg': 'User not found or inaccessible'}))
            return
        user_info = format_user_detail(
            detail, extra={'is_accept_request': is_accept})
        items = []
        for it in all_illusts:
            f = format_item(it)
            f['_slim_illust'] = it
            items.append(f)
        await ws.send_str(json.dumps({
            'type': 'user_detail_result',
            'user': user_info, 'items': items}, ensure_ascii=False))

    elif c == 'novel_detail':
        try:
            nid = int(cmd.get('id'))
        except (TypeError, ValueError):
            await ws.send_str(json.dumps(
                {'type': 'error', 'msg': 'Invalid novel id'}))
            return
        loop = asyncio.get_event_loop()

        def do_novel():
            api = make_api(bridge)
            api.ensure_login()
            detail = api.get_novel_detail(nid)
            text_resp = api.get_novel_text(nid) if detail else {}
            return detail, text_resp

        try:
            detail, text_resp = await loop.run_in_executor(None, do_novel)
        except Exception as e:
            await ws.send_str(json.dumps(
                {'type': 'error', 'msg': f'Novel detail failed: {e}'}))
            return
        if not detail:
            await ws.send_str(json.dumps(
                {'type': 'error', 'msg': 'Novel not found'}))
            return

        text = text_resp.get('novel_text', '') or text_resp.get('text', '')
        series_nav = text_resp.get('seriesNavigation', {}) or {}
        prev_nav = series_nav.get('prevNovel') or {}
        next_nav = series_nav.get('nextNovel') or {}

        payload = format_novel(detail)
        payload['text'] = text
        payload['caption'] = (detail.get('caption', '')
                              or text_resp.get('caption', ''))
        payload['series_title'] = (payload.get('series_title')
                                   or text_resp.get('seriesTitle', ''))
        payload['series_id'] = (payload.get('series_id')
                                or (int(text_resp['seriesId'])
                                    if text_resp.get('seriesId') else None))
        payload['prev_novel'] = (
            {'id': prev_nav.get('id'), 'title': prev_nav.get('title', '')}
            if prev_nav.get('id') else None)
        payload['next_novel'] = (
            {'id': next_nav.get('id'), 'title': next_nav.get('title', '')}
            if next_nav.get('id') else None)

        await ws.send_str(json.dumps(
            {'type': 'novel_detail_result', 'novel': payload},
            ensure_ascii=False))

    elif c == 'novel_series':
        try:
            series_id = int(cmd.get('series_id'))
        except (TypeError, ValueError):
            await ws.send_str(json.dumps(
                {'type': 'error', 'msg': 'Invalid series id'}))
            return
        loop = asyncio.get_event_loop()

        def do_series():
            api = make_api(bridge)
            api.ensure_login()
            return api.get_novel_series(series_id)

        try:
            resp = await loop.run_in_executor(None, do_series)
        except Exception as e:
            await ws.send_str(json.dumps(
                {'type': 'error', 'msg': f'Novel series failed: {e}'}))
            return
        novels = (resp.get('novel_series')
                  or resp.get('novels')
                  or []) if resp else []
        items = []
        for n in novels:
            f = format_novel(n)
            items.append(f)
        await ws.send_str(json.dumps({
            'type': 'novel_series_result',
            'series_id': series_id,
            'items': items}, ensure_ascii=False))
    # ---------- Follow / Unfollow ----------
    elif c == 'follow_user':
        uid = int(cmd.get('uid'))
        action = cmd.get('action', 'follow')
        loop = asyncio.get_event_loop()

        def do_follow():
            api = make_api(bridge)
            api.ensure_login()
            return (api.follow_user(uid) if action == 'follow'
                    else api.unfollow_user(uid))

        try:
            await loop.run_in_executor(None, do_follow)
            await ws.send_str(json.dumps({
                'type': 'follow_user_result',
                'uid': uid, 'action': action, 'success': True}))
        except Exception as e:
            await ws.send_str(json.dumps(
                {'type': 'error', 'msg': f'Follow failed: {e}'}))

    # ---------- Recommend ----------
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
                url = (it.get('url') if isinstance(it, dict)
                       else (it[0] if isinstance(it, tuple) else it))
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
                await ws.send_str(json.dumps(
                    {'type': 'error', 'msg': 'Invalid PID'}))
                return
            kwargs['bookmark_illust_ids'] = [pid]
        elif mode == 'advanced':
            adv = cmd.get('params', {})
            if adv.get('bookmark_illust_ids'):
                v = adv['bookmark_illust_ids']
                if isinstance(v, str):
                    v = [int(s.strip()) for s in v.split(',')
                         if s.strip().isdigit()]
                kwargs['bookmark_illust_ids'] = v[:30]
            if adv.get('viewed'):
                v = adv['viewed']
                if isinstance(v, str):
                    v = [int(s.strip()) for s in v.split(',')
                         if s.strip().isdigit()]
                kwargs['viewed'] = v[:30]
            if 'include_ranking_illusts' in adv:
                kwargs['include_ranking_illusts'] = \
                    bool(adv['include_ranking_illusts'])
            if 'include_privacy_policy' in adv:
                kwargs['include_privacy_policy'] = \
                    bool(adv['include_privacy_policy'])

        def do_rec():
            api = make_api(bridge)
            api.ensure_login()
            results = []
            offset = 0
            delay = float(bridge.config.get('api.request_delay', 0.3))
            while len(results) < limit:
                try:
                    resp = api.get_illust_recommended(
                        offset=offset, **kwargs)
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
            f['_slim_illust'] = it
            formatted.append(f)
        await ws.send_str(json.dumps({
            'type': 'recommend_result', 'items': formatted, 'mode': mode},
            ensure_ascii=False))

    # ---------- Follow new ----------
    elif c == 'follow_new':
        offset = int(cmd.get('offset', 0))
        restrict = cmd.get('restrict', 'all')
        if restrict not in ('all', 'public', 'private'):
            restrict = 'all'
        batch_size = 300
        loop = asyncio.get_event_loop()

        def do_follow():
            api = make_api(bridge)
            api.ensure_login()
            results = []
            seen = set()
            cur_offset = offset
            delay = float(bridge.config.get('api.request_delay', 0.3))
            max_iter = 40
            iters = 0
            while len(results) < batch_size and iters < max_iter:
                iters += 1
                bridge.broadcast({'type': 'follow_progress',
                                  'count': len(results)})
                try:
                    resp = api.get_illust_follow(
                        restrict=restrict, offset=cur_offset)
                except Exception as e:
                    write_log(t('follow_failed', error=str(e)), 'error')
                    break
                items = resp.get('illusts', []) or []
                if not items:
                    return results, False
                new_items = [it for it in items
                             if it.get('id') not in seen]
                if not new_items:
                    return results, False
                for it in new_items:
                    seen.add(it.get('id'))
                results.extend(new_items)
                nxt = resp.get('next_url')
                if not nxt:
                    return results[:batch_size], False
                new_offset = None
                try:
                    params = parse_qs(urlparse(nxt).query)
                    v = params.get('offset', [None])[0]
                    if v is not None:
                        new_offset = int(v)
                except (ValueError, TypeError):
                    pass
                if new_offset is None or new_offset <= cur_offset:
                    return results[:batch_size], False
                cur_offset = new_offset
                if len(results) >= batch_size:
                    return results[:batch_size], True
                time.sleep(delay)
            return results[:batch_size], False

        try:
            items, has_more = await loop.run_in_executor(None, do_follow)
        except Exception as e:
            await ws.send_str(json.dumps(
                {'type': 'error', 'msg': f'Follow new failed: {e}'}))
            return
        formatted = []
        for it in items:
            f = format_item(it)
            f['_slim_illust'] = it
            formatted.append(f)
        await ws.send_str(json.dumps({
            'type': 'follow_new_result',
            'items': formatted,
            'offset': offset,
            'batch_size': batch_size,
            'has_more': has_more}, ensure_ascii=False))

    # ---------- Account ----------
    elif c in ('get_account', 'refresh_account'):
        force = (c == 'refresh_account')
        loop = asyncio.get_event_loop()
        cached = bridge.accounts.get_current_profile()

        if not force and cached and cached.get('id'):
            await ws.send_str(json.dumps({
                'type': 'account_result',
                'profile': cached,
                'bookmarks': bridge.accounts.get_current_bookmarks()},
                ensure_ascii=False))
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
                'comment_parts': user.get('comment_parts', []),
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
            'bookmarks': bridge.accounts.get_current_bookmarks()},
            ensure_ascii=False))

    elif c == 'list_accounts':
        await ws.send_str(json.dumps({
            'type': 'account_list',
            'accounts': bridge.accounts.list_accounts(),
            'current_index': bridge.accounts.data.get('current_index', 0)},
            ensure_ascii=False))

    elif c == 'add_account':
        rt = cmd.get('refresh_token', '').strip()
        ps = cmd.get('phpsessid', '').strip()
        if not rt:
            await ws.send_str(json.dumps(
                {'type': 'error', 'msg': 'Refresh token is required'}))
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
                    'avatar': user.get('profile_image_urls', {})
                        .get('medium', ''),
                    'comment': user.get('comment', ''),
                    'total_follow_users': prof.get('total_follow_users', 0),
                    'total_illusts': prof.get('total_illusts', 0),
                    'total_manga': prof.get('total_manga', 0),
                    'total_illust_bookmarks_public':
                        prof.get('total_illust_bookmarks_public', 0),
                    'region': prof.get('region', ''),
                    'background_image_url':
                        prof.get('background_image_url'),
                    'is_premium': prof.get('is_premium', False),
                }
            except Exception as e:
                return False, str(e)

        ok, result = await loop.run_in_executor(None, do_validate)
        if not ok:
            await ws.send_str(json.dumps({
                'type': 'error',
                'msg': f'Invalid token: {result}'}))
            return
        idx = bridge.accounts.add_account(rt, phpsessid=ps)
        bridge.accounts.set_current_profile(result)
        bridge.worker.api.logged_in = False
        bridge.worker.api.api = None
        bridge.worker.api.ensure_login()
        await ws.send_str(json.dumps({
            'type': 'account_added', 'index': idx, 'profile': result},
            ensure_ascii=False))

    elif c == 'switch_account':
        index = int(cmd.get('index', 0))
        if bridge.accounts.switch_account(index):
            bridge.worker.api.logged_in = False
            bridge.worker.api.api = None
            bridge.worker.api.ensure_login()
            await ws.send_str(json.dumps(
                {'type': 'account_switched', 'index': index}))

    elif c == 'remove_account':
        index = int(cmd.get('index', 0))
        if bridge.accounts.remove_account(index):
            bridge.worker.api.logged_in = False
            bridge.worker.api.api = None
            bridge.worker.api.ensure_login()
            await ws.send_str(json.dumps(
                {'type': 'account_removed', 'index': index}))

    elif c == 'update_phpsessid':
        ps = cmd.get('phpsessid', '').strip()
        bridge.accounts.set_phpsessid(ps)
        write_log(f"PHPSESSID updated ({len(ps)} chars)", 'info')
        await ws.send_str(json.dumps({
            'type': 'phpsessid_updated', 'phpsessid': ps},
            ensure_ascii=False))

    elif c == 'load_following':
        loop = asyncio.get_event_loop()
        uid_self = bridge.accounts.get_self_uid()
        if not uid_self:
            await ws.send_str(json.dumps(
                {'type': 'error', 'msg': 'UID not available'}))
            return

        def do_following():
            api = make_api(bridge)
            api.ensure_login()
            results = []
            offset = 0
            delay = float(bridge.config.get('api.request_delay', 0.3))
            for _ in range(10):
                try:
                    resp = api._call_with_retry(
                        api.api.user_following, uid_self, offset=offset)
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
                        'avatar': u.get('profile_image_urls', {})
                            .get('medium', ''),
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
            await ws.send_str(json.dumps(
                {'type': 'following_list', 'items': following},
                ensure_ascii=False))
        except Exception as e:
            await ws.send_str(json.dumps(
                {'type': 'error', 'msg': f'Load following failed: {e}'}))

    elif c == 'load_bookmarks':
        loop = asyncio.get_event_loop()
        uid_self = bridge.accounts.get_self_uid()
        if not uid_self:
            await ws.send_str(json.dumps(
                {'type': 'error', 'msg': 'UID not available'}))
            return

        def do_bookmarks():
            api = make_api(bridge)
            api.ensure_login()
            results = []
            max_bookmark_id = None
            delay = float(bridge.config.get('api.request_delay', 0.3))
            for _ in range(10):
                try:
                    resp = api.get_user_bookmarks(
                        uid_self, restrict='public',
                        max_bookmark_id=max_bookmark_id)
                except Exception as e:
                    write_log(f"load_bookmarks failed: {e}", 'error')
                    break
                items = resp.get('illusts', []) or []
                if not items:
                    break
                for it in items:
                    f = format_item(it)
                    f['_slim_illust'] = it
                    results.append(f)

                next_url = resp.get('next_url')
                if not next_url:
                    break
                try:
                    params = parse_qs(urlparse(next_url).query)
                    v = params.get('max_bookmark_id', [None])[0]
                    max_bookmark_id = int(v) if v is not None else None
                except (ValueError, TypeError):
                    max_bookmark_id = None
                if max_bookmark_id is None:
                    break
                time.sleep(delay)
            return results

        try:
            bookmarks = await loop.run_in_executor(None, do_bookmarks)
            bridge.accounts.set_current_bookmarks(bookmarks)
            await ws.send_str(json.dumps(
                {'type': 'bookmarks_list', 'items': bookmarks},
                ensure_ascii=False))
        except Exception as e:
            await ws.send_str(json.dumps(
                {'type': 'error', 'msg': f'Load bookmarks failed: {e}'}))

    # ---------- Config ----------
    elif c == 'get_config':
        await ws.send_str(json.dumps(
            {'type': 'config', 'data': bridge.config.config}))

    elif c == 'save_config':
        for k, v in cmd.get('data', {}).items():
            if k in ('refresh_token', 'webapi.PHPSESSID'):
                continue
            bridge.config.set(k, v)
        bridge.config._resolve_auto_workers()
        bridge.config.save()
        await ws.send_str(json.dumps(
            {'type': 'success', 'msg': 'Config saved'}))
        await ws.send_str(json.dumps(bridge._queue_status_payload()))

    elif c == 'set_download_mode':
        mode = cmd.get('mode', 'normal')
        if mode not in ('normal', 'high'):
            mode = 'normal'
        bridge.config.set('performance.download_mode', mode)
        await ws.send_str(json.dumps(bridge._queue_status_payload()))

    elif c == 'test_latency':
        loop = asyncio.get_event_loop()
        latency = await loop.run_in_executor(
            None, measure_latency_sync, bridge.config)
        if latency is not None:
            await ws.send_str(json.dumps(
                {'type': 'latency_result',
                 'success': True, 'latency': latency}))
        else:
            await ws.send_str(json.dumps(
                {'type': 'latency_result', 'success': False,
                 'error': 'Request failed or timed out'}))

    else:
        await ws.send_str(json.dumps(
            {'type': 'error', 'msg': f'Unknown command: {c}'}))


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
        'User-Agent': ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/121.0.0.0 Safari/537.36"),
        'Referer': 'https://www.pixiv.net/',
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
    ws = web.WebSocketResponse(heartbeat=30.0)
    await ws.prepare(request)
    bridge = request.app['bridge']
    await bridge.register(ws)
    try:
        init = bridge._queue_status_payload()
        init['type'] = 'init'
        init['config'] = bridge.config.config
        init['ui_state'] = bridge.session.get_ui_state()
        with bridge.worker._items_lock:
            init['items'] = [
                {'pid': pid, **info}
                for pid, info in bridge.worker.items_status.items()]
        await ws.send_str(json.dumps(init, ensure_ascii=False))

        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    cmd = json.loads(msg.data)
                    await handle_command(bridge, cmd, ws)
                except Exception as e:
                    write_log(t('command_error', error=str(e)), 'error')
                    try:
                        await ws.send_str(json.dumps(
                            {'type': 'error', 'msg': str(e)}))
                    except Exception:
                        pass
            elif msg.type == aiohttp.WSMsgType.ERROR:
                break
    finally:
        await bridge.unregister(ws)
    return ws


# ============================================================
# Helpers
# ============================================================
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
    qd = session.get_queue()
    current = qd.get('current_tasks', []) or []
    failed = qd.get('failed_tasks', []) or []
    for it in current:
        worker.url_queue.put(it if isinstance(it, dict) else {'url': it})
    for item in failed:
        pid = item.get('pid')
        img_path = item.get('img_path')
        meta_d = item.get('metadata') or {}
        if pid:
            path_obj = Path(img_path) if img_path else None
            with worker.failed_lock:
                worker.failed_items.append((int(pid), path_obj, meta_d))
    if current or failed:
        write_log(t('queue_restored', pending=len(current),
                    failed=len(failed)), 'info')


async def startup_latency_check(bridge):
    loop = asyncio.get_event_loop()
    latency = await loop.run_in_executor(
        None, measure_latency_sync, bridge.config)
    if latency is not None:
        write_log(t('latency_startup', latency=latency), 'info')
        bridge.broadcast({'type': 'startup_latency', 'latency': latency})


async def no_cache_middleware(request, handler):
    response = await handler(request)
    path = request.path
    if (path.startswith('/static/')
            or path.startswith('/ui_icons/')
            or path.startswith('/static_icons/')
            or path == '/'):
        response.headers['Cache-Control'] = \
            'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response


async def main_async(port, config, accounts, session):
    app = web.Application(middlewares=[web.middleware(no_cache_middleware)])
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
        ext_icons = web_dir / "ext_search_icons"
        if ext_icons.exists():
            app.router.add_static('/ext_search_icons/', ext_icons)

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

    if not bridge.worker.url_queue.empty():
        write_log("Auto-starting queue with restored tasks", 'info')
        bridge.worker.start()

    while True:
        await asyncio.sleep(3600)


# ============================================================
# Main
# ============================================================
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
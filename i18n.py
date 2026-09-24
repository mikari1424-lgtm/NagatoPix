# -*- coding: utf-8 -*-
"""NagatoDownloader backend i18n / 后端国际化"""
import threading

_current_lang = 'en'
_lock = threading.Lock()


LOG_STRINGS = {
    'en': {
        'banner': 'NagatoDownloader v{version} - A Pixiv Artwork Downloader',
        'starting': 'Starting...',
        'server_started': 'Server started: {url}',
        'server_shutdown': 'Server shutdown, queue saved',
        'interrupted': 'Interrupted by user',
        'console_minimized': 'Console minimized to taskbar',
        'browser_opening': 'Opening browser...',

        'config_created': 'Created default config: {path}',
        'config_loaded': 'Loaded config: {path}',
        'config_load_failed': 'Config load failed, using defaults: {error}',
        'config_save_failed': 'Config save failed: {error}',
        'config_validated': 'Config validated OK',
        'config_invalid': 'Invalid config [{key}] = {value!r} ({error}), using default {default!r}',
        'config_migrated': 'Migrated legacy JSON config to TOML: {path}',

        'exiftool_found': 'ExifTool loaded: version {version}',
        'exiftool_not_found': 'ExifTool not found: {path} - metadata will be skipped',
        'exiftool_version_error': 'Could not get ExifTool version: {error}',

        'language_loaded': 'Language: {lang}',

        'login_success': 'Login succeeded',
        'login_failed': 'Login failed: {error}',
        'no_token': 'No refresh token configured',

        'queue_restored': 'Queue restored: {pending} pending, {failed} failed',
        'queue_restore_failed': 'Failed to restore queue: {error}',
        'queue_saved': 'Queue saved',
        'queue_save_failed': 'Queue save failed: {error}',
        'queue_empty': 'Queue is empty',
        'queue_cleared': 'Cleared {n} task(s)',
        'queue_finished_empty': 'All tasks done, queue file removed',
        'queue_finished_partial': 'Queue finished, {pending} pending + {failed} failed remain',
        'queue_file_remove_failed': 'Failed to remove queue file: {error}',
        'enqueued': 'Enqueued: {url}',
        'enqueued_n': 'Enqueued {n} URL(s)',
        'processing': 'Processing: {url} (remaining {remaining})',
        'workers_started': 'Started {n} worker(s)',
        'workers_stopped': 'All workers stopped',
        'stopping_queue': 'Stopping queue...',
        'task_success': 'Success: {url}',
        'task_failed': 'Failed: {url}',
        'task_retry': 'Retry: {url}',
        'retry_success': 'Retry succeeded: {url}',
        'retry_failed': 'Retry failed: {url}',
        'no_failed_tasks': 'No failed tasks',
        'requeued_failed': 'Re-enqueued {n} failed task(s)',
        'cannot_clear_running': 'Cannot clear while running',
        'cannot_retry_running': 'Cannot retry while running',

        'downloading': 'Downloading: {url} -> {path}',
        'download_done': 'Downloaded: {path}',
        'download_failed': 'Download failed: {url}',
        'file_exists': 'Already exists, skipping: {path}',
        'illust_fetch_failed': 'Cannot fetch illust {id}',
        'illust_invisible': 'Illust {id} is not visible, skipping',
        'no_image_url': 'No image URL found for {id}',
        'metadata_failed': 'Metadata write failed, recorded for retry: {path}',

        'rate_limited': 'Rate limit hit, waiting {delay}s',
        'api_retry_exhausted': 'API retry exhausted',
        'search_page_failed': 'Search page {page} failed: {error}',
        'ranking_failed': 'Ranking failed: {error}',
        'user_search_failed': 'User search failed: {error}',
        'user_detail_failed': 'User detail failed: {error}',
        'user_illusts_failed': 'Fetch user illusts failed: {error}',
        'recommend_failed': 'Recommendation failed: {error}',
        'follow_failed': 'Follow new failed: {error}',
        'user_not_found': 'User not found or inaccessible',
        'invalid_pid': 'Invalid PID',
        'invalid_uid': 'Invalid UID',
        'invalid_url': 'Invalid URL: {url}',

        'exiftool_failed': 'ExifTool exit {code}: {stderr}',
        'exiftool_exception': 'ExifTool exception: {error}',
        'exiftool_args_failed': 'Failed to create arg file: {error}',
        'exiftool_json_failed': 'JSON export failed: {error}',

        'proxy_failed': 'Image proxy failed: {error}',
        'bookmark_parse_failed': 'Bookmark parse failed: {error}',
        'history_load_failed': 'History load failed: {error}',
        'history_save_failed': 'History save failed: {error}',
        'command_error': 'Command handling error: {error}',
        'latency_failed': 'Latency probe failed: {error}',
        'latency_startup': 'Startup latency: {latency}ms',
    },
    'zh-CN': {
        'banner': 'NagatoDownloader v{version} - Pixiv 作品下载器',
        'starting': '正在启动...',
        'server_started': '服务器已启动: {url}',
        'server_shutdown': '服务器关闭，队列已保存',
        'interrupted': '用户中断，程序退出',
        'console_minimized': '控制台已最小化到任务栏',
        'browser_opening': '正在打开浏览器...',

        'config_created': '已创建默认配置文件: {path}',
        'config_loaded': '已加载配置文件: {path}',
        'config_load_failed': '配置文件读取失败，使用默认配置: {error}',
        'config_save_failed': '配置保存失败: {error}',
        'config_validated': '配置验证通过',
        'config_invalid': '配置项 [{key}] = {value!r} 无效 ({error})，使用默认值 {default!r}',
        'config_migrated': '已从旧版 JSON 配置迁移到 TOML: {path}',

        'exiftool_found': 'ExifTool 已加载: 版本 {version}',
        'exiftool_not_found': 'ExifTool 未找到: {path} - 元数据功能将跳过',
        'exiftool_version_error': '无法获取 ExifTool 版本: {error}',

        'language_loaded': '语言: {lang}',

        'login_success': '登录成功',
        'login_failed': '登录失败: {error}',
        'no_token': '未配置刷新令牌',

        'queue_restored': '已恢复队列: {pending} 个待处理，{failed} 个失败',
        'queue_restore_failed': '恢复队列失败: {error}',
        'queue_saved': '队列已保存',
        'queue_save_failed': '队列保存失败: {error}',
        'queue_empty': '队列为空',
        'queue_cleared': '已清空 {n} 个任务',
        'queue_finished_empty': '所有任务处理完毕，队列文件已移除',
        'queue_finished_partial': '队列处理完毕，剩余 {pending} 待处理 + {failed} 失败',
        'queue_file_remove_failed': '移除队列文件失败: {error}',
        'enqueued': '已加入队列: {url}',
        'enqueued_n': '已加入 {n} 个 URL 到队列',
        'processing': '处理中: {url} (剩余 {remaining})',
        'workers_started': '已启动 {n} 个工作线程',
        'workers_stopped': '所有线程已停止',
        'stopping_queue': '正在停止队列...',
        'task_success': '成功: {url}',
        'task_failed': '失败: {url}',
        'task_retry': '重试: {url}',
        'retry_success': '重试成功: {url}',
        'retry_failed': '重试失败: {url}',
        'no_failed_tasks': '没有失败任务',
        'requeued_failed': '已重新加入 {n} 个失败任务',
        'cannot_clear_running': '队列运行中，无法清空',
        'cannot_retry_running': '队列运行中，无法重试',

        'downloading': '下载中: {url} -> {path}',
        'download_done': '下载完成: {path}',
        'download_failed': '下载失败: {url}',
        'file_exists': '文件已存在，跳过: {path}',
        'illust_fetch_failed': '无法获取插画信息: {id}',
        'illust_invisible': '作品 {id} 不可见，跳过',
        'no_image_url': '未找到图片 URL: {id}',
        'metadata_failed': '元数据写入失败，已记录到失败列表: {path}',

        'rate_limited': '触发速率限制，等待 {delay} 秒',
        'api_retry_exhausted': 'API 重试次数已用尽',
        'search_page_failed': '搜索第 {page} 页失败: {error}',
        'ranking_failed': '排行榜获取失败: {error}',
        'user_search_failed': '用户搜索失败: {error}',
        'user_detail_failed': '获取用户详情失败: {error}',
        'user_illusts_failed': '获取用户作品失败: {error}',
        'recommend_failed': '推荐获取失败: {error}',
        'follow_failed': '关注新作获取失败: {error}',
        'user_not_found': '用户不存在或无法访问',
        'invalid_pid': '无效的 PID',
        'invalid_uid': '无效的 UID',
        'invalid_url': '无效的 URL: {url}',

        'exiftool_failed': 'ExifTool 返回码 {code}: {stderr}',
        'exiftool_exception': 'ExifTool 执行异常: {error}',
        'exiftool_args_failed': '创建参数文件失败: {error}',
        'exiftool_json_failed': 'JSON 导出失败: {error}',

        'proxy_failed': '图片代理失败: {error}',
        'bookmark_parse_failed': '书签解析失败: {error}',
        'history_load_failed': '历史加载失败: {error}',
        'history_save_failed': '历史保存失败: {error}',
        'command_error': '命令处理异常: {error}',
        'latency_failed': '延迟测试失败: {error}',
        'latency_startup': '启动延迟: {latency}ms',
    },
}


META_STRINGS = {
    'en': {
        'ai_generated': 'AI-generated',
        'source_url': 'Source URL',
        'description': 'Description',
    },
    'zh-CN': {
        'ai_generated': 'AI生成',
        'source_url': '原始链接',
        'description': '作品说明',
    },
}


def set_language(lang: str):
    global _current_lang
    if lang not in LOG_STRINGS:
        lang = 'en'
    with _lock:
        _current_lang = lang


def get_language() -> str:
    with _lock:
        return _current_lang


def t(key: str, **kwargs) -> str:
    with _lock:
        lang = _current_lang
    table = LOG_STRINGS.get(lang, LOG_STRINGS['en'])
    s = table.get(key)
    if s is None:
        s = LOG_STRINGS['en'].get(key, key)
    if kwargs:
        try:
            s = s.format(**kwargs)
        except (KeyError, IndexError):
            pass
    return s


def meta(key: str) -> str:
    with _lock:
        lang = _current_lang
    table = META_STRINGS.get(lang, META_STRINGS['en'])
    return table.get(key, key)
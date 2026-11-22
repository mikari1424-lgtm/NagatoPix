# -*- mode: python ; coding: utf-8 -*-

"""
PyInstaller spec for NagatoPix
- Entry: main.py
- Mode: onedir (not onefile)
- UPX: disabled
- Console: enabled
- Excludes: common unused libraries to reduce bundle size
"""

from PyInstaller.utils.hooks import collect_submodules


block_cipher = None


# ------------------------------------------------------------
# Excludes — remove libraries not used by NagatoPix
# 排除未使用的库，减小打包体积
# ------------------------------------------------------------
EXCLUDES = [
    # GUI frameworks (this is a WebUI app, no native GUI)
    'tkinter',
    'tkinter.ttk',
    'tkinter.scrolledtext',
    'tkinter.messagebox',
    'tkinter.filedialog',
    'Tkinter',
    'PyQt5',
    'PyQt6',
    'PySide2',
    'PySide6',
    'wx',
    'kivy',

    # Scientific / data
    'numpy',
    'scipy',
    'pandas',
    'matplotlib',
    'matplotlib.pyplot',
    'sympy',
    'sklearn',
    'statsmodels',


    # Notebook / IPython
    'IPython',
    'jupyter',
    'notebook',
    'nbformat',
    'nbconvert',
    'ipykernel',
    'ipywidgets',

    # Testing
    'pytest',
    'unittest',
    'nose',
    'hypothesis',
    'mock',

    # Dev tools
    'setuptools',
    'pip',
    'wheel',
    'distutils',
    'pkg_resources',
    'pydoc',
    'doctest',
    'pdb',
    'cProfile',
    'profile',
    'trace',
    'tracemalloc',

    # Python 2 remnants
    'commands',
    'ConfigParser',
    'Queue',
    'StringIO',
    'urllib2',
    'urlparse',
    'htmlentitydefs',
    'HTMLParser',

    # Uncommon stdlib (kept minimal)
    'curses',
    'turtle',
    'turtledemo',
    'idlelib',
    'lib2to3',
    'test',
    'ensurepip',
    'venv',
    'distutils.command',
    'sqlite3',
    'xmlrpc',
    'multiprocessing.popen_spawn_win32',
    'multiprocessing.popen_fork',
    'multiprocessing.popen_forkserver',
    'multiprocessing.popen_spawn_posix',
    'multiprocessing.shared_memory',

    # Network libs not used
    'twisted',
    'tornado',
    'flask',
    'django',
    'scrapy',
    'paramiko',
    'fabric',
    'telnetlib',
    'ftplib',
    'smtplib',
    'imaplib',
    'poplib',

    # Compression (only stdlib gzip/bz2 needed)
    'lzma',
    'zstd',
    'lzo',

    # Misc
    'cv2.cv2',
    'torch',
    'tensorflow',
    'keras',
    'onnx',
    'xgboost',
]


# ------------------------------------------------------------
# Hidden imports — pixivpy3 dynamically imports some modules
# pixivpy3 内部动态导入的模块需显式声明
# ------------------------------------------------------------
HIDDEN_IMPORTS = [
    'pixivpy3',
    'pixivpy3.api',
    'pixivpy3.utils',
    'pixivpy3.aapi',
    'pixivpy3.bypass',
    'pixivpy3.config',
    'bs4',
    'soupsieve',
    'aiohttp',
    'aiohttp.web',
    'aiohttp.http_websocket',
    'aiosignal',
    'async_timeout',
    'attrs',
    'multidict',
    'yarl',
    'frozenlist',
    'requests',
    'urllib3',
    'certifi',
    'charset_normalizer',
    'idna',
    'i18n',
    'tomllib',
    'tomli',
    'PIL',
    'Pillow',
]


# ------------------------------------------------------------
# Datas — bundle webui and ExifTool
# 打包前端资源与 ExifTool
# ------------------------------------------------------------
DATAS = [
    ('webui', 'webui'),
    ('plugins', 'plugins'),
]


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=DATAS,
    hiddenimports=HIDDEN_IMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)


pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)


exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='NagatoPix',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                      # UPX disabled / 禁用 UPX
    console=True,                   # Console enabled / 启用控制台
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='AppLogos/NagatoPix.ico'
)


coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,                      # UPX disabled / 禁用 UPX
    upx_exclude=[],
    name='NagatoPix',               # Output folder: dist/NagatoPix/
)
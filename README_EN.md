# NagatoPix

> **A Powerful Pixiv App**
> *Fetch the art. Keep the metadata.*

A client-server Pixiv app built on Python + WebSocket + vanilla WebUI. Maximum browsing and downloading output, minimum footprint.

[简体中文 →](README.md)

---

## Naming

> *"A humanoid interface created by the Data Overmind."* — Yuki Nagato

In *The Melancholy of Haruhi Suzumiya*, Yuki Nagato is an artificial humanoid interface: silent, precise, and quietly processing vast amounts of information into human-readable form.

This maps cleanly onto the program: no image rendering, no social features, no recommendation engines — just a quiet background process that fetches, searches, archives, and writes metadata, turning scattered artworks into a structured local library.

Renamed from **NagatoDownloader** to **NagatoPix**, the scope has expanded from a pure download tool to a full browsing + searching + archiving client.

---

## Why this exists

The official Pixiv client excels at **single-artwork browsing**, but is fundamentally constrained for **bulk browsing** and **metadata management**:

| Dimension | Official Client | NagatoPix |
| --- | --- | --- |
| Memory, 20 artworks | ~3.6 GB | ~135 MB |
| Memory, 100-artwork ranking | ~10 GB | < 500 MB |
| Sortable fields | 2 (date, popularity) | All available fields |
| Search within ranking | None | Tag cloud / author cloud |
| Single search limit | Unlimited but memory explodes | 6000 items |
| Bulk download | One by one | Queue + 1–8 workers |
| ExifTool metadata | None | Full support |
| Queue persistence | None | Supported (resume after restart) |

The core difference is not "more features" — it is **design philosophy**. The official client assumes *users want to view everything*. NagatoPix assumes *users want to browse metadata and download a few*. The former must hold images in memory; the latter only processes JSON metadata.

---

## Features

### Browsing & Discovery

- **Rankings**: 8 types, fixed 480 items, auto-compares today vs yesterday and flags new entries
- **Tag search**: up to 6000 items (200 pages × 30)
- **Search settings** (modal):
  - Scope: tags (partial / exact) / title & caption
  - Period: any / last day / last week / last month / **custom range**
  - Type: illust / manga / ugoira / novel
  - Bookmark count range (client-side filter)
- **Top-bar search**: illust / novel / user modes, press `Enter` to search
- **User detail**: illust / novel tabs, artwork list + profile + commission status + tag cloud
- **Recommendations**: auto / from queue / from history / from artwork / advanced
- **Followed artists' new works**: 300 per request, tag cloud + author cloud filter
- **Tag cloud / Author cloud**: collapsible, auto-generated from fetched results

### Download

- **Parallel queue**: 1–8 workers (high-speed mode), per-artwork granularity
- **Global rate-limit sync**: any worker hitting a rate limit pauses all workers
- **Queue persistence**: real-time save after each task; resume from `session.json`
- **Auto-start**: if saved tasks exist at startup, the queue starts automatically
- **Failure retry**: uses `-m` to ignore minor errors and exports JSON metadata
- **History**: last 2000 downloads archived to `history.json`
- **Download tab**: live progress bar, detailed stats, preset toggle, thread count

### Metadata

- **Full ExifTool write**: title, author, tags, date, URL, description
- **AI / R-15 / R-18 / R-18G markers**: written to XMP-dc:subject and EXIF:XPKeywords
- **Original filenames preserved**
- **Line breaks preserved**: `<br/>` correctly converted to newlines
- **Failed-task JSON export**: for manual inspection
- **Bilingual metadata**: Chinese or English tags based on UI language

### Interaction

- **Sidebar navigation**: clear at a glance
- **Dynamic float ball**: appears when artworks are selected, shows selection count
- **Direct artwork links**: click title → opens Pixiv artwork page
- **Direct author links**: click author → opens user detail page
- **Multi-select**: Ctrl/Shift select then add to queue
- **Sticky controls + scrollable results**: filters stay put
- **Multi-language UI**: Simplified Chinese / English, switchable in Settings and persisted
- **Latency probe**: measures Cloudflare RTT on startup
- **HashLink routing**: page state is written into the URL; refresh / back-forward restores the current tab and search parameters

---

## Quick Start

### Option 1: Prebuilt binary (recommended for most users)

1. Download `NagatoPix.zip` from [Releases](https://github.com/mikari1424-lgtm/NagatoPix/releases)
2. Extract to any directory (avoid non-ASCII paths)
3. Double-click `NagatoPix.exe`
4. The server starts and the WebUI opens in your browser

**First run requires a RefreshToken** (see below).

### Option 2: Run from source (developers)

```bash
git clone https://github.com/mikari1424-lgtm/NagatoPix.git
cd NagatoPix
pip install -r requirements.txt
python main.py
```

---

## Configuring RefreshToken

**Pixiv no longer supports username/password login.** This program uses a RefreshToken.

Click the **❓** icon next to the refresh-token field in Settings — the app includes a built-in guide. Summary:

### Method 1: Pixiv-Viewer (recommended)

1. Install [Redirector](https://einaregilsson.com/redirector/) and [Tampermonkey](https://www.tampermonkey.net/index.php)
2. Import redirect rule: `https://pixiv.pictures/helper/Redirector.json`
3. Install the [login helper userscript](https://fastly.jsdelivr.net/gh/asadahimeka/pixiv-viewer@master/public/helper/helper.user.js)
4. Visit `https://pixiv.pictures/account/login`, choose App API (OAuth)
5. Export the token from [Settings](https://pixiv.pictures/setting/others)

### Method 2: pxder (Node.js)

```bash
npm i -g pxder
pxder --login
pxder --export-token
```

### Method 3: PixEz (mobile)

Download from [GitHub](https://github.com/Notsfsssf/pixez-flutter), then: More → Account → Token export

> Original guide: [https://www.nanoka.top/posts/e78ef86/](https://www.nanoka.top/posts/e78ef86/)

**Note**: If you cannot reach Pixiv directly, configure a proxy in Settings first (socks5 / socks4 / http supported).

---

## Usage

### Sidebar

| Icon | Function |
| --- | --- |
| ✨ | Recommendations |
| 👥 | Followed artists |
| 🏆 | Rankings |
| ⬇️ | Download queue |
| 👤 | Account & bookmarks |
| ⚙️ | Settings |

> Tag/user search is entered from the top search bar; the user detail page is reached from user search results or author links and has no dedicated sidebar entry.

### Recommendations

- **Auto**: Pixiv default algorithm
- **From queue**: first 30 items as seeds
- **From history**: last 30 downloads as seeds
- **From artwork**: enter PID, recommends similar works
- **Advanced**: manual control over `bookmark_illust_ids`, `viewed`, etc.

Max 120 items (Pixiv API cap).

### Followed Artists

300 items per load (10 pages). Supports:

- Scope filter: all / public / private
- Tag cloud filter (click chip to toggle)
- Author cloud filter (click chip to toggle)
- Both clouds are combined with **AND** logic

### Rankings

8 types (daily, weekly, monthly, male, female, original, rookie, R-18), fixed **480 items**.

The program auto-compares today's and yesterday's rankings; **new entries show a green `NEW` badge**.

### Tag Search

Type a keyword in the top search bar, choose "Illust" or "Novel" mode, press `Enter`:

- **Modes**: illust / novel / user (dropdown in the top bar)
- **Tag**: exact / partial / title & caption
- **Sort**: newest / oldest
- **Page + Pages**: auto-step forward N pages from start (up to 200 pages = 6000 items)
- **Search settings** (gear button on the right of the search bar, opens a modal):
  - Scope
  - Period (including custom date range)
  - Type (illust / manga / ugoira / novel)
  - Bookmark count range (client-side)

### User Search / User Detail

Switch the top search bar mode to "User":

- Search by username / account
- Click name → user detail
- User detail auto-loads all artworks with illust / novel tabs and a tag cloud filter

### Download Queue

In any result list:

1. **Multi-select** (Ctrl / Shift click)
2. A **float ball** appears bottom-right showing selection count
3. Click the ball to enqueue all selected

Switch to the "Download" tab:

- **Progress summary**: percentage + remaining count + progress bar + failed count + status
- **Item list**: PID, title, status and progress per item (collapsible)
- **Preset toggle**:
  - "Normal": single-threaded, stable
  - "High-speed": 1–8 parallel workers
- **Ugoira format**: GIF / APNG / WebP
- **Actions**: clear queue, stop

**`+` button bottom-right**: opens the "Add Task" modal:

- **Manual**: single URL/ID, or batch one per line
- **Bookmarks**: select browser-exported HTML

### Settings

The Settings tab is split into four sections (matching `[download]` / `[api]` / `[preferences]` / `[network]` in `config.toml`):

- **Download**: directory, normal/high-speed mode, worker count, download delay, max retries, metadata cache, overwrite existing files, ugoira export format (GIF / APNG / WebP)
- **API**: request delay, parallel requests, default result count, Web Ajax mode (auto / disabled)
- **Preferences**: UI language (auto / 简体中文 / English), theme (dark / light)
- **Network**: proxy (socks5 / socks4 / http), start port
- Buttons: Save, Test login, Test latency

Account management (RefreshToken / multi-account switching) lives in the "Account" tab with a built-in ❓ guide.

---

## Architecture

```text
┌──────────────────────────────────────────┐
│  Browser (WebUI)                         │
│  index.html + style.css + main.js        │
│  + i18n.js                               │
└────────────┬─────────────────────────────┘
             │ WebSocket (/ws)
             │ HTTP (/proxy_image)
┌────────────▼─────────────────────────────┐
│  aiohttp server (main.py)                 │
│  ├─ WebBridge (WebSocket broadcast)      │
│  ├─ DownloadWorker (1–8 parallel)        │
│  │   ├─ PixivAPI (pixivpy3 wrapper)      │
│  │   ├─ RateLimiter (global sync)        │
│  │   └─ ExifToolWrapper                  │
│  └─ static resource routing              │
└──────────────────────────────────────────┘
```

### Key components

| Component | Responsibility |
| --- | --- |
| `RateLimiter` | When any worker hits a rate limit, all workers wait via `threading.Condition` |
| `WebBridge` | Backend status → broadcast to all WebSocket clients |
| `WebAjaxClient` | Web Ajax API channel: captions / profiles / novels / translated tags / totals |
| `DownloadWorker` | Queue consumption, failure tracking, real-time persistence |
| `ExifToolWrapper` | Each call uses an independent temp arg-file; CStr mode preserves newlines |
| `SessionManager` | Session / queue / UI state persisted together in `session.json` |
| `proxy_image` | Streams Pixiv CDN images through an aiohttp session (bypasses Referer, passes cache headers) |

### Files

```text
NagatoPix/
├── NagatoPix.exe
├── config.toml                # config (auto-created on first run)
├── session.json               # session / queue / UI state (real-time save)
├── accounts.json              # accounts (RefreshToken)
├── history.json               # download history (last 2000)
├── logs/
│   └── nagato-YYYYMMDD-HHMMSS.log
└── _internal/
    ├── webui/                 # frontend
    └── plugins/
        ├── ExifTool.exe
        └── exiftool_files/
```

---

## Building from source

### Requirements

```bash
pip install -r requirements.txt
```

`requirements.txt`:

```text
requests
aiohttp
beautifulsoup4
Pillow
pixivpy3>=3.7.5
tomli; python_version < "3.11"
```

Python 3.11+ is required (`tomllib` is stdlib); on Python 3.10 `tomli` is installed automatically as a fallback.

### Packaging as standalone executable

```bash
pip install pyinstaller
pyinstaller app.spec --noconfirm
```

Output: `dist/NagatoPix/`. Compress the whole directory to distribute.

Ensure `plugins/` contains the complete ExifTool:

```text
plugins/
├── ExifTool.exe
└── exiftool_files/          # must be sibling of the exe
```

---

## Known Limitations

- **Invisible artworks**: some works are visible on the website but the API returns `visible: false`. This is a Pixiv API-level filter — cannot be bypassed.
- **Novels**: browsing and search since 1.3.0, Markdown download since 1.3.1 (not written via ExifTool; metadata goes into YAML frontmatter)
- **"Popular" sort**: requires Pixiv Premium, removed.
- **Rate limit**: non-Japan IPs hit rate limits more often. The program waits and retries automatically.
- **ExifTool optional**: if ExifTool is missing, images still download but metadata is not written.

---

## FAQ

**Q: Port in use?**
A: The program starts from the configured start port (default 8765) and scans forward for a free one.

**Q: Blank browser page?**
A: Check the console for errors, or visit `http://127.0.0.1:<port>/` manually.

**Q: Downloads are slow?**
A: Switch to "High-speed" preset in the Download tab, and increase thread count (max 8).

**Q: Why does bookmark filtering only apply to current results?**
A: Server-side bookmark filtering requires Pixiv Premium. For regular users it is silently ignored. This program therefore performs client-side filtering. To filter a larger set, increase the "Pages" value first to fetch more results.

**Q: How to clear history?**
A: Delete `history.json`.

**Q: macOS / Linux support?**
A: The code is cross-platform, but you must replace ExifTool with the platform-specific binary and adjust the filename in `plugins/`.

**Q: How to switch language?**
A: Go to Settings → Preferences and pick the UI language. The choice persists.

---

## Acknowledgements

- [pixivpy3](https://github.com/upbit/pixivpy) — Pixiv API wrapper
- [ExifTool](https://exiftool.org/) — metadata writing
- [aiohttp](https://docs.aiohttp.org/) — async HTTP server
- [Yuki Nagato](https://en.wikipedia.org/wiki/Yuki_Nagato) — naming inspiration

---

## License

GPL v3 License

---

## Disclaimer

This program is for personal study. All downloaded content belongs to its original authors. Do not use for commercial purposes or redistribution. Comply with Pixiv's [Terms of Service](https://www.pixiv.net/terms.php) and local laws.

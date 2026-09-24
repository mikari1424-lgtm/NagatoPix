// NagatoDownloader main / 主逻辑

const filterSets = {
    "ranking-tag-cloud": new Set(),
    "udetail-tag-cloud": new Set(),
    "follow-tag-cloud": new Set(),
    "follow-author-cloud": new Set(),
};

let parsedBookmarkUrls = [];
let rankingItems = [],
    rankingItemsAll = [];
let searchItems = [],
    userSearchItems = [];
let recommendItems = [],
    followItems = [],
    followItemsAll = [];
let userDetailItems = [],
    userDetailAllItems = [];
let userDetailUid = null;
let followCurrentOffset = 0;
let followPage = 1;
let followBatchSize = 300;
let isConnected = false;
let lastQueueState = {
    queue: 0,
    failed: 0,
    processed: 0,
    running: false,
    stopping: false,
};
let searchItemsRaw = [];

// ============ WebSocket ============
let ws = null;
let reconnectTimer = null;

function connect() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(proto + "//" + location.host + "/ws");
    ws.onopen = () => {
        isConnected = true;
        document.getElementById("conn-status").className = "status-dot online";
        document.getElementById("conn-text").textContent = t("connected");
        send({ cmd: "set_language", lang: currentLang });
    };
    ws.onclose = () => {
        isConnected = false;
        document.getElementById("conn-status").className = "status-dot offline";
        document.getElementById("conn-text").textContent = t("disconnected");
        if (reconnectTimer) clearTimeout(reconnectTimer);
        reconnectTimer = setTimeout(connect, 2000);
    };
    ws.onerror = () => {};
    ws.onmessage = (ev) => {
        try {
            handleMessage(JSON.parse(ev.data));
        } catch (e) {
            console.error(e);
        }
    };
}

function send(obj) {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
    else toast(t("toast_no_connection"), "error");
}

function handleMessage(msg) {
    switch (msg.type) {
        case "init":
            fillConfig(msg.config);
            updateQueueStatus(msg);
            break;
        case "queue_status":
            updateQueueStatus(msg);
            break;
        case "queue_saved":
            toast(t("toast_queue_saved"), "success");
            break;
        case "search_result":
            renderSearchResults(msg.items, msg.start_page, msg.pages);
            break;
        case "search_progress":
            document.getElementById("search-list").innerHTML =
                `<div class="loading"><div class="spinner"></div>${t("loading_search")}</div>`;
            document.getElementById("search-status").textContent = t(
                "status_search_progress",
                msg.page,
                msg.current,
                msg.total,
            );
            break;
        case "ranking_result":
            renderRankingResults(msg.items, msg.stats);
            break;
        case "ranking_progress":
            document.getElementById("ranking-list").innerHTML =
                `<div class="loading"><div class="spinner"></div>${t("loading_ranking")} (${msg.phase}: ${msg.count})</div>`;
            document.getElementById("ranking-status").textContent = t(
                "status_requesting",
                `${msg.phase}: ${msg.count}`,
            );
            break;
        case "recommend_result":
            renderRecommendResults(msg.items, msg.mode);
            break;
        case "follow_progress":
            document.getElementById("follow-list").innerHTML =
                `<div class="loading"><div class="spinner"></div>${t("loading_follow")} (${msg.count})</div>`;
            break;
        case "follow_result":
            renderFollowResults(
                msg.items,
                msg.offset,
                msg.has_more,
                msg.batch_size,
            );
            break;
        case "bookmark_parsed":
            renderBookmarkPreview(msg.urls);
            break;
        case "config":
            fillConfig(msg.data);
            break;
        case "success":
            toast(msg.msg, "success");
            break;
        case "error":
            toast(msg.msg, "error");
            break;
        case "login_result":
            toast(
                msg.success ? t("toast_login_ok") : t("toast_login_fail"),
                msg.success ? "success" : "error",
            );
            break;
        case "language_set":
            break;
        case "user_search_result":
            renderUserSearchResults(msg.items);
            break;
        case "user_detail_phase":
            handleUserDetailPhase(msg);
            break;
        case "user_detail_result":
            renderUserDetail(msg.user, msg.items);
            break;
        case "rate_limited":
            showRateLimitToast(msg.delay);
            break;
        case "latency_result":
            if (msg.success) {
                const slow = msg.latency > 300;
                toast(
                    slow
                        ? t("toast_latency_slow", msg.latency)
                        : t("toast_latency_ok", msg.latency),
                    slow ? "warn" : "success",
                );
            } else {
                toast(t("toast_latency_fail", msg.error), "error");
            }
            break;
        case "startup_latency":
            if (msg.latency > 300) toast(t("toast_network_bad"), "warn");
            break;
    }
}

// ============ Toast ============
let toastTimer = null;
let rateLimitTimer = null;

function clearAllToasts() {
    if (toastTimer) {
        clearTimeout(toastTimer);
        toastTimer = null;
    }
    if (rateLimitTimer) {
        clearInterval(rateLimitTimer);
        rateLimitTimer = null;
    }
}

function toast(msg, type = "") {
    clearAllToasts();
    const el = document.getElementById("toast");
    el.textContent = msg;
    el.className = "toast show " + type;
    toastTimer = setTimeout(() => {
        el.className = "toast " + type;
    }, 2500);
}

function showRateLimitToast(delaySeconds) {
    clearAllToasts();
    const endTime = Date.now() + delaySeconds * 1000;
    const el = document.getElementById("toast");
    const tick = () => {
        const remaining = Math.max(0, Math.ceil((endTime - Date.now()) / 1000));
        if (remaining <= 0) {
            el.className = "toast";
            if (rateLimitTimer) {
                clearInterval(rateLimitTimer);
                rateLimitTimer = null;
            }
            return;
        }
        const prefix =
            currentLang === "zh-CN"
                ? "⚠️ 触发 API 速率限制"
                : "⚠️ Rate limit triggered";
        const suffix =
            currentLang === "zh-CN" ? "秒后自动重试" : "s until retry";
        el.textContent = `${prefix}，${remaining} ${suffix}...`;
        el.className = "toast show warn";
    };
    tick();
    rateLimitTimer = setInterval(tick, 500);
}

// ============ i18n render ============
function applyI18n() {
    document.querySelectorAll("[data-i18n]").forEach((el) => {
        el.textContent = t(el.dataset.i18n);
    });
    document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
        el.placeholder = t(el.dataset.i18nPlaceholder);
    });
    document.querySelectorAll("[data-i18n-title]").forEach((el) => {
        el.title = t(el.dataset.i18nTitle);
    });
    updateSelectionCount();
    document.getElementById("conn-text").textContent = isConnected
        ? t("connected")
        : t("connecting");
    const sw = document.getElementById("lang-switcher");
    if (sw) sw.value = currentLang;
    updateDownloadStatusText();
}

function switchLanguage(lang) {
    if (lang !== "zh-CN" && lang !== "en") return;
    currentLang = lang;
    localStorage.setItem("nagato_lang", lang);
    applyI18n();
    send({ cmd: "set_language", lang });
    renderTokenHelp();
}

function renderTokenHelp() {
    const el = document.getElementById("token-help-body");
    if (!el) return;
    if (currentLang === "zh-CN") {
        el.innerHTML = `
            <p style="margin-bottom:12px">由于 Pixiv 已不再支持用户名密码登录，您需要先获取一个 RefreshToken。以下方式任选其一：</p>
            <div style="background:#1e2228; border-radius:6px; padding:12px; margin-bottom:12px">
                <div style="color:#7eb6ff; font-weight:600; margin-bottom:8px">方式一：Pixiv-Viewer 网页端（推荐）</div>
                <ol style="margin-left:18px; color:#a0a4ab">
                    <li>安装 <a href="https://einaregilsson.com/redirector/" target="_blank" style="color:#7eb6ff">Redirector</a> 和 <a href="https://www.tampermonkey.net/index.php" target="_blank" style="color:#7eb6ff">Tampermonkey</a> 扩展</li>
                    <li>导入 Redirector 规则：<code style="background:#2f343c; padding:2px 6px; border-radius:3px; font-size:12px">https://pixiv.pictures/helper/Redirector.json</code></li>
                    <li>安装 <a href="https://fastly.jsdelivr.net/gh/asadahimeka/pixiv-viewer@master/public/helper/helper.user.js" target="_blank" style="color:#7eb6ff">登录工具用户脚本</a></li>
                    <li>访问 <a href="https://pixiv.pictures/account/login" target="_blank" style="color:#7eb6ff">pixiv.pictures/account/login</a>，选择 <b>App API (OAuth)</b> 登录</li>
                    <li>登录成功后，在 <a href="https://pixiv.pictures/setting/others" target="_blank" style="color:#7eb6ff">设置页面</a> 导出 RefreshToken</li>
                </ol>
            </div>
            <div style="background:#1e2228; border-radius:6px; padding:12px; margin-bottom:12px">
                <div style="color:#7eb6ff; font-weight:600; margin-bottom:8px">方式二：pxder（Node.js）</div>
                <ol style="margin-left:18px; color:#a0a4ab">
                    <li>安装 Node.js 16+，执行 <code style="background:#2f343c; padding:2px 6px; border-radius:3px; font-size:12px">npm i -g pxder</code></li>
                    <li>如需代理：<code style="background:#2f343c; padding:2px 6px; border-radius:3px; font-size:12px">pxder --setting</code> → 选择 5 设置代理</li>
                    <li>执行 <code style="background:#2f343c; padding:2px 6px; border-radius:3px; font-size:12px">pxder --login</code> 完成登录</li>
                    <li>执行 <code style="background:#2f343c; padding:2px 6px; border-radius:3px; font-size:12px">pxder --export-token</code> 导出 Token</li>
                </ol>
            </div>
            <div style="background:#1e2228; border-radius:6px; padding:12px; margin-bottom:12px">
                <div style="color:#7eb6ff; font-weight:600; margin-bottom:8px">方式三：PixEz（Android/iOS）</div>
                <ol style="margin-left:18px; color:#a0a4ab">
                    <li>从 <a href="https://github.com/Notsfsssf/pixez-flutter" target="_blank" style="color:#7eb6ff">GitHub</a> 下载安装</li>
                    <li>登录后进入 <b>更多 → 账户信息 → Token export</b> 导出</li>
                </ol>
            </div>
            <p style="color:#f59e0b; font-size:12px; margin-top:12px">⚠️ RefreshToken 时效较长，登录一次保存好即可长期使用。如果无法直连 Pixiv，请先在设置中配置代理。</p>
            <p style="color:#808590; font-size:12px; margin-top:8px">原始教程：<a href="https://www.nanoka.top/posts/e78ef86/" target="_blank" style="color:#7eb6ff">https://www.nanoka.top/posts/e78ef86/</a></p>
        `;
    } else {
        el.innerHTML = `
            <p style="margin-bottom:12px">Pixiv no longer supports username/password login. You need a RefreshToken. Choose one of the following methods:</p>
            <div style="background:#1e2228; border-radius:6px; padding:12px; margin-bottom:12px">
                <div style="color:#7eb6ff; font-weight:600; margin-bottom:8px">Method 1: Pixiv-Viewer (recommended)</div>
                <ol style="margin-left:18px; color:#a0a4ab">
                    <li>Install <a href="https://einaregilsson.com/redirector/" target="_blank" style="color:#7eb6ff">Redirector</a> and <a href="https://www.tampermonkey.net/index.php" target="_blank" style="color:#7eb6ff">Tampermonkey</a></li>
                    <li>Import redirect rule: <code style="background:#2f343c; padding:2px 6px; border-radius:3px; font-size:12px">https://pixiv.pictures/helper/Redirector.json</code></li>
                    <li>Install the <a href="https://fastly.jsdelivr.net/gh/asadahimeka/pixiv-viewer@master/public/helper/helper.user.js" target="_blank" style="color:#7eb6ff">login helper userscript</a></li>
                    <li>Visit <a href="https://pixiv.pictures/account/login" target="_blank" style="color:#7eb6ff">pixiv.pictures/account/login</a>, choose App API (OAuth)</li>
                    <li>Export the token from <a href="https://pixiv.pictures/setting/others" target="_blank" style="color:#7eb6ff">Settings</a></li>
                </ol>
            </div>
            <div style="background:#1e2228; border-radius:6px; padding:12px; margin-bottom:12px">
                <div style="color:#7eb6ff; font-weight:600; margin-bottom:8px">Method 2: pxder (Node.js)</div>
                <ol style="margin-left:18px; color:#a0a4ab">
                    <li>Install Node.js 16+, run <code style="background:#2f343c; padding:2px 6px; border-radius:3px; font-size:12px">npm i -g pxder</code></li>
                    <li>Proxy (if needed): <code style="background:#2f343c; padding:2px 6px; border-radius:3px; font-size:12px">pxder --setting</code> → option 5</li>
                    <li>Run <code style="background:#2f343c; padding:2px 6px; border-radius:3px; font-size:12px">pxder --login</code></li>
                    <li>Run <code style="background:#2f343c; padding:2px 6px; border-radius:3px; font-size:12px">pxder --export-token</code></li>
                </ol>
            </div>
            <div style="background:#1e2228; border-radius:6px; padding:12px; margin-bottom:12px">
                <div style="color:#7eb6ff; font-weight:600; margin-bottom:8px">Method 3: PixEz (mobile)</div>
                <ol style="margin-left:18px; color:#a0a4ab">
                    <li>Download from <a href="https://github.com/Notsfsssf/pixez-flutter" target="_blank" style="color:#7eb6ff">GitHub</a></li>
                    <li>More → Account → Token export</li>
                </ol>
            </div>
            <p style="color:#f59e0b; font-size:12px; margin-top:12px">⚠️ RefreshToken is long-lived. Save it once after login. If you cannot reach Pixiv directly, configure a proxy first.</p>
            <p style="color:#808590; font-size:12px; margin-top:8px">Original guide: <a href="https://www.nanoka.top/posts/e78ef86/" target="_blank" style="color:#7eb6ff">https://www.nanoka.top/posts/e78ef86/</a></p>
        `;
    }
}

// ============ Queue status ============
function updateQueueStatus(payload) {
    const q = payload.queue || 0;
    const f = payload.failed || 0;
    const p = payload.processed || 0;
    const running = payload.running || false;
    const stopping = payload.stopping || false;
    const mode = payload.mode || "normal";
    const workers = payload.workers || 1;

    lastQueueState = { queue: q, failed: f, processed: p, running, stopping };

    // Float ball
    const ball = document.getElementById("float-ball");
    const selCount = getSelectionCount();
    if (selCount > 0) {
        ball.classList.add("show");
        document.getElementById("ball-count").textContent = selCount;
    } else {
        ball.classList.remove("show");
    }

    // Download tab
    const total = q + p;
    const pct = total > 0 ? (p / total) * 100 : 0;
    document.getElementById("progress-fill").style.width = pct + "%";
    document.getElementById("progress-text").textContent = `${p} / ${total}`;
    document.getElementById("dl-pending").textContent = q;
    document.getElementById("dl-processed").textContent = p;
    document.getElementById("dl-failed").textContent = f;
    document.getElementById("dl-workers").textContent = workers;
    updateDownloadStatusText();

    // Download controls
    const presetSel = document.getElementById("dl-preset");
    if (presetSel) presetSel.value = mode;
    const threadsInput = document.getElementById("dl-threads");
    if (threadsInput) {
        threadsInput.value = workers;
        threadsInput.disabled = mode === "normal";
    }

    const btnStop = document.getElementById("btn-stop");
    if (btnStop) {
        btnStop.disabled = !running;
        btnStop.textContent = stopping ? t("btn_stopping") : t("btn_stop");
    }

    // Add-queue button disabled while running? Actually allow (they just add to queue)
    document.querySelectorAll(".add-queue-btn").forEach((btn) => {
        if (btn.id === "bookmark-add-btn") {
            btn.disabled = parsedBookmarkUrls.length === 0;
        }
    });

    updateSelectionCount();
}

function updateDownloadStatusText() {
    const el = document.getElementById("dl-status");
    if (!el) return;
    if (lastQueueState.stopping) el.textContent = t("btn_stopping");
    else if (lastQueueState.running) el.textContent = t("dl_running");
    else if (lastQueueState.queue > 0) el.textContent = t("dl_idle");
    else el.textContent = t("dl_idle");
}

// ============ Nav ============
document.querySelectorAll("nav button").forEach((btn) => {
    btn.onclick = () => {
        document
            .querySelectorAll("nav button")
            .forEach((b) => b.classList.remove("active"));
        document
            .querySelectorAll(".tab")
            .forEach((t) => t.classList.remove("active"));
        btn.classList.add("active");
        document
            .getElementById("tab-" + btn.dataset.tab)
            .classList.add("active");
        updateSelectionCount();
    };
});

// ============ Manual / Bookmark ============
function addSingleUrl() {
    const url = document.getElementById("manual-url").value.trim();
    if (!url) return toast(t("toast_need_url"), "error");
    send({ cmd: "add_urls", urls: [url] });
    document.getElementById("manual-url").value = "";
    closeAddTaskModal();
}

function addBatchUrls() {
    const text = document.getElementById("manual-batch").value.trim();
    if (!text) return toast(t("toast_need_urls"), "error");
    const urls = text
        .split("\n")
        .map((s) => s.trim())
        .filter((s) => s);
    send({ cmd: "add_urls", urls });
    document.getElementById("manual-batch").value = "";
    closeAddTaskModal();
}

function parseBookmark() {
    const fi = document.getElementById("bookmark-file");
    if (!fi.files.length) return toast(t("toast_select_file"), "error");
    const reader = new FileReader();
    reader.onload = (e) =>
        send({ cmd: "parse_bookmark", html: e.target.result });
    reader.readAsText(fi.files[0], "utf-8");
}

function renderBookmarkPreview(urls) {
    parsedBookmarkUrls = urls;
    document.getElementById("bookmark-preview").innerHTML = urls
        .map(
            (u) =>
                `<div style="padding:4px 0; border-bottom:1px solid #2f343c">${escapeHtml(u)}</div>`,
        )
        .join("");
    const btn = document.getElementById("bookmark-add-btn");
    btn.disabled = urls.length === 0;
    toast(t("toast_parsed", urls.length), "success");
}

function addBookmarkUrls() {
    if (!parsedBookmarkUrls.length) return;
    send({ cmd: "add_urls", urls: parsedBookmarkUrls });
    closeAddTaskModal();
}

// ============ Sorting ============
const WORK_COLUMNS = [
    { key: "id", get: "th_pid", numeric: true },
    { key: "title", get: "th_title", numeric: false },
    { key: "page_count", get: "th_pages", numeric: true },
    { key: "author", get: "th_author", numeric: false },
    { key: "views", get: "th_views", numeric: true },
    { key: "bookmarks", get: "th_bookmarks", numeric: true },
    { key: "tags", get: "th_tags", numeric: false },
    { key: "date", get: "th_date", numeric: false },
];

const TABLE_COLUMNS = {
    "ranking-list": WORK_COLUMNS,
    "search-list": WORK_COLUMNS,
    "recommend-list": WORK_COLUMNS,
    "follow-list": WORK_COLUMNS,
    "user-detail-list": [
        { key: "id", get: "th_pid", numeric: true },
        { key: "title", get: "th_title", numeric: false },
        { key: "page_count", get: "th_pages", numeric: true },
        { key: "views", get: "th_views", numeric: true },
        { key: "bookmarks", get: "th_bookmarks", numeric: true },
        { key: "tags", get: "th_tags", numeric: false },
        { key: "date", get: "th_date", numeric: false },
    ],
};

const sortState = {
    "ranking-list": { col: null, asc: true },
    "search-list": { col: null, asc: true },
    "recommend-list": { col: null, asc: true },
    "follow-list": { col: null, asc: true },
    "user-detail-list": { col: null, asc: true },
};

function getSortValue(item, key) {
    switch (key) {
        case "id":
            return item.id || 0;
        case "title":
            return (item.title || "").toLowerCase();
        case "page_count":
            return item.page_count || 1;
        case "author":
            return (item.author || "").toLowerCase();
        case "views":
            return item.views || 0;
        case "bookmarks":
            return item.bookmarks || 0;
        case "tags":
            return (item.tags || []).join(",").toLowerCase();
        case "date":
            return item.date || "";
        default:
            return "";
    }
}

function sortTable(containerId, colKey) {
    const state = sortState[containerId];
    if (state.col === colKey) state.asc = !state.asc;
    else {
        state.col = colKey;
        state.asc = true;
    }
    applySort(containerId);
}

function applySort(containerId) {
    const state = sortState[containerId];
    let items;
    if (containerId === "ranking-list") items = rankingItems;
    else if (containerId === "search-list") items = searchItems;
    else if (containerId === "recommend-list") items = recommendItems;
    else if (containerId === "follow-list") items = followItems;
    else if (containerId === "user-detail-list") items = userDetailItems;
    else return;
    if (!items || !items.length) return;

    if (state.col) {
        const colDef = TABLE_COLUMNS[containerId].find(
            (c) => c.key === state.col,
        );
        const numeric = colDef ? colDef.numeric : false;
        items.sort((a, b) => {
            let va = getSortValue(a, state.col);
            let vb = getSortValue(b, state.col);
            if (numeric) {
                const diff = (va || 0) - (vb || 0);
                return state.asc ? diff : -diff;
            } else {
                va = String(va);
                vb = String(vb);
                if (va < vb) return state.asc ? -1 : 1;
                if (va > vb) return state.asc ? 1 : -1;
                return 0;
            }
        });
    }
    renderTable(containerId, items);
}

// ============ Render table ============
function renderTable(containerId, items) {
    const container = document.getElementById(containerId);
    if (!items.length) {
        container.innerHTML = `<div style="padding:20px; text-align:center; color:#666">${t("no_result")}</div>`;
        updateSelectionCount();
        return;
    }
    const selectedPids = new Set();
    container.querySelectorAll("tr.selected").forEach((tr) => {
        const firstTd = tr.querySelector("td");
        if (firstTd) selectedPids.add(firstTd.textContent.trim());
    });
    const state = sortState[containerId];
    const cols = TABLE_COLUMNS[containerId];

    const thead = cols
        .map((c) => {
            const sortable = c.sortable !== false;
            const indicator =
                state.col === c.key ? (state.asc ? " ▲" : " ▼") : "";
            const cls = sortable ? "sortable-th" : "";
            const align = c.numeric ? ' style="text-align:right"' : "";
            const onclick = sortable
                ? ` onclick="sortTable('${containerId}', '${c.key}')"`
                : "";
            return `<th${align} class="${cls}"${onclick}>${t(c.get)}${indicator}</th>`;
        })
        .join("");

    const rows = items
        .map((it, idx) => {
            const isSelected = selectedPids.has(String(it.id));
            let badges = "";
            if (it.is_new) badges += '<span class="badge new">NEW</span>';
            if (it.ai_generated) badges += '<span class="badge ai">AI</span>';
            if (it.restriction) {
                const cls = it.restriction.toLowerCase().replace("-", "");
                badges += `<span class="badge ${cls}">${it.restriction}</span>`;
            }
            const tagsHtml = (it.tags || [])
                .slice(0, 5)
                .map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`)
                .join("");
            const titleHtml = `<a href="https://www.pixiv.net/artworks/${it.id}"
            target="_blank" rel="noopener"
            onclick="event.stopPropagation()"
            style="color:#7eb6ff; text-decoration:none; border-bottom:1px dashed #7eb6ff;"
            title="${t("th_title_link")}">${escapeHtml(truncate(it.title, 40))}</a>${badges}`;

            let tds = "";
            for (const c of cols) {
                switch (c.key) {
                    case "id":
                        tds += `<td>${it.id}</td>`;
                        break;
                    case "title":
                        tds += `<td>${titleHtml}</td>`;
                        break;
                    case "page_count":
                        tds += `<td style="text-align:right">${it.page_count || 1}</td>`;
                        break;
                    case "author":
                        if (it.author_id) {
                            tds += `<td><a href="#" onclick="event.preventDefault(); event.stopPropagation(); openUserDetail(${it.author_id}); return false;" style="color:#7eb6ff; text-decoration:none; border-bottom:1px dashed #7eb6ff;" title="${t("th_author_link")}">${escapeHtml(it.author)}</a></td>`;
                        } else {
                            tds += `<td>${escapeHtml(it.author)}</td>`;
                        }
                        break;
                    case "views":
                        tds += `<td style="text-align:right">${formatNum(it.views)}</td>`;
                        break;
                    case "bookmarks":
                        tds += `<td style="text-align:right">${formatNum(it.bookmarks)}</td>`;
                        break;
                    case "tags":
                        tds += `<td>${tagsHtml}</td>`;
                        break;
                    case "date":
                        tds += `<td>${it.date || ""}</td>`;
                        break;
                }
            }
            return `<tr data-idx="${idx}" class="${isSelected ? "selected" : ""}" onclick="toggleRow(this)">${tds}</tr>`;
        })
        .join("");
    container.innerHTML = `<table><thead><tr>${thead}</tr></thead><tbody>${rows}</tbody></table>`;
    updateSelectionCount();
}

function toggleRow(tr) {
    tr.classList.toggle("selected");
    updateSelectionCount();
}

function getSelectedUrls(containerId, items) {
    const urls = [];
    document.querySelectorAll(`#${containerId} tr.selected`).forEach((tr) => {
        const it = items[parseInt(tr.dataset.idx)];
        if (it) urls.push(`https://www.pixiv.net/artworks/${it.id}`);
    });
    return urls;
}

function formatNum(n) {
    return (n || 0).toLocaleString();
}
function truncate(s, n) {
    return !s ? "" : s.length > n ? s.slice(0, n) + "..." : s;
}
function escapeHtml(s) {
    if (!s) return "";
    return String(s).replace(
        /[&<>"']/g,
        (c) =>
            ({
                "&": "&amp;",
                "<": "&lt;",
                ">": "&gt;",
                '"': "&quot;",
                "'": "&#39;",
            })[c],
    );
}

// ============ Selection ============
function getActiveTab() {
    const active = document.querySelector("nav button.active");
    return active ? active.dataset.tab : null;
}

function getSelectionInfo() {
    const tab = getActiveTab();
    if (tab === "ranking")
        return { containerId: "ranking-list", items: rankingItems };
    if (tab === "search")
        return { containerId: "search-list", items: searchItems };
    if (tab === "recommend")
        return { containerId: "recommend-list", items: recommendItems };
    if (tab === "follow")
        return { containerId: "follow-list", items: followItems };
    if (tab === "user-detail")
        return { containerId: "user-detail-list", items: userDetailItems };
    return null;
}

function getSelectionCount() {
    const info = getSelectionInfo();
    if (!info) return 0;
    const container = document.getElementById(info.containerId);
    if (!container) return 0;
    return container.querySelectorAll("tr.selected").length;
}

function updateSelectionCount() {
    const count = getSelectionCount();
    // Float ball update
    const ball = document.getElementById("float-ball");
    if (count > 0) {
        ball.classList.add("show");
        document.getElementById("ball-count").textContent = count;
    } else {
        ball.classList.remove("show");
    }
}

function onFloatBallClick() {
    const info = getSelectionInfo();
    if (!info) return;
    const urls = getSelectedUrls(info.containerId, info.items);
    if (!urls.length) return;
    send({ cmd: "add_urls", urls });
    document
        .querySelectorAll(`#${info.containerId} tr.selected`)
        .forEach((tr) => tr.classList.remove("selected"));
    updateSelectionCount();
    toast(t("toast_selected_queued", urls.length), "success");
}

// ============ Ranking ============
function fetchRanking() {
    const mode = document.getElementById("ranking-mode").value;
    document.getElementById("ranking-list").innerHTML =
        `<div class="loading"><div class="spinner"></div>${t("loading_ranking")}</div>`;
    document.getElementById("btn-fetch-ranking").disabled = true;
    document.getElementById("ranking-status").textContent = t(
        "status_requesting",
        `${mode} / 480`,
    );
    send({ cmd: "ranking", mode, limit: 480 });
}

function renderRankingResults(items, stats) {
    rankingItemsAll = items;
    filterSets["ranking-tag-cloud"].clear();
    document.getElementById("ranking-filter-status").textContent = "";
    rankingItems = items.slice();
    buildTagCloud("ranking-tag-cloud", items, "filterRankingByTags");
    renderTable("ranking-list", rankingItems);
    document.getElementById("btn-fetch-ranking").disabled = false;
    document.getElementById("ranking-status").textContent = t(
        "status_done_ranking",
        items.length,
    );
    const newCount = items.filter((x) => x.is_new).length;
    toast(
        `${t("toast_ranking_done", items.length)} · NEW ${newCount}`,
        "success",
    );
}

function filterRankingByTags() {
    const chipTags = [...filterSets["ranking-tag-cloud"]].map((x) =>
        x.toLowerCase(),
    );
    if (chipTags.length === 0) {
        rankingItems = rankingItemsAll.slice();
    } else {
        rankingItems = rankingItemsAll.filter((it) => {
            const tagStr = (it.tags || []).join(" ").toLowerCase();
            return chipTags.every((k) => tagStr.includes(k));
        });
    }
    renderTable("ranking-list", rankingItems);
    const total = rankingItemsAll.length;
    const shown = rankingItems.length;
    document.getElementById("ranking-filter-status").textContent =
        chipTags.length ? t("status_filter", shown, total) : "";
}

function clearRankingFilter() {
    filterSets["ranking-tag-cloud"].clear();
    document
        .querySelectorAll("#ranking-tag-cloud .tag-chip")
        .forEach((el) => el.classList.remove("active"));
    filterRankingByTags();
}

// ============ Search ============
function doSearch() {
    const tag = document.getElementById("search-tag").value.trim();
    if (!tag) return toast(t("toast_need_tag"), "error");
    const sort = document.getElementById("search-sort").value;
    const target = document.getElementById("search-target").value;
    const durationRaw = document.getElementById("search-duration").value;
    const startPage =
        parseInt(document.getElementById("search-page").value) || 1;
    const pages = parseInt(document.getElementById("search-pages").value) || 1;
    const fIllust = document.getElementById("search-type-illust").checked;
    const fManga = document.getElementById("search-type-manga").checked;
    if (!fIllust && !fManga) {
        return toast(t("toast_need_type"), "error");
    }

    let duration = undefined;
    let start_date = undefined;
    let end_date = undefined;

    if (durationRaw === "custom") {
        start_date = document.getElementById("search-start-date").value || "";
        end_date = document.getElementById("search-end-date").value || "";
        if (!start_date || !end_date) {
            return toast(t("toast_need_dates"), "error");
        }
        if (start_date > end_date) {
            return toast(t("toast_date_order"), "error");
        }
    } else if (durationRaw) {
        duration = durationRaw;
    }

    document.getElementById("search-list").innerHTML =
        `<div class="loading"><div class="spinner"></div>${t("loading_search")}</div>`;
    document.getElementById("btn-search").disabled = true;
    document.getElementById("search-status").textContent = t(
        "status_requesting",
        `${tag} | ${startPage}→${startPage + pages - 1}`,
    );
    send({
        cmd: "search",
        tag,
        sort,
        target,
        duration: duration || "",
        start_date: start_date || "",
        end_date: end_date || "",
        start_page: startPage,
        pages,
        filters: { illust: fIllust, manga: fManga },
    });
}

function renderSearchResults(items, startPage, pages) {
    searchItemsRaw = items;
    applySearchBookmarkFilter(startPage, pages);
}

function applySearchBookmarkFilter(startPage, pages) {
    const bmMin = parseInt(document.getElementById("search-bm-min").value) || 0;
    const bmMax = parseInt(document.getElementById("search-bm-max").value) || 0;

    let filtered = searchItemsRaw;
    if (bmMin > 0 || bmMax > 0) {
        filtered = searchItemsRaw.filter((it) => {
            const bm = it.bookmarks || 0;
            if (bmMin > 0 && bm < bmMin) return false;
            if (bmMax > 0 && bm > bmMax) return false;
            return true;
        });
    }

    searchItems = filtered;
    renderTable("search-list", filtered);
    document.getElementById("btn-search").disabled = false;

    if (startPage !== undefined && pages !== undefined) {
        const suffix =
            filtered.length !== searchItemsRaw.length
                ? ` (filtered ${filtered.length}/${searchItemsRaw.length})`
                : "";
        document.getElementById("search-status").textContent =
            t("status_done_search", startPage, pages, filtered.length) + suffix;
        toast(t("toast_search_done", filtered.length), "success");
    } else {
        const total = searchItemsRaw.length;
        const shown = filtered.length;
        document.getElementById("search-status").textContent =
            bmMin > 0 || bmMax > 0
                ? t("status_filter", shown, total)
                : t("status_done", total);
    }
}

// ============ Tag cloud ============
function buildTagCloud(containerId, items, callbackName, field = "tags") {
    const container = document.getElementById(containerId);
    if (!container) return;
    const freq = {};
    for (const it of items) {
        if (field === "author") {
            const a = it.author || "";
            if (a) freq[a] = (freq[a] || 0) + 1;
        } else {
            for (const tag of it.tags || []) freq[tag] = (freq[tag] || 0) + 1;
        }
    }
    const sorted = Object.entries(freq)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 50);
    container.innerHTML = sorted
        .map(
            ([tag, count]) =>
                `<span class="tag-chip" data-tag="${escapeHtml(tag)}"
            onclick="tagChipClick(this, '${containerId}', '${callbackName}')">
            ${escapeHtml(tag)}<span class="count">${count}</span>
        </span>`,
        )
        .join("");
}

function tagChipClick(el, cloudId, callbackName) {
    const tag = el.dataset.tag;
    const set = filterSets[cloudId];
    if (!set) return;
    if (set.has(tag)) {
        set.delete(tag);
        el.classList.remove("active");
    } else {
        set.add(tag);
        el.classList.add("active");
    }
    if (callbackName === "filterRankingByTags") filterRankingByTags();
    else if (callbackName === "applyUserDetailFilter") applyUserDetailFilter();
    else if (callbackName === "applyFollowFilter") applyFollowFilter();
}

// ============ User search ============
function doUserSearch() {
    const word = document.getElementById("usearch-word").value.trim();
    if (!word) return toast(t("toast_need_keyword"), "error");
    const page = parseInt(document.getElementById("usearch-page").value) || 1;
    const offset = (page - 1) * 30;
    document.getElementById("usearch-list").innerHTML =
        `<div class="loading"><div class="spinner"></div>${t("loading_usearch")}</div>`;
    document.getElementById("btn-user-search").disabled = true;
    document.getElementById("usearch-status").textContent = t(
        "status_requesting",
        word,
    );
    send({ cmd: "search_users", word, offset });
}

function renderUserSearchResults(items) {
    userSearchItems = items;
    const container = document.getElementById("usearch-list");
    if (!items.length) {
        container.innerHTML = `<div style="padding:20px; text-align:center; color:#666">${t("no_result")}</div>`;
    } else {
        const rows = items
            .map(
                (u) => `
            <tr>
                <td>${u.id}</td>
                <td><a href="#" onclick="event.preventDefault(); openUserDetail(${u.id}); return false;"
                       style="color:#7eb6ff; text-decoration:none; border-bottom:1px dashed #7eb6ff;"
                       title="${t("th_user_detail_link")}">${escapeHtml(u.name)}</a></td>
                <td style="color:#808590">${escapeHtml(u.account)}</td>
                <td>${u.is_followed ? `<span style="color:#4ade80">${t("th_followed_yes")}</span>` : ""}</td>
            </tr>`,
            )
            .join("");
        container.innerHTML = `<table>
            <thead><tr><th>${t("th_uid")}</th><th>${t("th_name")}</th><th>${t("th_account")}</th><th>${t("th_followed")}</th></tr></thead>
            <tbody>${rows}</tbody>
        </table>`;
    }
    document.getElementById("btn-user-search").disabled = false;
    document.getElementById("usearch-status").textContent = t(
        "status_done",
        items.length,
    );
    toast(t("toast_user_search_done", items.length), "success");
}

// ============ User detail ============
function openUserDetail(uid) {
    document
        .querySelectorAll("nav button")
        .forEach((b) => b.classList.remove("active"));
    document
        .querySelectorAll(".tab")
        .forEach((t) => t.classList.remove("active"));
    const navBtn = document.querySelector('nav button[data-tab="user-detail"]');
    if (navBtn) navBtn.classList.add("active");
    document.getElementById("tab-user-detail").classList.add("active");
    document.getElementById("udetail-uid").value = uid;
    resetUserDetailView();
    document.getElementById("udetail-header").innerHTML =
        `<div class="loading"><div class="spinner"></div>${t("loading_user")}</div>`;
    document.getElementById("udetail-status").textContent = `UID: ${uid}`;
    document.getElementById("btn-load-udetail").disabled = true;
    send({ cmd: "user_detail", uid });
}

function resetUserDetailView() {
    userDetailUid = null;
    userDetailItems = [];
    userDetailAllItems = [];
    const cloud = document.getElementById("udetail-tag-cloud");
    if (cloud) cloud.innerHTML = "";
    filterSets["udetail-tag-cloud"] = new Set();
    const fi = document.getElementById("udetail-filter");
    if (fi) fi.value = "";
    document.getElementById("udetail-filter-status").textContent = "";
    document.getElementById("user-detail-list").innerHTML = "";
}

function loadUserDetailFromInput() {
    const v = document.getElementById("udetail-uid").value.trim();
    if (!v) return toast(t("toast_need_uid"), "error");
    const uid = parseInt(v);
    if (!uid) return toast(t("toast_invalid_uid"), "error");
    openUserDetail(uid);
}

function handleUserDetailPhase(msg) {
    if (msg.phase === "detail") {
        renderUserHeaderOnly(msg.user);
    } else if (msg.phase === "illusts") {
        document.getElementById("udetail-status").textContent = t(
            "status_loading_user_illusts",
            msg.page,
            msg.count,
        );
        document.getElementById("user-detail-list").innerHTML =
            `<div class="loading"><div class="spinner"></div>${t("loading_user_illusts", msg.page)}</div>`;
    }
}

function buildUserCardHtml(user) {
    const avatarProxy = user.avatar
        ? `/proxy_image?url=${encodeURIComponent(user.avatar)}`
        : "";
    const avatarHtml = avatarProxy
        ? `<img class="user-avatar" src="${avatarProxy}" alt="avatar"
                onerror="this.style.background='#3a3f48'; this.removeAttribute('src');">`
        : '<div class="user-avatar"></div>';
    const officialUrl = `https://www.pixiv.net/users/${user.id}`;
    const metaParts = [];
    if (user.region)
        metaParts.push(`${t("meta_region")} ${escapeHtml(user.region)}`);
    if (user.total_follow_users)
        metaParts.push(
            `${t("meta_followers")} ${formatNum(user.total_follow_users)}`,
        );
    if (user.total_illusts)
        metaParts.push(`${t("meta_illusts")} ${user.total_illusts}`);
    if (user.total_novels)
        metaParts.push(`${t("meta_novels")} ${user.total_novels}`);
    if (user.total_manga)
        metaParts.push(`${t("meta_manga")} ${user.total_manga}`);
    if (user.is_accept_request === true) {
        metaParts.push(
            `<span style="color:#4ade80">${t("meta_accept_request_yes")}</span>`,
        );
    } else if (user.is_accept_request === false) {
        metaParts.push(
            `<span style="color:#808590">${t("meta_accept_request_no")}</span>`,
        );
    }
    const commentHtml = user.comment
        ? `<div class="user-comment">${escapeHtml(user.comment)}</div>`
        : "";
    return `
        <div class="user-card">
            ${avatarHtml}
            <div class="user-info">
                <div>
                    <a class="user-name" href="${officialUrl}" target="_blank" rel="noopener"
                       title="${t("th_user_name_link")}">${escapeHtml(user.name)}</a>
                    <span class="user-account">@${escapeHtml(user.account)} (UID: ${user.id})</span>
                    ${user.is_followed ? `<span style="color:#4ade80; margin-left:8px; font-size:12px">${t("meta_following")}</span>` : ""}
                </div>
                <div class="user-meta">${metaParts.join("")}</div>
                ${commentHtml}
            </div>
        </div>`;
}

function renderUserHeaderOnly(user) {
    document.getElementById("udetail-header").innerHTML =
        buildUserCardHtml(user);
    document.getElementById("btn-load-udetail").disabled = false;
}

function renderUserDetail(user, items) {
    userDetailUid = user.id;
    renderUserHeaderOnly(user);
    document.getElementById("udetail-uid").value = user.id;
    document.getElementById("udetail-status").textContent = t(
        "status_done",
        `${user.name} (${items.length})`,
    );
    userDetailAllItems = items.slice();
    userDetailItems = items.slice();
    buildTagCloud("udetail-tag-cloud", items, "applyUserDetailFilter");
    renderTable("user-detail-list", userDetailItems);
    toast(t("toast_user_detail_done", items.length), "success");
}

function applyUserDetailFilter() {
    const chipTags = [...filterSets["udetail-tag-cloud"]].map((x) =>
        x.toLowerCase(),
    );
    if (chipTags.length === 0) {
        userDetailItems = userDetailAllItems.slice();
    } else {
        userDetailItems = userDetailAllItems.filter((it) => {
            const tagStr = (it.tags || []).join(" ").toLowerCase();
            return chipTags.every((k) => tagStr.includes(k));
        });
    }
    renderTable("user-detail-list", userDetailItems);
    const total = userDetailAllItems.length;
    const shown = userDetailItems.length;
    document.getElementById("udetail-filter-status").textContent =
        chipTags.length ? t("status_filter", shown, total) : "";
}

function clearUserDetailFilter() {
    filterSets["udetail-tag-cloud"].clear();
    document
        .querySelectorAll("#udetail-tag-cloud .tag-chip")
        .forEach((el) => el.classList.remove("active"));
    applyUserDetailFilter();
}

function clearUserDetailFilter() {
    document.getElementById("udetail-filter").value = "";
    filterSets["udetail-tag-cloud"].clear();
    document
        .querySelectorAll("#udetail-tag-cloud .tag-chip")
        .forEach((el) => el.classList.remove("active"));
    applyUserDetailFilter();
}

// ============ Recommend ============
function doRecommend(mode) {
    let pid = null;
    if (mode === "work") {
        const v = document.getElementById("recommend-pid").value.trim();
        if (!v) return toast(t("toast_need_pid"), "error");
        pid = parseInt(v);
        if (!pid || pid <= 0) return toast(t("toast_invalid_pid"), "error");
    }
    document.getElementById("recommend-list").innerHTML =
        `<div class="loading"><div class="spinner"></div>${t("loading_recommend")}</div>`;
    document.getElementById("recommend-status").textContent = t(
        "status_requesting",
        mode,
    );
    document.getElementById("btn-rec-auto").disabled = true;
    const cmd = { cmd: "recommend", mode, limit: 120 };
    if (pid) cmd.pid = pid;
    send(cmd);
}

function renderRecommendResults(items, mode) {
    recommendItems = items;
    renderTable("recommend-list", items);
    document.getElementById("btn-rec-auto").disabled = false;
    document.getElementById("recommend-status").textContent = t(
        "status_done_recommend",
        items.length,
        mode,
    );
    toast(t("toast_recommend_done", items.length), "success");
}

function openAdvancedRecommend() {
    document.getElementById("advanced-rec-modal").classList.add("show");
}
function closeAdvancedRecommend() {
    document.getElementById("advanced-rec-modal").classList.remove("show");
}

function submitAdvancedRecommend() {
    const seedsRaw = document.getElementById("adv-seeds").value.trim();
    const viewedRaw = document.getElementById("adv-viewed").value.trim();
    const includeRanking = document.getElementById("adv-ranking").checked;
    const includePrivacy = document.getElementById("adv-privacy").checked;
    const limit = parseInt(document.getElementById("adv-limit").value) || 60;

    const seedList = seedsRaw
        ? seedsRaw
              .split(",")
              .map((s) => s.trim())
              .filter((s) => s)
        : [];
    for (const s of seedList)
        if (!/^\d+$/.test(s))
            return toast(t("toast_adv_seeds_invalid", s), "error");
    if (seedList.length > 30) return toast(t("toast_adv_seeds_max"), "error");
    const viewedList = viewedRaw
        ? viewedRaw
              .split(",")
              .map((s) => s.trim())
              .filter((s) => s)
        : [];
    for (const v of viewedList)
        if (!/^\d+$/.test(v))
            return toast(t("toast_adv_viewed_invalid", v), "error");
    if (viewedList.length > 30)
        return toast(t("toast_adv_viewed_max"), "error");
    if (limit < 1 || limit > 120) return toast(t("toast_adv_limit"), "error");

    closeAdvancedRecommend();
    const params = {};
    if (seedList.length) params.bookmark_illust_ids = seedList;
    if (viewedList.length) params.viewed = viewedList;
    if (includeRanking) params.include_ranking_illusts = true;
    if (includePrivacy) params.include_privacy_policy = true;

    document.getElementById("recommend-list").innerHTML =
        `<div class="loading"><div class="spinner"></div>${t("loading_adv_recommend")}</div>`;
    document.getElementById("recommend-status").textContent = t(
        "status_requesting",
        "advanced",
    );
    document.getElementById("btn-rec-auto").disabled = true;
    send({ cmd: "recommend", mode: "advanced", limit, params });
}

// ============ Follow ============
function loadFollowNew(offset) {
    const restrict = document.getElementById("follow-restrict").value;
    document.getElementById("follow-list").innerHTML =
        `<div class="loading"><div class="spinner"></div>${t("loading_follow")}</div>`;
    document.getElementById("btn-load-follow").disabled = true;
    document.getElementById("follow-status").textContent = t(
        "status_requesting",
        `offset=${offset}`,
    );
    send({ cmd: "follow_new", offset, restrict });
}

function renderFollowResults(items, offset, hasMore, batchSize) {
    followItemsAll = items;
    followCurrentOffset = offset;
    followBatchSize = batchSize || 300;
    followItems = items.slice();
    filterSets["follow-tag-cloud"].clear();
    filterSets["follow-author-cloud"].clear();
    document.getElementById("follow-filter-status").textContent = "";
    buildTagCloud("follow-tag-cloud", items, "applyFollowFilter", "tags");
    buildTagCloud("follow-author-cloud", items, "applyFollowFilter", "author");
    renderTable("follow-list", followItems);
    document.getElementById("btn-load-follow").disabled = false;
    const page = Math.floor(offset / followBatchSize) + 1;
    followPage = page;
    document.getElementById("follow-status").textContent = t(
        "status_done",
        items.length,
    );
    document.getElementById("follow-page-info").textContent = t(
        "page_label",
        page,
    );
    toast(t("toast_follow_done", items.length), "success");
}

function applyFollowFilter() {
    const chipTags = [...filterSets["follow-tag-cloud"]].map((x) =>
        x.toLowerCase(),
    );
    const chipAuthors = [...filterSets["follow-author-cloud"]];
    let filtered = followItemsAll.slice();
    if (chipTags.length > 0) {
        filtered = filtered.filter((it) => {
            const tagStr = (it.tags || []).join(" ").toLowerCase();
            return chipTags.every((k) => tagStr.includes(k));
        });
    }
    if (chipAuthors.length > 0) {
        filtered = filtered.filter((it) =>
            chipAuthors.includes(it.author || ""),
        );
    }
    followItems = filtered;
    renderTable("follow-list", followItems);
    const total = followItemsAll.length;
    const shown = followItems.length;
    document.getElementById("follow-filter-status").textContent =
        chipTags.length || chipAuthors.length
            ? t("status_filter", shown, total)
            : "";
}

function clearFollowFilter() {
    document.getElementById("follow-filter").value = "";
    filterSets["follow-tag-cloud"].clear();
    filterSets["follow-author-cloud"].clear();
    document
        .querySelectorAll(
            "#follow-tag-cloud .tag-chip, #follow-author-cloud .tag-chip",
        )
        .forEach((el) => el.classList.remove("active"));
    applyFollowFilter();
}

function followPrevPage() {
    if (followCurrentOffset <= 0) return toast(t("toast_first_page"), "error");
    loadFollowNew(Math.max(0, followCurrentOffset - followBatchSize));
}
function followNextPage() {
    loadFollowNew(followCurrentOffset + followBatchSize);
}

// ============ Queue ============
function startQueue() {
    send({ cmd: "start_queue" });
}
function stopQueue() {
    send({ cmd: "stop_queue" });
}
function clearQueue() {
    if (confirm(t("toast_confirm_clear"))) send({ cmd: "clear_queue" });
}
function retryFailed() {
    if (confirm(t("toast_confirm_retry"))) send({ cmd: "retry_failed" });
}

// ============ Download controls ============
function onPresetChange() {
    const mode = document.getElementById("dl-preset").value;
    send({ cmd: "set_download_mode", mode });
    const threadsInput = document.getElementById("dl-threads");
    threadsInput.disabled = mode === "normal";
    if (mode === "normal") {
        threadsInput.value = 1;
    }
}

function onThreadsChange() {
    const v = Math.max(
        1,
        Math.min(8, parseInt(document.getElementById("dl-threads").value) || 1),
    );
    document.getElementById("dl-threads").value = v;
    // Also update config
    send({ cmd: "save_config", data: { parallel_workers: v } });
}

// ============ Config ============
const CONFIG_KEYS = [
    "refresh_token",
    "download_dir",
    "proxy",
    "language",
    "download_delay",
    "api_request_delay",
    "parallel_workers",
    "max_retries",
    "rate_limit_retry_delay",
    "max_results",
];

function fillConfig(cfg) {
    CONFIG_KEYS.forEach((k) => {
        const el = document.getElementById("cfg-" + k);
        if (el && cfg[k] !== undefined) el.value = cfg[k];
    });
    if (
        cfg.language &&
        (cfg.language === "zh-CN" || cfg.language === "en") &&
        cfg.language !== currentLang
    ) {
        currentLang = cfg.language;
        localStorage.setItem("nagato_lang", currentLang);
        applyI18n();
        renderTokenHelp();
    }
}

function saveConfig() {
    const data = {};
    CONFIG_KEYS.forEach((k) => {
        const el = document.getElementById("cfg-" + k);
        if (el)
            data[k] =
                el.type === "number" ? parseFloat(el.value) || 0 : el.value;
    });
    send({ cmd: "save_config", data });
    if (data.language === "zh-CN" || data.language === "en") {
        switchLanguage(data.language);
    }
}

function testLogin() {
    const rt = document.getElementById("cfg-refresh_token").value.trim();
    if (!rt) return toast(t("toast_need_token"), "error");
    send({ cmd: "login", refresh_token: rt });
}

function testLatency() {
    toast(t("toast_latency_testing"), "");
    send({ cmd: "test_latency" });
}

// ============ Token help modal ============
function showTokenHelp() {
    document.getElementById("token-help-modal").classList.add("show");
}
function closeTokenHelp() {
    document.getElementById("token-help-modal").classList.remove("show");
}
function toggleCloud(sectionId) {
    const el = document.getElementById(sectionId);
    if (el) el.classList.toggle("collapsed");
}
function openAddTaskModal() {
    const modal = document.getElementById("add-task-modal");
    if (modal) modal.classList.add("show");
    switchAddTaskTab("manual");
}

function closeAddTaskModal() {
    const modal = document.getElementById("add-task-modal");
    if (modal) modal.classList.remove("show");
    const preview = document.getElementById("bookmark-preview");
    if (preview) preview.innerHTML = "";
    parsedBookmarkUrls = [];
    const btn = document.getElementById("bookmark-add-btn");
    if (btn) btn.disabled = true;
}

function switchAddTaskTab(tab) {
    const tabs = document.querySelectorAll(".add-task-tab");
    tabs.forEach((el) => el.classList.remove("active"));
    document
        .querySelectorAll(".add-task-pane")
        .forEach((el) => el.classList.remove("active"));

    if (tab === "manual" && tabs[0]) tabs[0].classList.add("active");
    else if (tab === "bookmark" && tabs[1]) tabs[1].classList.add("active");

    const pane = document.getElementById("add-task-" + tab);
    if (pane) pane.classList.add("active");
}
function onSearchModeChange() {
    const mode = document.getElementById("search-mode").value;
    document.getElementById("search-pane-illust").style.display =
        mode === "illust" ? "" : "none";
    document.getElementById("search-pane-user").style.display =
        mode === "user" ? "" : "none";
}
function onDurationChange() {
    const v = document.getElementById("search-duration").value;
    const row = document.getElementById("search-custom-dates");
    if (v === "custom") {
        row.style.display = "";
    } else {
        row.style.display = "none";
    }
}
// ============ Boot ============
currentLang = detectLang();
applyI18n();
renderTokenHelp();
connect();

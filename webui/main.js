// NagatoPix main / 主逻辑
// Requires i18n.js loaded first / 需先加载 i18n.js

// ============ Global state / 全局状态 ============
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
    searchItemsRaw = [],
    userSearchItems = [];
let recommendItems = [],
    followItems = [],
    followItemsAll = [];
let userDetailItems = [],
    userDetailAllItems = [];
let userDetailUid = null;
let currentUserDetail = null;
let currentAccounts = [];
let currentAccountProfile = null;
let followCurrentOffset = 0;
let followBatchSize = 300;
let isConnected = false;
let queueItems = [];
let dlItemsExpanded = false;
let lastQueueState = {
    queue: 0,
    failed: 0,
    processed: 0,
    running: false,
    stopping: false,
    retryPass: 0,
    maxRetry: 3,
};
const lastCheckedIdx = {};

// Illust viewer state / 查看模态框状态
let ivState = {
    containerId: null,
    items: null,
    idx: -1,
    pages: [],
    pageIdx: 0,
};

const tableItemGetters = {
    "ranking-list": () => rankingItems,
    "search-list": () => searchItems,
    "recommend-list": () => recommendItems,
    "follow-list": () => followItems,
    "user-detail-list": () => userDetailItems,
    "account-bookmarks": () =>
        currentAccountProfile ? currentAccountProfile.bookmarks || [] : [],
};

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

// ============ Message handling ============
function handleMessage(msg) {
    switch (msg.type) {
        case "init":
            fillConfig(msg.config);
            updateQueueStatus(msg);
            if (msg.ui_state) restoreUiState(msg.ui_state);
            if (msg.config.theme) applyTheme(msg.config.theme);
            if (msg.items) {
                queueItems = msg.items;
                renderQueueItems();
            }
            break;

        case "queue_status":
            updateQueueStatus(msg);
            break;
        case "queue_saved":
            toast(t("toast_queue_saved"), "success");
            break;
        case "queue_items":
            queueItems = msg.items || [];
            renderQueueItems();
            break;

        case "search_result":
            renderSearchResults(msg.items, msg.start_page, msg.pages);
            break;
        case "search_progress":
            setSearchLoading(
                t("status_search_progress", msg.page, msg.current, msg.total),
            );
            break;

        case "ranking_result":
            renderRankingResults(msg.items, msg.stats);
            break;
        case "ranking_progress":
            setRankingLoading(msg.phase, msg.count);
            break;

        case "recommend_result":
            renderRecommendResults(msg.items, msg.mode);
            break;
        case "follow_progress":
            setFollowLoading(msg.count);
            break;
        case "follow_new_result":
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
        case "theme_set":
            applyTheme(msg.theme);
            break;
        case "ui_state_saved":
            break;
        case "items_added":
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

        case "follow_user_result":
            if (
                msg.success &&
                currentUserDetail &&
                currentUserDetail.id === msg.uid
            ) {
                currentUserDetail.is_followed = msg.action === "follow";
                renderUserHeaderOnly(currentUserDetail);
                toast(
                    msg.action === "follow"
                        ? t("toast_followed")
                        : t("toast_unfollowed"),
                    "success",
                );
            }
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

        // Account
        case "account_result":
            currentAccountProfile = msg.profile || {};
            renderAccount(msg.profile);
            break;
        case "account_list":
            currentAccounts = msg.accounts || [];
            renderAccountList(msg.accounts, msg.current_index);
            if (currentAccountProfile) renderAccount(currentAccountProfile);
            break;
        case "account_added":
            closeAddAccountModal();
            toast(t("account_added"), "success");
            loadAccount(true);
            break;
        case "account_switched":
            toast(t("account_switched"), "success");
            loadAccount(true);
            break;
        case "account_removed":
            toast(t("account_removed"), "success");
            loadAccount(true);
            break;
        case "phpsessid_updated":
            toast(t("toast_phpsessid_saved"), "success");
            send({ cmd: "list_accounts" });
            break;
        case "following_list":
            renderFollowingList(msg.items);
            break;
        case "bookmarks_list":
            renderBookmarksList(msg.items);
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
        const rem = Math.max(0, Math.ceil((endTime - Date.now()) / 1000));
        if (rem <= 0) {
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
        el.textContent = `${prefix}，${rem} ${suffix}...`;
        el.className = "toast show warn";
    };
    tick();
    rateLimitTimer = setInterval(tick, 500);
}

// ============ i18n / theme ============
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

function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    document.getElementById("theme-icon").textContent =
        theme === "dark" ? "🌙" : "☀️";
    localStorage.setItem("nagato_theme", theme);
}

function toggleTheme() {
    const cur = document.documentElement.getAttribute("data-theme") || "dark";
    const next = cur === "dark" ? "light" : "dark";
    applyTheme(next);
    send({ cmd: "set_theme", theme: next });
}

function renderTokenHelp() {
    const el = document.getElementById("token-help-body");
    if (!el) return;
    if (currentLang === "zh-CN") {
        el.innerHTML = `
            <p>由于 Pixiv 已不再支持用户名密码登录，您需要先获取一个 RefreshToken。以下方式任选其一：</p>
            <div class="help-block">
                <div class="help-block-title">方式一：Pixiv-Viewer 网页端（推荐）</div>
                <ol>
                    <li>安装 <a href="https://einaregilsson.com/redirector/" target="_blank">Redirector</a> 和 <a href="https://www.tampermonkey.net/index.php" target="_blank">Tampermonkey</a> 扩展</li>
                    <li>导入 Redirector 规则：<code>https://pixiv.pictures/helper/Redirector.json</code></li>
                    <li>安装 <a href="https://fastly.jsdelivr.net/gh/asadahimeka/pixiv-viewer@master/public/helper/helper.user.js" target="_blank">登录工具用户脚本</a></li>
                    <li>访问 <a href="https://pixiv.pictures/account/login" target="_blank">pixiv.pictures/account/login</a>，选择 <b>App API (OAuth)</b> 登录</li>
                    <li>登录成功后，在 <a href="https://pixiv.pictures/setting/others" target="_blank">设置页面</a> 导出 RefreshToken</li>
                </ol>
            </div>
            <div class="help-block">
                <div class="help-block-title">方式二：pxder（Node.js）</div>
                <ol>
                    <li>安装 Node.js 16+，执行 <code>npm i -g pxder</code></li>
                    <li>如需代理：<code>pxder --setting</code> → 选择 5 设置代理</li>
                    <li>执行 <code>pxder --login</code> 完成登录</li>
                    <li>执行 <code>pxder --export-token</code> 导出 Token</li>
                </ol>
            </div>
            <div class="help-block">
                <div class="help-block-title">方式三：PixEz（Android/iOS）</div>
                <ol>
                    <li>从 <a href="https://github.com/Notsfsssf/pixez-flutter" target="_blank">GitHub</a> 下载安装</li>
                    <li>登录后进入 <b>更多 → 账户信息 → Token export</b> 导出</li>
                </ol>
            </div>
            <p class="help-warn">⚠️ RefreshToken 时效较长，登录一次保存好即可长期使用。如果无法直连 Pixiv，请先在设置中配置代理。</p>
            <p class="help-note">原始教程：<a href="https://www.nanoka.top/posts/e78ef86/" target="_blank">https://www.nanoka.top/posts/e78ef86/</a></p>
        `;
    } else {
        el.innerHTML = `
            <p>Pixiv no longer supports username/password login. You need a RefreshToken. Choose one:</p>
            <div class="help-block">
                <div class="help-block-title">Method 1: Pixiv-Viewer (recommended)</div>
                <ol>
                    <li>Install <a href="https://einaregilsson.com/redirector/" target="_blank">Redirector</a> and <a href="https://www.tampermonkey.net/index.php" target="_blank">Tampermonkey</a></li>
                    <li>Import redirect rule: <code>https://pixiv.pictures/helper/Redirector.json</code></li>
                    <li>Install the <a href="https://fastly.jsdelivr.net/gh/asadahimeka/pixiv-viewer@master/public/helper/helper.user.js" target="_blank">login helper userscript</a></li>
                    <li>Visit <a href="https://pixiv.pictures/account/login" target="_blank">pixiv.pictures/account/login</a>, choose App API (OAuth)</li>
                    <li>Export the token from <a href="https://pixiv.pictures/setting/others" target="_blank">Settings</a></li>
                </ol>
            </div>
            <div class="help-block">
                <div class="help-block-title">Method 2: pxder (Node.js)</div>
                <ol>
                    <li>Install Node.js 16+, run <code>npm i -g pxder</code></li>
                    <li>Proxy (if needed): <code>pxder --setting</code> → option 5</li>
                    <li>Run <code>pxder --login</code></li>
                    <li>Run <code>pxder --export-token</code></li>
                </ol>
            </div>
            <div class="help-block">
                <div class="help-block-title">Method 3: PixEz (mobile)</div>
                <ol>
                    <li>Download from <a href="https://github.com/Notsfsssf/pixez-flutter" target="_blank">GitHub</a></li>
                    <li>More → Account → Token export</li>
                </ol>
            </div>
            <p class="help-warn">⚠️ RefreshToken is long-lived. Configure a proxy first if you cannot reach Pixiv directly.</p>
            <p class="help-note">Original guide: <a href="https://www.nanoka.top/posts/e78ef86/" target="_blank">https://www.nanoka.top/posts/e78ef86/</a></p>
        `;
    }
}

// ============ Queue status / 队列状态 ============
function updateQueueStatus(payload) {
    const q = payload.queue || 0;
    const f = payload.failed || 0;
    const p = payload.processed || 0;
    const running = payload.running || false;
    const stopping = payload.stopping || false;
    const mode = payload.mode || "normal";
    const workers = payload.workers || 1;
    const retryPass = payload.retry_pass || 0;
    const maxRetry = payload.max_retry || 3;

    lastQueueState = {
        queue: q,
        failed: f,
        processed: p,
        running,
        stopping,
        retryPass,
        maxRetry,
    };

    updateSelectionCount();

    const total = q + p;
    const pct = total > 0 ? (p / total) * 100 : 0;

    setEl("progress-fill", (el) => (el.style.width = pct.toFixed(1) + "%"));
    setEl("dl-pct", (el) => (el.textContent = pct.toFixed(1) + "%"));
    setEl("dl-remaining", (el) => (el.textContent = t("dl_remaining_fmt", q)));

    setEl("dl-failed-line", (el) => {
        el.textContent = t("dl_failed_fmt", f);
        el.style.color = f > 0 ? "var(--error)" : "";
    });

    updateDownloadStatusText();

    setEl("dl-preset", (el) => (el.value = mode));
    setEl("dl-threads", (el) => {
        el.value = workers;
        el.disabled = mode === "normal";
    });

    const stopBtn = document.getElementById("btn-stop");
    if (stopBtn) {
        stopBtn.disabled = !running;
        stopBtn.textContent = stopping ? t("btn_stopping") : t("btn_stop");
    }
}

function updateDownloadStatusText() {
    const el = document.getElementById("dl-status");
    if (!el) return;
    if (lastQueueState.stopping) el.textContent = t("dl_status_stopping");
    else if (lastQueueState.running) {
        el.textContent =
            lastQueueState.retryPass > 0
                ? t(
                      "dl_status_retry",
                      lastQueueState.retryPass,
                      lastQueueState.maxRetry,
                  )
                : t("dl_status_running");
    } else el.textContent = t("dl_status_idle");
}

function setEl(id, fn) {
    const el = document.getElementById(id);
    if (el) fn(el);
}

// ============ Selection / 选择 ============
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
    return container ? container.querySelectorAll("tr.selected").length : 0;
}

function updateSelectionCount() {
    const count = getSelectionCount();
    const ball = document.getElementById("float-ball");
    const ballCount = document.getElementById("ball-count");
    if (ball) {
        if (count > 0) {
            ball.classList.add("show");
            if (ballCount) ballCount.textContent = count;
        } else {
            ball.classList.remove("show");
        }
    }
}

function onFloatBallClick() {
    const info = getSelectionInfo();
    if (!info) return;
    enqueueSelected(info.containerId, info.items);
}

function enqueueSelected(containerId, items) {
    const selected = [];
    document.querySelectorAll(`#${containerId} tr.selected`).forEach((tr) => {
        const it = items[parseInt(tr.dataset.idx)];
        if (it) selected.push(it);
    });
    if (!selected.length) return toast(t("toast_no_select"), "error");

    const payload = selected.map((it) => {
        const entry = { url: `https://www.pixiv.net/artworks/${it.id}` };
        if (it._slim_illust) entry.metadata = { illust: it._slim_illust };
        return entry;
    });
    send({ cmd: "add_items", items: payload });

    document.querySelectorAll(`#${containerId} tr.selected`).forEach((tr) => {
        tr.classList.remove("selected");
        updateCheckboxIcon(tr);
    });
    lastCheckedIdx[containerId] = null;
    updateSelectionCount();
    toast(t("toast_selected_queued", selected.length), "success");
}

// ============ Table sorting / 表格排序 ============
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
        case "likes":
            return item.likes || 0;
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
    const items = tableItemGetters[containerId]
        ? tableItemGetters[containerId]()
        : null;
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
            }
            va = String(va);
            vb = String(vb);
            if (va < vb) return state.asc ? -1 : 1;
            if (va > vb) return state.asc ? 1 : -1;
            return 0;
        });
    }
    renderTable(containerId, items);
}

// ============ Table render ============
function renderTable(containerId, items) {
    const container = document.getElementById(containerId);
    if (!container) return;

    if (!items.length) {
        container.innerHTML = `<div class="empty-msg">${t("no_result")}</div>`;
        updateSelectionCount();
        return;
    }

    // Preserve selected PIDs
    const selectedPids = new Set();
    container.querySelectorAll("tr.selected").forEach((tr) => {
        const idTd = tr.querySelector('td[data-col="id"]');
        if (idTd) selectedPids.add(idTd.textContent.trim());
    });

    const state = sortState[containerId];
    const cols = TABLE_COLUMNS[containerId];

    const thead =
        '<th class="col-checkbox"></th>' +
        cols
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
                .slice(0, 6)
                .map(
                    (tag) =>
                        `<span class="tag tag-clickable" data-action="tag-search"
                   data-tag="${escapeHtml(tag)}"
                   title="${t("tag_search_title")}">${escapeHtml(tag)}</span>`,
                )
                .join("");

            const titleHtml = `<a href="#" class="illust-title-link"
            data-action="open-illust"
            data-container="${containerId}"
            data-idx="${idx}"
            title="${t("iv_open_pixiv")}">${escapeHtml(truncate(it.title || "", 40))}</a>${badges}`;

            let tds = `<td class="col-checkbox">
            <img class="row-checkbox"
                 src="/ui_icons/${isSelected ? "selected" : "unselected"}.svg"
                 alt=""
                 data-action="toggle-checkbox"
                 data-container="${containerId}"
                 data-idx="${idx}">
        </td>`;

            for (const c of cols) {
                switch (c.key) {
                    case "id":
                        tds += `<td data-col="id">${it.id}</td>`;
                        break;
                    case "title":
                        tds += `<td data-col="title">${titleHtml}</td>`;
                        break;
                    case "page_count":
                        tds += `<td data-col="page_count" style="text-align:right">${it.page_count || 1}</td>`;
                        break;
                    case "author":
                        if (it.author_id) {
                            tds += `<td data-col="author"><a href="#" class="user-link"
                            data-action="open-user" data-uid="${it.author_id}"
                            title="${t("th_author_link")}">${escapeHtml(it.author)}</a></td>`;
                        } else {
                            tds += `<td data-col="author">${escapeHtml(it.author)}</td>`;
                        }
                        break;
                    case "views":
                        tds += `<td data-col="views" style="text-align:right">${formatNum(it.views)}</td>`;
                        break;
                    case "bookmarks":
                        tds += `<td data-col="bookmarks" style="text-align:right">${formatNum(it.bookmarks)}</td>`;
                        break;
                    case "likes":
                        tds += `<td data-col="likes" style="text-align:right">${formatNum(it.likes)}</td>`;
                        break;
                    case "tags":
                        tds += `<td data-col="tags">${tagsHtml}</td>`;
                        break;
                    case "date":
                        tds += `<td data-col="date">${it.date || ""}</td>`;
                        break;
                }
            }

            return `<tr data-idx="${idx}" class="${isSelected ? "selected" : ""}">${tds}</tr>`;
        })
        .join("");

    container.innerHTML = `<table><thead><tr>${thead}</tr></thead><tbody>${rows}</tbody></table>`;
    updateSelectionCount();
}

function updateCheckboxIcon(row) {
    const cb = row.querySelector(".row-checkbox");
    if (!cb) return;
    cb.src = row.classList.contains("selected")
        ? "/ui_icons/selected.svg"
        : "/ui_icons/unselected.svg";
}

function onCheckboxClick(evt, containerId, idx) {
    evt.preventDefault();
    evt.stopPropagation();

    const container = document.getElementById(containerId);
    if (!container) return;
    const rows = container.querySelectorAll("tr[data-idx]");
    if (!rows[idx]) return;

    const lastIdx = lastCheckedIdx[containerId];

    if (evt.shiftKey && lastIdx !== undefined && lastIdx !== null) {
        const start = Math.min(lastIdx, idx);
        const end = Math.max(lastIdx, idx);
        const targetSelected = !rows[idx].classList.contains("selected");
        for (let i = start; i <= end; i++) {
            const row = rows[i];
            if (!row) continue;
            if (targetSelected) row.classList.add("selected");
            else row.classList.remove("selected");
            updateCheckboxIcon(row);
        }
    } else {
        rows[idx].classList.toggle("selected");
        updateCheckboxIcon(rows[idx]);
    }

    lastCheckedIdx[containerId] = idx;
    updateSelectionCount();
    scheduleUiStateSave();
}

// ============ Table event delegation ============
document.addEventListener(
    "click",
    (e) => {
        const target = e.target.closest("[data-action]");
        if (!target) return;
        const action = target.dataset.action;

        if (action === "toggle-checkbox") {
            e.preventDefault();
            e.stopPropagation();
            onCheckboxClick(
                e,
                target.dataset.container,
                parseInt(target.dataset.idx, 10),
            );
            return;
        }
        if (action === "open-illust") {
            e.preventDefault();
            e.stopPropagation();
            openIllustViewer(
                target.dataset.container,
                parseInt(target.dataset.idx, 10),
            );
            return;
        }
        if (action === "open-user") {
            e.preventDefault();
            e.stopPropagation();
            const uid = parseInt(target.dataset.uid, 10);
            if (uid) openUserDetail(uid);
            return;
        }
        if (action === "tag-search") {
            e.preventDefault();
            e.stopPropagation();
            onTagClick(e, target);
            return;
        }
    },
    true,
);

// ============ Tag click ============
function onTagClick(evt, el) {
    if (evt) evt.stopPropagation();
    let tag = el.dataset.tag || "";
    const m = tag.match(/^([^(]+?)(?:\(.+\))?$/);
    if (m) tag = m[1].trim();
    if (!tag) return;

    const navBtn = document.querySelector('nav button[data-tab="search"]');
    if (navBtn) navBtn.click();

    setEl("search-tag", (el) => (el.value = tag));
    setEl("search-target", (el) => (el.value = "exact_match_for_tags"));

    const modeSel = document.getElementById("search-mode");
    if (modeSel && modeSel.value !== "illust") {
        modeSel.value = "illust";
        onSearchModeChange();
    }

    closeIllustViewer();
    setTimeout(doSearch, 30);
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
        applyUserBgVisibility();
        updateSelectionCount();
        scheduleUiStateSave();
    };
});

// ============ Search ============
function onSearchModeChange() {
    const mode = document.getElementById("search-mode").value;
    setEl(
        "search-pane-illust",
        (el) => (el.style.display = mode === "illust" ? "" : "none"),
    );
    setEl(
        "search-pane-user",
        (el) => (el.style.display = mode === "user" ? "" : "none"),
    );
}

function onDurationChange() {
    const v = document.getElementById("search-duration").value;
    setEl(
        "search-custom-dates",
        (el) => (el.style.display = v === "custom" ? "" : "none"),
    );
}

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
    if (!fIllust && !fManga) return toast(t("toast_need_type"), "error");

    let duration, start_date, end_date;
    if (durationRaw === "custom") {
        start_date = document.getElementById("search-start-date").value || "";
        end_date = document.getElementById("search-end-date").value || "";
        if (!start_date || !end_date)
            return toast(t("toast_need_dates"), "error");
        if (start_date > end_date) return toast(t("toast_date_order"), "error");
    } else if (durationRaw) {
        duration = durationRaw;
    }

    setSearchLoading(
        t(
            "status_requesting",
            `${tag} | ${startPage}→${startPage + pages - 1}`,
        ),
    );
    document.getElementById("btn-search").disabled = true;

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

function setSearchLoading(text) {
    setEl(
        "search-list",
        (el) =>
            (el.innerHTML = `<div class="loading"><div class="spinner"></div>${t("loading_search")}</div>`),
    );
    setEl("search-status", (el) => (el.textContent = text));
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
        setEl(
            "search-status",
            (el) =>
                (el.textContent =
                    t("status_done_search", startPage, pages, filtered.length) +
                    suffix),
        );
        toast(t("toast_search_done", filtered.length), "success");
    } else {
        const total = searchItemsRaw.length;
        const shown = filtered.length;
        setEl(
            "search-status",
            (el) =>
                (el.textContent =
                    bmMin > 0 || bmMax > 0
                        ? t("status_filter", shown, total)
                        : t("status_done", total)),
        );
    }
}

function doUserSearch() {
    const word = document.getElementById("usearch-word").value.trim();
    if (!word) return toast(t("toast_need_keyword"), "error");
    const page = parseInt(document.getElementById("usearch-page").value) || 1;
    const offset = (page - 1) * 30;

    setEl(
        "search-list",
        (el) =>
            (el.innerHTML = `<div class="loading"><div class="spinner"></div>${t("loading_usearch")}</div>`),
    );
    setEl("btn-user-search", (el) => (el.disabled = true));
    setEl(
        "usearch-status",
        (el) => (el.textContent = t("status_requesting", word)),
    );

    send({ cmd: "search_users", word, offset });
}

function renderUserSearchResults(items) {
    userSearchItems = items;
    const container = document.getElementById("search-list");
    if (!container) return;

    if (!items.length) {
        container.innerHTML = `<div class="empty-msg">${t("no_result")}</div>`;
    } else {
        const rows = items
            .map(
                (u) => `
            <tr>
                <td>${u.id}</td>
                <td><a href="#" class="user-link"
                       data-action="open-user" data-uid="${u.id}"
                       title="${t("th_user_detail_link")}">${escapeHtml(u.name)}</a></td>
                <td style="color:var(--text-tertiary)">${escapeHtml(u.account)}</td>
                <td>${u.is_followed ? `<span style="color:var(--success)">${t("th_followed_yes")}</span>` : ""}</td>
            </tr>`,
            )
            .join("");
        container.innerHTML = `<table>
            <thead><tr>
                <th>${t("th_uid")}</th><th>${t("th_name")}</th>
                <th>${t("th_account")}</th><th>${t("th_followed")}</th>
            </tr></thead>
            <tbody>${rows}</tbody>
        </table>`;
    }

    setEl("btn-user-search", (el) => (el.disabled = false));
    setEl(
        "usearch-status",
        (el) => (el.textContent = t("status_done", items.length)),
    );
    toast(t("toast_user_search_done", items.length), "success");
}

// ============ Ranking ============
function fetchRanking() {
    const mode = document.getElementById("ranking-mode").value;
    setRankingLoading(mode, "");
    document.getElementById("btn-fetch-ranking").disabled = true;
    send({ cmd: "ranking", mode, limit: 480 });
}

function setRankingLoading(phase, count) {
    setEl(
        "ranking-list",
        (el) =>
            (el.innerHTML = `<div class="loading"><div class="spinner"></div>${t("loading_ranking")} (${phase}: ${count})</div>`),
    );
    setEl(
        "ranking-status",
        (el) => (el.textContent = t("status_requesting", `${phase}: ${count}`)),
    );
}

function renderRankingResults(items, stats) {
    rankingItemsAll = items;
    filterSets["ranking-tag-cloud"].clear();
    rankingItems = items.slice();
    buildTagCloud("ranking-tag-cloud", items, "filterRankingByTags");
    renderTable("ranking-list", rankingItems);
    document.getElementById("btn-fetch-ranking").disabled = false;

    const todayCount = stats?.today ?? items.length;
    const yCount = stats?.yesterday ?? 0;
    const newCount = stats?.new ?? 0;
    setEl(
        "ranking-status",
        (el) => (el.textContent = t("status_done_ranking", todayCount)),
    );
    toast(
        `${t("toast_ranking_done", todayCount)} · NEW ${newCount} (y: ${yCount})`,
        "success",
    );
    scheduleUiStateSave();
}

function filterRankingByTags() {
    const chipTags = [...filterSets["ranking-tag-cloud"]].map((x) =>
        x.toLowerCase(),
    );
    if (chipTags.length === 0) rankingItems = rankingItemsAll.slice();
    else {
        rankingItems = rankingItemsAll.filter((it) => {
            const s = (it.tags || []).join(" ").toLowerCase();
            return chipTags.every((k) => s.includes(k));
        });
    }
    renderTable("ranking-list", rankingItems);
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

function toggleCloud(sectionId) {
    const el = document.getElementById(sectionId);
    if (el) el.classList.toggle("collapsed");
}

// ============ Follow filter ============
function applyFollowFilter() {
    const chipTags = [...filterSets["follow-tag-cloud"]].map((x) =>
        x.toLowerCase(),
    );
    const chipAuthors = [...filterSets["follow-author-cloud"]];
    let filtered = followItemsAll.slice();
    if (chipTags.length) {
        filtered = filtered.filter((it) => {
            const s = (it.tags || []).join(" ").toLowerCase();
            return chipTags.every((k) => s.includes(k));
        });
    }
    if (chipAuthors.length) {
        filtered = filtered.filter((it) =>
            chipAuthors.includes(it.author || ""),
        );
    }
    followItems = filtered;
    renderTable("follow-list", followItems);
}

// ============ Follow new ============
function loadFollowNew(offset) {
    const restrict = document.getElementById("follow-restrict").value;
    setFollowLoading(0);
    document.getElementById("btn-load-follow").disabled = true;
    send({ cmd: "follow_new", offset, restrict });
}

function setFollowLoading(count) {
    setEl(
        "follow-list",
        (el) =>
            (el.innerHTML = `<div class="loading"><div class="spinner"></div>${t("loading_follow")} (${count})</div>`),
    );
}

function renderFollowResults(items, offset, hasMore, batchSize) {
    const btn = document.getElementById("btn-load-follow");
    if (btn) btn.disabled = false;

    followItemsAll = items;
    followCurrentOffset = offset;
    followBatchSize = batchSize || 300;
    followItems = items.slice();
    filterSets["follow-tag-cloud"].clear();
    filterSets["follow-author-cloud"].clear();

    try {
        buildTagCloud("follow-tag-cloud", items, "applyFollowFilter", "tags");
        buildTagCloud(
            "follow-author-cloud",
            items,
            "applyFollowFilter",
            "author",
        );
        renderTable("follow-list", followItems);
    } catch (e) {
        console.error(e);
        return;
    }

    const page = Math.floor(offset / followBatchSize) + 1;
    setEl(
        "follow-status",
        (el) => (el.textContent = t("status_done", items.length)),
    );
    const pageEl = document.getElementById("follow-page-info");
    if (pageEl) pageEl.textContent = t("page_label", page);

    if (!hasMore) {
        toast(t("toast_follow_end"), "warn");
        if (pageEl) pageEl.textContent += " · " + t("toast_follow_end");
    } else {
        toast(t("toast_follow_done", items.length), "success");
    }
    scheduleUiStateSave();
}

function followPrevPage() {
    if (followCurrentOffset <= 0) return toast(t("toast_first_page"), "error");
    loadFollowNew(Math.max(0, followCurrentOffset - followBatchSize));
}

function followNextPage() {
    loadFollowNew(followCurrentOffset + followBatchSize);
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
    setEl(
        "recommend-list",
        (el) =>
            (el.innerHTML = `<div class="loading"><div class="spinner"></div>${t("loading_recommend")}</div>`),
    );
    setEl(
        "recommend-status",
        (el) => (el.textContent = t("status_requesting", mode)),
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
    setEl(
        "recommend-status",
        (el) =>
            (el.textContent = t("status_done_recommend", items.length, mode)),
    );
    toast(t("toast_recommend_done", items.length), "success");
    scheduleUiStateSave();
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
    for (const s of seedList) {
        if (!/^\d+$/.test(s))
            return toast(t("toast_adv_seeds_invalid", s), "error");
    }
    if (seedList.length > 30) return toast(t("toast_adv_seeds_max"), "error");

    const viewedList = viewedRaw
        ? viewedRaw
              .split(",")
              .map((s) => s.trim())
              .filter((s) => s)
        : [];
    for (const v of viewedList) {
        if (!/^\d+$/.test(v))
            return toast(t("toast_adv_viewed_invalid", v), "error");
    }
    if (viewedList.length > 30)
        return toast(t("toast_adv_viewed_max"), "error");
    if (limit < 1 || limit > 120) return toast(t("toast_adv_limit"), "error");

    closeAdvancedRecommend();
    const params = {};
    if (seedList.length) params.bookmark_illust_ids = seedList;
    if (viewedList.length) params.viewed = viewedList;
    if (includeRanking) params.include_ranking_illusts = true;
    if (includePrivacy) params.include_privacy_policy = true;

    setEl(
        "recommend-list",
        (el) =>
            (el.innerHTML = `<div class="loading"><div class="spinner"></div>${t("loading_adv_recommend")}</div>`),
    );
    setEl(
        "recommend-status",
        (el) => (el.textContent = t("status_requesting", "advanced")),
    );
    document.getElementById("btn-rec-auto").disabled = true;
    send({ cmd: "recommend", mode: "advanced", limit, params });
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
    document.body.classList.remove("has-user-bg");

    setEl("udetail-uid", (el) => (el.value = uid));
    resetUserDetailView();

    setEl(
        "udetail-header",
        (el) =>
            (el.innerHTML = `<div class="loading"><div class="spinner"></div>${t("loading_user")}</div>`),
    );
    setEl("udetail-status", (el) => (el.textContent = `UID: ${uid}`));
    document.getElementById("btn-load-udetail").disabled = true;
    send({ cmd: "user_detail", uid });
}

function resetUserDetailView() {
    userDetailUid = null;
    userDetailItems = [];
    userDetailAllItems = [];
    currentUserDetail = null;
    document.body.style.removeProperty("--user-bg");
    document.body.classList.remove("has-user-bg");

    setEl("udetail-tag-cloud", (el) => (el.innerHTML = ""));
    filterSets["udetail-tag-cloud"] = new Set();
    setEl("user-detail-list", (el) => (el.innerHTML = ""));
    setEl("udetail-header", (el) => (el.innerHTML = ""));
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
        setEl(
            "udetail-status",
            (el) =>
                (el.textContent = t(
                    "status_loading_user_illusts",
                    msg.page,
                    msg.count,
                )),
        );
        setEl(
            "user-detail-list",
            (el) =>
                (el.innerHTML = `<div class="loading"><div class="spinner"></div>${t("loading_user_illusts", msg.page)}</div>`),
        );
    }
}

function buildUserCardHtml(user) {
    const avatarProxy = user.avatar
        ? `/proxy_image?url=${encodeURIComponent(user.avatar)}`
        : "";
    const avatarHtml = avatarProxy
        ? `<img class="user-avatar" src="${avatarProxy}" alt=""
                onerror="this.onerror=null; this.removeAttribute('src');">`
        : '<div class="user-avatar"></div>';

    const officialUrl = `https://www.pixiv.net/users/${user.id}`;
    const metaParts = [];
    if (user.region) metaParts.push(`🌍 ${escapeHtml(user.region)}`);
    if (user.total_follow_users)
        metaParts.push(`👥 ${formatNum(user.total_follow_users)}`);
    if (user.total_illusts) metaParts.push(`🎨 ${user.total_illusts}`);
    if (user.total_manga) metaParts.push(`📚 ${user.total_manga}`);
    if (user.is_accept_request === true) {
        metaParts.push(
            `<span style="color:var(--success)">${t("meta_accept_request_yes")}</span>`,
        );
    } else if (user.is_accept_request === false) {
        metaParts.push(
            `<span style="color:var(--text-tertiary)">${t("meta_accept_request_no")}</span>`,
        );
    }

    const followBtn = user.is_followed
        ? `<button class="follow-btn following" onclick="toggleFollow()">${t("following_btn")}</button>`
        : `<button class="follow-btn" onclick="toggleFollow()">${t("follow_btn")}</button>`;

    let commentHtml = "";
    if (Array.isArray(user.comment_parts) && user.comment_parts.length) {
        commentHtml = `<div class="user-comment">${renderCommentParts(user.comment_parts)}</div>`;
    } else if (user.comment) {
        commentHtml = `<div class="user-comment">${escapeHtml(user.comment).replace(/\n/g, "<br>")}</div>`;
    }

    return `
        <div class="user-card">
            ${avatarHtml}
            <div class="user-info">
                <div style="display:flex; align-items:center; gap:12px">
                    <div>
                        <a class="user-name" href="${officialUrl}" target="_blank" rel="noopener"
                           title="${t("th_user_name_link")}">${escapeHtml(user.name)}</a>
                        <span class="user-account">@${escapeHtml(user.account)} (UID: ${user.id})</span>
                    </div>
                    ${followBtn}
                </div>
                <div class="user-meta">${metaParts.join("")}</div>
                ${commentHtml}
            </div>
        </div>`;
}

function renderUserHeaderOnly(user) {
    currentUserDetail = user;
    if (user.background_image_url) {
        const proxy = `/proxy_image?url=${encodeURIComponent(user.background_image_url)}`;
        document.body.style.setProperty("--user-bg", `url("${proxy}")`);
    } else {
        document.body.style.removeProperty("--user-bg");
    }
    applyUserBgVisibility();

    setEl("udetail-header", (el) => (el.innerHTML = buildUserCardHtml(user)));
    document.getElementById("btn-load-udetail").disabled = false;
}

function applyUserBgVisibility() {
    const activeTab = document.querySelector("nav button.active")?.dataset.tab;
    const hasBg = !!(
        currentUserDetail && currentUserDetail.background_image_url
    );
    if (activeTab === "user-detail" && hasBg)
        document.body.classList.add("has-user-bg");
    else document.body.classList.remove("has-user-bg");
}

function renderUserDetail(user, items) {
    userDetailUid = user.id;
    renderUserHeaderOnly(user);
    setEl("udetail-uid", (el) => (el.value = user.id));
    setEl(
        "udetail-status",
        (el) =>
            (el.textContent = t(
                "status_done",
                `${user.name} (${items.length})`,
            )),
    );

    userDetailAllItems = items.slice();
    userDetailItems = items.slice();
    buildTagCloud("udetail-tag-cloud", items, "applyUserDetailFilter");
    renderTable("user-detail-list", userDetailItems);
    toast(t("toast_user_detail_done", items.length), "success");
    scheduleUiStateSave();
}

function applyUserDetailFilter() {
    const chipTags = [...filterSets["udetail-tag-cloud"]].map((x) =>
        x.toLowerCase(),
    );
    if (chipTags.length === 0) userDetailItems = userDetailAllItems.slice();
    else {
        userDetailItems = userDetailAllItems.filter((it) => {
            const s = (it.tags || []).join(" ").toLowerCase();
            return chipTags.every((k) => s.includes(k));
        });
    }
    renderTable("user-detail-list", userDetailItems);
}

function toggleFollow() {
    if (!currentUserDetail) return;
    const uid = currentUserDetail.id;
    const action = currentUserDetail.is_followed ? "unfollow" : "follow";
    send({ cmd: "follow_user", uid, action });
}

// ============ Comment parts rendering ============
function sanitizeUrl(url) {
    if (!url) return null;
    url = String(url).trim();
    if (/^https?:\/\//i.test(url)) return url;
    if (url.startsWith("/")) return "https://www.pixiv.net" + url;
    return null;
}

function renderCommentParts(parts) {
    if (!parts || !parts.length) return "";
    return parts
        .map((p) => {
            if (!p || typeof p !== "object") return "";
            if (p.type === "text") {
                return escapeHtml(p.value || "").replace(/\n/g, "<br>");
            }
            if (p.type === "link") {
                const href = sanitizeUrl(p.href);
                if (!href) return escapeHtml(p.text || p.href || "");
                const text = escapeHtml(p.text || p.href || "");
                return `<a href="${escapeHtml(href)}" target="_blank"
                       rel="noopener noreferrer" class="comment-link">${text}</a>`;
            }
            return "";
        })
        .join("");
}

// ============ Illust viewer ============
function getIllustPages(slim) {
    const pages = [];
    if (!slim) return pages;

    const pageCount = slim.page_count || 1;
    const metaPages = slim.meta_pages || [];
    const single = slim.meta_single_page || {};

    if (pageCount === 1 || metaPages.length === 0) {
        const primary =
            single.large_image_url || single.original_image_url || "";
        const fallback = single.original_image_url || primary;
        if (primary) pages.push({ primary, fallback });
    } else {
        for (const p of metaPages) {
            const im = p.image_urls || {};
            const primary = im.large || im.medium || "";
            const fallback = im.original || primary;
            if (primary) pages.push({ primary, fallback });
        }
    }
    return pages;
}

function openIllustViewer(containerId, idx) {
    const getter = tableItemGetters[containerId];
    if (!getter) return;
    const items = getter();
    const it = items[idx];
    if (!it) return;

    ivState.containerId = containerId;
    ivState.items = items;
    ivState.idx = idx;

    renderIllustViewer();
    document.getElementById("illust-viewer-modal").classList.add("show");
}

function closeIllustViewer() {
    document.getElementById("illust-viewer-modal").classList.remove("show");
    const img = document.getElementById("iv-image");
    if (img) {
        img.onerror = null;
        img.src = "";
    }
}

function illustViewerPrev() {
    if (ivState.idx > 0) {
        ivState.idx--;
        renderIllustViewer();
    }
}

function illustViewerNext() {
    if (ivState.idx < ivState.items.length - 1) {
        ivState.idx++;
        renderIllustViewer();
    }
}

function illustViewerPagePrev() {
    if (ivState.pageIdx > 0) {
        ivState.pageIdx--;
        renderIvImage();
    }
}

function illustViewerPageNext() {
    if (ivState.pageIdx < ivState.pages.length - 1) {
        ivState.pageIdx++;
        renderIvImage();
    }
}

function renderIllustViewer() {
    const it = ivState.items[ivState.idx];
    if (!it) return;
    const slim = it._slim_illust || {};
    const user = slim.user || {};

    setEl(
        "iv-index",
        (el) =>
            (el.textContent = `${ivState.idx + 1} / ${ivState.items.length}`),
    );
    setEl("iv-prev", (el) => (el.disabled = ivState.idx <= 0));
    setEl(
        "iv-next",
        (el) => (el.disabled = ivState.idx >= ivState.items.length - 1),
    );

    ivState.pages = getIllustPages(slim);
    ivState.pageIdx = 0;
    renderIvImage();

    const titleEl = document.getElementById("iv-title");
    if (titleEl) {
        titleEl.textContent = it.title || "";
        titleEl.href = `https://www.pixiv.net/artworks/${it.id}`;
        titleEl.title = t("iv_open_pixiv");
    }

    let badges = "";
    if (it.is_new) badges += '<span class="badge new">NEW</span>';
    if (it.ai_generated) badges += '<span class="badge ai">AI</span>';
    if (it.restriction) {
        const cls = it.restriction.toLowerCase().replace("-", "");
        badges += `<span class="badge ${cls}">${it.restriction}</span>`;
    }
    setEl("iv-badges", (el) => (el.innerHTML = badges));

    setEl("iv-views", (el) => (el.textContent = formatNum(it.views)));
    setEl("iv-bookmarks", (el) => (el.textContent = formatNum(it.bookmarks)));
    setEl("iv-likes", (el) => (el.textContent = formatNum(it.likes)));
    setEl("iv-pages", (el) => (el.textContent = it.page_count || 1));
    setEl("iv-date", (el) => (el.textContent = it.date || "—"));

    const tagsHtml = (it.tags || [])
        .map(
            (tag) =>
                `<span class="tag tag-clickable" data-action="tag-search"
               data-tag="${escapeHtml(tag)}"
               title="${t("tag_search_title")}">${escapeHtml(tag)}</span>`,
        )
        .join("");
    setEl("iv-tags", (el) => (el.innerHTML = tagsHtml));

    renderIvUser(user, it);
    renderIvActions(it);
}

function renderIvUser(user, it) {
    const container = document.getElementById("iv-user-card");
    if (!container) return;

    const uid = user.id || it.author_id;
    const name = user.name || it.author || "";
    const account = user.account || it.author_account || "";
    const avatar =
        (user.profile_image_urls && user.profile_image_urls.medium) ||
        it.author_avatar ||
        "";

    const avatarHtml = avatar
        ? `<img class="iv-user-avatar"
                src="/proxy_image?url=${encodeURIComponent(avatar)}"
                alt=""
                onerror="this.onerror=null; this.removeAttribute('src');">`
        : '<div class="iv-user-avatar"></div>';

    const nameHtml = uid
        ? `<a class="iv-user-name" href="#" data-action="open-user"
               data-uid="${uid}" title="${t("th_author_link")}">${escapeHtml(name)}</a>`
        : `<span class="iv-user-name">${escapeHtml(name)}</span>`;

    const accountHtml = account
        ? `<div class="iv-user-account">@${escapeHtml(account)}</div>`
        : "";

    container.innerHTML = `
        ${avatarHtml}
        <div class="iv-user-info">
            ${nameHtml}
            ${accountHtml}
        </div>`;
}

function renderIvActions(it) {
    const btn = document.getElementById("iv-bookmark-btn");
    const label = document.getElementById("iv-bookmark-label");
    if (!btn || !label) return;
    const marked = !!it.is_bookmarked;
    btn.classList.toggle("active", marked);
    label.textContent = marked
        ? t("btn_pixiv_bookmarked")
        : t("btn_pixiv_bookmark");
}

function toggleIllustBookmark() {
    const it = ivState.items?.[ivState.idx];
    if (!it) return;
    send({
        cmd: "bookmark_toggle",
        id: it.id,
        action: it.is_bookmarked ? "delete" : "add",
    });
}

function downloadCurrentIllust() {
    const it = ivState.items?.[ivState.idx];
    if (!it) return;
    const entry = { url: `https://www.pixiv.net/artworks/${it.id}` };
    if (it._slim_illust) entry.metadata = { illust: it._slim_illust };
    send({ cmd: "add_items", items: [entry] });
    toast(t("toast_download_added"), "success");
}

function renderIvImage() {
    const img = document.getElementById("iv-image");
    if (!img) return;
    const page = ivState.pages[ivState.pageIdx];

    if (page) {
        img.onerror = function () {
            if (
                page.fallback &&
                page.fallback !== page.primary &&
                img.dataset.triedFallback !== "1"
            ) {
                img.dataset.triedFallback = "1";
                img.src = `/proxy_image?url=${encodeURIComponent(page.fallback)}`;
            } else {
                img.onerror = null;
                img.style.display = "none";
            }
        };
        img.dataset.triedFallback = "0";
        img.src = `/proxy_image?url=${encodeURIComponent(page.primary)}`;
        img.style.display = "";
    } else {
        img.onerror = null;
        img.removeAttribute("src");
        img.style.display = "none";
    }

    const nav = document.getElementById("iv-page-nav");
    if (!nav) return;
    if (ivState.pages.length > 1) {
        nav.style.display = "flex";
        setEl(
            "iv-page-index",
            (el) =>
                (el.textContent = `${ivState.pageIdx + 1} / ${ivState.pages.length}`),
        );
        setEl("iv-page-prev", (el) => (el.disabled = ivState.pageIdx <= 0));
        setEl(
            "iv-page-next",
            (el) => (el.disabled = ivState.pageIdx >= ivState.pages.length - 1),
        );
    } else {
        nav.style.display = "none";
    }
}

// Keyboard shortcuts for viewer
document.addEventListener("keydown", (e) => {
    const modal = document.getElementById("illust-viewer-modal");
    if (!modal || !modal.classList.contains("show")) return;

    if (e.key === "Escape") closeIllustViewer();
    else if (e.key === "ArrowLeft" && !e.shiftKey) illustViewerPrev();
    else if (e.key === "ArrowRight" && !e.shiftKey) illustViewerNext();
    else if (e.key === "ArrowLeft" && e.shiftKey) illustViewerPagePrev();
    else if (e.key === "ArrowRight" && e.shiftKey) illustViewerPageNext();
});

document.addEventListener("click", (e) => {
    const modal = document.getElementById("illust-viewer-modal");
    if (modal && modal.classList.contains("show") && e.target === modal) {
        closeIllustViewer();
    }
});

// ============ Encyclopedia search ============
function searchEncyclopedia() {
    const tag = document.getElementById("search-tag")?.value.trim();
    if (!tag) return toast(t("toast_need_tag_for_encyclopedia"), "error");
    const url = `https://zh.moegirl.org.cn/index.php?fulltext=1&search=%22${encodeURIComponent(tag)}%22&title=Special%3A%E6%90%9C%E7%B4%A2`;
    window.open(url, "_blank", "noopener");
}

// ============ Queue / download tab ============
function toggleDownloadItems() {
    dlItemsExpanded = !dlItemsExpanded;
    setEl(
        "dl-items-wrap",
        (el) => (el.style.display = dlItemsExpanded ? "flex" : "none"),
    );
    const btn = document.getElementById("btn-toggle-items");
    if (btn) btn.classList.toggle("expanded", dlItemsExpanded);
    if (dlItemsExpanded) renderQueueItems();
}

function renderQueueItems() {
    const list = document.getElementById("dl-items-list");
    const countEl = document.getElementById("dl-items-count");
    if (countEl) countEl.textContent = `(${queueItems.length})`;
    if (!list) return;

    if (!queueItems.length) {
        list.innerHTML = `<div class="empty-msg" style="padding:20px">${t("no_result")}</div>`;
        return;
    }

    list.innerHTML = queueItems
        .map((it) => {
            const pid = it.pid || "—";
            const title = it.title || "";
            const titleHtml = title
                ? `<a href="https://www.pixiv.net/artworks/${pid}"
                  target="_blank" rel="noopener" class="dl-item-title"
                  title="${escapeHtml(title)}">${escapeHtml(title)}</a>`
                : `<span class="dl-item-title empty">—</span>`;

            const status = it.status || "pending";
            const stage = it.stage || "";
            let statusText = t(`dl_item_status_${status}`) || status;
            if (status === "processing" && stage) {
                statusText = t(`dl_stage_${stage}`) || statusText;
            }
            const statusClass =
                status === "processing"
                    ? "processing"
                    : status === "success"
                      ? "success"
                      : status === "failed"
                        ? "failed"
                        : "";

            const progress = it.progress || 0;
            const progressClass =
                status === "success"
                    ? "success"
                    : status === "failed"
                      ? "failed"
                      : "";
            const errorAttr = it.error
                ? ` class="dl-item-error" title="${escapeHtml(it.error)}"`
                : "";

            return `<div class="dl-item">
            <span class="dl-item-pid">${pid}</span>
            ${titleHtml}
            <span class="dl-item-status ${statusClass}"${errorAttr}>
                ${escapeHtml(statusText)}
            </span>
            <div class="dl-item-progress ${progressClass}">
                <div class="dl-item-progress-bar">
                    <div class="dl-item-progress-fill"
                         style="width:${Math.min(100, Math.max(0, progress))}%"></div>
                </div>
                <span class="dl-item-progress-text">${progress}%</span>
            </div>
        </div>`;
        })
        .join("");
}

function onPresetChange() {
    const mode = document.getElementById("dl-preset").value;
    send({ cmd: "set_download_mode", mode });
    const ti = document.getElementById("dl-threads");
    if (ti) {
        ti.disabled = mode === "normal";
        if (mode === "normal") ti.value = 1;
    }
}

function onThreadsChange() {
    const v = Math.max(
        1,
        Math.min(8, parseInt(document.getElementById("dl-threads").value) || 1),
    );
    document.getElementById("dl-threads").value = v;
    send({ cmd: "save_config", data: { "performance.parallel_workers": v } });
}

function stopQueue() {
    send({ cmd: "stop_queue" });
}

function clearQueue() {
    if (confirm(t("toast_confirm_clear"))) send({ cmd: "clear_queue" });
}

// ============ Add task modal ============
function openAddTaskModal() {
    const modal = document.getElementById("add-task-modal");
    if (modal) modal.classList.add("show");
    switchAddTaskTab("manual");
}

function closeAddTaskModal() {
    const modal = document.getElementById("add-task-modal");
    if (modal) modal.classList.remove("show");
    setEl("bookmark-preview", (el) => (el.innerHTML = ""));
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

function addSingleUrl() {
    const url = document.getElementById("manual-url").value.trim();
    if (!url) return toast(t("toast_need_url"), "error");
    send({ cmd: "add_items", items: [{ url }] });
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
    send({ cmd: "add_items", items: urls.map((u) => ({ url: u })) });
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
    setEl(
        "bookmark-preview",
        (el) =>
            (el.innerHTML = urls
                .map(
                    (u) =>
                        `<div style="padding:4px 0; border-bottom:1px solid var(--border)">${escapeHtml(u)}</div>`,
                )
                .join("")),
    );
    const btn = document.getElementById("bookmark-add-btn");
    if (btn) btn.disabled = urls.length === 0;
    toast(t("toast_parsed", urls.length), "success");
}

function addBookmarkUrls() {
    if (!parsedBookmarkUrls.length) return;
    send({
        cmd: "add_items",
        items: parsedBookmarkUrls.map((u) => ({ url: u })),
    });
    closeAddTaskModal();
}

// ============ Account ============
function loadAccount(forceRefresh) {
    setEl(
        "account-header",
        (el) =>
            (el.innerHTML = `<div class="loading"><div class="spinner"></div>${t("loading_account")}</div>`),
    );
    send({ cmd: forceRefresh ? "refresh_account" : "get_account" });
    send({ cmd: "list_accounts" });
}

function renderAccount(profile) {
    const container = document.getElementById("account-header");
    if (!container) return;
    if (!profile || !profile.id) {
        container.innerHTML = `<div class="empty-msg">${t("account_load_failed")}</div>`;
        return;
    }

    const avatarHtml = profile.avatar
        ? `<img class="account-avatar"
                src="/proxy_image?url=${encodeURIComponent(profile.avatar)}"
                alt=""
                onerror="this.onerror=null; this.removeAttribute('src');">`
        : '<div class="account-avatar"></div>';

    let rtPreview = "",
        rtFull = "",
        psFull = "";
    try {
        const cur = currentAccounts.find((a) => a.is_current);
        if (cur) {
            rtFull = cur.refresh_token || "";
            rtPreview = cur.refresh_token_preview || "";
            psFull = cur.phpsessid || "";
        }
    } catch (e) {}

    const rtHtml = rtPreview
        ? `<div class="account-token" title="${escapeHtml(rtFull)}">
              <span class="account-token-label">${t("account_refresh_token")}:</span>
              <code class="account-token-value">${escapeHtml(rtPreview)}</code>
              <button class="secondary account-token-btn"
                      onclick="copyRefreshToken()">${t("btn_copy")}</button>
           </div>`
        : "";

    const psHtml = `
        <div class="account-phpsessid">
            <span class="account-token-label">${t("settings_phpsessid")}</span>
            <input type="text" id="account-phpsessid-input"
                   value="${escapeHtml(psFull)}"
                   data-i18n-placeholder="phpsessid_ph">
            <button class="secondary account-token-btn"
                    onclick="savePhpsessid()">${t("btn_save")}</button>
        </div>`;

    let commentHtml = "";
    if (Array.isArray(profile.comment_parts) && profile.comment_parts.length) {
        commentHtml = `<div class="account-comment">${renderCommentParts(profile.comment_parts)}</div>`;
    } else if (profile.comment) {
        commentHtml = `<div class="account-comment">${escapeHtml(profile.comment).replace(/\n/g, "<br>")}</div>`;
    }

    container.innerHTML = `
        <div class="account-card">
            ${avatarHtml}
            <div class="account-info">
                <div>
                    <a class="account-name"
                       href="https://www.pixiv.net/users/${profile.id}"
                       target="_blank" rel="noopener">
                        ${escapeHtml(profile.name || "")}
                    </a>
                    <span class="account-account">@${escapeHtml(profile.account || "")}</span>
                </div>
                <div class="account-stats">
                    <div class="account-stat">
                        <span class="num">${formatNum(profile.total_illusts || 0)}</span>
                        <span class="lbl">${t("meta_illusts")}</span>
                    </div>
                    <div class="account-stat clickable"
                         onclick="loadFollowing()"
                         title="${t("account_click_load_following")}">
                        <span class="num">${formatNum(profile.total_follow_users || 0)}</span>
                        <span class="lbl">${t("meta_following")}</span>
                    </div>
                    <div class="account-stat clickable"
                         onclick="loadBookmarks()"
                         title="${t("account_click_load_bookmarks")}">
                        <span class="num">${formatNum(profile.total_illust_bookmarks_public || 0)}</span>
                        <span class="lbl">${t("account_bookmarks_short")}</span>
                    </div>
                </div>
                ${commentHtml}
                ${rtHtml}
                ${psHtml}
            </div>
        </div>`;
}

function renderAccountList(accounts, currentIndex) {
    const container = document.getElementById("account-list");
    if (!container) return;
    if (!accounts.length) {
        container.innerHTML = `<div class="empty-msg">${t("no_result")}</div>`;
        return;
    }
    const rows = accounts
        .map((a) => {
            const avatarHtml = a.avatar
                ? `<img class="account-list-avatar"
                    src="/proxy_image?url=${encodeURIComponent(a.avatar)}"
                    alt=""
                    onerror="this.onerror=null; this.removeAttribute('src');">`
                : '<div class="account-list-avatar"></div>';
            const isCurrent = a.is_current;
            const actions = isCurrent
                ? `<span class="badge ai">${t("account_current")}</span>`
                : `<button class="secondary" onclick="switchAccount(${a.index})">${t("account_switch")}</button>
               <button class="secondary" onclick="removeAccount(${a.index})">${t("account_remove")}</button>`;
            return `<tr class="${isCurrent ? "selected" : ""}">
            <td style="width:44px">${avatarHtml}</td>
            <td>${a.id || "?"}</td>
            <td>${escapeHtml(a.name || "")}</td>
            <td style="color:var(--text-tertiary)">${escapeHtml(a.account || "")}</td>
            <td style="text-align:right">${actions}</td>
        </tr>`;
        })
        .join("");
    container.innerHTML = `<table>
        <thead><tr>
            <th></th><th>${t("th_uid")}</th><th>${t("th_name")}</th>
            <th>${t("th_account")}</th><th style="text-align:right"></th>
        </tr></thead>
        <tbody>${rows}</tbody>
    </table>`;
}

function renderFollowingList(items) {
    const container = document.getElementById("following-list");
    if (!container) return;
    if (!items.length) {
        container.innerHTML = `<div class="empty-msg">${t("no_result")}</div>`;
        return;
    }
    const rows = items
        .map((u) => {
            const avatarHtml = u.avatar
                ? `<img class="following-avatar"
                    src="/proxy_image?url=${encodeURIComponent(u.avatar)}"
                    alt=""
                    onerror="this.onerror=null; this.removeAttribute('src');">`
                : '<div class="following-avatar"></div>';
            return `<tr>
            <td style="width:44px">${avatarHtml}</td>
            <td>${u.id || ""}</td>
            <td><a href="#" data-action="open-user" data-uid="${u.id}"
                   class="user-link">${escapeHtml(u.name || "")}</a></td>
            <td style="color:var(--text-tertiary)">${escapeHtml(u.account || "")}</td>
        </tr>`;
        })
        .join("");
    container.innerHTML = `<table>
        <thead><tr>
            <th></th><th>${t("th_uid")}</th>
            <th>${t("th_name")}</th><th>${t("th_account")}</th>
        </tr></thead>
        <tbody>${rows}</tbody>
    </table>`;
}

function renderBookmarksList(items) {
    if (currentAccountProfile) currentAccountProfile.bookmarks = items;
    const container = document.getElementById("account-bookmarks");
    if (!container) return;
    if (!items.length) {
        container.innerHTML = `<div class="empty-msg">${t("no_result")}</div>`;
        return;
    }
    const rows = items
        .map((it, idx) => {
            let badges = "";
            if (it.ai_generated) badges += '<span class="badge ai">AI</span>';
            if (it.restriction) {
                const cls = it.restriction.toLowerCase().replace("-", "");
                badges += `<span class="badge ${cls}">${it.restriction}</span>`;
            }
            const titleHtml = `<a href="#" class="illust-title-link"
            data-action="open-illust"
            data-container="account-bookmarks"
            data-idx="${idx}"
            title="${t("iv_open_pixiv")}">${escapeHtml(truncate(it.title || "", 40))}</a>${badges}`;
            const tagsHtml = (it.tags || [])
                .slice(0, 5)
                .map(
                    (tag) =>
                        `<span class="tag tag-clickable" data-action="tag-search"
                   data-tag="${escapeHtml(tag)}">${escapeHtml(tag)}</span>`,
                )
                .join("");
            return `<tr>
            <td>${it.id}</td>
            <td>${titleHtml}</td>
            <td>${it.page_count || 1}</td>
            <td>${escapeHtml(it.author || "")}</td>
            <td style="text-align:right">${formatNum(it.bookmarks)}</td>
            <td>${tagsHtml}</td>
        </tr>`;
        })
        .join("");
    container.innerHTML = `<table>
        <thead><tr>
            <th>${t("th_pid")}</th><th>${t("th_title")}</th>
            <th>${t("th_pages")}</th><th>${t("th_author")}</th>
            <th style="text-align:right">${t("th_bookmarks")}</th>
            <th>${t("th_tags")}</th>
        </tr></thead>
        <tbody>${rows}</tbody>
    </table>`;
}

function loadFollowing() {
    const panel = document.getElementById("following-panel");
    const list = document.getElementById("following-list");
    if (!panel || !list) return;
    panel.style.display = "";
    list.innerHTML = `<div class="loading"><div class="spinner"></div>${t("loading_following")}</div>`;
    send({ cmd: "load_following" });
}

function hideFollowing() {
    const p = document.getElementById("following-panel");
    if (p) p.style.display = "none";
}

function loadBookmarks() {
    const panel = document.getElementById("bookmarks-panel");
    const list = document.getElementById("account-bookmarks");
    if (!panel || !list) return;
    panel.style.display = "";
    list.innerHTML = `<div class="loading"><div class="spinner"></div>${t("loading_bookmarks")}</div>`;
    send({ cmd: "load_bookmarks" });
}

function hideBookmarks() {
    const p = document.getElementById("bookmarks-panel");
    if (p) p.style.display = "none";
}

function switchAccount(index) {
    send({ cmd: "switch_account", index });
}

function removeAccount(index) {
    if (!confirm(t("account_remove_confirm"))) return;
    send({ cmd: "remove_account", index });
}

function copyRefreshToken() {
    try {
        const cur = currentAccounts.find((a) => a.is_current);
        if (!cur || !cur.refresh_token) return;
        navigator.clipboard
            .writeText(cur.refresh_token)
            .then(() => toast(t("toast_token_copied"), "success"))
            .catch(() => toast(t("toast_clipboard_failed"), "error"));
    } catch (e) {
        toast(t("toast_clipboard_failed"), "error");
    }
}

function savePhpsessid() {
    const input = document.getElementById("account-phpsessid-input");
    if (!input) return;
    send({ cmd: "update_phpsessid", phpsessid: input.value.trim() });
}

function openAddAccountModal() {
    const modal = document.getElementById("add-account-modal");
    if (!modal) return;
    setEl("new-account-token", (el) => (el.value = ""));
    setEl("new-account-phpsessid", (el) => (el.value = ""));
    modal.classList.add("show");
}

function closeAddAccountModal() {
    const modal = document.getElementById("add-account-modal");
    if (modal) modal.classList.remove("show");
}

function submitAddAccount() {
    const rtInput = document.getElementById("new-account-token");
    const psInput = document.getElementById("new-account-phpsessid");
    if (!rtInput) return;
    const rt = rtInput.value.trim();
    const ps = psInput ? psInput.value.trim() : "";
    if (!rt) return toast(t("toast_need_token"), "error");
    toast(t("account_validating"), "");
    send({ cmd: "add_account", refresh_token: rt, phpsessid: ps });
}

// ============ Config ============
const CONFIG_KEYS = [
    "download_dir",
    "proxy",
    "language",
    "theme",
    "performance.download_mode",
    "performance.parallel_workers",
    "performance.download_delay",
    "performance.max_retries",
    "performance.enable_download_metadata_cache",
    "api.request_delay",
    "api.rate_limit_wait",
    "api.max_results",
    "api.parallel_requests",
    "api.web_ajax_mode",
];

let configSaveTimer = null;

function getDotted(obj, path) {
    return path
        .split(".")
        .reduce((o, k) => (o && o[k] !== undefined ? o[k] : undefined), obj);
}

function fillConfig(cfg) {
    CONFIG_KEYS.forEach((k) => {
        const el = document.getElementById("cfg-" + k);
        if (!el) return;
        const val = getDotted(cfg, k);
        if (val === undefined) return;
        if (el.type === "checkbox") el.checked = !!val;
        else el.value = val;
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
    if (cfg.theme) applyTheme(cfg.theme);
}

function scheduleConfigSave() {
    if (configSaveTimer) clearTimeout(configSaveTimer);
    configSaveTimer = setTimeout(() => saveConfig(true), 700);
}

function saveConfig(silent = false) {
    const data = {};
    CONFIG_KEYS.forEach((k) => {
        const el = document.getElementById("cfg-" + k);
        if (!el) return;
        if (el.type === "checkbox") data[k] = el.checked;
        else if (el.type === "number") {
            const v = parseFloat(el.value);
            data[k] = isNaN(v) ? 0 : v;
        } else data[k] = el.value;
    });
    send({ cmd: "save_config", data });

    if (data.language === "zh-CN" || data.language === "en") {
        switchLanguage(data.language);
    }
    if (!silent) toast(t("toast_config_saved"), "success");
}

function bindConfigAutoSave() {
    CONFIG_KEYS.forEach((k) => {
        const el = document.getElementById("cfg-" + k);
        if (!el) return;
        const tag = el.tagName.toLowerCase();
        const type = (el.type || "").toLowerCase();
        if (tag === "select" || type === "checkbox") {
            el.addEventListener("change", scheduleConfigSave);
        } else {
            el.addEventListener("input", scheduleConfigSave);
            el.addEventListener("change", scheduleConfigSave);
        }
    });
}

// ============ Test / latency / token help ============
function testLogin() {
    send({ cmd: "login" });
}

function testLatency() {
    toast(t("toast_latency_testing"), "");
    send({ cmd: "test_latency" });
}

function showTokenHelp() {
    document.getElementById("token-help-modal").classList.add("show");
}

function closeTokenHelp() {
    document.getElementById("token-help-modal").classList.remove("show");
}

// ============ UI state ============
let uiStateSaveTimer = null;

function scheduleUiStateSave() {
    if (uiStateSaveTimer) clearTimeout(uiStateSaveTimer);
    uiStateSaveTimer = setTimeout(saveUiState, 500);
}

function saveUiState() {
    const state = {
        active_tab: getActiveTab(),
        theme: document.documentElement.getAttribute("data-theme") || "dark",
        ranking: {
            mode: document.getElementById("ranking-mode")?.value,
            items: rankingItemsAll.slice(0, 500),
        },
        search: {
            mode: document.getElementById("search-mode")?.value,
            tag: document.getElementById("search-tag")?.value,
            sort: document.getElementById("search-sort")?.value,
            page: document.getElementById("search-page")?.value,
            pages: document.getElementById("search-pages")?.value,
            target: document.getElementById("search-target")?.value,
            duration: document.getElementById("search-duration")?.value,
            items: searchItemsRaw.slice(0, 500),
        },
        recommend: { items: recommendItems.slice(0, 500) },
        follow: {
            restrict: document.getElementById("follow-restrict")?.value,
            offset: followCurrentOffset,
            items: followItemsAll.slice(0, 500),
        },
        user_detail: {
            uid: userDetailUid,
            user: currentUserDetail ? { ...currentUserDetail } : null,
            items: userDetailAllItems.slice(0, 500),
        },
    };
    send({ cmd: "save_ui_state", state });
}

function restoreUiState(state) {
    if (!state) return;
    if (state.theme) applyTheme(state.theme);

    if (state.ranking?.mode) {
        setEl("ranking-mode", (el) => (el.value = state.ranking.mode));
    }
    if (state.ranking?.items?.length) {
        rankingItemsAll = state.ranking.items;
        rankingItems = rankingItemsAll.slice();
        buildTagCloud("ranking-tag-cloud", rankingItems, "filterRankingByTags");
        renderTable("ranking-list", rankingItems);
    }

    if (state.search?.tag)
        setEl("search-tag", (el) => (el.value = state.search.tag));
    if (state.search?.items?.length) {
        searchItemsRaw = state.search.items;
        searchItems = searchItemsRaw.slice();
        renderTable("search-list", searchItems);
    }

    if (state.recommend?.items?.length) {
        recommendItems = state.recommend.items;
        renderTable("recommend-list", recommendItems);
    }

    if (state.follow?.items?.length) {
        followItemsAll = state.follow.items;
        followItems = followItemsAll.slice();
        followCurrentOffset = state.follow.offset || 0;
        buildTagCloud(
            "follow-tag-cloud",
            followItems,
            "applyFollowFilter",
            "tags",
        );
        buildTagCloud(
            "follow-author-cloud",
            followItems,
            "applyFollowFilter",
            "author",
        );
        renderTable("follow-list", followItems);
    }

    if (state.user_detail?.uid && state.user_detail?.user) {
        userDetailUid = state.user_detail.uid;
        currentUserDetail = state.user_detail.user;
        renderUserHeaderOnly(currentUserDetail);
        if (state.user_detail.items?.length) {
            userDetailAllItems = state.user_detail.items;
            userDetailItems = userDetailAllItems.slice();
            buildTagCloud(
                "udetail-tag-cloud",
                userDetailItems,
                "applyUserDetailFilter",
            );
            renderTable("user-detail-list", userDetailItems);
        }
    }

    if (state.active_tab) {
        const btn = document.querySelector(
            `nav button[data-tab="${state.active_tab}"]`,
        );
        if (btn) btn.click();
    }
}

// ============ Utilities ============
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

// ============ Boot ============
currentLang = detectLang();
applyTheme(localStorage.getItem("nagato_theme") || "dark");
applyI18n();
renderTokenHelp();
connect();
bindConfigAutoSave();

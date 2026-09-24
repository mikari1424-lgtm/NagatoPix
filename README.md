# NagatoPix

> **A Powerful Pixiv App**
> *Fetch the art. Keep the metadata.*

一个前后端分离的 Pixiv 客户端。基于 Python + WebSocket + 原生 WebUI，用最少的资源完成最多的浏览与下载。

[English Version →](README_EN.md)

---

## 命名由来

> "情报统合思念体制造的人形界面" —— 长门有希

《凉宫春日的忧郁》中，长门有希是"情报统合思念体"制造的人形界面：极少言语、静默运行、精确处理海量信息，把杂乱的数据组织成人类可读的形式。

这与本程序的功能高度契合：它不渲染图像、不参与社交、不做推荐算法，只是安静地在后台抓取、检索、归档、写入元数据——把散落的作品信息整理成结构化的本地资产。

从 **NagatoDownloader** 到 **NagatoPix**，程序的能力边界从"下载"扩展到了"浏览 + 检索 + 归档"。

---

## 为什么会有这个程序

官方 Pixiv 客户端在**单作品浏览**上做到了极致，但在**批量浏览**和**元数据管理**上有先天限制：

| 维度 | 官方客户端 | NagatoPix |
| --- | --- | --- |
| 20 作品页面内存 | ~3.6 GB | ~135 MB |
| 100 作品排行榜内存 | ~10 GB | < 500 MB |
| 排序字段 | 2 个（发布时间、热度） | 全部可获取字段 |
| 排行榜内搜索 | 无 | 支持（标签云 / 作者云） |
| 单次搜索上限 | 无固定上限但资源消耗爆炸 | 6000 条 |
| 批量下载 | 逐张手动 | 队列 + 1~8 并行 |
| ExifTool 元数据 | 无 | 完整支持 |
| 队列持久化 | 无 | 支持（关闭后可续传） |
| 搜索设置 | 基础 | 检索范围 / 时间 / 类型 / 收藏数 |

核心差异不是"功能更多"，而是**设计哲学**：官方客户端的假设是"用户想看所有内容"，本程序的假设是"用户只想浏览元数据、下载少数作品"。前者需要把图像纳入内存模型，后者只需要处理 JSON 元数据。

---

## 特性

### 浏览与发现

- **排行榜**：8 种类型，固定返回 480 条，自动对比昨日榜单并标记新增作品
- **标签搜索**：支持 6000 条上限（200 页批量获取）
- **搜索设置**（可折叠）：
  - 检索范围：标签（部分/完全一致）/ 标题与说明
  - 投稿时间：不限 / 最近一天 / 最近一周 / 最近一月 / **自定义日期范围**
  - 作品类型：插画 / 漫画（动图已排除）
  - 收藏数范围筛选（客户端实时过滤）
- **合并搜索**：作品搜索与用户搜索通过下拉选单切换
- **用户详情**：作品列表 + 用户信息 + 约稿状态
- **作品推荐**：自动 / 基于队列 / 基于历史 / 基于作品 / 高级参数
- **已关注新作**：单次 300 条，支持标签云与作者云筛选
- **标签云 / 作者云**：可折叠，从已获取作品自动生成高频标签与作者

### 下载

- **并行队列**：1~8 工作线程（高速模式），以作品为单位避免文件竞争
- **全局限速同步**：任一任务触发 Rate Limit，所有线程同步等待
- **队列持久化**：每个任务完成后实时保存，关闭程序后可从 `queue.json` 恢复
- **自动启动**：启动程序时，若队列中有已保存的任务，立即开始处理
- **失败重试**：使用 `-m` 忽略次要错误 + 导出 JSON 元数据
- **下载历史**：最近 2000 条自动归档到 `history.json`
- **下载标签页**：实时进度条、详细统计、预设模式切换、线程数调节

### 元数据

- **ExifTool 完整写入**：标题、作者、标签、时间、链接、说明
- **AI / R-15 / R-18 / R-18G 标记**：写入 XMP-dc:subject 和 EXIF:XPKeywords
- **原始文件名保留**：不重命名，直接使用 Pixiv CDN 的原始文件名
- **作品说明换行保留**：`<br/>` 正确转换为换行符
- **失败任务 JSON 导出**：便于人工修复和二次处理
- **双语元数据**：根据界面语言，写入中文或英文标签

### 交互

- **侧边栏导航**：功能一目了然
- **动态悬浮球**：选中作品时出现，实时显示选中数量
- **作品链接直达**：点击标题在新标签页打开 Pixiv 官方作品页
- **作者链接直达**：点击作者名跳转用户详情页
- **多选批量操作**：Ctrl / Shift 多选后一次性加入队列
- **固定控件 + 滚动结果**：筛选参数不随结果滚动
- **多语言界面**：简体中文 / English 一键切换
- **延迟检测**：启动时自动测量到 Cloudflare 的延迟

---

## 快速开始

### 方式一：直接使用打包版（推荐普通用户）

1. 从 [Releases](https://github.com/mikari1424-lgtm/NagatoPix/releases) 下载 `NagatoPix.zip`
2. 解压到任意目录（建议路径不含中文）
3. 双击 `NagatoPix.exe`
4. 程序自动启动服务并在浏览器中打开界面

**首次使用需要配置 RefreshToken**（见下节）。

### 方式二：从源码运行（推荐开发者）

```bash
git clone https://github.com/mikari1424-lgtm/NagatoPix.git
cd NagatoPix
pip install -r requirements.txt
python pixiv_server.py
```

---

## 配置 RefreshToken

**Pixiv 已不再支持用户名密码登录**，本程序使用 RefreshToken 认证。

点击设置面板中"刷新令牌"旁的 **❓** 图标，程序内置了详细的获取指南。简要步骤：

### 方式一：Pixiv-Viewer 网页端（推荐）

1. 安装 [Redirector](https://einaregilsson.com/redirector/) 和 [Tampermonkey](https://www.tampermonkey.net/index.php)
2. 导入规则：`https://pixiv.pictures/helper/Redirector.json`
3. 安装[登录工具脚本](https://fastly.jsdelivr.net/gh/asadahimeka/pixiv-viewer@master/public/helper/helper.user.js)
4. 访问 `https://pixiv.pictures/account/login`，选择 App API (OAuth) 登录
5. 在[设置页面](https://pixiv.pictures/setting/others)导出 Token

### 方式二：pxder（Node.js）

```bash
npm i -g pxder
pxder --login
pxder --export-token
```

### 方式三：PixEz（移动端）

从 [GitHub](https://github.com/Notsfsssf/pixez-flutter) 下载，登录后 → 更多 → 账户信息 → Token export

> 原始教程：[https://www.nanoka.top/posts/e78ef86/](https://www.nanoka.top/posts/e78ef86/)

**注意**：如果无法直连 Pixiv，请先在设置中配置代理（支持 socks5 / socks4 / http）。

---

## 使用指南

### 侧边栏

| 图标 | 功能 |
| --- | --- |
| ✨ | 作品推荐 |
| 👥 | 已关注新作 |
| 🏆 | 排行榜 |
| 🔍 | 标签搜索 / 用户搜索 |
| 📋 | 用户详情 |
| ⬇️ | 下载队列 |
| ⚙️ | 设置 |

### 作品推荐

- **自动推荐**：基于 Pixiv 默认算法
- **根据下载队列**：以队列中前 30 个作品为种子
- **根据历史记录**：以最近 30 条下载记录为种子
- **根据作品**：输入 PID，推荐相似作品
- **高级推荐**：手动控制 `bookmark_illust_ids`、`viewed` 等参数

最大返回 120 条（Pixiv API 限制）。

### 已关注新作

单次加载 300 条（10 页批量）。支持：

- 范围筛选：全部 / 公开 / 私密
- 标签云筛选（点击 chip 高亮）
- 作者云筛选（点击 chip 高亮）
- 两个云之间为 **AND** 关系

### 排行榜

8 种类型（日榜、周榜、月榜、男性向、女性向、原创、新人、R-18），固定返回 **480 条**。

程序自动拉取今日与昨日榜单，**今日新出现的作品会显示绿色 `NEW` 徽章**。

### 标签搜索

在搜索标签页顶部下拉选单中选择「作品」：

- **标签**：完全匹配 / 部分匹配 / 标题与说明
- **排序**：最新 / 最早
- **页码 + 页数**：从起始页自动向后步进 N 页（最多 200 页 = 6000 条）
- **搜索设置**（点击展开）：
  - 检索范围
  - 投稿时间（含自定义日期范围）
  - 作品类型（插画 / 漫画，动图已排除）
  - 收藏数范围（客户端实时过滤）

### 用户搜索 / 用户详情

在搜索标签页下拉选单中选择「用户」：

- 输入关键词搜索用户名 / 账户名
- 点击用户名跳转用户详情
- 用户详情自动加载该用户全部作品，支持标签云筛选

### 下载队列

在任意结果列表中：

1. **多选作品**（Ctrl / Shift 点击行）
2. 右下角出现**悬浮球**，显示选中数量
3. 点击悬浮球，一键加入下载队列

切换到「下载」标签页：

- **进度条**：已处理 / 总数
- **统计面板**：待处理、已处理、失败、工作线程、状态
- **预设切换**：
  - 「普通」：单线程，稳
  - 「高速」：1–8 线程并行
- **操作按钮**：重试失败、清空队列、停止

**右下角 `+` 按钮**：打开「添加任务」模态框，包含：

- **手动输入**：单个 URL / ID，或批量每行一个
- **收藏夹导入**：选择浏览器导出的 HTML 文件

### 设置

- **账号**：RefreshToken（附带 ❓ 内置指南）
- **界面语言**：自动 / 简体中文 / English
- **下载目录**、**代理**、**下载延迟**、**API 延迟**
- **最大重试次数**、**限速等待时长**、**默认结果数**

---

## 架构

```text
┌──────────────────────────────────────────┐
│  浏览器（WebUI）                          │
│  index.html + style.css + main.js        │
│  + i18n.js                               │
└────────────┬─────────────────────────────┘
             │ WebSocket (/ws)
             │ HTTP (/proxy_image)
┌────────────▼─────────────────────────────┐
│  aiohttp 服务器（pixiv_server.py）        │
│  ├─ WebBridge（WebSocket 广播）          │
│  ├─ DownloadWorker（1~8 并行线程）       │
│  │   ├─ PixivAPI（pixivpy3 封装）        │
│  │   ├─ RateLimiter（全局限速同步）      │
│  │   └─ ExifToolWrapper                  │
│  └─ 静态资源路由                          │
└──────────────────────────────────────────┘
```

### 关键设计

| 组件 | 职责 |
| --- | --- |
| `RateLimiter` | 任一工作线程触发限速时，通过 `threading.Condition` 让所有线程同步等待 |
| `WebBridge` | 后端状态 → WebSocket 广播到所有连接的客户端 |
| `DownloadWorker` | 队列消费、失败记录、实时持久化 |
| `ExifToolWrapper` | 每次调用使用独立临时参数文件，CStr 模式保留换行 |
| `proxy_image` | 转发 Pixiv CDN 图像，绕过 Referer 防盗链 |

### 数据文件

```text
NagatoPix/
├── NagatoPix.exe
├── config.toml                # 配置（首次运行自动创建）
├── queue.json                 # 队列（实时保存）
├── history.json               # 下载历史（最近 2000 条）
├── logs/
│   └── nagato-YYYYMMDD-HHMMSS.log
└── _internal/
    ├── webui/                 # 前端资源
    └── plugins/
        ├── ExifTool.exe
        └── exiftool_files/
```

---

## 从源码构建

### 依赖

```bash
pip install -r requirements.txt
```

`requirements.txt`：

```text
aiohttp
pixivpy3
requests
beautifulsoup4
tomli; python_version < "3.11"
```

### 打包为独立可执行文件

```bash
pip install pyinstaller
pyinstaller NagatoPix.spec --noconfirm
```

输出位于 `dist/NagatoPix/`，整个目录压缩后即可分发。

打包前确保 `plugins/` 目录包含完整的 ExifTool：

```text
plugins/
├── ExifTool.exe
└── exiftool_files/          # 必须与 exe 同级
```

---

## 已知限制

- **不可见作品**：部分作品在网页上可见但 API 返回 `visible: false`，这是 Pixiv 的 API 级过滤，无法绕过
- **小说**：本版本已移除小说相关功能
- **"最热"排序**：依赖 Pixiv Premium 会员，已移除
- **Rate Limit**：非日本 IP 访问 API 更容易触发限速，程序会自动等待重试
- **ExifTool 可选**：若未找到 ExifTool，图片仍会下载但元数据不会写入

---

## 常见问题

**Q: 端口被占用？**
A: 程序会自动在 8765–8864 范围内寻找空闲端口。

**Q: 浏览器白屏？**
A: 检查控制台是否有错误，或访问 `http://127.0.0.1:<端口>/` 手动确认。

**Q: 下载很慢？**
A: 在下载标签页切换到「高速」预设，并调高线程数（最大 8）。

**Q: 收藏数筛选为什么只对当前结果生效？**
A: 服务端收藏数筛选参数需要 Pixiv Premium 会员，普通用户会被静默忽略。因此本程序改为客户端实时过滤。如需筛选更大范围，先在「页数」中填更大的值获取更多结果。

**Q: 如何清空历史记录？**
A: 直接删除 `history.json` 文件即可。

**Q: 支持 macOS / Linux 吗？**
A: 代码跨平台，但需要自行替换 ExifTool 为对应平台的版本，并修改 `plugins/` 目录中的文件名。

**Q: 如何切换语言？**
A: 侧边栏底部有语言切换下拉框，或在设置中选择。语言设置会持久化。

---

## 致谢

- [pixivpy3](https://github.com/upbit/pixivpy) — Pixiv API 封装
- [ExifTool](https://exiftool.org/) — 元数据写入
- [aiohttp](https://docs.aiohttp.org/) — 异步 HTTP 服务器
- [长门有希](https://zh.wikipedia.org/wiki/長門有希) — 命名灵感

---

## 许可证

GPL v3 License

---

## 免责声明

本程序为个人学习用途。使用本程序下载的内容版权归原作者所有，请勿用于商业用途或二次分发。请遵守 Pixiv 的[服务条款](https://www.pixiv.net/terms.php)和当地法律法规。

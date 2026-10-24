# pixivpy3 AppPixivAPI 使用说明

## 1. **免责声明**

本文只收录已经确认的内容。所有无法确认语义的字段（枚举取值、未观察到的对象结构、个人资料的 ID 映射等）已从文档中移除，不再列出，以免误导。表格中出现的 `null`/`0`/`{}`/`[]` 只是「本次转储里的值」，不代表字段含义；标「不在本文范围内」的字段仅有名字和类型。

## 2. 快速开始

### 2.1 安装与导入

```bash
pip install pixivpy3
```

```python
from pixivpy3 import AppPixivAPI, PixivError
```

`AppPixivAPI` 使用 `https://app-api.pixiv.net` 作为 API Host，默认模拟 iOS 客户端：

- `app-os: ios`
- `app-os-version: 14.6`
- `user-agent: PixivIOSApp/7.13.3 (iOS 14.6; iPhone13,2)`

这些默认头由 `no_auth_requests_call()` 自动添加。

### 2.2 认证

```python
import os

from pixivpy3 import AppPixivAPI, PixivError

api = AppPixivAPI()
try:
    token = api.auth(refresh_token=os.environ["PIXIV_REFRESH_TOKEN"])
except PixivError as exc:
    print("认证失败：", exc.reason)
    raise
print("当前账号 UID：", api.user_id)
```

`auth()` 的签名：

```python
def auth(username=None, password=None, refresh_token=None, headers=None)
```

行为：

- 用 `refresh_token` 向 `https://oauth.secure.pixiv.net/auth/token` 换取 `access_token`。
- 成功后把 `access_token`、`refresh_token`、`user_id` 写入实例；后续请求自动带 `Authorization: Bearer ...`。
- 返回值为 token 响应（`response.access_token`、`response.refresh_token`、`response.user.id` 等）。
- 也支持 `auth(username=..., password=...)`；refresh_token 方式更适合脚本。

> **安全提示**：`demo.py` 第 7 行把 refresh_token 硬编码在源码里。refresh_token 等同于账号凭据，建议改用环境变量或本地配置文件，并避免提交到仓库。本文不重复该 token 的值。

### 2.3 demo.py 的组织方式

`demo.py` 的结构很直接：

1. 第 5 行创建 `AppPixivAPI()`。
2. 第 7–14 行定义 refresh_token、数据目录和 5 个输入 ID/关键词。
3. 第 16 行调用 `api.auth(refresh_token=...)`。
4. 第 18–20 行定义 `export_json_data()`，用 `json.dumps(..., ensure_ascii=False, indent=4)` 写文件。
5. 第 23–73 行依次调用 9 个方法，并把返回值写入 `AppAPI_dump/`。

`export_json_data()` 的实现：

```python
def export_json_data(response, filename):
    with open(DATA_DIR / filename, "w", encoding="utf-8") as f:
        f.write(json.dumps(response, ensure_ascii=False, indent=4))
```

`ensure_ascii=False` 保留日文、中文等非 ASCII 字符；`indent=4` 便于人工比对字段。

> `demo.py` 没有 `if __name__ == "__main__":` 保护，导入模块时就会执行全部网络请求。复用时建议把调用包进 `main()`。

### 2.4 最小示例

```python
import json
import os
from pathlib import Path

from pixivpy3 import AppPixivAPI

OUT = Path("AppAPI_dump")
OUT.mkdir(exist_ok=True)

api = AppPixivAPI()
api.auth(refresh_token=os.environ["PIXIV_REFRESH_TOKEN"])

resp = api.search_illust(
    word="NTE",
    search_target="exact_match_for_tags",
    sort="date_desc",
    filter="",
    offset=0,
)

(OUT / "search_results.json").write_text(
    json.dumps(resp, ensure_ascii=False, indent=4),
    encoding="utf-8",
)
```

---

## 3. 通用约定

### 3.1 返回值是“可属性访问的 dict”

pixivpy3 把 JSON 解析为 `JsonDict`（`dict` 的子类），因此下面两种写法等价：

```python
resp.illust.id
resp["illust"]["id"]
```

访问不存在的属性不会抛 `KeyError`，而是返回 `None`（`JsonDict.__getattr__` 调用 `self.get(attr)`）。这对可选字段很方便，但也容易把“字段不存在”和“字段值为 null”混在一起，必要时用 `"key" in resp` 判断。

上述 API 方法都是同步调用，直接返回解析后的 JSON，没有额外的分页对象。

### 3.2 `filter`：`for_ios` 与空字符串

pixivpy3 的多数列表方法默认 `filter='for_ios'`；传 `filter=''` 时 query 中会保留一个空的 `filter=`（转储的 `next_url` 可以直接看到）。

- `filter='for_ios'`：发送 `filter=for_ios`。
- `filter=''`：发送空的 `filter=`。

具体哪些作品会被服务端过滤由 Pixiv 决定，本文不推断过滤规则。本次 5 个列表转储都是 `filter=''` 的结果；详情类调用没有这个参数。

### 3.3 分页：`next_url` + `parse_qs`

列表响应通常带 `next_url`，它已经把下一页所需的 query 参数拼好。pixivpy3 提供类方法 `parse_qs()` 把 URL 拆成可直接传回方法的 dict：

```python
resp = api.search_illust(word="NTE", filter="", offset=0)
while True:
    for illust in resp.illusts:
        print(illust.id, illust.title)

    if not resp.next_url:
        break
    params = api.parse_qs(resp.next_url)
    resp = api.search_illust(**params)
```

`parse_qs()` 会：

- 去掉 `next_url` 的 scheme/host/path，只保留 query。
- 把 `viewed[0]`、`viewed[1]` 这类带方括号的键合并成 `viewed` 列表。
- 把 `seed_illust_ids[]` 合并成 `seed_illust_ids` 列表。
- 对普通键取最后一个值。
- 传入 `None` 时返回 `None`。

不同列表的翻页参数不同，直接整体复用 `next_url` 最稳妥：

- 搜索：`offset=90`
- 新作：`max_illust_id=150334557`
- 排行：`offset=30`
- 推荐：`offset=0`，同时带一长串 `viewed[]`

### 3.4 图片 URL

Illust 的图片有两层：

| 位置 | 键 | 说明 |
| --- | --- | --- |
| `illust.image_urls` | `square_medium` / `medium` / `large` | 作品级缩略图，**不含** `original` |
| `illust.meta_single_page` | `original_image_url` | 单页作品的原图；多页作品该对象为 `{}` |
| `illust.meta_pages[].image_urls` | `square_medium` / `medium` / `large` / `original` | 多页作品每一页的图；单页作品该数组为 `[]` |

本次转储中的 URL 规律（）：

- `square_medium`：`.../c/360x360_10_webp/..._square1200.jpg`
- `medium`：`.../c/540x540_70/..._master1200.jpg`
- `large`：`.../c/600x1200_90_webp/..._master1200.jpg`
- `original`：`.../img-original/..._p0.jpg` 或 `..._p0.png`

尺寸参数由服务端生成，不保证长期固定。原图扩展名可能是 `.jpg`、`.png` 等，下载时建议从 URL 取扩展名。

`i.pximg.net` 有 Referer 校验。`AppPixivAPI.download()` 默认会带：

```text
Referer: https://app-api.pixiv.net/
```

如果自己用 `requests` 下载，需要显式设置这个 Referer。

### 3.5 时间与文本

- `illust.create_date`、`novel.create_date`：ISO 8601，带时区，例如 `2026-09-29T00:00:41+09:00`。
- `novel_text.cdate`：只有日期，例如 `2026-06-23`。
- `illust.caption`：说明文，**可能包含 HTML 片段**，例如 `<br />`、`<strong>`、`<a href="pixiv://illusts/...">`。展示前应转义或清洗，不要直接当纯文本。
- `novel_text.text`：正文是含 `\n` 转义的裸文字内容，没有包装结构，可直接使用（见 4.8）。
- `tags[].translated_name`：可能为 `null`；是否返回翻译与请求头 `Accept-Language` 有关（可用 `api.set_accept_language("zh-cn")` 设置，）。

### 3.6 错误处理

pixivpy3 的异常类型是 `PixivError`：

```python
from pixivpy3 import PixivError

try:
    resp = api.illust_detail(91108678)
except PixivError as exc:
    print(exc.reason)
    print(exc.header)
    print(exc.body)
```

- `reason`：错误描述。
- `header`：HTTP 响应头（可能为 `None`）。
- `body`：HTTP 响应正文（可能为 `None`）。

`requests_call()` 会把底层网络异常包装成 `PixivError`，`parse_result()` 解析失败也会抛 `PixivError`。

---

## 4. 方法参考

### 4.1 `search_illust()`

```python
def search_illust(
    word,
    search_target="partial_match_for_tags",
    sort="date_desc",
    duration=None,
    start_date=None,
    end_date=None,
    filter="for_ios",
    search_ai_type=None,
    offset=None,
    req_auth=True,
)
```

- 端点：`GET /v1/search/illust`
- 转储：[`search_results.json`](../_demo/AppAPI/AppAPI_dump/search_results.json)
- 返回：`illusts`、`next_url`、`search_span_limit`

| 参数 | 类型 | 默认 | demo 值 | 说明 |
| --- | --- | --- | --- | --- |
| `word` | `str` | 必填 | `"NTE"` | 搜索关键词 |
| `search_target` | `str` | `partial_match_for_tags` | `exact_match_for_tags` | 可选：`partial_match_for_tags`、`exact_match_for_tags`、`title_and_caption`、`keyword`、`""` |
| `sort` | `str` | `date_desc` | `date_desc` | 可选：`date_desc`、`date_asc`、`popular_desc`、`""`；源码注释说明 `popular_desc` 为会员的热门排序 |
| `duration` | `str \| None` | `None` | 未传 | 可选：`within_last_day`、`within_last_week`、`within_last_month` |
| `start_date` | `str \| None` | `None` | 未传 | 起始日期，格式 `YYYY-MM-DD` |
| `end_date` | `str \| None` | `None` | 未传 | 结束日期，格式 `YYYY-MM-DD` |
| `filter` | `str` | `for_ios` | `""` | `for_ios` 或 `""` |
| `search_ai_type` | `int \| None` | `None` | 未传 | 源码注释：`0` 过滤 AI 生成作品，`1` 显示 AI 生成作品 |
| `offset` | `int \| str \| None` | `None` | `60` | 偏移量；本次每页 30 条，下一页 `next_url` 为 `offset=90` |
| `req_auth` | `bool` | `True` | 默认 | 是否要求登录态 |

本次返回 30 条作品，`search_span_limit` 为 `31536000`（该字段的含义不在本文范围内）。

> 源码用 `if search_ai_type:` 判断是否把该参数写入 query；因此传 `0` 时不会发送这个参数。如需“过滤 AI 生成作品”，不能只依赖传 `0`。

### 4.2 `illust_new()`

```python
def illust_new(
    content_type="illust",
    filter="for_ios",
    max_illust_id=None,
    req_auth=True,
)
```

- 端点：`GET /v1/illust/new`
- 转储：[`illust_new.json`](../_demo/AppAPI/AppAPI_dump/illust_new.json)
- 返回：`illusts`、`next_url`

| 参数 | 类型 | 默认 | demo 值 | 说明 |
| --- | --- | --- | --- | --- |
| `content_type` | `str` | `illust` | 默认 `illust` | 可选：`illust`、`manga`、`""` |
| `filter` | `str` | `for_ios` | `""` | `for_ios` 或 `""` |
| `max_illust_id` | `int \| str \| None` | `None` | 未传 | 翻页用；本次 `next_url` 使用最后一条作品的 ID：`max_illust_id=150334557` |
| `req_auth` | `bool` | `True` | 默认 | 是否要求登录态 |

本次返回 30 条作品。列表中的作品可能带 `restriction_attributes`（敏感内容标识，见 5.1）。

### 4.3 `illust_recommended()`

```python
def illust_recommended(
    content_type="illust",
    include_ranking_label=True,
    filter="for_ios",
    max_bookmark_id_for_recommend=None,
    min_bookmark_id_for_recent_illust=None,
    offset=None,
    include_ranking_illusts=None,
    bookmark_illust_ids=None,
    include_privacy_policy=None,
    viewed=None,
    req_auth=True,
)
```

- 端点：`GET /v1/illust/recommended`；当 `req_auth=False` 时改用 `/v1/illust/recommended-nologin`
- 转储：[`illust_recommended.json`](../_demo/AppAPI/AppAPI_dump/illust_recommended.json)
- 返回：`illusts`、`ranking_illusts`、`contest_exists`、`privacy_policy`、`next_url`

| 参数 | 类型 | 默认 | demo 值 | 说明 |
| --- | --- | --- | --- | --- |
| `content_type` | `str` | `illust` | 默认 | 可选：`illust`、`manga`、`""` |
| `include_ranking_label` | `bool \| str` | `True` | 默认 | 是否包含排行标签 |
| `filter` | `str` | `for_ios` | `""` | `for_ios` 或 `""` |
| `max_bookmark_id_for_recommend` | `int \| str \| None` | `None` | 未传 | 推荐翻页参数 |
| `min_bookmark_id_for_recent_illust` | `int \| str \| None` | `None` | 未传 | 新作推荐参数 |
| `offset` | `int \| str \| None` | `None` | 未传 | 偏移量 |
| `include_ranking_illusts` | `bool \| str \| None` | `None` | 未传 | 是否包含排行作品 |
| `bookmark_illust_ids` | `str \| list \| None` | `None` | 未传 | 源码只在 `req_auth=False` 时使用 |
| `include_privacy_policy` | `str \| list \| None` | `None` | 未传 | 是否包含隐私政策 |
| `viewed` | `str \| list[str] \| None` | `None` | 未传 | 已浏览作品 ID；`next_url` 中表现为 `viewed[0]`、`viewed[1]`… |
| `req_auth` | `bool` | `True` | 默认 | 是否要求登录态 |

本次返回 86 条作品；`ranking_illusts` 为空数组，`contest_exists` 为 `false`，`privacy_policy` 为空对象（非空时的结构不在本文范围内）。`next_url` 中 `offset=0`，但带有一长串 `viewed[]`，翻页时应整体使用 `next_url` 的参数。

### 4.4 `illust_ranking()`

```python
def illust_ranking(
    mode="day",
    filter="for_ios",
    date=None,
    offset=None,
    req_auth=True,
)
```

- 端点：`GET /v1/illust/ranking`
- 转储：[`illust_ranking.json`](../_demo/AppAPI/AppAPI_dump/illust_ranking.json)
- 返回：`illusts`、`next_url`

| 参数 | 类型 | 默认 | demo 值 | 说明 |
| --- | --- | --- | --- | --- |
| `mode` | `str` | `day` | `day` | 可选：`day`、`week`、`month`、`day_male`、`day_female`、`week_original`、`week_rookie`、`day_manga`、`day_r18`、`day_male_r18`、`day_female_r18`、`week_r18`、`week_r18g`、`""` |
| `filter` | `str` | `for_ios` | `""` | `for_ios` 或 `""` |
| `date` | `str \| None` | `None` | 未传 | 日期，格式 `YYYY-MM-DD` |
| `offset` | `int \| str \| None` | `None` | 未传 | 偏移量；本次下一页为 `offset=30` |
| `req_auth` | `bool` | `True` | 默认 | 是否要求登录态 |

本次返回 30 条作品，响应中没有单独的 `ranking_date` 字段。

### 4.5 `illust_detail()`

```python
def illust_detail(illust_id, req_auth=True)
```

- 端点：`GET /v1/illust/detail`
- 转储：[`illust_detail.json`](../_demo/AppAPI/AppAPI_dump/illust_detail.json)
- 返回：`illust`

| 参数 | 类型 | 默认 | demo 值 | 说明 |
| --- | --- | --- | --- | --- |
| `illust_id` | `int \| str` | 必填 | `91108678` | 作品 ID |
| `req_auth` | `bool` | `True` | 默认 | 是否要求登录态 |

本次样本是一个不可见作品：`visible=false`、`title` 为空、`user.name` 与 `user.account` 为空、所有图片 URL 都是 `limit_unviewable_360.png` 占位图、`width`/`height` 为 `100`/`100`。这是 Pixiv 对 App API 的服务端限制，不是作品上传时设置的限制；据额外测试，这类作品在网页端可见。`limit_unviewable_360.png` 是 Pixiv 默认占位图，`100`/`100` 是 `width`/`height` 字段的固定占位值。本次详情响应包含 `comment_access_control`，但没有列表响应里的 `event_banners` 和 `restriction_attributes`。

### 4.6 `user_detail()`

```python
def user_detail(user_id, filter="for_ios", req_auth=True)
```

- 端点：`GET /v1/user/detail`
- 转储：[`user_detail.json`](../_demo/AppAPI/AppAPI_dump/user_detail.json)
- 返回：`user`、`profile`、`profile_publicity`、`workspace`

| 参数 | 类型 | 默认 | demo 值 | 说明 |
| --- | --- | --- | --- | --- |
| `user_id` | `int \| str` | 必填 | `26385162` | 用户 ID |
| `filter` | `str` | `for_ios` | `""` | `for_ios` 或 `""` |
| `req_auth` | `bool` | `True` | 默认 | 是否要求登录态 |

字段见 5.2、5.3。

### 4.7 `novel_detail()`

```python
def novel_detail(novel_id, req_auth=True)
```

- 端点：`GET /v2/novel/detail`
- 转储：[`novel_detail.json`](../_demo/AppAPI/AppAPI_dump/novel_detail.json)
- 返回：`novel`

| 参数 | 类型 | 默认 | demo 值 | 说明 |
| --- | --- | --- | --- | --- |
| `novel_id` | `int \| str` | 必填 | `28423494` | 小说 ID |
| `req_auth` | `bool` | `True` | 默认 | 是否要求登录态 |

字段见 5.4。

### 4.8 `novel_text()`

```python
def novel_text(novel_id, req_auth=True)
```

- 状态：源码注释标记为 **deprecated**
- 实现：`/v1/novel/text` 已不存在，pixivpy3 改为调用 `webview_novel()`，从 webview HTML 中提取 JSON，再追加 `novel_text` 字段
- 转储：[`novel_text.json`](../_demo/AppAPI/AppAPI_dump/novel_text.json)
- 返回：**没有外层包装**，直接是 webview 小说对象

| 参数 | 类型 | 默认 | demo 值 | 说明 |
| --- | --- | --- | --- | --- |
| `novel_id` | `int \| str` | 必填 | `28423494` | 小说 ID |
| `req_auth` | `bool` | `True` | 默认 | 是否要求登录态 |

注意：

- 字段是 camelCase（`seriesId`、`userId`、`cdate`、`aiType` 等），与 App API 的 snake_case 不同。
- `novel_text` 字段是 pixivpy3 追加的，值等于 `text`（3.7.5 源码）。
- `id`、`userId`、`seriesId` 在该响应中是字符串，而 `novel_detail` 中对应字段是整数。
- 本次转储 `text` 与 `novel_text` 都已被手动清空为 `""`，不是接口原始返回。

正文格式：`text` 是一个**包含 `\n` 转义的字符串**，内容就是正文本身——裸文字内容，没有外层包装结构（不是 JSON 对象）。直接用即可，例如：

```python
resp = api.novel_text(28423494)
content = resp.text  # 正文裸文字，含 \n 转义
```

字段见 5.5。

### 4.9 `ugoira_metadata()`

```python
def ugoira_metadata(illust_id, req_auth=True)
```

- 端点：`GET /v1/ugoira/metadata`
- 转储：[`ugoira_detail.json`](../_demo/AppAPI/AppAPI_dump/ugoira_detail.json)
- 返回：`ugoira_metadata`

| 参数 | 类型 | 默认 | demo 值 | 说明 |
| --- | --- | --- | --- | --- |
| `illust_id` | `int \| str` | 必填 | `150060073` | 动图作品 ID |
| `req_auth` | `bool` | `True` | 默认 | 是否要求登录态 |

该接口只返回 zip 地址和帧信息，不返回作品标题、作者等；需要作品信息时另调 `illust_detail()`。

字段见 5.6。

---

## 5. 数据结构

### 5.1 Illust（插画/漫画作品）

来源：搜索、新作、推荐、排行、详情。列表与详情的字段略有差异。

| 字段 | 类型 | 本次示例 | 说明 |
| --- | --- | --- | --- |
| `id` | `int` | `150146250` | 作品 ID |
| `title` | `str` | `"일로이 수영복 스킨 [이환]"` | 标题；不可见作品为空串 |
| `type` | `str` | `"illust"` / `"manga"` | 作品类型；转储中见这两种 |
| `image_urls` | `object` | `{square_medium, medium, large}` | 作品级缩略图；不含 `original` |
| `caption` | `str` | `"NTEまんが58<br />..."` | 说明文，含 HTML 片段 |
| `restrict` | `int` | `0` | 限制标志；含义不在本文范围内 |
| `user` | `object` | `{id, name, account, ...}` | 作者，字段随上下文变化，见 5.2 |
| `tags` | `array` | `[{"name": "NTE", "translated_name": null}]` | 标签数组；元素结构见 5.8 |
| `tools` | `array[str]` | `["SAI", "CLIP STUDIO PAINT"]` | 作画工具；无工具时为 `[]` |
| `create_date` | `str` | `"2026-09-29T00:00:41+09:00"` | 投稿时间，ISO 8601 |
| `page_count` | `int` | `2` | 页数 |
| `width` | `int` | `1000` | 宽度（px） |
| `height` | `int` | `1498` | 高度（px） |
| `sanity_level` | `int` | `2` / `4` | 安全/内容级别字段；其余取值含义不在本文范围内 |
| `x_restrict` | `int` | `0` | 限制标记；`1`=R-18，`2`=R-18G；转储中为 `0` |
| `series` | `null \| object` | `{"id": 351467, "title": "こんなん読みたい"}` | 所属系列；无系列时为 `null` |
| `meta_single_page` | `object` | `{"original_image_url": "..."}` 或 `{}` | 单页作品的原图；多页时为 `{}` |
| `meta_pages` | `array` | `[{"image_urls": {..., "original": "..."}}]` | 多页作品每页图片；单页时为 `[]` |
| `total_view` | `int` | `47601` | 浏览数 |
| `total_bookmarks` | `int` | `8929` | 收藏数 |
| `is_bookmarked` | `bool` | `false` | 当前登录账号是否已收藏 |
| `visible` | `bool` | `true` / `false` | 是否可见；`false` 时的表现见下文 |
| `is_muted` | `bool` | `false` | 是否被屏蔽；转储中均为 `false` |
| `seasonal_effect_animation_urls` | `null` | `null` | 作品活动动态效果；转储中均为 `null` |
| `event_banners` | `null` | `null` | 作品参与的活动；本次只出现在列表响应，转储中均为 `null` |
| `illust_ai_type` | `int` | `0` / `1` | 作品 AI 标记：`0`=无标记，`1`=原创，`2`=AI 生成 |
| `illust_book_style` | `int` | `0` | 书籍样式标志；取值含义不在本文范围内 |
| `request` | `null \| object` | `null` 或对象 | 约稿标记；`null` 表示未声明，非空对象表示约稿信息 |
| `restriction_attributes` | `array[str]` | `["restricted_mode"]` | 敏感内容标识；本次只出现在列表响应 |
| `comment_access_control` | `int` | `0` | 评论设置：`0`=允许评论，`1`=作者关闭评论区 |

#### **字段存在性差异**

- 本次列表响应（搜索、新作、推荐、排行）有 `event_banners`，没有 `comment_access_control`。
- 本次详情响应有 `comment_access_control`，没有 `event_banners`、`restriction_attributes`。
- `restriction_attributes` 只在部分列表作品上出现；本次 `illust_new` 的 30 条全部有，搜索、排行、推荐只有部分作品有。

#### **`visible=false` 的样本（节选）**

`illust_detail.json` 中的作品：

```json
{
    "id": 91108678,
    "title": "",
    "image_urls": {
        "square_medium": "https://s.pximg.net/common/images/limit_unviewable_360.png",
        "medium": "https://s.pximg.net/common/images/limit_unviewable_360.png",
        "large": "https://s.pximg.net/common/images/limit_unviewable_360.png"
    },
    "user": {
        "id": 1960050,
        "name": "",
        "account": "",
        "profile_image_urls": {
            "medium": "https://s.pximg.net/common/images/no_profile.png"
        },
        "is_accept_request": false
    },
    "tags": [],
    "tools": [],
    "page_count": 1,
    "width": 100,
    "height": 100,
    "visible": false
}
```

可以确认的现象：

- `title`、`user.name`、`user.account` 为空字符串。
- `tags`、`tools` 为空数组。
- 图片全部是 `limit_unviewable_360.png`。
- `width`/`height` 为 `100`/`100`，是 `width`/`height` 字段的固定占位值。
- `total_view`、`total_bookmarks` 为 `0`。
- `user.id` 仍然保留（`1960050`）。

不可见的原因是 Pixiv 对 App API 的服务端限制，而不是作品上传时设置的限制；据额外测试，这类作品在网页端可见。`limit_unviewable_360.png` 是 Pixiv 默认占位图（固定占位图）。

#### **`request` 非空时的对象形状**

```json
{
    "request_info": {
        "fan_user_id": 2890122,
        "collaborate_status": {
            "collaborating": false,
            "collaborate_anonymous_flag": false,
            "collaborate_user_samples": []
        },
        "role": "others"
    },
    "request_users": [
        {
            "id": 2890122,
            "name": "ヴィード",
            "account": "vied_rebellion",
            "profile_image_urls": {
                "medium": "https://i.pximg.net/user/profile/img/..."
            },
            "is_followed": false,
            "is_access_blocking_user": false,
            "is_accept_request": false
        }
    ]
}
```

`request` 非空表示存在约稿信息；其中各子字段的语义不在本文范围内。

### 5.2 User（用户）

`user` 对象在不同上下文中的字段不同（）：

| 上下文 | 字段 |
| --- | --- |
| `illust.user`（列表） | `id`, `name`, `account`, `profile_image_urls`, `is_followed`, `is_accept_request` |
| `illust.user`（详情） | `id`, `name`, `account`, `profile_image_urls`, `is_accept_request` |
| `novel.user` | `id`, `name`, `account`, `profile_image_urls`, `is_followed`, `is_accept_request` |
| `user_detail.user` | `id`, `name`, `account`, `profile_image_urls`, `comment`, `is_followed`, `is_access_blocking_user` |
| `request.request_users[]` | `id`, `name`, `account`, `profile_image_urls`, `is_followed`, `is_access_blocking_user`, `is_accept_request` |

| 字段 | 类型 | 本次示例 | 说明 |
| --- | --- | --- | --- |
| `id` | `int` | `74882740` | 用户 ID |
| `name` | `str` | `"仮病人"` | 昵称 |
| `account` | `str` | `"user_mfkt7878"` | 账号 ID |
| `profile_image_urls` | `object` | `{"medium": "..."}` | 头像；本次只出现 `medium` |
| `comment` | `str` | `""` | 个人简介；只出现在 `user_detail.user` |
| `is_followed` | `bool` | `false` | 当前登录账号是否关注该用户 |
| `is_access_blocking_user` | `bool` | `false` | 黑名单状态 |
| `is_accept_request` | `bool` | `false` | 约稿接受状态：`false`=不接受，`true`=接受 |

头像占位图：`https://s.pximg.net/common/images/no_profile.png`。

### 5.3 Profile、ProfilePublicity、Workspace

#### `profile`

| 字段 | 类型 | 本次示例 | 说明 |
| --- | --- | --- | --- |
| `webpage` | `str` | `""` | 主页 URL |
| `gender` | `str` | `"male"` | 性别 |
| `birth` | `str` | `"1997-05-06"` | 生日（完整日期） |
| `birth_day` | `str` | `"05-06"` | 生日（月-日） |
| `birth_year` | `int` | `1997` | 出生年 |
| `region` | `str` | `"China"` | 地区（自由文本） |
| `address_id` | `int` | `48` | 地址 ID；具体映射不在本文范围内 |
| `country_code` | `str` | `"CN"` | 国家/地区代码 |
| `job` | `str` | `""` | 职业（自由文本） |
| `job_id` | `int` | `0` | 职业 ID；具体映射不在本文范围内 |
| `total_follow_users` | `int` | `271` | 关注数 |
| `total_mypixiv_users` | `int` | `1` | mypixiv 数 |
| `total_illusts` | `int` | `150` | 插画数 |
| `total_manga` | `int` | `0` | 漫画数 |
| `total_novels` | `int` | `0` | 小说数 |
| `total_illust_bookmarks_public` | `int` | `75` | 公开收藏数 |
| `total_illust_series` | `int` | `0` | 插画系列数 |
| `total_novel_series` | `int` | `0` | 小说系列数 |
| `background_image_url` | `null \| str` | `null` | 背景图 URL |
| `twitter_account` | `str` | `""` | Twitter 账号 |
| `twitter_url` | `str` | `""` | Twitter URL |
| `pawoo_url` | `null \| str` | `null` | Pawoo URL |
| `is_premium` | `bool` | `false` | 是否高级会员 |
| `is_using_custom_profile_image` | `bool` | `true` | 是否使用自定义头像 |

#### `profile_publicity`

| 字段 | 类型 | 本次值 | 说明 |
| --- | --- | --- | --- |
| `gender` | `str` | `"public"` | 公开状态 |
| `region` | `str` | `"public"` | 公开状态 |
| `birth_day` | `str` | `"public"` | 公开状态 |
| `birth_year` | `str` | `"public"` | 公开状态 |
| `job` | `str` | `"public"` | 公开状态 |
| `pawoo` | `bool` | `true` | 注意：这里是布尔值，其余字段是字符串 |

非 `public` 时的取值不在本文范围内。该样本中 `pawoo=true` 但 `profile.pawoo_url=null`，两者并不一致。

#### `workspace`

| 字段 | 类型 | 本次值 | 说明 |
| --- | --- | --- | --- |
| `pc` | `str` | `"MSI"` | 电脑 |
| `monitor` | `str` | `"DELL"` | 显示器 |
| `tool` | `str` | `"PS2018"` | 绘图软件 |
| `scanner` | `str` | `""` | 扫描仪 |
| `tablet` | `str` | `"WACOM"` | 数位板 |
| `mouse` | `str` | `""` | 鼠标 |
| `printer` | `str` | `""` | 打印机 |
| `desktop` | `str` | `""` | 桌面 |
| `music` | `str` | `""` | 音乐 |
| `desk` | `str` | `""` | 桌子 |
| `chair` | `str` | `""` | 椅子 |
| `comment` | `str` | `""` | 备注 |
| `workspace_image_url` | `null \| str` | `null` | 工作环境图片 |

### 5.4 Novel（小说）

来源：[`novel_detail.json`](../_demo/AppAPI/AppAPI_dump/novel_detail.json) 的 `novel`。

| 字段 | 类型 | 本次示例 | 说明 |
| --- | --- | --- | --- |
| `id` | `int` | `28423494` | 小说 ID |
| `title` | `str` | `""`（当前转储被手动清空） | 标题 |
| `caption` | `str` | `""` | 说明文 |
| `restrict` | `int` | `0` | 限制标志；含义不在本文范围内 |
| `x_restrict` | `int` | `0` | 限制标记；`1`=R-18，`2`=R-18G；本次为 `0` |
| `is_original` | `bool` | `true` | 是否原创 |
| `image_urls` | `object` | `{}` 或 `{square_medium, medium, large}` | 封面图；本样本当前转储为 `{}`，有封面时的结构与示例见 5.9 |
| `create_date` | `str` | `"2026-06-23T20:37:52+09:00"` | 投稿时间 |
| `tags` | `array` | `[]`（当前转储被手动清空） | 标签数组；实际元素结构见 5.8 |
| `page_count` | `int` | `1` | 页数 |
| `text_length` | `int` | `30635` | 正文长度字段 |
| `user` | `object` | `{id, name, account, ...}` | 作者，见 5.2 |
| `series` | `object` | `{"id": 16098507, "title": "【不可言说的爱】"}` | 所属系列 |
| `is_bookmarked` | `bool` | `true` | 当前账号是否已收藏 |
| `total_bookmarks` | `int` | `32` | 收藏数 |
| `total_view` | `int` | `413` | 浏览数 |
| `visible` | `bool` | `true` | 是否可见 |
| `total_comments` | `int` | `5` | 评论数 |
| `is_muted` | `bool` | `false` | 是否被屏蔽 |
| `is_mypixiv_only` | `bool` | `false` | 布尔标志；含义不在本文范围内 |
| `is_x_restricted` | `bool` | `false` | 布尔标志；含义不在本文范围内 |
| `novel_ai_type` | `int` | `2` | 作品 AI 标记：`0`=无标记，`1`=原创，`2`=AI 生成 |
| `request` | `null` | `null` | 约稿标记；本次为 `null`（未声明） |
| `comment_access_control` | `int` | `0` | 评论设置：`0`=允许评论，`1`=作者关闭评论区 |

> 当前 `novel_detail.json` 的 `tags` 已在转储后被手动清空；实际标签结构见 5.8，共 8 个标签，每个都带 `added_by_uploaded_user: true`。

### 5.5 Novel text（webview 小说正文）

来源：[`novel_text.json`](../_demo/AppAPI/AppAPI_dump/novel_text.json)。这是 `novel_text()` 从 webview HTML 中提取的对象，字段为 camelCase。

| 字段 | 类型 | 本次示例 | 说明 |
| --- | --- | --- | --- |
| `id` | `str` | `"28423494"` | 小说 ID；注意是字符串 |
| `title` | `str` | `"【不可言说的爱】第1-10话"` | 标题 |
| `seriesId` | `str` | `"16098507"` | 系列 ID；字符串 |
| `seriesTitle` | `str` | `"【不可言说的爱】"` | 系列标题 |
| `seriesIsWatched` | `bool` | `false` | 是否追更该系列（不是观看状态） |
| `userId` | `str` | `"121811052"` | 作者 ID；字符串 |
| `coverUrl` | `str` | `""` | 封面 URL |
| `tags` | `array[str]` | `["Gemini", "ChatGPT", "AI少女", ...]` | 标签字符串数组 |
| `caption` | `str` | `""` | 说明文 |
| `cdate` | `str` | `"2026-06-23"` | 创建日期，仅日期 |
| `rating` | `object` | `{"like": 21, "bookmark": 32, "view": 413}` | 互动计数（like/bookmark/view） |
| `text` | `str` | `""`（当前转储被手动清空） | 正文；包含 `\n` 转义的裸文字内容，无包装结构 |
| `marker` | `null` | `null` | 字段存在，含义不在本文范围内 |
| `illusts` | `array` | `[]` | 数组字段；元素结构不在本文范围内 |
| `images` | `array` | `[]` | 数组字段；元素结构不在本文范围内 |
| `seriesNavigation` | `object` | `{}` | 系列导航；与小说详情中的 `series` 信息一致 （本次转储为 `{}`） |
| `glossaryItems` | `array` | `[]` | 数组字段；元素结构不在本文范围内 |
| `replaceableItemIds` | `array` | `[]` | 数组字段；元素结构不在本文范围内 |
| `aiType` | `int` | `2` | 作品 AI 标记：`0`=无标记，`1`=原创，`2`=AI 生成；与 `novel_ai_type` 相同 |
| `isOriginal` | `bool` | `true` | 是否原创 |
| `seasonalEffectTagData` | `null` | `null` | 字段存在，含义不在本文范围内 |
| `eventBanners` | `null` | `null` | 字段存在，含义不在本文范围内 |
| `language` | `str` | `"zh-cn"` | 语言代码 |
| `novel_text` | `str` | `""`（随 `text` 被清空） | pixivpy3 追加，值等于 `text`；同样是含 `\n` 转义的裸文字 |

### 5.6 Ugoira metadata（动图元数据）

来源：[`ugoira_detail.json`](../_demo/AppAPI/AppAPI_dump/ugoira_detail.json) 的 `ugoira_metadata`。

| 字段 | 类型 | 本次示例 | 说明 |
| --- | --- | --- | --- |
| `zip_urls` | `object` | `{"medium": "https://i.pximg.net/img-zip-ugoira/..._ugoira600x600.zip"}` | zip 下载地址；本次只出现 `medium` |
| `frames` | `array` | `[{"file": "000000.jpg", "delay": 50}, ...]` | 帧列表 |
| `frames[].file` | `str` | `"000000.jpg"` | zip 内文件名，6 位补零 |
| `frames[].delay` | `int` | `50` | 帧延迟，单位毫秒（ms） |

本次 200 帧，所有 `delay` 都是 `50`。

### 5.7 列表响应包装

| 方法 | 顶层字段 | 说明 |
| --- | --- | --- |
| `search_illust()` | `illusts`, `next_url`, `search_span_limit` | `search_span_limit` 本次为 `31536000` |
| `illust_new()` | `illusts`, `next_url` | `next_url` 用 `max_illust_id` 翻页 |
| `illust_recommended()` | `illusts`, `ranking_illusts`, `contest_exists`, `privacy_policy`, `next_url` | `ranking_illusts` 本次为 `[]`；`privacy_policy` 为 `{}`；`contest_exists` 为 `false` |
| `illust_ranking()` | `illusts`, `next_url` | 本次没有 `ranking_date` |
| `illust_detail()` | `illust` | 单对象 |
| `user_detail()` | `user`, `profile`, `profile_publicity`, `workspace` | 4 个对象 |
| `novel_detail()` | `novel` | 单对象 |
| `novel_text()` | 无包装 | 扁平 webview 对象 |
| `ugoira_metadata()` | `ugoira_metadata` | 单对象 |

`next_url` 只出现在列表类响应（`search_illust`、`illust_new`、`illust_recommended`、`illust_ranking`）；详情、用户、小说、动图响应没有该字段。翻页时把 `next_url` 交给 `api.parse_qs()` 再传回对应方法即可。

### 5.8 Tag（标签）

插画与小说详情的 `tags` 元素使用同一结构。当前 `novel_detail.json` 中的标签已被手动清空，下面按已确认的实际结构整理：

```json
{
    "name": "Gemini",
    "translated_name": null,
    "added_by_uploaded_user": true
}
```

| 字段 | 类型 | 示例 | 说明 |
| --- | --- | --- | --- |
| `name` | `str` | `"Gemini"` | 标签名 |
| `translated_name` | `str \| null` | `null` / `"AI girl"` | 翻译名；没有翻译时为 `null` |
| `added_by_uploaded_user` | `bool` | `true` | 该标签是否由上传作品的用户添加（Pixiv 允许非作者为作品加标签） |

本次小说样本有 8 个标签，`added_by_uploaded_user` 全部为 `true`；`translated_name` 有的为 `null`，有的为英文翻译。当前插画转储的标签对象中只出现了 `name`、`translated_name`。

### 5.9 小说封面 `image_urls`

`novel.image_urls` 在有封面时是 `square_medium` / `medium` / `large` 三个 URL，指向 `novel-cover-master`；没有封面时为空对象 `{}`（当前 `novel_detail.json` 即为此情况）。

本例的封面 URL：

```text
square_medium: https://i.pximg.net/c/128x128/novel-cover-master/img/2026/06/23/20/40/47/
               sci16098507_d4d2538a10884a751f32afd18e5e0192_square1200.jpg
medium:        https://i.pximg.net/c/176x352/novel-cover-master/img/2026/06/23/20/40/47/
               sci16098507_d4d2538a10884a751f32afd18e5e0192_master1200.jpg
large:         https://i.pximg.net/c/240x480_80/novel-cover-master/img/2026/06/23/20/40/47/
               sci16098507_d4d2538a10884a751f32afd18e5e0192_master1200.jpg
```

| 键 | 路径特征 | 说明 |
| --- | --- | --- |
| `square_medium` | `/c/128x128/novel-cover-master/..._square1200.jpg` | 方形缩略图 |
| `medium` | `/c/176x352/novel-cover-master/..._master1200.jpg` | 中等尺寸 |
| `large` | `/c/240x480_80/novel-cover-master/..._master1200.jpg` | 大尺寸 |

与插画不同，小说封面顶层 `image_urls` 就包含三档尺寸，没有 `original`。原图/封面下载仍需 `Referer`（见 3.4）。

---

## 6. 典型用法

### 6.1 翻页搜索

```python
resp = api.search_illust(
    word="NTE",
    search_target="exact_match_for_tags",
    sort="date_desc",
    filter="",
    offset=0,
)

while True:
    for illust in resp.illusts:
        print(illust.id, illust.title)

    if not resp.next_url:
        break
    resp = api.search_illust(**api.parse_qs(resp.next_url))
```

`parse_qs()` 返回的 `offset` 是字符串，pixivpy3 的参数类型接受 `int | str`，可以直接传回。

### 6.2 下载原图

```python
import os
from pathlib import Path


def download_illust(api, illust, out_dir="downloads"):
    if not illust.visible:
        return

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    if illust.page_count == 1:
        url = illust.meta_single_page.original_image_url
        if not url:
            return
        ext = os.path.splitext(url)[1]
        api.download(url, path=str(out), name=f"{illust.id}_p0{ext}")
        return

    for index, page in enumerate(illust.meta_pages):
        url = page.image_urls.original
        ext = os.path.splitext(url)[1]
        api.download(url, path=str(out), name=f"{illust.id}_p{index}{ext}")
```

`AppPixivAPI.download()` 的签名（3.7.5，）：

```python
def download(
    url,
    prefix="",
    path=os.path.curdir,
    name=None,
    replace=False,
    fname=None,
    referer="https://app-api.pixiv.net/",
)
```

- 文件已存在且 `replace=False` 时返回 `False`，不重复下载。
- 默认带 `Referer`，用于通过 `i.pximg.net` 的 Referer 校验。
- 建议用关键字参数传 `path`、`name`，避免位置参数顺序混淆。

### 6.3 单页与多页

```python
illust = api.illust_detail(91108678).illust

if illust.page_count == 1:
    original = illust.meta_single_page.original_image_url
else:
    originals = [page.image_urls.original for page in illust.meta_pages]
```

- 单页：`meta_single_page` 有 `original_image_url`，`meta_pages` 为 `[]`。
- 多页：`meta_single_page` 为 `{}`，`meta_pages` 长度通常等于 `page_count`。

### 6.4 处理不可见作品

```python
illust = api.illust_detail(91108678).illust
if not illust.visible:
    print("作品不可见，返回的是占位图")
```

不要只根据 `restrict` 或 `x_restrict` 判断；本次不可见样本的 `restrict` 和 `x_restrict` 都是 `0`。这类不可见是 App API 的服务端限制，同一作品在网页端可能仍可见。

## 7. 安全与使用建议

- refresh_token 等同于账号密码，使用环境变量或本地配置，不要提交仓库。
- 控制请求频率；批量翻页/下载时加入延迟。
- 下载原图时保留 `Referer: https://app-api.pixiv.net/`。
- `caption` 是 HTML，展示前清洗。
- 本说明只描述字段和调用方式，不构成对 Pixiv 服务条款的授权；使用前请遵守 Pixiv 的条款和当地法律。

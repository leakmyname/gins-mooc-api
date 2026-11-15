# gins-mooc-api

Python 完整复刻 [https://ginnnnnn.top/mooc](https://ginnnnnn.top/mooc)（Gins 中国大学 MOOC 答案助手）的后端 API，
并附带全量抓取到的课程 / 测验 / 题目 / 答案数据。

数据规模：**455 门课程 · 5060 个测验 · 52093 道题 · 173710 个选项**（绝大多数带标准答案）。

---

## 1. 复刻的 API

路径与响应结构与上游一致（`{"status":200,"msg":"","data":{...}}`）。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET  | `/api/mooc/course` | 课程列表，分页 `page`（**0-based**），返回 `totalPages` / `courseList` |
| GET  | `/api/mooc/course/{cid}` | 课程详情 + 该课程测验列表 `testList` |
| GET  | `/api/mooc/test/{tid}` | 测验详情 + `questionList`（选项 `answer` 标记正确项；填空题 `stdAnswer`） |
| GET  | `/api/mooc/test/{tid}?type=isExisting` | 校验测验数据是否存在 → `{"existing":true}` |
| POST | `/api/mooc/test/{tid}` | 答案查询，入参 `tid` / `oidList` / `titleList`，返回 `choiceAns` / `completionAns` / `homeworkAns` |
| GET  | `/api/mooc/announcement` | 公告 |
| GET  | `/api/mooc/notice/website` | 网页端公告 |
| GET  | `/api/mooc/notice/extension` | 扩展端公告 |
| GET  | `/api/mooc/course/refresh/{tid}` | SSE 进度流（`total` / `finished` / `status`） |

上游还有一条非本站接口，扩展中直接调用、需要网易课堂登录 Cookie（`NTESSTUDYSI`）：

```
POST https://www.icourse163.org/mm-tiku/web/j/mocExamBean.getPaper.rpc
```

### 快速验证

```bash
curl http://127.0.0.1:8811/api/mooc/course?page=0
curl http://127.0.0.1:8811/api/mooc/course/1487762444
curl http://127.0.0.1:8811/api/mooc/test/1258515449
curl -X POST http://127.0.0.1:8811/api/mooc/test/1258515449 -d "tid=1258515449"
```

---

## 2. 存储方案：SQLite

| 表 | 内容 |
|---|---|
| `course` | 课程（id / name / school / image_url） |
| `test` | 测验（id / course_id / name / objective / 时间 / 章节） |
| `question` | 题目（id / test_id / seq / type / title / title_html / std_answer / answer） |
| `option` | 选项（question_id / id / content / content_html / is_answer） |
| `raw_answer` | `POST /mooc/test/{tid}` 的原始响应，便于回放对账 |
| `notice` | 公告与 notice |

选型理由：

* 总量仅 5 万题 / 17 万选项，**单文件 SQLite 完全够用**，无需 Postgres；
* 只读多、写入少（批量导入），SQLite 的 WAL 模式足够；
* 零运维、单文件可直接分发（发布版 30MB gzip）；
* `title_html` 与 `title` 并存：既保留原始 `<img>` 图片链接，又提供可检索纯文本；
* 答案列存 JSON 字符串，兼容选择题（选项 id 数组）/ 填空题（多答案数组）/ 作业（文本）三类；
* 需要全文检索时可直接启用 FTS5（unicode61 分词，中文建议 trigram 分词器）。

其它可选：`PostgreSQL + tsvector`（需要并发写与多用户协作时）、`Meilisearch`（纯搜索场景）。

### 建表语句
见 [`schema.sql`](schema.sql)；导入脚本 [`importer.py`](importer.py)。

---

## 3. 快速开始

```bash
# 依赖
pip install -r requirements.txt

# 解压随仓库附带的数据（SQLite 库 + JSON 数据）
bash setup.sh          # 等价于 make setup

# 启动 API 服务
python3 server.py      # http://0.0.0.0:8811  (PORT 环境变量可改)
# 或
uvicorn server:app --host 0.0.0.0 --port 8811
```

环境变量 `GINS_MOOC_DB` 可指定数据库路径。

---

## 4. 目录结构

```
.
├── crawler.py          # 上游站点爬虫（逆向出的真实 API）
├── server.py           # FastAPI 复刻服务
├── importer.py         # JSON → SQLite 导入
├── schema.sql          # SQLite DDL
├── setup.sh            # 解压附带数据
├── requirements.txt
├── release/
│   ├── gins_mooc.db.gz # 预构建数据库 (30MB)
│   └── data.tar.gz     # 原始 JSON 数据 (21MB)
└── data/               # setup.sh 解压后生成
    ├── courses.json        # 课程列表
    ├── courses/{cid}.json  # 课程详情
    ├── tests/{tid}.json    # 测验题目 + 答案
    ├── answers.json        # POST 答案接口原始响应
    ├── questions.jsonl     # 扁平化题目，便于检索
    ├── notices.json
    └── mooc_answers.md     # 可读 Markdown 汇总
```

## 5. 重新抓取上游

```bash
python3 crawler.py                 # 全量（约 25 分钟）
python3 crawler.py --pages 3       # 只抓前 3 页
python3 crawler.py --courses 1487762444
python3 crawler.py --no-proxy      # 不走 http://127.0.0.1:7893
python3 importer.py                # 重新导入 SQLite
```

> 注意：上游 `page` 参数是 **0-based**，`page=0` 与不带参数等价；漏掉 `page=0` 会丢前 20 门课。

## 6. 免责声明

本项目仅用于技术研究与学习。数据版权归原平台（网易云课堂 / 中国大学 MOOC）所有，请勿用于作弊或商业用途。

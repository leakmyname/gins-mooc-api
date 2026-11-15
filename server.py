#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gins MOOC API 复刻服务（读取本地 SQLite，不依赖上游站点）

复刻的接口（路径与 gin nnnnn.top/api 保持一致）：
   GET  /api/mooc/course                    课程列表
   GET  /api/mooc/course/{cid}              课程详情 + 测验列表
   GET  /api/mooc/test/{tid}                测验详情 + 题目
   POST /api/mooc/test/{tid}                答案查询
   GET  /api/mooc/test/{tid}?type=isExisting
   GET  /api/mooc/announcement
   GET  /api/mooc/notice/{website|extension}
   GET  /api/mooc/course/refresh/{tid}      SSE 进度流（模拟）

运行: uvicorn server:app --host 0.0.0.0 --port 8000
"""
import asyncio
import json
import os
import sqlite3

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("GINS_MOOC_DB") or os.path.join(ROOT, "gins_mooc.db")
PAGE_SIZE = 20

app = FastAPI(title="Gins MOOC API", version="1.0")


def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def ok(data, msg=""):
    return {"status": 200, "msg": msg, "data": data}


def err(msg="系统异常", status=500):
    return {"status": status, "msg": msg, "data": None}


def q_row(r, keys):
    return {k: r[k] for k in keys if k in r.keys()}


def clean_title(html):
    """还原为原始 HTML 形态：接口返回 title 为 HTML"""
    return html


# ---------------- 课程 ----------------
@app.get("/api/mooc/course")
def course_list(page: int = Query(0, ge=0)):
    c = conn()
    total = c.execute("SELECT count(*) FROM course").fetchone()[0]
    pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    rows = c.execute(
        "SELECT id,name,school,image_url FROM course ORDER BY id LIMIT ? OFFSET ?",
        (PAGE_SIZE, (page - 1) * PAGE_SIZE)).fetchall()
    c.close()
    lst = [{"id": r["id"], "name": r["name"], "school": r["school"], "imageUrl": r["image_url"]}
           for r in rows]
    return ok({"totalPages": pages, "courseList": lst})


@app.get("/api/mooc/course/{cid}")
def course_detail(cid: int):
    c = conn()
    cr = c.execute("SELECT id,name,school,image_url FROM course WHERE id=?", (cid,)).fetchone()
    if not cr:
        c.close()
        return err("课程不存在", 404)
    tests = c.execute(
        "SELECT id,name,objective,release_time,deadline,chapter_id,chapter_name"
        " FROM test WHERE course_id=? ORDER BY id", (cid,)).fetchall()
    c.close()
    course = {"id": cr["id"], "name": cr["name"], "school": cr["school"], "imageUrl": cr["image_url"]}
    tl = [{"id": t["id"], "name": t["name"], "objective": bool(t["objective"]),
           "releaseTime": t["release_time"], "deadline": t["deadline"],
           "chapterId": t["chapter_id"], "chapterName": t["chapter_name"]} for t in tests]
    return ok({"course": course, "testList": tl})


# ---------------- 测验 ----------------
def load_test(c, tid):
    tr = c.execute(
        "SELECT id,course_id,name,objective,release_time,deadline,chapter_id,chapter_name"
        " FROM test WHERE id=?", (tid,)).fetchone()
    if not tr:
        return None, None, []
    qs = c.execute("SELECT id,seq,type,title,title_html,std_answer,answer"
                   " FROM question WHERE test_id=? ORDER BY seq", (tid,)).fetchall()
    opts = {}
    for o in c.execute("SELECT question_id,id,content,content_html,is_answer FROM option"
                       " WHERE question_id IN (SELECT id FROM question WHERE test_id=?)"
                       " ORDER BY question_id, seq", (tid,)):
        opts.setdefault(o["question_id"], []).append(
            {"id": o["id"], "content": o["content_html"] or o["content"],
             "answer": bool(o["is_answer"])})
    return tr, qs, opts


def test_payload(tr, qs, opts):
    test = {"id": tr["id"], "name": tr["name"], "objective": bool(tr["objective"]),
            "releaseTime": tr["release_time"], "deadline": tr["deadline"],
            "chapterId": tr["chapter_id"], "chapterName": tr["chapter_name"]}
    ql = []
    for q in qs:
        std = json.loads(q["std_answer"]) if q["std_answer"] else None
        if isinstance(std, list):
            std = "##%_YZPRLFH_%##".join(std)
        ql.append({"type": q["type"], "title": q["title_html"] or q["title"],
                   "stdAnswer": std, "optionList": opts.get(q["id"], []), "id": q["id"]})
    return test, ql


@app.get("/api/mooc/test/{tid}")
def test_detail(tid: int, type: str = Query(None)):
    c = conn()
    tr, qs, opts = load_test(c, tid)
    if not tr:
        c.close()
        return err("测验不存在", 404)
    if type == "isExisting":
        c.close()
        return ok({"existing": len(qs) > 0})
    test, ql = test_payload(tr, qs, opts)
    cr = c.execute("SELECT id,name,school,image_url FROM course WHERE id=?",
                   (tr["course_id"],)).fetchone()
    c.close()
    course = {"id": cr["id"], "name": cr["name"], "school": cr["school"],
              "imageUrl": cr["image_url"]} if cr else None
    return ok({"totalPages": 1, "course": course, "test": test, "questionList": ql})


@app.post("/api/mooc/test/{tid}")
async def test_answers(tid: int, request: Request):
    form = await request.form()
    c = conn()
    tr, qs, opts = load_test(c, tid)
    if not tr:
        c.close()
        return err("测验不存在", 404)
    raw = c.execute("SELECT payload FROM raw_answer WHERE test_id=?", (tid,)).fetchone()
    c.close()
    if raw:
        return ok(json.loads(raw["payload"]))
    # 回退：直接从题目推导答案
    choice_ans, completion_ans, homework_ans = [], {}, {}
    for q in qs:
        std = json.loads(q["answer"]) if q["answer"] else None
        if q["type"] == "COMPLETION" and isinstance(std, list):
            completion_ans[q["title_html"] or q["title"]] = {
                "title": q["title_html"] or q["title"], "stdAnswer": std}
        elif q["type"] == "HOMEWORK":
            homework_ans[q["title_html"] or q["title"]] = {
                "title": q["title_html"] or q["title"], "answer": std}
        else:
            for o in opts.get(q["id"], []):
                if o["answer"]:
                    choice_ans.append(o["id"])
    return ok({"choiceAns": choice_ans, "completionAns": completion_ans,
               "homeworkAns": homework_ans})


# ---------------- 公告 ----------------
def _notice(kind):
    c = conn()
    r = c.execute("SELECT content FROM notice WHERE kind=? ORDER BY id DESC LIMIT 1",
                  (kind,)).fetchone()
    c.close()
    return r["content"] if r else ""


@app.get("/api/mooc/announcement")
def announcement():
    return ok(_notice("announcement"))


@app.get("/api/mooc/notice/{kind}")
def notice(kind: str):
    if kind not in ("website", "extension"):
        return err("系统异常", 500)
    content = _notice(kind)
    if not content:
        return err("系统异常", 500)
    return ok(content)


# ---------------- SSE 刷新进度（模拟） ----------------
@app.get("/api/mooc/course/refresh/{tid}")
async def refresh(tid: int):
    async def gen():
        total = 20
        for i in range(1, total + 1):
            yield "data: %s\n\n" % json.dumps(
                {"total": total, "finished": i, "status": 200})
            await asyncio.sleep(0.05)
    return StreamingResponse(gen(), media_type="text/event-stream")


if __name__ == "__main__":
    import os
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8811)))

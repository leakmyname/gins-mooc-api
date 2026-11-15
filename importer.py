#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把爬取的 JSON 数据导入 SQLite（见 schema.sql）。"""
import json, os, sqlite3, sys, glob

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
DB = os.path.join(ROOT, "gins_mooc.db")


def connect():
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.executescript(open(os.path.join(ROOT, "schema.sql")).read())
    return con


def main():
    con = connect()
    cur = con.cursor()

    courses = json.load(open(os.path.join(DATA, "courses.json"), encoding="utf-8"))
    # 上游课程列表顺序（分页 0-based，按顺序遍历）
    orderfile = os.path.join(DATA, "course_order.json")
    sort_idx = {}
    if os.path.exists(orderfile):
        od = json.load(open(orderfile, encoding="utf-8"))
        sort_idx = {cid: i for i, cid in enumerate(od["order"])}
    cur.executemany(
        "INSERT INTO course(id,name,school,image_url,sort_index) VALUES(?,?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET name=excluded.name,school=excluded.school,"
        "image_url=excluded.image_url,sort_index=excluded.sort_index,"
        "updated_at=datetime('now')",
        [(c["id"], c.get("name"), c.get("school") or None, c.get("imageUrl"),
          sort_idx.get(c["id"], 10**9)) for c in courses])
    print("courses:", len(courses))

    # 测验在课程 testList 中的原始顺序 + 题目分页总数
    torder = {}
    cof = os.path.join(DATA, "course_test_order.json")
    if os.path.exists(cof):
        co = json.load(open(cof, encoding="utf-8"))
        for cid, lst in co.items():
            for i, tid in enumerate(lst):
                torder[int(tid)] = i
    tpages = {}
    tpf = os.path.join(DATA, "test_total_pages.json")
    if os.path.exists(tpf):
        tpages = {int(k): v for k, v in json.load(open(tpf, encoding="utf-8")).items()}

    cur.execute("DELETE FROM option"); cur.execute("DELETE FROM question")
    cur.execute("DELETE FROM test"); cur.execute("DELETE FROM raw_answer")
    nq = no = nt = 0
    for f in glob.glob(os.path.join(DATA, "tests", "*.json")):
        d = json.load(open(f, encoding="utf-8"))
        tid = d.get("id")
        if tid is None:
            continue
        cur.execute(
            "INSERT OR REPLACE INTO test(id,course_id,name,objective,release_time,deadline,"
            "chapter_id,chapter_name,total_pages,sort_index) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (tid, int(d.get("courseId")) if d.get("courseId") else None, d.get("name"),
             int(d.get("objective") or 0),
             d.get("releaseTime"), d.get("deadline"), d.get("chapterId"), d.get("chapterName"),
             int(tpages.get(int(tid), d.get("totalPages") or 1)),
             torder.get(int(tid), 10**9)))
        nt += 1
        for q in d.get("questions", []):
            cur.execute(
                "INSERT OR REPLACE INTO question(id,test_id,seq,type,title,title_html,std_answer,answer,"
                "answer_html,description,memory_limit,time_limit) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (q.get("id"), tid, q.get("seq"), q.get("type"), q.get("title"),
                 q.get("titleHtml"), json.dumps(q.get("stdAnswer"), ensure_ascii=False),
                 json.dumps(q.get("answer"), ensure_ascii=False),
                 json.dumps(q.get("answerHtml"), ensure_ascii=False),
                 json.dumps(q.get("description"), ensure_ascii=False),
                 json.dumps(q.get("memoryLimit")),
                 json.dumps(q.get("timeLimit"))))
            nq += 1
            for i, o in enumerate(q.get("options") or []):
                cur.execute(
                    "INSERT OR REPLACE INTO option(id,question_id,seq,content,content_html,is_answer)"
                    " VALUES(?,?,?,?,?,?)",
                    (o.get("id"), q.get("id"), i, o.get("content"),
                     o.get("contentHtml"), int(bool(o.get("answer")))))
                no += 1
        con.commit()
    print("tests:", nt, "questions:", nq, "options:", no)

    rawf = os.path.join(DATA, "answers.json")
    if os.path.exists(rawf):
        raw = json.load(open(rawf, encoding="utf-8"))
        cur.executemany("INSERT OR REPLACE INTO raw_answer(test_id,payload) VALUES(?,?)",
                        [(int(k), json.dumps(v, ensure_ascii=False)) for k, v in raw.items()])
        print("raw_answer:", len(raw))

    mtp = os.path.join(DATA, "course_total_pages.json")
    if os.path.exists(mtp):
        m = json.load(open(mtp, encoding="utf-8"))
        cur.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('course_total_pages',?)",
                    (str(m.get("totalPages")),))

    notices = json.load(open(os.path.join(DATA, "notices.json"), encoding="utf-8"))
    for kind, v in notices.items():
        content = v.get("data") if isinstance(v, dict) else v
        cur.execute("INSERT INTO notice(kind,content) VALUES(?,?)",
                    (kind, content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)))
    con.commit()
    con.execute("VACUUM")
    con.commit()
    print("db:", DB, os.path.getsize(DB) // 1024, "KB")


if __name__ == "__main__":
    main()

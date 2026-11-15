#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把爬取的 JSON 数据导入 SQLite（见 schema.sql）。"""
import json, os, sqlite3, sys, glob

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
DB = os.path.join(ROOT, "gins_mooc.db")


def connect():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.executescript(open(os.path.join(ROOT, "schema.sql")).read())
    return con


def main():
    con = connect()
    cur = con.cursor()

    courses = json.load(open(os.path.join(DATA, "courses.json"), encoding="utf-8"))
    cur.executemany(
        "INSERT INTO course(id,name,school,image_url) VALUES(?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET name=excluded.name,school=excluded.school,"
        "image_url=excluded.image_url,updated_at=datetime('now')",
        [(c["id"], c.get("name"), c.get("school"), c.get("imageUrl")) for c in courses])
    print("courses:", len(courses))

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
            "chapter_id,chapter_name) VALUES(?,?,?,?,?,?,?,?)",
            (tid, d.get("courseId"), d.get("name"), int(d.get("objective") or 0),
             d.get("releaseTime"), d.get("deadline"), d.get("chapterId"), d.get("chapterName")))
        nt += 1
        for q in d.get("questions", []):
            cur.execute(
                "INSERT OR REPLACE INTO question(id,test_id,seq,type,title,title_html,std_answer,answer)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (q.get("id"), tid, q.get("seq"), q.get("type"), q.get("title"),
                 q.get("titleHtml"), json.dumps(q.get("stdAnswer"), ensure_ascii=False),
                 json.dumps(q.get("answer"), ensure_ascii=False)))
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

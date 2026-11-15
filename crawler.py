#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gins-mooc 爬虫

抓取 https://ginnnnnn.top/mooc 前端所使用的全部 API，保存课程 / 测验 / 题目 / 答案等数据。

API（均以 https://ginnnnnn.top/api 为前缀）：
   GET  /mooc/course                          课程列表（分页 page, totalPages）
   GET  /mooc/course/{cid}                    课程详情 + 测验列表 testList
   GET  /mooc/test/{tid}                      测验详情 + 题目 questionList(选项 answer / stdAnswer)
   POST /mooc/test/{tid}                      查询答案(choiceAns / completionAns / homeworkAns)
   GET  /mooc/test/{tid}?type=isExisting      校验测验是否已抓取
   GET  /mooc/announcement                    公告
   GET  /mooc/notice/website                  网页公告
   GET  /mooc/notice/extension                扩展公告
   SSE  /mooc/course/refresh/{tid}            刷新课程进度(事件流)

用法:
   python3 crawler.py                          # 全量抓取
   python3 crawler.py --pages 3                # 只抓 3 页课程
   python3 crawler.py --courses 1487762444     # 指定课程 id
   python3 crawler.py --no-proxy               # 不走本地代理
"""

import argparse
import json
import os
import re
import sys
import time
import random
from html import unescape

import requests

BASE = "https://ginnnnnn.top"
API = BASE + "/api"
PROXY = "http://127.0.0.1:7893"
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

TAG_RE = re.compile(r"<[^>]+>")


def now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def log(msg):
    print("[%s] %s" % (now(), msg), flush=True)


def strip_html(s):
    if not s:
        return ""
    s = re.sub(r"<img[^>]*src=[\"']([^\"']+)[\"'][^>]*>", r"【图片:\1】", s)
    s = TAG_RE.sub("", s)
    s = unescape(s)
    return re.sub(r"\s+", " ", s).strip()


class Client:
    def __init__(self, proxy=PROXY, delay=0.15):
        self.s = requests.Session()
        if proxy:
            self.s.proxies = {"http": proxy, "https": proxy}
        self.s.headers.update({
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Referer": BASE + "/mooc",
        })
        self.delay = delay
        self.last = 0.0

    def _throttle(self):
        wait = self.delay - (time.time() - self.last)
        if wait > 0:
            time.sleep(wait)
        self.last = time.time()

    def get(self, path, **params):
        self._throttle()
        r = self.s.get(API + path, params=params, timeout=40)
        return self._unwrap(r)

    def post(self, path, data):
        self._throttle()
        r = self.s.post(API + path, data=data, timeout=40)
        return self._unwrap(r)

    @staticmethod
    def _unwrap(r):
        try:
            j = r.json()
        except Exception:
            return {"status": r.status_code, "msg": r.text[:200], "data": None}
        if isinstance(j, dict) and "status" in j:
            return j
        return {"status": 200, "msg": "", "data": j}


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def save_jsonl(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# ---------------- API 各接口 ----------------

def api_course_list(cli, page):
    return cli.get("/mooc/course", page=page)


def api_course_detail(cli, cid):
    return cli.get("/mooc/course/%s" % cid)


def api_test_detail(cli, tid, page=None):
    """上游 questionList 分页，每页 20 题，page 为 0-based"""
    if page is None:
        return cli.get("/mooc/test/%s" % tid)
    return cli.get("/mooc/test/%s" % tid, page=page)


def api_test_answers(cli, tid, oid_list=None, title_list=None):
    data = {"tid": str(tid)}
    if oid_list is not None:
        data["oidList"] = json.dumps(oid_list)
    if title_list is not None:
        data["titleList"] = json.dumps(title_list, ensure_ascii=False)
    return cli.post("/mooc/test/%s" % tid, data)


def api_test_exists(cli, tid):
    return cli.get("/mooc/test/%s" % tid, type="isExisting")


def api_announcement(cli):
    return cli.get("/mooc/announcement")


def api_notice(cli, kind="website"):
    return cli.get("/mooc/notice/%s" % kind)


# ---------------- 归一化 ----------------

def norm_question(q, seq):
    opts = []
    correct = []
    for o in (q.get("optionList") or []):
        ans = bool(o.get("answer"))
        opts.append({"id": o.get("id"), "content": strip_html(o.get("content")),
                     "contentHtml": o.get("content"), "answer": ans})
        if ans:
            correct.append(o.get("id"))
    std = q.get("stdAnswer")
    if isinstance(std, str) and "##%_YZPRLFH_%##" in std:
        std = std.split("##%_YZPRLFH_%##")
    qtype = q.get("type")
    if qtype == "COMPLETION":
        answer = std
    elif qtype in ("HOMEWORK", "ONLINE_JUDGE"):
        answer = strip_html(q.get("answer"))
    else:
        answer = correct
    return {
        "id": q.get("id"),
        "seq": seq,
        "type": qtype,
        "title": strip_html(q.get("title")),
        "titleHtml": q.get("title"),
        "options": opts,
        "stdAnswer": std,
        "answer": answer,
        # 保留上游原始字段，保证接口可 1:1 复刻
        "answerHtml": q.get("answer"),
        "description": q.get("description"),
        "memoryLimit": q.get("memoryLimit"),
        "timeLimit": q.get("timeLimit"),
    }


def norm_test(td):
    """td 为 /mooc/test/{tid} 返回的 data"""
    ql = td.get("questionList") or []
    meta = td.get("test") or {}
    return {
        "id": meta.get("id"),
        "name": meta.get("name"),
        "objective": meta.get("objective"),
        "releaseTime": meta.get("releaseTime"),
        "deadline": meta.get("deadline"),
        "chapterId": meta.get("chapterId"),
        "chapterName": meta.get("chapterName"),
        "totalPages": td.get("totalPages", 1),
        "questions": [norm_question(q, i + 1) for i, q in enumerate(ql)],
    }


def fetch_courses(cli, max_pages=None, only_ids=None):
    courses = []
    seen = set()
    # 先探测分页总数：上游 page 参数为 0-based，page=0 与不带参数等价
    r = api_course_list(cli, 0)
    total_pages = ((r or {}).get("data") or {}).get("totalPages", 1)
    pages = list(range(0, total_pages))
    if max_pages:
        pages = pages[:max_pages]
    for page in pages:
        r = api_course_list(cli, page)
        d = (r or {}).get("data") or {}
        lst = d.get("courseList") or []
        for c in lst:
            cid = c.get("id")
            if cid in seen:
                continue
            seen.add(cid)
            c = dict(c)
            c["name"] = strip_html(c.get("name"))
            c["school"] = strip_html(c.get("school")) if c.get("school") is not None else None
            courses.append(c)
        log("课程列表 page %d/%d, 累计 %d 门" % (page, total_pages - 1, len(courses)))
        time.sleep(random.uniform(0.1, 0.3))
    if only_ids:
        ids = set(str(i) for i in only_ids)
        courses = [c for c in courses if str(c.get("id")) in ids]
    # 保存上游原始顺序，供 SQLite 复刻分页顺序
    save_json(os.path.join(OUT_DIR, "course_order.json"),
              {"order": [c["id"] for c in courses],
               "meta": {str(c["id"]): c for c in courses}})
    return courses


def crawl(cli, max_pages=None, only_ids=None, with_answers=True):
    os.makedirs(OUT_DIR, exist_ok=True)

    # 1) 课程列表
    courses = fetch_courses(cli, max_pages=max_pages, only_ids=only_ids)
    save_json(os.path.join(OUT_DIR, "courses.json"), courses)
    log("共 %d 门课程" % len(courses))

    # 2) 课程详情 (测验列表)
    course_details = {}
    for c in courses:
        cid = c["id"]
        r = api_course_detail(cli, cid)
        d = (r or {}).get("data") or {}
        course_details[str(cid)] = {"course": c, "testList": d.get("testList") or []}
        save_json(os.path.join(OUT_DIR, "courses", "%s.json" % cid), course_details[str(cid)])
    log("课程详情抓取完成")

    # 3) 测验详情 (题目 + 标准答案)
    tests = {}
    total_tests = sum(len(v["testList"]) for v in course_details.values())
    done = 0
    for cid, v in course_details.items():
        for t in v["testList"]:
            tid = t.get("id")
            if not tid:
                continue
            r = api_test_detail(cli, tid)
            d = (r or {}).get("data") or {}
            if not d.get("questionList"):
                continue
            t2 = norm_test(d)
            if not t2.get("name"):
                t2["name"] = t.get("name")
            # 题目分页：抓取全部页
            total_pages = d.get("totalPages") or 1
            if total_pages > 1:
                merged = list(t2["questions"])
                for pg in range(1, total_pages):
                    rp = api_test_detail(cli, tid, page=pg)
                    dp = (rp or {}).get("data") or {}
                    for q in dp.get("questionList") or []:
                        nq = norm_question(q, len(merged) + 1)
                        merged.append(nq)
                t2["questions"] = merged
                t2["totalPages"] = total_pages
            t2["courseId"] = cid
            t2["courseName"] = v["course"]["name"]
            tests[str(tid)] = t2
            save_json(os.path.join(OUT_DIR, "tests", "%s.json" % tid), t2)
            done += 1
            if done % 20 == 0:
                log("测验 %d/%d" % (done, total_tests))
    log("测验题目抓取完成: %d 个" % len(tests))

    # 4) 答案接口
    if with_answers:
        ans_all = {}
        for tid, t in tests.items():
            oid_list = []
            title_list = []
            for q in t.get("questions", []):
                for o in q.get("options") or []:
                    if o.get("id") is not None:
                        oid_list.append(o["id"])
                title_list.append(q.get("titleHtml") or q.get("title") or "")
            r = api_test_answers(cli, tid, oid_list, title_list)
            ans_all[tid] = (r or {}).get("data") or {}
        save_json(os.path.join(OUT_DIR, "answers.json"), ans_all)
        log("答案接口抓取完成")

    # 5) 公告 / notice
    notices = {
        "announcement": api_announcement(cli),
        "notice_website": api_notice(cli, "website"),
        "notice_extension": api_notice(cli, "extension"),
    }
    save_json(os.path.join(OUT_DIR, "notices.json"), notices)

    return courses, tests


def export_markdown(tests, path):
    lines = ["# Gins MOOC 题目与答案汇总", ""]
    by_course = {}
    for tid, t in tests.items():
        by_course.setdefault((t.get("courseId"), t.get("courseName")), []).append(t)
    for (cid, cname), arr in sorted(by_course.items(), key=lambda x: str(x[0][0])):
        lines.append("## %s (%s)" % (cname, cid))
        lines.append("")
        for t in arr:
            lines.append("### %s" % t.get("name"))
            lines.append("")
            for q in t.get("questions", []):
                lines.append("**%d. [%s]** %s" % (q["seq"], q.get("type"), q.get("title")))
                lines.append("")
                for o in q.get("options") or []:
                    lines.append("   - %s %s" % ("[x]" if o.get("answer") else "[ ]", o.get("content")))
                a = q.get("answer")
                if isinstance(a, list) and q.get("type") != "COMPLETION":
                    a = ", ".join((o.get("content") or str(o.get("id")))
                                  for o in q.get("options", []) if o.get("id") in a) or a
                elif isinstance(a, list):
                    a = " / ".join(str(x) for x in a)
                lines.append("   - **答案**: %s" % (a if a not in (None, [], "") else "（未提供）"))
                lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    log("Markdown 导出: %s" % path)


def refresh_tests(cli, only_ids=None):
    """仅重新抓取测验题目（保留 contentHtml 等完整信息）"""
    tests = {}
    for f in sorted(os.listdir(os.path.join(OUT_DIR, "tests"))) if os.path.isdir(os.path.join(OUT_DIR, "tests")) else []:
        pass
    src = os.path.join(OUT_DIR, "tests")
    files = sorted(os.listdir(src)) if os.path.isdir(src) else []
    n = 0
    for fn in files:
        if not fn.endswith(".json"):
            continue
        tid = fn[:-5]
        if only_ids and tid not in {str(i) for i in only_ids}:
            continue
        r = api_test_detail(cli, tid)
        d = (r or {}).get("data") or {}
        if not d.get("questionList"):
            continue
        oldp = os.path.join(src, fn)
        old = json.load(open(oldp, encoding="utf-8")) if os.path.exists(oldp) else {}
        t2 = norm_test(d)
        total_pages = d.get("totalPages") or 1
        if total_pages > 1:
            merged = list(t2["questions"])
            for pg in range(1, total_pages):
                rp = api_test_detail(cli, tid, page=pg)
                dp = (rp or {}).get("data") or {}
                for q in dp.get("questionList") or []:
                    merged.append(norm_question(q, len(merged) + 1))
            t2["questions"] = merged
            t2["totalPages"] = total_pages
        t2["courseId"] = old.get("courseId")
        t2["courseName"] = old.get("courseName")
        save_json(oldp, t2)
        n += 1
        if n % 50 == 0:
            log("刷新测验 %d/%d" % (n, len(files)))
    log("测验刷新完成: %d 个" % n)
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=None, help="只抓前 N 页课程")
    ap.add_argument("--courses", nargs="*", default=None, help="指定课程 id")
    ap.add_argument("--no-proxy", action="store_true")
    ap.add_argument("--delay", type=float, default=0.15)
    ap.add_argument("--no-answers", action="store_true")
    ap.add_argument("--only-tests", action="store_true", help="仅刷新已有测验题目数据")
    args = ap.parse_args()

    cli = Client(proxy=None if args.no_proxy else PROXY, delay=args.delay)
    if args.only_tests:
        refresh_tests(cli, only_ids=args.courses)
        return
    courses, tests = crawl(cli, max_pages=args.pages, only_ids=args.courses,
                            with_answers=not args.no_answers)
    export_markdown(tests, os.path.join(OUT_DIR, "mooc_answers.md"))
    rows = []
    for t in tests.values():
        for q in t["questions"]:
            row = {"course": t.get("courseName"), "test": t.get("name")}
            row.update(q)
            rows.append(row)
    save_jsonl(os.path.join(OUT_DIR, "questions.jsonl"), rows)
    log("全部完成, 数据位于 %s" % OUT_DIR)


if __name__ == "__main__":
    main()

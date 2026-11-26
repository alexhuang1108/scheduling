"""航空地勤排班系統 - Flask 主程式"""
import hashlib
import os
from functools import wraps
from datetime import date, datetime, timedelta
from pathlib import Path

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify
)

from models import get_db, init_db, get_setting, set_setting, log_login
from i18n import t, LANGS, LANG_NAMES

app = Flask(__name__)
app.secret_key = "scheduling-dev-secret-change-me"


@app.context_processor
def inject_i18n():
    lang = session.get("lang", "zh")
    if lang not in LANGS:
        lang = "zh"
    unread = 0
    if "user_id" in session:
        try:
            db = get_db()
            me = session["user_id"]
            unread = db.execute(
                """SELECT COUNT(*) c FROM messages m
                   WHERE (m.recipient_id=? OR (m.kind='announcement' AND m.recipient_id IS NULL))
                     AND NOT EXISTS (SELECT 1 FROM message_reads r
                                     WHERE r.message_id=m.id AND r.user_id=?)""",
                (me, me)).fetchone()["c"]
            db.close()
        except Exception:
            unread = 0
    return {
        "lang": lang,
        "langs": LANGS,
        "lang_names": LANG_NAMES,
        "T": lambda key, **kw: t(key, lang).format(**kw) if kw else t(key, lang),
        "is_super": session.get("role") == "superadmin",
        "is_admin": session.get("role") in ("admin", "superadmin"),
        "is_staff": session.get("role") == "staff",
        "me_id": session.get("user_id"),
        "unread_count": unread,
    }


@app.route("/favicon.ico")
def favicon():
    return ("", 204)


@app.route("/lang/<code>")
def set_lang(code):
    if code in LANGS:
        session["lang"] = code
    ref = request.referrer
    if ref:
        return redirect(ref)
    return redirect(url_for("index"))



def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()


def login_required(role=None):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            if "user_id" not in session:
                return redirect(url_for("login"))
            if role:
                allowed = role if isinstance(role, (list, tuple)) else [role]
                if session.get("role") not in allowed:
                    flash(t("need_admin", session.get("lang", "zh")), "warning")
                    return redirect(url_for("index"))
            return fn(*a, **kw)
        return wrapper
    return deco


@app.before_request
def _ensure_db():
    if not hasattr(app, "_db_ready"):
        init_db()
        app._db_ready = True


# ---------- 認證 ----------

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    quick = get_setting("quick_login", "off") == "on"
    quick_method = get_setting("quick_method", "screen")
    remembered = request.form.get("username", "").strip() or session.get("username", "")
    if request.method == "POST":
        u = remembered
        p = request.form.get("password", "")
        db = get_db()
        row = db.execute(
            "SELECT * FROM users WHERE username=? AND active=1", (u,)).fetchone()
        db.close()
        if row and row["password_hash"] == hash_pw(p):
            session["user_id"] = row["id"]
            session["username"] = row["username"]
            session["full_name"] = row["full_name"]
            session["role"] = row["role"]
            log_login(user_id=row["id"], username=row["username"],
                      full_name=row["full_name"], role=row["role"],
                      action="login", method="password",
                      ip=request.remote_addr, user_agent=request.headers.get("User-Agent"),
                      lang=session.get("lang", "zh"))
            return redirect(url_for("index"))
        error = t("login_error", session.get("lang", "zh"))
        log_login(username=u, action="login_failed", method="password",
                  ip=request.remote_addr, user_agent=request.headers.get("User-Agent"),
                  lang=session.get("lang", "zh"))
    return render_template("login.html", error=error, quick=quick,
                           quick_method=quick_method,
                           remembered=remembered or request.args.get("u", ""))


@app.route("/quick-login", methods=["POST"])
def quick_login():
    """快速登入：用瀏覽器本地記住的帳號，跳過密碼（裝置生物辨識/螢幕鎖把關）。"""
    u = request.form.get("username", "").strip() or session.get("username", "")
    if not u:
        return redirect(url_for("login"))
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE username=? AND active=1", (u,)).fetchone()
    db.close()
    if not row:
        return redirect(url_for("login"))
    session["user_id"] = row["id"]
    session["username"] = row["username"]
    session["full_name"] = row["full_name"]
    session["role"] = row["role"]
    log_login(user_id=row["id"], username=row["username"], full_name=row["full_name"],
              role=row["role"], action="login", method="quick",
              ip=request.remote_addr, user_agent=request.headers.get("User-Agent"),
              lang=session.get("lang", "zh"))
    return redirect(url_for("index"))


@app.route("/logout")
def logout():
    if "user_id" in session:
        log_login(user_id=session.get("user_id"), username=session.get("username"),
                  full_name=session.get("full_name"), role=session.get("role"),
                  action="logout",
                  ip=request.remote_addr, user_agent=request.headers.get("User-Agent"),
                  lang=session.get("lang", "zh"))
    session.clear()
    return redirect(url_for("login"))


# ---------- 首頁（儀表板）----------

@app.route("/")
@login_required()
def index():
    today = date.today().isoformat()
    db = get_db()
    shifts = db.execute("SELECT * FROM shifts WHERE active=1 ORDER BY start_time").fetchall()
    if session["role"] in ("admin", "superadmin"):
        staff_count = db.execute(
            "SELECT COUNT(*) FROM users WHERE role='staff' AND active=1").fetchone()[0]
        today_sched = db.execute(
            """SELECT s.date, u.full_name, sh.name AS shift_name, sh.color, f.flight_no
               FROM schedules s JOIN users u ON u.id=s.user_id
               JOIN shifts sh ON sh.id=s.shift_id
               LEFT JOIN flights f ON f.id=s.flight_id
               WHERE s.date=? ORDER BY sh.start_time""", (today,)).fetchall()
        pending = db.execute(
            "SELECT COUNT(*) FROM leave_requests WHERE status='pending'").fetchone()[0]
    else:
        staff_count = 0
        today_sched = []
        pending = 0
    db.close()
    return render_template("index.html", today=today, shifts=shifts,
                           staff_count=staff_count, today_sched=today_sched,
                           pending=pending)


# ---------- 班表 ----------

@app.route("/schedule")
@login_required()
def schedule():
    d = request.args.get("date", date.today().isoformat())
    db = get_db()
    shifts = db.execute("SELECT * FROM shifts WHERE active=1 ORDER BY start_time").fetchall()
    staff = db.execute(
        "SELECT * FROM users WHERE role='staff' AND active=1 ORDER BY full_name").fetchall()
    rows = db.execute(
        """SELECT s.id, s.user_id, s.shift_id, s.note, sh.name AS shift_name, sh.color,
                  f.flight_no
           FROM schedules s JOIN shifts sh ON sh.id=s.shift_id
           LEFT JOIN flights f ON f.id=s.flight_id
           WHERE s.date=?""", (d,)).fetchall()
    db.close()
    grid = {s["id"]: {} for s in staff}
    for r in rows:
        grid.setdefault(r["user_id"], {})[r["shift_id"]] = r
    return render_template("schedule.html", date=d, shifts=shifts,
                           staff=staff, grid=grid)


@app.route("/schedule/add", methods=["POST"])
@login_required(("admin", "superadmin"))
def schedule_add():
    uid = int(request.form["user_id"])
    d = request.form["date"]
    sid = int(request.form["shift_id"])
    fid = request.form.get("flight_id") or None
    db = get_db()
    try:
        db.execute(
            "INSERT INTO schedules (user_id,date,shift_id,flight_id,created_by) VALUES (?,?,?,?,?)",
            (uid, d, sid, fid, session["user_id"]))
        db.commit()
    except Exception:
        db.close()
        flash(t("dup_shift", session.get("lang", "zh")), "warning")
        return redirect(url_for("schedule", date=d))
    db.close()
    return redirect(url_for("schedule", date=d))


@app.route("/schedule/delete/<int:sid>")
@login_required(("admin", "superadmin"))
def schedule_delete(sid):
    db = get_db()
    row = db.execute("SELECT date FROM schedules WHERE id=?", (sid,)).fetchone()
    db.execute("DELETE FROM schedules WHERE id=?", (sid,))
    db.commit()
    db.close()
    return redirect(url_for("schedule", date=row["date"] if row else date.today().isoformat()))


# ---------- 個人班表 ----------

@app.route("/my-schedule")
@login_required()
def my_schedule():
    uid = session["user_id"]
    if session["role"] in ("admin", "superadmin") and request.args.get("user_id"):
        uid = int(request.args["user_id"])
    db = get_db()
    rows = db.execute(
        """SELECT s.*, sh.name AS shift_name, sh.color, sh.start_time, sh.end_time,
                  f.flight_no, f.terminal, f.gate,
                  da.iata AS dep_iata, da.name_zh AS dep_name_zh, da.name_en AS dep_name_en,
                  da.name_ja AS dep_name_ja,
                  aa.iata AS arr_iata, aa.name_zh AS arr_name_zh, aa.name_en AS arr_name_en,
                  aa.name_ja AS arr_name_ja
           FROM schedules s JOIN shifts sh ON sh.id=s.shift_id
           LEFT JOIN flights f ON f.id=s.flight_id
           LEFT JOIN airports da ON da.id=f.dep_airport_id
           LEFT JOIN airports aa ON aa.id=f.arr_airport_id
           WHERE s.user_id=? ORDER BY s.date DESC LIMIT 60""", (uid,)).fetchall()
    user = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    db.close()
    return render_template("my_schedule.html", rows=rows, user=user)


# ---------- 人員管理（管理層）----------

@app.route("/users")
@login_required(("admin", "superadmin"))
def users():
    db = get_db()
    rows = db.execute("SELECT * FROM users ORDER BY role, full_name").fetchall()
    db.close()
    return render_template("users.html", users=rows, org=org_options(),
                           seniority=_seniority_map(rows))


def _seniority_map(rows):
    """由 hire_date 計算年資字串。"""
    out = {}
    today = date.today()
    for u in rows:
        hd = u["hire_date"] if "hire_date" in u.keys() else None
        if not hd:
            out[u["id"]] = "-"
            continue
        try:
            d = date.fromisoformat(hd[:10])
        except ValueError:
            out[u["id"]] = "-"
            continue
        months = (today.year - d.year) * 12 + (today.month - d.month)
        if today.day < d.day:
            months -= 1
        lang = session.get("lang", "zh")
        if months < 0:
            out[u["id"]] = "-"
        elif months < 12:
            out[u["id"]] = t("seniority_months", lang).format(m=months)
        else:
            out[u["id"]] = t("seniority_years", lang).format(
                y=months // 12, m=months % 12)
    return out


@app.route("/users/add", methods=["POST"])
@login_required(("admin", "superadmin"))
def users_add():
    import secrets
    import string
    alphabet = string.ascii_letters + string.digits
    default_pw = "".join(secrets.choice(alphabet) for _ in range(8))
    db = get_db()
    try:
        db.execute(
            """INSERT INTO users (username,password_hash,full_name,role,
                                  employee_no,department,unit,duty,job_title,hire_date)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (request.form["username"], hash_pw(default_pw),
             request.form["full_name"], "staff",
             request.form.get("employee_no"), request.form.get("department"),
             request.form.get("unit"), request.form.get("duty"),
             request.form.get("job_title"), request.form.get("hire_date")))
        db.commit()
    except Exception:
        db.close()
        flash(t("dup_username", session.get("lang", "zh")), "warning")
        return redirect(url_for("users"))
    db.close()
    flash(t("user_created", session.get("lang", "zh")).format(
        name=request.form["full_name"], pw=default_pw), "success")
    return redirect(url_for("users"))


@app.route("/users/set-role/<int:uid>/<newrole>")
@login_required("superadmin")
def users_set_role(uid, newrole):
    if newrole not in ("admin", "staff"):
        newrole = "staff"
    db = get_db()
    row = db.execute("SELECT role FROM users WHERE id=?", (uid,)).fetchone()
    if row and row["role"] != "superadmin":
        db.execute("UPDATE users SET role=? WHERE id=?", (newrole, uid))
        db.commit()
    db.close()
    return redirect(url_for("users"))


@app.route("/users/reset-pw/<int:uid>")
@login_required(("admin", "superadmin"))
def users_reset_pw(uid):
    """管理層把某人密碼重設回系統預設密碼。"""
    import secrets, string
    alphabet = string.ascii_letters + string.digits
    default_pw = "".join(secrets.choice(alphabet) for _ in range(8))
    db = get_db()
    db.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_pw(default_pw), uid))
    row = db.execute("SELECT full_name FROM users WHERE id=?", (uid,)).fetchone()
    db.commit()
    db.close()
    flash(t("pw_reset", session.get("lang", "zh")).format(
        name=row["full_name"] if row else uid, pw=default_pw), "success")
    return redirect(url_for("users"))


@app.route("/users/toggle/<int:uid>")
@login_required(("admin", "superadmin"))
def users_toggle(uid):
    db = get_db()
    db.execute("UPDATE users SET active=1-active WHERE id=?", (uid,))
    db.commit()
    db.close()
    return redirect(url_for("users"))


# ---------- 航班資訊 ----------

@app.route("/flights")
@login_required()
def flights():
    q = (request.args.get("q") or "").strip()
    fno = (request.args.get("flight_no") or "").strip()
    airline = (request.args.get("airline") or "").strip()
    fdate = (request.args.get("fdate") or "").strip()
    status = (request.args.get("fstatus") or "").strip()

    sql = """SELECT f.*,
                  da.iata AS dep_iata, da.name_zh AS dep_name_zh, da.name_en AS dep_name_en,
                  da.name_ja AS dep_name_ja, da.city_zh AS dep_city_zh, da.city_en AS dep_city_en,
                  da.city_ja AS dep_city_ja,
                  aa.iata AS arr_iata, aa.name_zh AS arr_name_zh, aa.name_en AS arr_name_en,
                  aa.name_ja AS arr_name_ja, aa.city_zh AS arr_city_zh, aa.city_en AS arr_city_en,
                  aa.city_ja AS arr_city_ja
           FROM flights f
           LEFT JOIN airports da ON da.id=f.dep_airport_id
           LEFT JOIN airports aa ON aa.id=f.arr_airport_id
           WHERE 1=1"""
    args = []
    if fno:
        sql += " AND f.flight_no LIKE ?"
        args.append(f"%{fno}%")
    if airline:
        sql += " AND f.airline LIKE ?"
        args.append(f"%{airline}%")
    if fdate:
        sql += " AND f.date=?"
        args.append(fdate)
    if status:
        sql += " AND f.status=?"
        args.append(status)
    if q:
        sql += (""" AND (f.flight_no LIKE ? OR f.airline LIKE ?
                    OR f.terminal LIKE ? OR f.gate LIKE ? OR f.stand LIKE ?
                    OR da.iata LIKE ? OR da.name_zh LIKE ? OR da.city_zh LIKE ?
                    OR aa.iata LIKE ? OR aa.name_zh LIKE ? OR aa.city_zh LIKE ?)""")
        like = f"%{q}%"
        args += [like] * 11
    sql += " ORDER BY f.date DESC, f.dep_time LIMIT 300"

    db = get_db()
    rows = db.execute(sql, args).fetchall()
    db.close()
    return render_template("flights.html", flights=rows, live=_live_positions(rows),
                           q=q, fno=fno, airline=airline, fdate=fdate,
                           fstatus=status,
                           statuses=("scheduled", "boarding", "departed",
                                     "arrived", "delayed", "cancelled"))


# ---------- OpenSky 即時位置（免 key）----------

_opensky_cache = {"ts": 0.0, "data": {}}


def _callsign_candidates(flight_no, airline, callsign):
    """由航班號/航空公司/自填 callsign 產生可能的 OpenSky callsign。"""
    import re
    cands = set()
    if callsign:
        cands.add(callsign.strip().upper().replace(" ", ""))
    fn = (flight_no or "").strip().upper().replace(" ", "")
    if fn:
        cands.add(fn)
        # 常見台灣航空公司 ICAO 對照
        icao_map = {"CI": "CAL", "BR": "EVA", "JX": "SJA", "IT": "AE",
                    "GX": "GEA", "VV": "VN", "MU": "CES", "CX": "CPA",
                    "SQ": "SIA", "NH": "ANA", "JL": "JAL", "KE": "KAL",
                    "TG": "THY", "HK": "HWU", "B7": "SR"}
        m = re.match(r"^([A-Z]{2})(\d+.*)$", fn)
        if m and m.group(1) in icao_map:
            cands.add(icao_map[m.group(1)] + m.group(2))
    return cands


def _live_positions(rows):
    """回傳 {flight_row_id: {lat, lon, baro, vel, on_ground, callsign}}。"""
    import time, urllib.request, json
    cands = {}
    for r in rows:
        cs = r["callsign"] if "callsign" in r.keys() else None
        for c in _callsign_candidates(r["flight_no"], r["airline"], cs):
            cands.setdefault(c, []).append(r["id"])
    if not cands:
        return {}
    now = time.time()
    if now - _opensky_cache["ts"] > 30 or not _opensky_cache["data"]:
        try:
            url = ("https://opensky-network.org/api/states/all"
                   "?lamin=18&lomin=108&lamax=34&lomax=132")
            req = urllib.request.Request(url, headers={"User-Agent": "scheduling/1.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode())
            table = {}
            for st in data.get("states", []):
                cs = (st[1] or "").strip().upper().replace(" ", "")
                if cs:
                    table[cs] = st
            _opensky_cache.update(ts=now, data=table)
        except Exception:
            _opensky_cache.update(ts=now, data=_opensky_cache["data"] or {})
    table = _opensky_cache["data"]
    out = {}
    for c, ids in cands.items():
        st = table.get(c)
        if not st:
            continue
        lon, lat, baro, on_ground, vel, ver = st[5], st[6], st[7], st[8], st[9], st[11]
        for fid in ids:
            out[fid] = {"lat": lat, "lon": lon, "baro": baro,
                        "on_ground": bool(on_ground), "vel": vel, "ver": ver,
                        "true_track": st[10], "callsign": c}
    return out


@app.route("/radar")
@login_required()
def radar():
    """雷達圖：顯示空域內所有真實在飛的飛機（OpenSky 公開資料）。"""
    import time, urllib.request, json
    # 可選空域（預設台灣）
    box = request.args.get("box", "tw")
    boxes = {
        "tw": (22.0, 118.0, 26.5, 123.5, "台灣"),
        "jp": (30.0, 128.0, 46.0, 146.0, "日本"),
        "hk": (21.5, 112.5, 24.5, 116.5, "港澳"),
        "sea": (-10.0, 95.0, 20.0, 125.0, "東南亞"),
        "all": (10.0, 100.0, 50.0, 150.0, "東亞"),
    }
    if box not in boxes:
        box = "tw"
    lamin, lomin, lamax, lomax, label = boxes[box]

    now = time.time()
    key = f"radar:{box}"
    cache = _opensky_cache.setdefault("boxes", {})
    if now - cache.get(key, {}).get("ts", 0) > 20:
        try:
            url = (f"https://opensky-network.org/api/states/all"
                   f"?lamin={lamin}&lomin={lomin}&lamax={lamax}&lomax={lomax}")
            req = urllib.request.Request(url, headers={"User-Agent": "scheduling/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
            planes = []
            for st in data.get("states", []):
                icao24, cs, origin, lon, lat, baro, on_ground = (
                    st[0], st[1], st[2], st[5], st[6], st[7], st[8])
                if lat is None or lon is None or on_ground:
                    continue
                cs = (cs or "").strip().upper().replace(" ", "")
                planes.append({
                    "icao24": icao24, "callsign": cs, "origin": origin or "",
                    "lat": lat, "lon": lon, "baro": baro, "vel": st[9],
                    "true_track": st[10], "ver": st[11], "squawk": st[14],
                })
            cache[key] = {"ts": now, "data": planes}
        except Exception:
            cache.setdefault(key, {"ts": now, "data": []})
    planes = cache.get(key, {}).get("data", [])

    # 自己建檔且已起飛的航班呼號 → 高亮
    db = get_db()
    rows = db.execute(
        """SELECT f.*,
                  da.iata AS dep_iata, da.city_zh AS dep_city_zh, da.city_en AS dep_city_en,
                  da.city_ja AS dep_city_ja,
                  aa.iata AS arr_iata, aa.city_zh AS arr_city_zh, aa.city_en AS arr_city_en,
                  aa.city_ja AS arr_city_ja
           FROM flights f
           LEFT JOIN airports da ON da.id=f.dep_airport_id
           LEFT JOIN airports aa ON aa.id=f.arr_airport_id
           WHERE f.status IN ('departed','delayed')
           ORDER BY f.date DESC, f.dep_time LIMIT 100""").fetchall()
    db.close()
    mine = {}
    for r in rows:
        cs = r["callsign"] if "callsign" in r.keys() else None
        for c in _callsign_candidates(r["flight_no"], r["airline"], cs):
            mine[c] = {
                "flight_no": r["flight_no"], "airline": r["airline"] or "",
                "dep_iata": r["dep_iata"], "arr_iata": r["arr_iata"],
                "dep_city": r["dep_city_zh"] or r["dep_city_en"] or r["dep_city_ja"] or "",
                "arr_city": r["arr_city_zh"] or r["arr_city_en"] or r["arr_city_ja"] or "",
                "dep_time": r["dep_time"], "arr_time": r["arr_time"],
                "date": r["date"], "status": r["status"],
            }
    for p in planes:
        p["mine"] = mine.get(p["callsign"])
    return render_template("radar.html", planes=planes, box=box,
                           boxes={k: v[4] for k, v in boxes.items()},
                           count=len(planes))


@app.route("/flights/new")
@login_required(("admin", "superadmin"))
def flights_new():
    db = get_db()
    countries = db.execute("SELECT * FROM countries ORDER BY name_zh").fetchall()
    airports = db.execute(
        """SELECT a.*, c.code AS country_code FROM airports a
           JOIN countries c ON c.id=a.country_id ORDER BY c.name_zh, a.iata""").fetchall()
    db.close()
    return render_template("flight_form.html", countries=countries, airports=airports)


@app.route("/flights/add", methods=["POST"])
@login_required(("admin", "superadmin"))
def flights_add():
    db = get_db()
    dep = request.form.get("dep_airport_id") or None
    arr = request.form.get("arr_airport_id") or None
    db.execute(
        """INSERT INTO flights (flight_no,airline,dep_airport_id,arr_airport_id,
                                dep_time,arr_time,terminal,gate,stand,status,date,callsign)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (request.form["flight_no"], request.form.get("airline"),
         dep, arr,
         request.form.get("dep_time"),
         request.form.get("arr_time"), request.form.get("terminal"),
         request.form.get("gate"), request.form.get("stand"),
         request.form.get("status", "scheduled"), request.form.get("date"),
         (request.form.get("callsign") or "").strip() or None))
    db.commit()
    db.close()
    return redirect(url_for("flights"))


# ---------- 休假申請 ----------

@app.route("/leave")
@login_required()
def leave():
    db = get_db()
    if session["role"] in ("admin", "superadmin"):
        rows = db.execute(
            """SELECT l.*, u.full_name FROM leave_requests l
               JOIN users u ON u.id=l.user_id ORDER BY l.created_at DESC""").fetchall()
    else:
        rows = db.execute(
            """SELECT l.*, u.full_name FROM leave_requests l
               JOIN users u ON u.id=l.user_id WHERE l.user_id=? ORDER BY l.created_at DESC""",
            (session["user_id"],)).fetchall()
    db.close()
    return render_template("leave.html", leaves=rows)


@app.route("/leave/apply", methods=["POST"])
@login_required()
def leave_apply():
    db = get_db()
    db.execute(
        "INSERT INTO leave_requests (user_id,start_date,end_date,leave_type,reason) VALUES (?,?,?,?,?)",
        (session["user_id"], request.form["start_date"], request.form["end_date"],
         request.form["leave_type"], request.form.get("reason")))
    db.commit()
    db.close()
    flash(t("leave_submitted", session.get("lang", "zh")), "success")
    return redirect(url_for("leave"))


@app.route("/leave/review/<int:lid>/<action>")
@login_required(("admin", "superadmin"))
def leave_review(lid, action):
    db = get_db()
    db.execute(
        "UPDATE leave_requests SET status=?, reviewed_by=?, reviewed_at=? WHERE id=?",
        ("approved" if action == "approve" else "rejected",
         session["user_id"], datetime.now().isoformat(), lid))
    db.commit()
    db.close()
    return redirect(url_for("leave"))


# ---------- 系統設定（管理層）----------

@app.route("/my-settings", methods=["GET", "POST"])
@login_required()
def my_settings():
    """登入者自行修改密碼。"""
    if request.method == "POST":
        old = request.form.get("old_password", "")
        new = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")
        db = get_db()
        row = db.execute("SELECT password_hash FROM users WHERE id=?",
                         (session["user_id"],)).fetchone()
        db.close()
        if not row or row["password_hash"] != hash_pw(old):
            flash(t("pw_wrong_old", session.get("lang", "zh")), "error")
        elif len(new) < 4:
            flash(t("pw_too_short", session.get("lang", "zh")), "error")
        elif new != confirm:
            flash(t("pw_mismatch", session.get("lang", "zh")), "error")
        else:
            db = get_db()
            db.execute("UPDATE users SET password_hash=? WHERE id=?",
                       (hash_pw(new), session["user_id"]))
            db.commit()
            db.close()
            flash(t("pw_changed", session.get("lang", "zh")), "success")
            return redirect(url_for("my_settings"))
    return render_template("my_settings.html")


@app.route("/settings", methods=["GET", "POST"])
@login_required(("admin", "superadmin"))
def settings():
    if request.method == "POST":
        set_setting("quick_login", "on" if request.form.get("quick_login") else "off")
        method = request.form.get("quick_method", "screen")
        if method not in ("fingerprint", "faceid", "screen"):
            method = "screen"
        set_setting("quick_method", method)
        flash(t("saved", session.get("lang", "zh")), "success")
        return redirect(url_for("settings"))
    quick = get_setting("quick_login", "off") == "on"
    method = get_setting("quick_method", "screen")
    return render_template("settings.html", quick=quick, method=method)


# ---------- 登入紀錄（僅最高權限）----------

@app.route("/login-logs")
@login_required("superadmin")
def login_logs():
    db = get_db()
    rows = db.execute(
        "SELECT * FROM login_logs ORDER BY created_at DESC, id DESC LIMIT 300").fetchall()
    db.close()
    return render_template("login_logs.html", logs=rows)


# ---------- 組織資料（部門／單位／職務／職稱）----------

ORG_KINDS = ("department", "unit", "duty", "job_title")


def org_options():
    db = get_db()
    opts = {k: db.execute(
        "SELECT name FROM org_items WHERE kind=? ORDER BY name", (k,)).fetchall()
        for k in ORG_KINDS}
    db.close()
    return {k: [r["name"] for r in v] for k, v in opts.items()}


@app.route("/org")
@login_required("superadmin")
def org():
    db = get_db()
    items = {k: db.execute(
        "SELECT * FROM org_items WHERE kind=? ORDER BY name", (k,)).fetchall()
        for k in ORG_KINDS}
    db.close()
    return render_template("org.html", items=items, kinds=ORG_KINDS)


@app.route("/org/add", methods=["POST"])
@login_required("superadmin")
def org_add():
    kind = request.form.get("kind")
    name = (request.form.get("name") or "").strip()
    if kind in ORG_KINDS and name:
        db = get_db()
        db.execute("INSERT OR IGNORE INTO org_items (kind,name) VALUES (?,?)",
                   (kind, name))
        db.commit()
        db.close()
        flash(t("saved", session.get("lang", "zh")), "success")
    return redirect(url_for("org"))


@app.route("/org/delete/<int:oid>")
@login_required("superadmin")
def org_delete(oid):
    db = get_db()
    db.execute("DELETE FROM org_items WHERE id=?", (oid,))
    db.commit()
    db.close()
    return redirect(url_for("org"))


# ---------- 個人資訊卡與大頭貼 ----------

AVATAR_DIR = Path(os.environ.get("SCHED_DATA", "/data")) / "avatars"
ALLOWED_EXT = {".png": "image/png", ".jpg": "image/jpeg",
               ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}


@app.route("/profile")
@app.route("/profile/<int:uid>")
@login_required()
def profile(uid=None):
    me = session["user_id"]
    role = session.get("role")
    # 一般人員只能看自己的資訊卡
    if uid is None or role == "staff":
        uid = me
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not user:
        db.close()
        flash(t("not_found", session.get("lang", "zh")), "warning")
        return redirect(url_for("index"))
    pending = db.execute(
        "SELECT * FROM avatar_requests WHERE user_id=? AND status='pending' "
        "ORDER BY id DESC LIMIT 1", (uid,)).fetchone()
    db.close()
    sen = _seniority_map([user]).get(uid, "-")
    return render_template("profile.html", user=user, seniority=sen,
                           pending=pending, is_self=(uid == me),
                           can_review=role in ("admin", "superadmin"))


@app.route("/profile/avatar/upload", methods=["POST"])
@login_required()
def avatar_upload():
    lang = session.get("lang", "zh")
    me = session["user_id"]
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?", (me,)).fetchone()
    f = request.files.get("avatar")
    if not f or not f.filename:
        db.close()
        flash(t("avatar_only_image", lang), "error")
        return redirect(url_for("profile"))
    ext = Path(f.filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        db.close()
        flash(t("avatar_only_image", lang), "error")
        return redirect(url_for("profile"))
    f.seek(0, 2)
    size = f.tell()
    f.seek(0)
    if size > 2 * 1024 * 1024:
        db.close()
        flash(t("avatar_too_big", lang), "error")
        return redirect(url_for("profile"))
    # 第一次上傳：直接存；已解鎖：改一次後再鎖住
    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    fname = f"{me}_{datetime.now().strftime('%Y%m%d%H%M%S')}{ext}"
    f.save(AVATAR_DIR / fname)
    old = user["avatar"] if "avatar" in user.keys() else None
    if old:
        try:
            (AVATAR_DIR / old).unlink(missing_ok=True)
        except Exception:
            pass
    db.execute("UPDATE users SET avatar=?, avatar_unlocked=0 WHERE id=?",
               (fname, me))
    db.commit()
    db.close()
    flash(t("avatar_uploaded" if not user["avatar"] else "avatar_changed",
            lang), "success")
    return redirect(url_for("profile"))


@app.route("/profile/avatar/request", methods=["POST"])
@login_required()
def avatar_request():
    lang = session.get("lang", "zh")
    me = session["user_id"]
    db = get_db()
    user = db.execute("SELECT avatar FROM users WHERE id=?", (me,)).fetchone()
    if not user or not user["avatar"]:
        db.close()
        flash(t("avatar_upload", lang), "warning")
        return redirect(url_for("profile"))
    pend = db.execute(
        "SELECT id FROM avatar_requests WHERE user_id=? AND status='pending'",
        (me,)).fetchone()
    if not pend:
        db.execute("INSERT INTO avatar_requests (user_id) VALUES (?)", (me,))
        db.commit()
    db.close()
    flash(t("avatar_request_sent", lang), "success")
    return redirect(url_for("profile"))


def _notify(recipient_id, title_key, body_key):
    """系統訊息通知（寄件人用收件者自己，顯示為系統）。"""
    lang = session.get("lang", "zh")
    db = get_db()
    db.execute(
        "INSERT INTO messages (sender_id, recipient_id, title, body, kind) "
        "VALUES (?,?,?,?, 'personal')",
        (recipient_id, recipient_id, t(title_key, lang), t(body_key, lang)))
    db.commit()
    db.close()


@app.route("/avatar-requests")
@login_required(("admin", "superadmin"))
def avatar_requests():
    db = get_db()
    reqs = db.execute(
        """SELECT a.*, u.full_name, u.username FROM avatar_requests a
           JOIN users u ON u.id=a.user_id
           WHERE a.status='pending' ORDER BY a.id DESC""").fetchall()
    db.close()
    return render_template("avatar_requests.html", reqs=reqs)


@app.route("/avatar-requests/review/<int:rid>/<decision>")
@login_required(("admin", "superadmin"))
def avatar_review(rid, decision):
    lang = session.get("lang", "zh")
    db = get_db()
    req = db.execute("SELECT * FROM avatar_requests WHERE id=?", (rid,)).fetchone()
    if not req or req["status"] != "pending":
        db.close()
        return redirect(url_for("avatar_requests"))
    approved = decision == "approve"
    db.execute(
        "UPDATE avatar_requests SET status=?, reviewed_by=?, reviewed_at=? WHERE id=?",
        ("approved" if approved else "rejected", session["user_id"],
         datetime.now().isoformat(), rid))
    if approved:
        db.execute("UPDATE users SET avatar_unlocked=1 WHERE id=?",
                   (req["user_id"],))
    db.commit()
    db.close()
    _notify(req["user_id"], "avatar",
            "avatar_approved_msg" if approved else "avatar_rejected_msg")
    return redirect(url_for("avatar_requests"))


@app.route("/avatars/<path:fname>")
@login_required()
def avatar_file(fname):
    from flask import send_from_directory
    return send_from_directory(AVATAR_DIR, fname)


# ---------- 訊息 ----------

MANAGER_ROLES = ("admin", "superadmin")


@app.route("/messages")
@login_required()
def messages():
    db = get_db()
    me = session["user_id"]
    role = session.get("role")
    if role in MANAGER_ROLES:
        rows = db.execute(
            """SELECT m.*, s.full_name AS sender_name, u.full_name AS recipient_name,
                      (SELECT COUNT(*) FROM message_reads r
                        WHERE r.message_id=m.id AND r.user_id=?) AS mine_read
               FROM messages m
               JOIN users s ON s.id=m.sender_id
               LEFT JOIN users u ON u.id=m.recipient_id
               WHERE m.sender_id=? OR m.recipient_id=?
                  OR (m.kind='announcement' AND m.recipient_id IS NULL)
               ORDER BY m.created_at DESC, m.id DESC LIMIT 300""",
            (me, me, me)).fetchall()
        sent = db.execute(
            """SELECT m.*, u.full_name AS recipient_name FROM messages m
               LEFT JOIN users u ON u.id=m.recipient_id
               WHERE m.sender_id=? ORDER BY m.created_at DESC, m.id DESC LIMIT 100""",
            (me,)).fetchall()
    else:
        rows = db.execute(
            """SELECT m.*, s.full_name AS sender_name, u.full_name AS recipient_name,
                      (SELECT COUNT(*) FROM message_reads r
                        WHERE r.message_id=m.id AND r.user_id=?) AS mine_read
               FROM messages m
               JOIN users s ON s.id=m.sender_id
               LEFT JOIN users u ON u.id=m.recipient_id
               WHERE m.recipient_id=?
                  OR (m.kind='announcement' AND m.recipient_id IS NULL)
               ORDER BY m.created_at DESC, m.id DESC LIMIT 300""",
            (me, me)).fetchall()
        sent = []
    staffs = db.execute(
        "SELECT id, full_name, username FROM users WHERE active=1 ORDER BY full_name"
    ).fetchall()
    unread = db.execute(
        """SELECT COUNT(*) c FROM messages m
           WHERE (m.recipient_id=? OR (m.kind='announcement' AND m.recipient_id IS NULL))
             AND NOT EXISTS (SELECT 1 FROM message_reads r
                             WHERE r.message_id=m.id AND r.user_id=?)""",
        (me, me)).fetchone()["c"]
    db.close()
    return render_template("messages.html", msgs=rows, sent=sent, staffs=staffs,
                           unread=unread, can_send=role in MANAGER_ROLES)


@app.route("/messages/send", methods=["POST"])
@login_required(MANAGER_ROLES)
def messages_send():
    lang = session.get("lang", "zh")
    title = (request.form.get("title") or "").strip()
    body = (request.form.get("body") or "").strip()
    kind = request.form.get("kind", "personal")
    recipient = request.form.get("recipient_id", type=int)
    if not title:
        flash(t("msg_need_title", lang), "warning")
    elif kind == "personal" and not recipient:
        flash(t("msg_select_recipient", lang), "warning")
    else:
        db = get_db()
        db.execute(
            "INSERT INTO messages (sender_id, recipient_id, title, body, kind) VALUES (?,?,?,?,?)",
            (session["user_id"], recipient if kind == "personal" else None,
             title, body, kind))
        db.commit()
        db.close()
        flash(t("msg_sent", lang), "success")
    return redirect(url_for("messages"))


@app.route("/messages/read/<int:mid>")
@login_required()
def messages_read(mid):
    db = get_db()
    db.execute(
        "INSERT OR IGNORE INTO message_reads (message_id, user_id) VALUES (?,?)",
        (mid, session["user_id"]))
    db.commit()
    db.close()
    nxt = request.args.get("next") or url_for("messages")
    return redirect(nxt)


@app.route("/messages/unread-count")
@login_required()
def messages_unread_count():
    db = get_db()
    me = session["user_id"]
    c = db.execute(
        """SELECT COUNT(*) c FROM messages m
           WHERE (m.recipient_id=? OR (m.kind='announcement' AND m.recipient_id IS NULL))
             AND NOT EXISTS (SELECT 1 FROM message_reads r
                             WHERE r.message_id=m.id AND r.user_id=?)""",
        (me, me)).fetchone()["c"]
    db.close()
    return jsonify(unread=c)


# ---------- API（之後接差勤用）----------

@app.route("/api/schedule")
@login_required()
def api_schedule():
    d = request.args.get("date", date.today().isoformat())
    db = get_db()
    rows = db.execute(
        """SELECT u.full_name, u.employee_no, sh.name AS shift, s.date, f.flight_no
           FROM schedules s JOIN users u ON u.id=s.user_id
           JOIN shifts sh ON sh.id=s.shift_id
           LEFT JOIN flights f ON f.id=s.flight_id
           WHERE s.date=?""", (d,)).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


if __name__ == "__main__":
    init_db()
    import os, threading
    if os.environ.get("FLASK_DEV"):
        app.run(host="0.0.0.0", port=5000, debug=False)
    else:
        from waitress import serve
        cert = os.environ.get("SSL_CERT")
        key = os.environ.get("SSL_KEY")
        if cert and key and os.path.exists(cert) and os.path.exists(key):
            # 背景跑 HTTP（相容舊網址），前景跑 HTTPS（werkzeug 支援 ssl_context）
            threading.Thread(
                target=lambda: serve(app, host="0.0.0.0", port=5000, threads=8),
                daemon=True).start()
            print("HTTPS on :8443, HTTP on :5000")
            from werkzeug.serving import run_simple
            run_simple("0.0.0.0", 8443, app,
                       ssl_context=(cert, key), threaded=True)
        else:
            serve(app, host="0.0.0.0", port=5000, threads=8)

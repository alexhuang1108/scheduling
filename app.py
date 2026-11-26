"""航空地勤排班系統 - Flask 主程式"""
import hashlib
import os
from functools import wraps
from datetime import date, datetime, timedelta
from pathlib import Path

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, send_file
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

WEEKDAYS_ZH = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]
WEEKDAYS_EN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
WEEKDAYS_JA = ["月", "火", "水", "木", "金", "土", "日"]


@app.route("/schedule")
@login_required()
def schedule():
    d = request.args.get("date", date.today().isoformat())
    view = request.args.get("view", "day")
    if view not in ("day", "week", "month"):
        view = "day"
    db = get_db()
    shifts = db.execute("SELECT * FROM shifts WHERE active=1 ORDER BY start_time").fetchall()
    staff = db.execute(
        "SELECT * FROM users WHERE role='staff' AND active=1 ORDER BY full_name").fetchall()

    base = date.fromisoformat(d)

    # 決定要顯示的日期範圍
    if view == "day":
        days = [base]
    elif view == "week":
        monday = base - timedelta(days=base.weekday())
        days = [monday + timedelta(days=i) for i in range(7)]
    else:  # month
        days = []
        cur = base.replace(day=1)
        while cur.month == base.month:
            days.append(cur)
            cur += timedelta(days=1)

    dmin, dmax = days[0].isoformat(), days[-1].isoformat()
    rows = db.execute(
        """SELECT s.id, s.user_id, s.shift_id, s.date, s.note,
                  sh.name AS shift_name, sh.color, f.flight_no
           FROM schedules s JOIN shifts sh ON sh.id=s.shift_id
           LEFT JOIN flights f ON f.id=s.flight_id
           WHERE s.date>=? AND s.date<=?""", (dmin, dmax)).fetchall()
    db.close()

    # grid[user_id][date][shift_id] = row
    grid = {s["id"]: {} for s in staff}
    for r in rows:
        grid.setdefault(r["user_id"], {}).setdefault(r["date"], {})[r["shift_id"]] = r

    lang = session.get("lang", "zh")
    weekdays = {"zh": WEEKDAYS_ZH, "en": WEEKDAYS_EN, "ja": WEEKDAYS_JA}.get(lang, WEEKDAYS_ZH)
    day_meta = [{"iso": dd.isoformat(),
                 "label": f"{dd.month}/{dd.day}",
                 "weekday": weekdays[dd.weekday()],
                 "is_weekend": dd.weekday() >= 5} for dd in days]

    return render_template("schedule.html", date=d, view=view, shifts=shifts,
                           staff=staff, grid=grid, day_meta=day_meta)


@app.route("/schedule/export")
@login_required(("admin", "superadmin"))
def schedule_export():
    """匯出指定日期總排班表為 Excel。"""
    from io import BytesIO
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    d = request.args.get("date", date.today().isoformat())
    db = get_db()
    shifts = db.execute("SELECT * FROM shifts WHERE active=1 ORDER BY start_time").fetchall()
    staff = db.execute(
        "SELECT * FROM users WHERE role='staff' AND active=1 ORDER BY full_name").fetchall()
    rows = db.execute(
        """SELECT s.user_id, s.shift_id, sh.name AS shift_name, sh.color, f.flight_no
           FROM schedules s JOIN shifts sh ON sh.id=s.shift_id
           LEFT JOIN flights f ON f.id=s.flight_id
           WHERE s.date=?""", (d,)).fetchall()
    db.close()

    grid = {}
    for r in rows:
        grid.setdefault(r["user_id"], {})[r["shift_id"]] = r

    wb = Workbook()
    ws = wb.active
    ws.title = d

    thin = Side(style="thin", color="CBD5E1")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    head_fill = PatternFill("solid", fgColor="1E3A8A")
    head_font = Font(bold=True, color="FFFFFF")
    center = Alignment(horizontal="center", vertical="center")

    headers = ["員工", "員工編號", "部門", "單位", "職務", "職稱"] + \
              [f"{sh['name']} {sh['start_time']}-{sh['end_time']}" for sh in shifts]
    ws.append(headers)
    for c in ws[1]:
        c.fill = head_fill
        c.font = head_font
        c.alignment = center
        c.border = border

    for s in staff:
        row = [s["full_name"], s["employee_no"] or "", s["department"] or "",
               s["unit"] or "", s["duty"] or "", s["job_title"] or ""]
        for sh in shifts:
            cell = grid.get(s["id"], {}).get(sh["id"])
            if cell:
                txt = sh["name"]
                if cell["flight_no"]:
                    txt += f"（{cell['flight_no']}）"
                row.append(txt)
            else:
                row.append("")
        ws.append(row)

    for r in range(2, ws.max_row + 1):
        for c in range(1, ws.max_column + 1):
            cell = ws.cell(row=r, column=c)
            cell.border = border
            if c >= 7:
                cell.alignment = center

    from openpyxl.utils import get_column_letter
    widths = [12, 10, 12, 12, 12, 12] + [16] * len(shifts)
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)
    return send_file(
        bio, as_attachment=True, download_name=f"schedule_{d}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


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


@app.route("/users/import", methods=["POST"])
@login_required(("admin", "superadmin"))
def users_import():
    """從 Excel 批次匯入人員（欄位：username, full_name, employee_no, department, unit, duty, job_title, hire_date）。"""
    import secrets, string
    from io import BytesIO
    from openpyxl import load_workbook

    f = request.files.get("file")
    if not f or not f.filename:
        flash(t("import_no_file", session.get("lang", "zh")), "warning")
        return redirect(url_for("users"))
    try:
        wb = load_workbook(BytesIO(f.read()), read_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
    except Exception:
        flash(t("import_bad_file", session.get("lang", "zh")), "warning")
        return redirect(url_for("users"))

    if not rows:
        flash(t("import_empty", session.get("lang", "zh")), "warning")
        return redirect(url_for("users"))

    # 解析標題列（支援繁中/英欄位名）
    header = [str(c).strip().lower() if c else "" for c in rows[0]]
    col_map = {}
    aliases = {
        "username": {"username", "帳號", "帳號id", "id"},
        "full_name": {"full_name", "姓名", "name", "員工姓名"},
        "employee_no": {"employee_no", "員工編號", "員工號", "employee no", "no"},
        "department": {"department", "部門", "dept"},
        "unit": {"unit", "單位"},
        "duty": {"duty", "職務"},
        "job_title": {"job_title", "職稱", "title"},
        "hire_date": {"hire_date", "到職日期", "到職日", "入職日期", "入職日", "member since"},
    }
    for i, h in enumerate(header):
        for key, names in aliases.items():
            if h in names:
                col_map[key] = i
                break

    if "username" not in col_map or "full_name" not in col_map:
        flash(t("import_bad_header", session.get("lang", "zh")), "warning")
        return redirect(url_for("users"))

    def cell(row, key):
        i = col_map.get(key)
        if i is None or i >= len(row):
            return None
        v = row[i]
        if v is None:
            return None
        if hasattr(v, "strftime"):
            return v.strftime("%Y-%m-%d")
        return str(v).strip() or None

    alphabet = string.ascii_letters + string.digits
    db = get_db()
    added, skipped = 0, 0
    pw_list = []
    for row in rows[1:]:
        uname = cell(row, "username")
        fname = cell(row, "full_name")
        if not uname or not fname:
            continue
        existing = db.execute("SELECT id FROM users WHERE username=?", (uname,)).fetchone()
        if existing:
            skipped += 1
            continue
        default_pw = "".join(secrets.choice(alphabet) for _ in range(8))
        try:
            db.execute(
                """INSERT INTO users (username,password_hash,full_name,role,
                                      employee_no,department,unit,duty,job_title,hire_date)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (uname, hash_pw(default_pw), fname, "staff",
                 cell(row, "employee_no"), cell(row, "department"),
                 cell(row, "unit"), cell(row, "duty"),
                 cell(row, "job_title"), cell(row, "hire_date")))
            added += 1
            pw_list.append(f"{fname}:{default_pw}")
        except Exception:
            skipped += 1
    db.commit()
    db.close()
    flash(t("import_done", session.get("lang", "zh")).format(
        added=added, skipped=skipped), "success")
    if pw_list:
        flash(t("import_pw_list", session.get("lang", "zh")).format(
            pw_list="、".join(pw_list[:10])), "info")
    return redirect(url_for("users"))


@app.route("/users/template")
@login_required(("admin", "superadmin"))
def users_template():
    """下載人員匯入 Excel 範本。"""
    from io import BytesIO
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "人員匯入"
    ws.append(["username", "full_name", "employee_no", "department",
               "unit", "duty", "job_title", "hire_date"])
    ws.append(["alice", "王小明", "G1001", "客運組", "", "", "", "2024-01-01"])
    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)
    return send_file(
        bio, as_attachment=True, download_name="staff_import_template.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


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


@app.route("/users/delete/<int:uid>", methods=["POST"])
@login_required("superadmin")
def users_delete(uid):
    """最高權限刪除離職人員帳號（連帶清掉排班/請假/訊息/頭貼紀錄）。"""
    db = get_db()
    row = db.execute(
        "SELECT role, full_name, avatar, active FROM users WHERE id=?", (uid,)).fetchone()
    if not row:
        db.close()
        return redirect(url_for("users"))
    if row["role"] == "superadmin":
        db.close()
        flash(t("cannot_delete_super", session.get("lang", "zh")), "warning")
        return redirect(url_for("users"))
    if row["active"]:
        db.close()
        flash(t("delete_inactive_only", session.get("lang", "zh")), "warning")
        return redirect(url_for("users"))
    # 先清關聯資料，再刪本人
    db.execute("DELETE FROM schedules WHERE user_id=?", (uid,))
    db.execute("DELETE FROM leave_requests WHERE user_id=?", (uid,))
    db.execute("DELETE FROM message_reads WHERE user_id=?", (uid,))
    db.execute("DELETE FROM avatar_requests WHERE user_id=?", (uid,))
    db.execute("DELETE FROM messages WHERE sender_id=? OR recipient_id=?", (uid, uid))
    db.execute("UPDATE login_logs SET user_id=NULL WHERE user_id=?", (uid,))
    db.execute("UPDATE schedules SET created_by=NULL WHERE created_by=?", (uid,))
    db.execute("DELETE FROM users WHERE id=?", (uid,))
    db.commit()
    db.close()
    if row["avatar"]:
        try:
            (AVATAR_DIR / row["avatar"]).unlink(missing_ok=True)
        except Exception:
            pass
    flash(t("user_deleted", session.get("lang", "zh")).format(
        name=row["full_name"]), "success")
    return redirect(url_for("users"))



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
    f = request.files.get("attachment")
    fname = None
    if f and f.filename:
        ext = Path(f.filename).suffix.lower()
        if ext in ALLOWED_DOC_EXT:
            f.seek(0, 2)
            size = f.tell()
            f.seek(0)
            if size <= 5 * 1024 * 1024:
                LEAVE_DOC_DIR.mkdir(parents=True, exist_ok=True)
                fname = f"leave_{session['user_id']}_{datetime.now().strftime('%Y%m%d%H%M%S')}{ext}"
                f.save(LEAVE_DOC_DIR / fname)
    db = get_db()
    db.execute(
        "INSERT INTO leave_requests (user_id,start_date,end_date,leave_type,reason,attachment) VALUES (?,?,?,?,?,?)",
        (session["user_id"], request.form["start_date"], request.form["end_date"],
         request.form["leave_type"], request.form.get("reason"), fname))
    db.commit()
    db.close()
    flash(t("leave_submitted", session.get("lang", "zh")), "success")
    return redirect(url_for("leave"))


@app.route("/leave/attachment/<fname>")
@login_required()
def leave_attachment(fname):
    from flask import send_from_directory
    return send_from_directory(LEAVE_DOC_DIR, fname)


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
LEAVE_DOC_DIR = Path(os.environ.get("SCHED_DATA", "/data")) / "leave_docs"
ALLOWED_EXT = {".png": "image/png", ".jpg": "image/jpeg",
               ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}
ALLOWED_DOC_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf"}


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

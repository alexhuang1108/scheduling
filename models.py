"""航空地勤排班系統 - 資料模型與初始化"""
import os
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(os.environ.get("SCHED_DB", Path(__file__).parent / "scheduling.db"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    full_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('superadmin','admin','staff')),
    employee_no TEXT,
    department TEXT,
    unit TEXT,
    duty TEXT,
    job_title TEXT,
    hire_date TEXT,
    avatar TEXT,
    avatar_unlocked INTEGER DEFAULT 0,
    avatar_pending INTEGER DEFAULT 0,
    active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS org_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL CHECK(kind IN ('department','unit','duty','job_title')),
    name TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(kind, name)
);

CREATE TABLE IF NOT EXISTS avatar_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
    created_at TEXT DEFAULT (datetime('now')),
    reviewed_by INTEGER REFERENCES users(id),
    reviewed_at TEXT
);

CREATE TABLE IF NOT EXISTS login_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id),
    username TEXT,
    full_name TEXT,
    role TEXT,
    action TEXT NOT NULL,
    method TEXT DEFAULT 'password',
    ip TEXT,
    user_agent TEXT,
    lang TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_id INTEGER NOT NULL REFERENCES users(id),
    recipient_id INTEGER REFERENCES users(id),
    title TEXT NOT NULL,
    body TEXT,
    kind TEXT NOT NULL DEFAULT 'personal' CHECK(kind IN ('personal','announcement')),
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS message_reads (
    message_id INTEGER NOT NULL REFERENCES messages(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    read_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (message_id, user_id)
);

CREATE TABLE IF NOT EXISTS shifts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    color TEXT DEFAULT '#6b7280',
    active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS countries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    name_zh TEXT NOT NULL,
    name_en TEXT NOT NULL,
    name_ja TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS airports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    iata TEXT UNIQUE NOT NULL,
    icao TEXT,
    name_zh TEXT NOT NULL,
    name_en TEXT NOT NULL,
    name_ja TEXT NOT NULL,
    city_zh TEXT,
    city_en TEXT,
    city_ja TEXT,
    country_id INTEGER REFERENCES countries(id)
);

CREATE TABLE IF NOT EXISTS flights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    flight_no TEXT NOT NULL,
    airline TEXT,
    dep_airport_id INTEGER REFERENCES airports(id),
    arr_airport_id INTEGER REFERENCES airports(id),
    dep_time TEXT,
    arr_time TEXT,
    terminal TEXT,
    gate TEXT,
    stand TEXT,
    status TEXT DEFAULT 'scheduled',
    date TEXT,
    callsign TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    date TEXT NOT NULL,
    shift_id INTEGER NOT NULL REFERENCES shifts(id),
    flight_id INTEGER REFERENCES flights(id),
    note TEXT,
    created_by INTEGER REFERENCES users(id),
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(user_id, date, shift_id)
);

CREATE TABLE IF NOT EXISTS leave_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    leave_type TEXT NOT NULL,
    reason TEXT,
    status TEXT DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
    reviewed_by INTEGER REFERENCES users(id),
    reviewed_at TEXT,
    attachment TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
"""

SEED_SHIFTS = [
    ("早班", "07:00", "15:00", "#f59e0b"),
    ("中班", "15:00", "23:00", "#3b82f6"),
    ("大夜班", "23:00", "07:00", "#8b5cf6"),
]

# 國家：code, 中, 英, 日
SEED_COUNTRIES = [
    ("TW", "臺灣", "Taiwan", "台湾"),
    ("JP", "日本", "Japan", "日本"),
    ("KR", "韓國", "South Korea", "韓国"),
    ("CN", "中國", "China", "中国"),
    ("HK", "香港", "Hong Kong", "香港"),
    ("MO", "澳門", "Macao", "マカオ"),
    ("SG", "新加坡", "Singapore", "シンガポール"),
    ("TH", "泰國", "Thailand", "タイ"),
    ("VN", "越南", "Vietnam", "ベトナム"),
    ("MY", "馬來西亞", "Malaysia", "マレーシア"),
    ("PH", "菲律賓", "Philippines", "フィリピン"),
    ("US", "美國", "United States", "アメリカ"),
    ("CA", "加拿大", "Canada", "カナダ"),
    ("GB", "英國", "United Kingdom", "イギリス"),
    ("DE", "德國", "Germany", "ドイツ"),
    ("FR", "法國", "France", "フランス"),
    ("NL", "荷蘭", "Netherlands", "オランダ"),
    ("IT", "義大利", "Italy", "イタリア"),
    ("ES", "西班牙", "Spain", "スペイン"),
    ("AU", "澳洲", "Australia", "オーストラリア"),
    ("NZ", "紐西蘭", "New Zealand", "ニュージーランド"),
    ("AE", "阿聯", "United Arab Emirates", "アラブ首長国連邦"),
    ("TR", "土耳其", "Türkiye", "トルコ"),
    ("IN", "印度", "India", "インド"),
    ("ID", "印尼", "Indonesia", "インドネシア"),
    ("KH", "柬埔寨", "Cambodia", "カンボジア"),
    ("MN", "蒙古", "Mongolia", "モンゴル"),
]

# 機場：iata, icao, 中名, 英名, 日名, 中城市, 英城市, 日城市, 國家code
SEED_AIRPORTS = [
    ("TPE", "RCTP", "臺灣桃園國際機場", "Taiwan Taoyuan International Airport", "台湾桃園国際空港", "桃園", "Taoyuan", "桃園", "TW"),
    ("TSA", "RCSS", "台北松山機場", "Taipei Songshan Airport", "台北松山空港", "台北", "Taipei", "台北", "TW"),
    ("KHH", "RCKH", "高雄國際機場", "Kaohsiung International Airport", "高雄国際空港", "高雄", "Kaohsiung", "高雄", "TW"),
    ("NRT", "RJAA", "成田國際機場", "Narita International Airport", "成田国際空港", "東京", "Tokyo", "東京", "JP"),
    ("HND", "RJTT", "東京羽田機場", "Tokyo Haneda Airport", "東京国際空港", "東京", "Tokyo", "東京", "JP"),
    ("KIX", "RJBB", "關西國際機場", "Kansai International Airport", "関西国際空港", "大阪", "Osaka", "大阪", "JP"),
    ("ITM", "RJOO", "大阪國際機場", "Osaka International Airport", "大阪国際空港", "大阪", "Osaka", "大阪", "JP"),
    ("NGO", "RJGG", "中部國際機場", "Chubu Centrair International Airport", "中部国際空港", "名古屋", "Nagoya", "名古屋", "JP"),
    ("FUK", "RJFF", "福岡機場", "Fukuoka Airport", "福岡空港", "福岡", "Fukuoka", "福岡", "JP"),
    ("CTS", "RJCC", "新千歲機場", "New Chitose Airport", "新千歳空港", "札幌", "Sapporo", "札幌", "JP"),
    ("OKA", "ROAH", "那霸機場", "Naha Airport", "那覇空港", "沖繩", "Okinawa", "沖縄", "JP"),
    ("ICN", "RKSI", "仁川國際機場", "Incheon International Airport", "仁川国際空港", "首爾", "Seoul", "ソウル", "KR"),
    ("GMP", "RKSS", "金浦機場", "Gimpo International Airport", "金浦空港", "首爾", "Seoul", "ソウル", "KR"),
    ("PUS", "RKPK", "金海機場", "Gimhae International Airport", "金海空港", "釜山", "Busan", "釜山", "KR"),
    ("PEK", "ZBAA", "北京首都國際機場", "Beijing Capital International Airport", "北京首都国際空港", "北京", "Beijing", "北京", "CN"),
    ("PKX", "ZBAD", "北京大興國際機場", "Beijing Daxing International Airport", "北京大興国際空港", "北京", "Beijing", "北京", "CN"),
    ("PVG", "ZSPD", "上海浦東國際機場", "Shanghai Pudong International Airport", "上海浦東国際空港", "上海", "Shanghai", "上海", "CN"),
    ("SHA", "ZSSS", "上海虹橋國際機場", "Shanghai Hongqiao International Airport", "上海虹橋国際空港", "上海", "Shanghai", "上海", "CN"),
    ("CAN", "ZGGG", "廣州白雲國際機場", "Guangzhou Baiyun International Airport", "広州白雲国際空港", "廣州", "Guangzhou", "広州", "CN"),
    ("XMN", "ZSAM", "廈門高崎國際機場", "Xiamen Gaoqi International Airport", "厦門高崎国際空港", "廈門", "Xiamen", "厦門", "CN"),
    ("HKG", "VHHH", "香港國際機場", "Hong Kong International Airport", "香港国際空港", "香港", "Hong Kong", "香港", "HK"),
    ("MFM", "VMMC", "澳門國際機場", "Macao International Airport", "マカオ国際空港", "澳門", "Macao", "マカオ", "MO"),
    ("SIN", "WSSS", "新加坡樟宜機場", "Singapore Changi Airport", "シンガポール・チャンギ空港", "新加坡", "Singapore", "シンガポール", "SG"),
    ("BKK", "VTBB", "素萬那普機場", "Suvarnabhumi Airport", "スワンナプーム国際空港", "曼谷", "Bangkok", "バンコク", "TH"),
    ("DMK", "VTBD", "廊曼國際機場", "Don Mueang International Airport", "ドンムアン空港", "曼谷", "Bangkok", "バンコク", "TH"),
    ("HAN", "VVNB", "內排國際機場", "Noi Bai International Airport", "ノイバイ国際空港", "河內", "Hanoi", "ハノイ", "VN"),
    ("SGN", "VVTS", "新山一國際機場", "Tan Son Nhat International Airport", "タンソンニャット国際空港", "胡志明市", "Ho Chi Minh City", "ホーチミン", "VN"),
    ("DAD", "VVDN", "峴港國際機場", "Da Nang International Airport", "ダナン国際空港", "峴港", "Da Nang", "ダナン", "VN"),
    ("KUL", "WMKK", "吉隆坡國際機場", "Kuala Lumpur International Airport", "クアラルンプール国際空港", "吉隆坡", "Kuala Lumpur", "クアラルンプール", "MY"),
    ("MNL", "RPLL", "尼諾伊阿基諾國際機場", "Ninoy Aquino International Airport", "ニノイ・アキノ国際空港", "馬尼拉", "Manila", "マニラ", "PH"),
    ("LAX", "KLAX", "洛杉磯國際機場", "Los Angeles International Airport", "ロサンゼルス国際空港", "洛杉磯", "Los Angeles", "ロサンゼルス", "US"),
    ("SFO", "KSFO", "舊金山國際機場", "San Francisco International Airport", "サンフランシスコ国際空港", "舊金山", "San Francisco", "サンフランシスコ", "US"),
    ("JFK", "KJFK", "甘迺迪國際機場", "John F. Kennedy International Airport", "ジョン・F・ケネディ国際空港", "紐約", "New York", "ニューヨーク", "US"),
    ("ORD", "KORD", "歐海尔國際機場", "O'Hare International Airport", "シカゴ・オヘア国際空港", "芝加哥", "Chicago", "シカゴ", "US"),
    ("SEA", "KSEA", "西雅圖塔科馬國際機場", "Seattle Tacoma International Airport", "シアトル・タコマ国際空港", "西雅圖", "Seattle", "シアトル", "US"),
    ("YVR", "CYVR", "溫哥華國際機場", "Vancouver International Airport", "バンクーバー国際空港", "溫哥華", "Vancouver", "バンクーバー", "CA"),
    ("YYZ", "CYYZ", "多倫多皮爾遜國際機場", "Toronto Pearson International Airport", "トロント・ピアソン国際空港", "多倫多", "Toronto", "トロント", "CA"),
    ("LHR", "EGLL", "倫敦希斯洛機場", "London Heathrow Airport", "ロンドン・ヒースロー空港", "倫敦", "London", "ロンドン", "GB"),
    ("FRA", "EDDF", "法蘭克福機場", "Frankfurt Airport", "フランクフルト空港", "法蘭克福", "Frankfurt", "フランクフルト", "DE"),
    ("MUC", "EDDM", "慕尼黑機場", "Munich Airport", "ミュンヘン空港", "慕尼黑", "Munich", "ミュンヘン", "DE"),
    ("CDG", "LFPG", "巴黎夏爾戴高樂機場", "Paris Charles de Gaulle Airport", "シャルル・ド・ゴール空港", "巴黎", "Paris", "パリ", "FR"),
    ("AMS", "EHAM", "阿姆斯特丹史基浦機場", "Amsterdam Airport Schiphol", "アムステルダム・スキポール空港", "阿姆斯特丹", "Amsterdam", "アムステルダム", "NL"),
    ("FCO", "LIRF", "羅馬菲烏米奇諾機場", "Leonardo da Vinci–Fiumicino Airport", "レオナルド・ダ・ヴィンチ空港", "羅馬", "Rome", "ローマ", "IT"),
    ("MAD", "LEMD", "馬德里巴拉哈斯機場", "Adolfo Suárez Madrid–Barajas Airport", "マドリード・バラハス空港", "馬德里", "Madrid", "マドリード", "ES"),
    ("SYD", "YSSY", "悉尼金斯福德史密斯機場", "Sydney Kingsford Smith Airport", "シドニーキングスフォースミス空港", "悉尼", "Sydney", "シドニー", "AU"),
    ("MEL", "YMML", "墨爾本機場", "Melbourne Airport", "メルボルン空港", "墨爾本", "Melbourne", "メルボルン", "AU"),
    ("AKL", "NZAA", "奧克蘭機場", "Auckland Airport", "オークランド空港", "奧克蘭", "Auckland", "オークランド", "NZ"),
    ("DXB", "OMDB", "杜拜國際機場", "Dubai International Airport", "ドバイ国際空港", "杜拜", "Dubai", "ドバイ", "AE"),
    ("IST", "LTFM", "伊斯坦堡機場", "Istanbul Airport", "イスタンブール空港", "伊斯坦堡", "Istanbul", "イスタンブール", "TR"),
    ("DEL", "VIDP", "英迪拉甘地國際機場", "Indira Gandhi International Airport", "インディラ・ガンディー国際空港", "新德里", "New Delhi", "ニューデリー", "IN"),
    ("CGK", "WIII", "蘇加諾哈達國際機場", "Soekarno-Hatta International Airport", "スカルノ・ハッタ国際空港", "雅加達", "Jakarta", "ジャカルタ", "ID"),
    ("REP", "VDSP", "暹粒國際機場", "Siem Reap International Airport", "シェムリアップ国際空港", "暹粒", "Siem Reap", "シェムリアップ", "KH"),
    ("UBN", "ZMCK", "成吉思汗國際機場", "Chinggis Khaan International Airport", "チンギス・ハーン国際空港", "烏蘭巴托", "Ulaanbaatar", "ウランバートル", "MN"),
]


def get_setting(key, default=None):
    conn = get_db()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key, value):
    conn = get_db()
    conn.execute(
        "INSERT INTO settings (key,value) VALUES (?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value))
    conn.commit()
    conn.close()


# 可模組化的導覽/模組顯示名稱（key -> 預設名稱）
MODULE_LABELS = {
    "nav_dashboard": "儀表板",
    "nav_schedule": "總排班表",
    "nav_mine": "我的班表",
    "nav_leave": "休假申請",
    "nav_messages": "訊息",
    "nav_profile": "個人資訊卡",
    "nav_my_settings": "我的設定",
    "nav_users": "人員管理",
    "nav_settings": "系統設定",
    "nav_logs": "登入紀錄",
}


def get_module_names():
    """取得各模組的自訂顯示名稱（未設定則回傳預設）。"""
    result = {}
    for key, default in MODULE_LABELS.items():
        result[key] = get_setting("module_name:" + key, default)
    return result


def log_login(user_id=None, username=None, full_name=None, role=None,
              action="login", method="password", ip=None, user_agent=None, lang=None):
    conn = get_db()
    conn.execute(
        """INSERT INTO login_logs
           (user_id,username,full_name,role,action,method,ip,user_agent,lang)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (user_id, username, full_name, role, action, method, ip, user_agent, lang))
    conn.commit()
    conn.close()


def init_db():
    conn = get_db()
    conn.executescript(SCHEMA)
    # 遷移：舊資料庫補上組織資料與大頭貼欄位
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
    for col, decl in [("unit", "TEXT"), ("duty", "TEXT"), ("job_title", "TEXT"),
                      ("hire_date", "TEXT"), ("avatar", "TEXT"),
                      ("avatar_unlocked", "INTEGER DEFAULT 0"),
                      ("avatar_pending", "INTEGER DEFAULT 0")]:
        if col not in cols:
            conn.execute(f"ALTER TABLE users ADD COLUMN {col} {decl}")
    fcols = {r["name"] for r in conn.execute("PRAGMA table_info(flights)")}
    if "callsign" not in fcols:
        conn.execute("ALTER TABLE flights ADD COLUMN callsign TEXT")
    lcols = {r["name"] for r in conn.execute("PRAGMA table_info(leave_requests)")}
    if "attachment" not in lcols:
        conn.execute("ALTER TABLE leave_requests ADD COLUMN attachment TEXT")
    conn.commit()
    # 預設三班制
    if conn.execute("SELECT COUNT(*) FROM shifts").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO shifts (name,start_time,end_time,color) VALUES (?,?,?,?)",
            SEED_SHIFTS)
    # 國家與機場基礎資料
    if conn.execute("SELECT COUNT(*) FROM countries").fetchone()[0] == 0:
        conn.executemany(
            "INSERT OR IGNORE INTO countries (code,name_zh,name_en,name_ja) VALUES (?,?,?,?)",
            SEED_COUNTRIES)
    if conn.execute("SELECT COUNT(*) FROM airports").fetchone()[0] == 0:
        rows = []
        for a in SEED_AIRPORTS:
            cid = conn.execute(
                "SELECT id FROM countries WHERE code=?", (a[8],)).fetchone()
            rows.append((a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7],
                         cid[0] if cid else None))
        conn.executemany(
            """INSERT OR IGNORE INTO airports
               (iata,icao,name_zh,name_en,name_ja,city_zh,city_en,city_ja,country_id)
               VALUES (?,?,?,?,?,?,?,?,?)""", rows)
    # 預設帳號：super / admin / staff（密碼都是 password123）
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        import hashlib
        h = hashlib.sha256("password123".encode()).hexdigest()
        conn.executemany(
            "INSERT INTO users (username,password_hash,full_name,role,employee_no,department) VALUES (?,?,?,?,?,?)",
            [
                ("super", h, "超級管理員", "superadmin", "S001", "管理部"),
                ("admin", h, "管理員", "admin", "A001", "管理部"),
                ("staff1", h, "王小明", "staff", "G1001", "客運組"),
                ("staff2", h, "李小華", "staff", "G1002", "客運組"),
                ("staff3", h, "陳大文", "staff", "G1003", "航務組"),
            ])
    # 系統設定預設值
    if conn.execute("SELECT COUNT(*) FROM settings").fetchone()[0] == 0:
        conn.executemany(
            "INSERT OR IGNORE INTO settings (key,value) VALUES (?,?)",
            [("quick_login", "off"), ("quick_method", "screen"),
             ("default_lang", "zh")])
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print("DB initialized:", DB_PATH)

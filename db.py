# -*- coding: utf-8 -*-
"""
أدوات قاعدة البيانات والمساعدات العامة
نظام إدارة المشاريع الإنشائية - Flask + SQLite (schema.db)

نفس الواجهة التي كانت متوفرة مع MySQL، لكن السائق الداخلي انتقل إلى
sqlite3 مع طبقة ترجمة صغيرة لتعبيرات MySQL الشائعة (%s -> ?).
"""
import os, re, sqlite3
from datetime import date

try:
    from config import DB_PATH
except ImportError:
    BASE = os.path.dirname(os.path.abspath(__file__))
    DB_PATH = os.environ.get('DB_PATH', os.path.join(BASE, 'database', 'schema.db'))


def _translate_sql(sql):
    """ترجمة استعلام MySQL إلى SQLite:
    - %s -> ? خارج النصوص
    - مادة_type_id<=>val  ->  (material_type_id IS NULL OR material_type_id = val)
    """
    out, i, n = [], 0, len(sql)
    in_str, quote = False, None
    while i < n:
        ch = sql[i]
        if in_str:
            out.append(ch)
            if ch == quote:
                in_str = False
            i += 1; continue
        if ch in ("'", '"'):
            in_str = True; quote = ch; out.append(ch); i += 1; continue
        if ch == '%' and i + 1 < n and sql[i + 1] == 's':
            out.append('?'); i += 2; continue
        out.append(ch); i += 1
    text = ''.join(out)
    # material_type_id <=> val  ->  (material_type_id IS val OR material_type_id IS NULL AND val IS NULL)
    # Simplified: only WHEN val is provided as placeholder `?`.
    text = re.sub(r"(\w+)\s*<=>\s*\?",
                  r"(\1 IS ? OR (\1 IS NULL AND ? IS NULL))",
                  text)
    return text


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON;')
    return conn


def _row_to_dict(row):
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}


def get_db():
    return _connect()


def db_query(sql, params=None, one=False):
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(_translate_sql(sql), list(params or ()))
        rows = cur.fetchall()
        conn.commit()
        if one:
            return _row_to_dict(rows[0]) if rows else None
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def db_exec(sql, params=None, fetch_id=False):
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(_translate_sql(sql), list(params or ()))
        lid = cur.lastrowid if fetch_id else None
        conn.commit()
        return lid
    finally:
        conn.close()


def db_exec_many(sql, seq_of_params):
    seq = list(seq_of_params or [])
    if not seq:
        return
    conn = _connect()
    try:
        cur = conn.cursor()
        ts = _translate_sql(sql)
        for p in seq:
            cur.execute(ts, list(p))
        conn.commit()
    finally:
        conn.close()


def esc(v): return (v or '').strip()


def num(v, default=0.0):
    try: return float(v)
    except (TypeError, ValueError): return default


def money(v):
    try: return "{:,.0f}".format(num(v))
    except Exception: return "0"


def today(): return date.today()


def month_start(): return date.today().replace(day=1)


# ---------- العملات ----------
def cur_list():
    return db_query("SELECT * FROM currencies ORDER BY is_local DESC, name_ar ASC")


def cur_by_id(cid):
    return db_query("SELECT * FROM currencies WHERE id=?", (cid,), one=True)


def make_tx(currency_id, amount, rate_override=None):
    c = cur_by_id(currency_id)
    if not c:
        c = cur_by_id(1)
    rate = num(rate_override) if rate_override is not None else num(c['rate_to_local'])
    amount_local = round(num(amount) * rate, 3)
    return rate, amount_local


# ---------- الإشعارات ----------
def notify(user_ids, title, message, link=None, ntype='info'):
    ids = [uid for uid in (user_ids or []) if uid]
    if ids:
        db_exec_many(
            "INSERT INTO notifications (user_id,title,message,type,link) VALUES (?,?,?,?,?)",
            [(uid, title, message, ntype, link) for uid in ids])


def admin_ids():
    return [r['id'] for r in db_query("SELECT id FROM users WHERE role='admin' AND is_active=1")]


def supervisor_ids(project_id):
    if not project_id: return []
    return [r['id'] for r in db_query(
        "SELECT id FROM users WHERE role='supervisor' AND project_id=? AND is_active=1", (project_id,))]


def notify_admins(title, message, link=None):
    notify(admin_ids(), title, message, link)


def notify_supervisors(project_id, title, message, link=None):
    notify(supervisor_ids(project_id), title, message, link)


# ---------- حالة المخزون ----------
def stock_balance(project_id=None, warehouse_id=None):
    sql = """SELECT sm.warehouse_id, wh.name AS warehouse_name,
                    sm.material_id, m.name_ar AS material_name, u.name_ar AS unit_name,
                    sm.material_type_id, sm.unit_id, mt.name_ar AS type_name,
                    SUM(CASE WHEN sm.movement_type IN ('in','return') THEN sm.quantity ELSE -sm.quantity END) AS balance
             FROM stock_movements sm
             JOIN warehouses wh ON wh.id = sm.warehouse_id
             JOIN materials m ON m.id = sm.material_id
             LEFT JOIN material_types mt ON mt.id = sm.material_type_id
             JOIN units u ON u.id = sm.unit_id
             WHERE 1=1"""
    params = []
    if project_id:
        sql += " AND wh.project_id=?"; params.append(project_id)
    if warehouse_id:
        sql += " AND sm.warehouse_id=?"; params.append(warehouse_id)
    sql += " GROUP BY sm.warehouse_id, sm.material_id, sm.material_type_id, sm.unit_id, m.name_ar, mt.name_ar, u.name_ar, wh.name ORDER BY m.name_ar, mt.name_ar, u.name_ar"
    return db_query(sql, params)


def stock_balance_row(warehouse_id, material_id, material_type_id, unit_id):
    """الرصيد الحالي لخلية محددة."""
    if material_type_id is None:
        r = db_query(
            """SELECT COALESCE(SUM(CASE WHEN movement_type IN ('in','return') THEN quantity ELSE -quantity END),0) AS b
               FROM stock_movements
               WHERE warehouse_id=? AND material_id=? AND material_type_id IS NULL AND unit_id=?""",
            (warehouse_id, material_id, unit_id), one=True)
    else:
        r = db_query(
            """SELECT COALESCE(SUM(CASE WHEN movement_type IN ('in','return') THEN quantity ELSE -quantity END),0) AS b
               FROM stock_movements
               WHERE warehouse_id=? AND material_id=? AND material_type_id=? AND unit_id=?""",
            (warehouse_id, material_id, material_type_id, unit_id), one=True)
    return num(r['b'] if r else 0)


def material_types_of(mid):
    return db_query("SELECT * FROM material_types WHERE material_id=? ORDER BY name_ar", (mid,))


def material_units_of(mid):
    return db_query(
        """SELECT mu.*, u.name_ar AS unit_name FROM material_units mu
           JOIN units u ON u.id=mu.unit_id WHERE mu.material_id=? ORDER BY u.name_ar""",
        (mid,))


def damaged_list(project_id=None, warehouse_id=None, material_id=None):
    sql = """SELECT d.*, wh.name AS warehouse_name, m.name_ar AS material_name,
                    mt.name_ar AS type_name, u.name_ar AS unit_name, u2.full_name AS by_name
             FROM damaged_goods d
             JOIN warehouses wh ON wh.id=d.warehouse_id
             JOIN materials m ON m.id=d.material_id
             LEFT JOIN material_types mt ON mt.id=d.material_type_id
             JOIN units u ON u.id=d.unit_id
             LEFT JOIN users u2 ON u2.id=d.created_by
             WHERE 1=1"""
    params = []
    if project_id: sql += " AND wh.project_id=?"; params.append(project_id)
    if warehouse_id: sql += " AND d.warehouse_id=?"; params.append(warehouse_id)
    if material_id: sql += " AND d.material_id=?"; params.append(material_id)
    sql += " ORDER BY d.damage_date DESC, d.id DESC"
    return db_query(sql, params)


def damaged_totals(project_id=None, warehouse_id=None):
    sql = """SELECT wh.name AS warehouse_name, m.name_ar AS material_name, mt.name_ar AS type_name,
                    u.name_ar AS unit_name, SUM(d.quantity) qty, COALESCE(SUM(d.value_local),0) AS val
             FROM damaged_goods d
             JOIN warehouses wh ON wh.id=d.warehouse_id
             JOIN materials m ON m.id=d.material_id
             LEFT JOIN material_types mt ON mt.id=d.material_type_id
             JOIN units u ON u.id=d.unit_id
             WHERE 1=1"""
    params = []
    if project_id: sql += " AND wh.project_id=?"; params.append(project_id)
    if warehouse_id: sql += " AND d.warehouse_id=?"; params.append(warehouse_id)
    sql += " GROUP BY wh.name, m.name_ar, mt.name_ar, u.name_ar ORDER BY m.name_ar"
    return db_query(sql, params)


def main_account(project_id):
    return db_query(
        "SELECT * FROM accounts WHERE project_id=? AND acc_type='project' AND is_main=1 ORDER BY id LIMIT 1",
        (project_id,), one=True)


def ensure_worker_account(worker_id, project_id):
    a = db_query(
        "SELECT id FROM accounts WHERE acc_type='worker' AND party_type='worker' AND party_id=?",
        (worker_id,), one=True)
    if a: return a['id']
    w = db_query("SELECT name FROM workers WHERE id=?", (worker_id,), one=True)
    return db_exec(
        "INSERT INTO accounts (project_id,name,acc_type,party_type,party_id) VALUES (?,?,'worker','worker',?)",
        (project_id, 'حساب العامل: ' + (w['name'] if w else ''), worker_id), fetch_id=True)


def ensure_supervisor_account(user_id, project_id):
    a = db_query(
        "SELECT id FROM accounts WHERE acc_type='supervisor' AND party_type='user' AND party_id=?",
        (user_id,), one=True)
    if a: return a['id']
    u = db_query("SELECT full_name FROM users WHERE id=?", (user_id,), one=True)
    return db_exec(
        "INSERT INTO accounts (project_id,name,acc_type,party_type,party_id) VALUES (?,?,'supervisor','user',?)",
        (project_id, 'حساب المشرف: ' + (u['full_name'] if u else ''), user_id), fetch_id=True)


def account_balance(account_id):
    r = db_query(
        """SELECT COALESCE(SUM(CASE WHEN direction='debit' THEN amount_local ELSE -amount_local END),0) AS b
           FROM account_entries WHERE account_id=?""", (account_id,), one=True)
    return num(r['b'] if r else 0)


def post_account_entry(account_id, project_id, direction, amount, currency_id, amount_local,
                      ref_type, ref_id, note, entry_date, created_by):
    db_exec(
        """INSERT INTO account_entries (account_id,project_id,direction,amount,currency_id,exchange_rate,
           amount_local,ref_type,ref_id,note,entry_date,created_by)
           VALUES (?,?,?,?,?,1,?,?,?,?,?,?)""",
        (account_id, project_id, direction, amount, currency_id, amount_local,
         ref_type, ref_id, note, entry_date, created_by))

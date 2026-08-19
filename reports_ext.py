# -*- coding: utf-8 -*-
"""تقارير لكل عامل، مشرف، مادة + تقرير حسابات مفصل"""
from datetime import date, timedelta
from flask import Blueprint, render_template, request

from db import db_query, num
from auth import require_roles, scope_project_id
from finance_ext import worker_balance, supervisor_balance

reports_ext_bp = Blueprint('reports_ext', __name__)


def _date_range():
    """تحويل فترة تاريخ مخصصة."""
    s = request.args.get('start') or ''
    e = request.args.get('end') or ''
    if not s or not e:
        today = date.today()
        s = today.replace(day=1).isoformat()
        e = today.isoformat()
    return s, e


# ============== تقرير كل عامل (مستحقات/خصومات/سحوبات حسابه) ==============
@reports_ext_bp.route('/worker')
@require_roles('admin','supervisor')
def worker_report():
    spid = scope_project_id()
    s, e = _date_range()
    wid = request.args.get('worker_id', type=int)
    sql = """SELECT w.id, w.name, wt.name_ar type_name, ph.name phase_name, p.name project_name,
                    w.wage_per_day, cc.code cur_code, cc.rate_to_local rate,
                    p.id project_id
             FROM workers w
             JOIN worker_types wt ON wt.id=w.worker_type_id
             JOIN phases ph ON ph.id=w.phase_id
             JOIN projects p ON p.id=ph.project_id
             JOIN currencies cc ON cc.id=w.currency_id WHERE 1=1"""
    params = []
    if spid:
        sql += " AND ph.project_id=%s"; params.append(spid)
    if wid:
        sql += " AND w.id=%s"; params.append(wid)
    sql += " ORDER BY p.name, ph.name, w.name"
    rows = db_query(sql, params)
    # تفصيل لكل عامل
    for r in rows:
        r['balance'] = worker_balance(r['id'])
        days = db_query(
            "SELECT COUNT(*) c FROM worker_attendance WHERE worker_id=%s AND work_date BETWEEN %s AND %s",
            (r['id'], s, e))[0]['c']
        r['days'] = days
        r['gross'] = num(r['wage_per_day']) * num(r['rate']) * days
        deds = db_query(
            """SELECT COALESCE(SUM(d.amount*c2.rate_to_local),0) t
               FROM worker_deductions d JOIN currencies c2 ON c2.id=d.currency_id
               WHERE d.worker_id=%s AND d.created_at BETWEEN %s AND %s + INTERVAL 1 DAY""",
            (r['id'], s, e))[0]['t']
        wds = db_query(
            """SELECT COALESCE(SUM(x.amount*c2.rate_to_local),0) t
               FROM worker_withdrawals x JOIN currencies c2 ON c2.id=x.currency_id
               WHERE x.worker_id=%s AND x.created_at BETWEEN %s AND %s + INTERVAL 1 DAY""",
            (r['id'], s, e))[0]['t']
        # المصروف/سحب من expense_lines على العامل
        line_deds = db_query(
            """SELECT COALESCE(SUM(el.total_local),0) t FROM expense_lines el
               WHERE el.worker_id=%s AND el.created_at BETWEEN %s AND %s + INTERVAL 1 DAY""",
            (r['id'], s, e))[0]['t']
        # حركات على حسابه
        acc_debits = db_query(
            """SELECT COALESCE(SUM(m.amount*c2.rate_to_local),0) t FROM worker_account_moves m
               JOIN currencies c2 ON c2.id=m.currency_id
               WHERE m.worker_id=%s AND m.move_type='debit' AND m.move_date BETWEEN %s AND %s""",
            (r['id'], s, e))[0]['t']
        acc_credits = db_query(
            """SELECT COALESCE(SUM(m.amount*c2.rate_to_local),0) t FROM worker_account_moves m
               JOIN currencies c2 ON c2.id=m.currency_id
               WHERE m.worker_id=%s AND m.move_type='credit' AND m.move_date BETWEEN %s AND %s""",
            (r['id'], s, e))[0]['t']
        r['deductions'] = num(deds) + num(line_deds) + num(acc_debits)
        r['withdrawals'] = num(wds) + num(acc_credits)
        r['net'] = r['gross'] - r['deductions'] - r['withdrawals']
    workers = db_query(
        "SELECT id, name FROM workers ORDER BY name") if not spid else db_query(
        "SELECT w.id, w.name FROM workers w JOIN phases ph ON ph.id=w.phase_id WHERE ph.project_id=%s ORDER BY w.name", (spid,))
    totals = {
        'gross': sum(num(r['gross']) for r in rows),
        'deductions': sum(num(r['deductions']) for r in rows),
        'withdrawals': sum(num(r['withdrawals']) for r in rows),
        'net': sum(num(r['net']) for r in rows),
        'balance': sum(num(r['balance']) for r in rows),
    }
    return render_template('reports_ext/worker_report.html', items=rows, workers=workers,
                           selected_wid=wid, start=s, end=e, totals=totals)


# ============== تقرير كل مشرف ==============
@reports_ext_bp.route('/supervisor')
@require_roles('admin')
def supervisor_report():
    s, e = _date_range()
    rows = db_query(
        """SELECT u.id, u.username, u.full_name, p.name project_name,
                  (SELECT COALESCE(SUM(exp.amount_local),0) FROM expenses exp
                   WHERE exp.created_by=u.id AND exp.expense_date BETWEEN %s AND %s) AS expenses,
                  (SELECT COALESCE(SUM(w.amount_local),0) FROM withdrawals w
                   WHERE w.created_by=u.id AND w.withdraw_date BETWEEN %s AND %s) AS withdrawals,
                  (SELECT COALESCE(SUM(sd.total_local),0) FROM supplier_deliveries sd
                   WHERE sd.created_by=u.id) AS deliveries_total
           FROM users u LEFT JOIN projects p ON p.id=u.project_id
           WHERE u.role='supervisor' AND u.is_active=1 ORDER BY u.full_name""", (s, e, s, e))
    for r in rows:
        r['balance'] = supervisor_balance(r['id'])
        r['acc_debits'] = db_query(
            """SELECT COALESCE(SUM(m.amount*c2.rate_to_local),0) t FROM supervisor_account_moves m
               JOIN currencies c2 ON c2.id=m.currency_id
               WHERE m.user_id=%s AND m.move_type='debit' AND m.move_date BETWEEN %s AND %s""",
            (r['id'], s, e))[0]['t']
        r['acc_credits'] = db_query(
            """SELECT COALESCE(SUM(m.amount*c2.rate_to_local),0) t FROM supervisor_account_moves m
               JOIN currencies c2 ON c2.id=m.currency_id
               WHERE m.user_id=%s AND m.move_type='credit' AND m.move_date BETWEEN %s AND %s""",
            (r['id'], s, e))[0]['t']
        r['net'] = num(r['expenses']) + num(r['withdrawals']) + num(r['acc_debits']) - num(r['acc_credits'])
    totals = {
        'expenses': sum(num(r['expenses']) for r in rows),
        'withdrawals': sum(num(r['withdrawals']) for r in rows),
        'balance': sum(num(r['balance']) for r in rows),
        'deliveries': sum(num(r['deliveries_total'] or 0) for r in rows),
    }
    return render_template('reports_ext/supervisor_report.html', items=rows, start=s, end=e, totals=totals)


# ============== تقرير كل مادة (مخزون، تالف، استهلاك) ==============
@reports_ext_bp.route('/material')
@require_roles('admin','supervisor')
def material_report():
    s, e = _date_range()
    spid = scope_project_id()
    # المادة
    items = db_query(
        """SELECT m.*, u.name_ar default_unit, c.code cur_code FROM materials m
           JOIN units u ON u.id=m.unit_id LEFT JOIN currencies c ON c.id=m.currency_id ORDER BY m.name_ar""")
    types_map = {}
    for r in db_query(
        """SELECT mt.*, COALESCE(SUM(d.quantity),0) damaged_qty
           FROM material_types mt LEFT JOIN damaged_stock d ON d.material_type_id=mt.id
           GROUP BY mt.id ORDER BY mt.material_id, mt.name_ar"""):
        types_map.setdefault(r['material_id'], []).append(r)
    rpmap = {}
    units_map = {}
    for r in db_query(
        """SELECT mu.*, u.name_ar unit_name FROM material_units mu JOIN units u ON u.id=mu.unit_id"""):
        units_map.setdefault(r['material_id'], []).append(r)
    # المخزون الحالي والحركات في الفترة لكل مادة
    rows_data = []
    for m in items:
        # الرصيد الافتتاحي للفترة
        in_total = db_query(
            """SELECT COALESCE(SUM(sm.quantity),0) t FROM stock_movements sm
               WHERE sm.material_id=%s AND sm.movement_type='in' AND sm.movement_date<%s""",
            (m['id'], s))[0]['t']
        out_total = db_query(
            """SELECT COALESCE(SUM(sm.quantity),0) t FROM stock_movements sm
               WHERE sm.material_id=%s AND sm.movement_type='out' AND sm.movement_date<%s""",
            (m['id'], s))[0]['t']
        damage_total = db_query(
            """SELECT COALESCE(SUM(sm.quantity),0) t FROM stock_movements sm
               WHERE sm.material_id=%s AND sm.movement_type='damage' AND sm.movement_date<%s""",
            (m['id'], s))[0]['t']
        opening_bal = num(in_total) - num(out_total) - num(damage_total)
        # في الفترة
        in_period = db_query(
            """SELECT COALESCE(SUM(sm.quantity),0) t FROM stock_movements sm
               WHERE sm.material_id=%s AND sm.movement_type='in' AND sm.movement_date BETWEEN %s AND %s""",
            (m['id'], s, e))[0]['t']
        out_period = db_query(
            """SELECT COALESCE(SUM(sm.quantity),0) t FROM stock_movements sm
               WHERE sm.material_id=%s AND sm.movement_type='out' AND sm.movement_date BETWEEN %s AND %s""",
            (m['id'], s, e))[0]['t']
        damage_period = db_query(
            """SELECT COALESCE(SUM(sm.quantity),0) t FROM stock_movements sm
               WHERE sm.material_id=%s AND sm.movement_type='damage' AND sm.movement_date BETWEEN %s AND %s""",
            (m['id'], s, e))[0]['t']
        current = opening_bal + num(in_period) - num(out_period) - num(damage_period)
        damaged_total = db_query(
            "SELECT COALESCE(SUM(quantity),0) t FROM damaged_stock WHERE material_id=%s AND damaged_date BETWEEN %s AND %s",
            (m['id'], s, e))[0]['t']
        # قيمة الإهلاك من expense_lines
        used_value = db_query(
            """SELECT COALESCE(SUM(el.total_local),0) t FROM expense_lines el
               WHERE el.material_id=%s AND el.created_at BETWEEN %s AND %s + INTERVAL 1 DAY""",
            (m['id'], s, e))[0]['t']
        rows_data.append(dict(
            id=m['id'], name=m['name_ar'], default_unit=m['default_unit'], cur_code=m['cur_code'] or '',
            opening=opening_bal, in_qty=num(in_period), out_qty=num(out_period),
            damage_qty=num(damage_period)+num(damaged_total), current=current, used_value=num(used_value),
            types=types_map.get(m['id'], []), units=units_map.get(m['id'], [])
        ))
    totals = {
        'opening': sum(r['opening'] for r in rows_data),
        'in_qty': sum(r['in_qty'] for r in rows_data),
        'out_qty': sum(r['out_qty'] for r in rows_data),
        'damage_qty': sum(r['damage_qty'] for r in rows_data),
        'used_value': sum(r['used_value'] for r in rows_data),
    }
    return render_template('reports_ext/material_report.html', items=rows_data, start=s, end=e, totals=totals)


# ============== قائمة الحسابات الرئيسية ==============
@reports_ext_bp.route('/accounts-summary')
@require_roles('admin')
def accounts_summary():
    pae = db_query(
        """SELECT entry_type, sum(amount_local) tot, sum(recognized_amount_local) rec_tot,
                  COUNT(*) n FROM project_account_entries GROUP BY entry_type""")
    pae_map = {r['entry_type']: r for r in pae}
    workers_total = db_query(
        """SELECT COALESCE(SUM(opening_balance + COALESCE(m.b,0)),0) t FROM worker_account wa
           LEFT JOIN (SELECT worker_id, SUM(CASE WHEN move_type='credit' THEN amount ELSE -amount END) b
                      FROM worker_account_moves GROUP BY worker_id) m ON m.worker_id=wa.worker_id""")[0]['t']
    sups_total = db_query(
        """SELECT COALESCE(SUM(opening_balance + COALESCE(m.b,0)),0) t FROM supervisor_account sa
           LEFT JOIN (SELECT user_id, SUM(CASE WHEN move_type='credit' THEN amount ELSE -amount END) b
                      FROM supervisor_account_moves GROUP BY user_id) m ON m.user_id=sa.user_id""")[0]['t']
    damaged_total = db_query("SELECT COALESCE(SUM(quantity),0) t FROM damaged_stock")[0]['t']
    return render_template('reports_ext/accounts_summary.html',
                           pae_map=pae_map,
                           workers_total=num(workers_total),
                           sups_total=num(sups_total),
                           damaged_total=num(damaged_total))

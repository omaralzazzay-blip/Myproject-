# -*- coding: utf-8 -*-
"""التقارير: عامة / كشوف حسابات (عامل، مشرف) / حركة مادة / تالف / مالية
   مع تصدير PDF و Excel بدعم كامل للعربية."""
from datetime import date, timedelta
from io import BytesIO
from flask import Blueprint, render_template, request, send_file

from db import db_query, num, stock_balance, damaged_list, damaged_totals
from auth import require_roles, is_admin, scope_project_id
import exporters

reports_bp = Blueprint('reports', __name__)

PERIODS = {'daily': 'يومي', 'weekly': 'أسبوعي', 'monthly': 'شهري', 'yearly': 'سنوي'}


def _find_range(period, ref):
    try:
        d = date.fromisoformat(ref) if ref else date.today()
    except ValueError:
        d = date.today()
    if period == 'daily':
        return d, d
    if period == 'weekly':
        start = d - timedelta(days=d.weekday())
        return start, start + timedelta(days=6)
    if period == 'monthly':
        start = d.replace(day=1)
        return start, (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    if period == 'yearly':
        start = d.replace(month=1, day=1)
        return start, d.replace(month=12, day=31)
    return d, d


def _collect(period, ref, project_id=None, phase_id=None):
    start, end = _find_range(period, ref)
    where = " WHERE %s BETWEEN %s AND %s"
    params = [start, end]
    pwhere = " WHERE 1=1"
    pparams = []
    if project_id:
        pwhere += " AND project_id=%s"; pparams.append(project_id)
    if phase_id:
        pwhere += " AND phase_id=%s"; pparams.append(phase_id)
    expenses = db_query("SELECT COALESCE(SUM(amount_local),0) t FROM expenses WHERE expense_date BETWEEN %s AND %s", params)[0]['t']
    withdrawals = db_query("SELECT COALESCE(SUM(amount_local),0) t FROM withdrawals WHERE withdraw_date BETWEEN %s AND %s", params)[0]['t']
    exp_detail = db_query("SELECT COALESCE(SUM(amount_local),0) t FROM expenses" + pwhere, pparams)[0]['t']
    wd_detail = db_query("SELECT COALESCE(SUM(amount_local),0) t FROM withdrawals" + pwhere, pparams)[0]['t']
    stock_in = db_query("SELECT COALESCE(SUM(total_local),0) t FROM stock_movements WHERE movement_type='in' AND movement_date BETWEEN %s AND %s",
                        (start, end))[0]['t']
    stock_out = db_query("SELECT COALESCE(SUM(total_local),0) t FROM stock_movements WHERE movement_type IN ('out','damage') AND movement_date BETWEEN %s AND %s",
                         (start, end))[0]['t']
    budget_added = db_query("SELECT COALESCE(SUM(amount_local),0) t FROM budgets WHERE created_at >= %s AND created_at <= %s + INTERVAL 1 DAY",
                            (start, end))[0]['t']
    rows_exp = db_query(
        """SELECT 'مصروف' kind, e.expense_date d, e.description txt, e.amount_local amt,
                  p.name project_name, ph.name phase_name
           FROM expenses e LEFT JOIN projects p ON p.id=e.project_id LEFT JOIN phases ph ON ph.id=e.phase_id
           WHERE e.expense_date BETWEEN %s AND %s ORDER BY e.expense_date DESC""", (start, end))
    rows_wd = db_query(
        """SELECT 'سحب' kind, w.withdraw_date d, w.description txt, w.amount_local amt,
                  p.name project_name, ph.name phase_name
           FROM withdrawals w LEFT JOIN projects p ON p.id=w.project_id LEFT JOIN phases ph ON ph.id=w.phase_id
           WHERE w.withdraw_date BETWEEN %s AND %s ORDER BY w.withdraw_date DESC""", (start, end))
    rows = sorted(rows_exp + rows_wd, key=lambda r: r['d'], reverse=True)
    return dict(start=start, end=end, expenses=expenses, withdrawals=withdrawals,
                exp_detail=exp_detail, wd_detail=wd_detail, stock_in=stock_in, stock_out=stock_out,
                budget_added=budget_added, rows=rows)


# ---------------- تقرير عام (د/أ/ش/س) ----------------
@reports_bp.route('/reports')
@require_roles('admin', 'supervisor')
def reports_home():
    period = request.args.get('period') or 'monthly'
    ref = request.args.get('ref') or date.today().isoformat()
    project_id = request.args.get('project_id', type=int)
    phase_id = request.args.get('phase_id', type=int)
    spid = scope_project_id()
    if spid:
        project_id = spid
        phase_id = None
    projects = db_query("SELECT id, name FROM projects ORDER BY name")
    phases = db_query("SELECT ph.id, ph.name, p.name AS pname FROM phases ph JOIN projects p ON p.id=ph.project_id ORDER BY p.name, ph.name")
    data = _collect(period, ref, project_id, phase_id)

    workers_report = None
    if spid or is_admin():
        wsql = """SELECT w.id, w.name, wt.name_ar type_name, p.name project_name, ph.name phase_name,
                         w.wage_per_day, c.code cur_code, c.rate_to_local rate,
                         (SELECT COUNT(*) FROM worker_attendance a WHERE a.worker_id=w.id AND a.work_date BETWEEN %s AND %s) days
                  FROM workers w
                  JOIN worker_types wt ON wt.id=w.worker_type_id
                  JOIN phases ph ON ph.id=w.phase_id
                  JOIN projects p ON p.id=ph.project_id
                  JOIN currencies c ON c.id=w.currency_id WHERE 1=1"""
        wparams = [data['start'], data['end']]
        if spid:
            wsql += " AND ph.project_id=%s"; wparams.append(spid)
        if phase_id:
            wsql += " AND w.phase_id=%s"; wparams.append(phase_id)
        wsql += " ORDER BY p.name, ph.name, w.name"
        rows_w = db_query(wsql, wparams)
        for r in rows_w:
            r['gross'] = num(r['wage_per_day']) * num(r['rate']) * num(r['days'])
            ded = num(db_query(
                """SELECT COALESCE(SUM(d.amount*d2.rate_to_local),0) t FROM worker_deductions d
                   JOIN currencies d2 ON d2.id=d.currency_id
                   WHERE d.worker_id=%s AND d.created_at BETWEEN %s AND %s + INTERVAL 1 DAY""",
                (r['id'], data['start'], data['end']))[0]['t'])
            wd2 = num(db_query(
                """SELECT COALESCE(SUM(x.amount*x2.rate_to_local),0) t FROM worker_withdrawals x
                   JOIN currencies x2 ON x2.id=x.currency_id
                   WHERE x.worker_id=%s AND x.created_at BETWEEN %s AND %s + INTERVAL 1 DAY""",
                (r['id'], data['start'], data['end']))[0]['t'])
            r['ded'] = ded; r['wd'] = wd2; r['net'] = r['gross'] - ded - wd2
        workers_report = rows_w

    balances = stock_balance(project_id=project_id or spid)

    if request.args.get('export') == 'pdf':
        rows_out = [[r['kind'], r['d'], r['txt'] or '—', r['project_name'] or '—', r['phase_name'] or '—', '{:,.0f}'.format(num(r['amt']))]
                    for r in data['rows']]
        buf = exporters.make_pdf('التقرير العام {} - من {} إلى {}'.format(PERIODS.get(period), data['start'], data['end']),
                                 ['النوع', 'التاريخ', 'البيان', 'المشروع', 'المرحلة', 'المبلغ (محلي)'], rows_out)
        return send_file(buf, mimetype='application/pdf', as_attachment=True, download_name='report_periodic.pdf')
    if request.args.get('export') == 'xlsx':
        rows_out = [[r['kind'], r['d'], r['txt'] or '—', r['project_name'] or '—', r['phase_name'] or '—', num(r['amt'])]
                    for r in data['rows']]
        buf = exporters.make_xlsx('التقرير العام', ['النوع', 'التاريخ', 'البيان', 'المشروع', 'المرحلة', 'المبلغ (محلي)'], rows_out)
        return send_file(buf, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                         as_attachment=True, download_name='report_periodic.xlsx')

    return render_template('reports/report.html', period=period, ref=ref,
                           period_name=PERIODS.get(period, ''),
                           project_id=project_id, phase_id=phase_id, projects=projects, phases=phases,
                           data=data, workers_report=workers_report, balances=balances)


# ---------------- كشف حساب العامل ----------------
@reports_bp.route('/reports/worker')
@require_roles('admin', 'supervisor')
def worker_report():
    spid = scope_project_id()
    wsql = """SELECT w.id, w.name, wt.name_ar type_name, p.name project_name, p.id project_id,
                     c.code cur_code FROM workers w
              JOIN worker_types wt ON wt.id=w.worker_type_id
              JOIN phases ph ON ph.id=w.phase_id JOIN projects p ON p.id=ph.project_id
              JOIN currencies c ON c.id=w.currency_id WHERE w.status='active'"""
    wparams = []
    if spid:
        wsql += " AND p.id=%s"; wparams.append(spid)
    wsql += " ORDER BY w.name"
    workers = db_query(wsql, wparams)
    wid = request.args.get('worker_id', type=int)
    if spid and wid and not any(w['id'] == wid for w in workers):
        wid = None
    frm = request.args.get('from') or date.today().replace(day=1).isoformat()
    to = request.args.get('to') or date.today().isoformat()
    rows, totals, worker = [], {}, None
    if wid:
        worker = db_query("SELECT * FROM workers WHERE id=%s", (wid,), one=True)
        rows = db_query(
            """SELECT i.*, w.name AS warehouse_name, m.name_ar AS material_name, mt.name_ar AS type_name,
                      u.name_ar AS unit_name, c.code AS cur_code
               FROM issues i
               LEFT JOIN warehouses w ON w.id=i.warehouse_id
               LEFT JOIN materials m ON m.id=i.material_id
               LEFT JOIN material_types mt ON mt.id=i.material_type_id
               LEFT JOIN units u ON u.id=i.unit_id
               JOIN currencies c ON c.id=i.currency_id
               WHERE i.beneficiary_type='worker' AND i.worker_id=%s AND i.issue_date BETWEEN %s AND %s
               ORDER BY i.issue_date, i.id""", (wid, frm, to))
        totals['material'] = sum(num(r['total_local']) for r in rows if r['issue_kind'] == 'material')
        totals['cash'] = sum(num(r['total_local']) for r in rows if r['issue_kind'] == 'cash')
        totals['all'] = totals['material'] + totals['cash']
    export = request.args.get('export')
    if export in ('pdf', 'xlsx') and wid:
        out = [[r['issue_date'], 'مواد' if r['issue_kind'] == 'material' else 'نقدي',
                r['material_name'] or '—', '{:,.0f}'.format(num(r['quantity'])) if r['quantity'] else '—',
                r['unit_name'] or '—', '{:,.0f}'.format(num(r['total_local'])), r['description'] or '—']
               for r in rows]
        out.append(['', 'الإجمالي', '', '', '', '{:,.0f}'.format(totals['all']), ''])
        headers = ['التاريخ', 'النوع', 'المادة', 'الكمية', 'الوحدة', 'المبلغ (محلي)', 'البيان']
        title = 'كشف حساب العامل: {} ({} → {})'.format(worker['name'], frm, to)
        if export == 'pdf':
            buf = exporters.make_pdf(title, headers, out, landscape=True)
            return send_file(buf, mimetype='application/pdf', as_attachment=True, download_name='worker_statement.pdf')
        buf = exporters.make_xlsx(title, headers, out)
        return send_file(buf, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                         as_attachment=True, download_name='worker_statement.xlsx')
    return render_template('reports/worker.html', workers=workers, wid=wid, frm=frm, to=to,
                           rows=rows, totals=totals, worker=worker)


# ---------------- كشف حساب المشرف ----------------
@reports_bp.route('/reports/supervisor')
@require_roles('admin', 'supervisor')
def supervisor_report():
    spid = scope_project_id()
    sql = """SELECT u.id, u.full_name AS name, p.name AS project_name FROM users u
             LEFT JOIN projects p ON p.id=u.project_id
             WHERE u.role='supervisor' AND u.is_active=1"""
    params = []
    if spid:
        sql += " AND u.project_id=%s"; params.append(spid)
    sql += " ORDER BY u.full_name"
    supervisors = db_query(sql, params)
    sid = request.args.get('supervisor_id', type=int)
    if spid and sid and not any(s['id'] == sid for s in supervisors):
        sid = None
    frm = request.args.get('from') or date.today().replace(day=1).isoformat()
    to = request.args.get('to') or date.today().isoformat()
    rows, totals, sup = [], {}, None
    if sid:
        sup = db_query("SELECT * FROM users WHERE id=%s", (sid,), one=True)
        rows = db_query(
            """SELECT i.*, w.name AS warehouse_name, m.name_ar AS material_name, mt.name_ar AS type_name,
                      u.name_ar AS unit_name, c.code AS cur_code
               FROM issues i
               LEFT JOIN warehouses w ON w.id=i.warehouse_id
               LEFT JOIN materials m ON m.id=i.material_id
               LEFT JOIN material_types mt ON mt.id=i.material_type_id
               LEFT JOIN units u ON u.id=i.unit_id
               JOIN currencies c ON c.id=i.currency_id
               WHERE i.beneficiary_type='supervisor' AND i.supervisor_user_id=%s AND i.issue_date BETWEEN %s AND %s
               ORDER BY i.issue_date, i.id""", (sid, frm, to))
        totals['material'] = sum(num(r['total_local']) for r in rows if r['issue_kind'] == 'material')
        totals['cash'] = sum(num(r['total_local']) for r in rows if r['issue_kind'] == 'cash')
        totals['all'] = totals['material'] + totals['cash']
    export = request.args.get('export')
    if export in ('pdf', 'xlsx') and sid:
        out = [[r['issue_date'], 'مواد' if r['issue_kind'] == 'material' else 'نقدي',
                r['material_name'] or '—', '{:,.0f}'.format(num(r['quantity'])) if r['quantity'] else '—',
                r['unit_name'] or '—', '{:,.0f}'.format(num(r['total_local'])), r['description'] or '—']
               for r in rows]
        out.append(['', 'الإجمالي', '', '', '', '{:,.0f}'.format(totals['all']), ''])
        headers = ['التاريخ', 'النوع', 'المادة', 'الكمية', 'الوحدة', 'المبلغ (محلي)', 'البيان']
        title = 'كشف حساب المشرف: {} ({} → {})'.format(sup['full_name'], frm, to)
        if export == 'pdf':
            buf = exporters.make_pdf(title, headers, out, landscape=True)
            return send_file(buf, mimetype='application/pdf', as_attachment=True, download_name='supervisor_statement.pdf')
        buf = exporters.make_xlsx(title, headers, out)
        return send_file(buf, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                         as_attachment=True, download_name='supervisor_statement.xlsx')
    return render_template('reports/supervisor.html', supervisors=supervisors, sid=sid, frm=frm, to=to,
                           rows=rows, totals=totals, sup=sup)


# ---------------- حركة مادة / رصيد / تالف ----------------
@reports_bp.route('/reports/material')
@require_roles('admin', 'supervisor')
def material_report():
    spid = scope_project_id()
    msql = "SELECT m.id, m.name_ar AS name, p.id AS project_id, p.name AS project_name FROM materials m CROSS JOIN projects p WHERE 1=1"
    mparams = []
    if spid:
        msql += " AND p.id=%s"; mparams.append(spid)
    msql += " ORDER BY m.name_ar, p.name"
    materials = db_query(msql, mparams)
    mid = request.args.get('material_id', type=int)
    wid = request.args.get('warehouse_id', type=int)
    frm = request.args.get('from') or (date.today() - timedelta(days=90)).isoformat()
    to = request.args.get('to') or date.today().isoformat()
    rows, summary = [], None
    warehouses = db_query("""SELECT w.*, p.name AS pname FROM warehouses w JOIN projects p ON p.id=w.project_id ORDER BY p.name""")
    if mid:
        wpar = [mid, frm, to]
        psql = """SELECT sm.*, wh.name AS warehouse_name, mt.name_ar AS type_name, u.name_ar AS unit_name,
                         m.name_ar AS material_name FROM stock_movements sm
                  JOIN warehouses wh ON wh.id=sm.warehouse_id
                  LEFT JOIN material_types mt ON mt.id=sm.material_type_id
                  JOIN units u ON u.id=sm.unit_id JOIN materials m ON m.id=sm.material_id
                  WHERE sm.material_id=%s AND sm.movement_date BETWEEN %s AND %s"""
        if wid:
            psql += " AND sm.warehouse_id=%s"; wpar.append(wid)
        psql += " ORDER BY sm.movement_date, sm.id"
        rows = db_query(psql, wpar)
        bal = 0.0
        for r in rows:
            d = num(r['quantity'])
            if r['movement_type'] in ('in', 'return'):
                bal += d
            else:
                bal -= d
            r['run'] = bal
        dmg = db_query(
            """SELECT COALESCE(SUM(quantity),0) q, COALESCE(SUM(value_local),0) v FROM damaged_goods d
               LEFT JOIN warehouses wh ON wh.id=d.warehouse_id
               WHERE d.material_id=%s AND d.damage_date BETWEEN %s AND %s""", (mid, frm, to))[0]
        summary = dict(balance=bal, dmg_qty=num(dmg['q']), dmg_val=num(dmg['v']))
    export = request.args.get('export')
    if export in ('pdf', 'xlsx') and mid:
        label = {'in': 'إدخال', 'out': 'صرف', 'return': 'إرجاع', 'damage': 'تالف'}
        out = [[r['movement_date'], r['warehouse_name'], r['type_name'] or '—',
                label.get(r['movement_type'], r['movement_type']), '{:,.0f}'.format(num(r['quantity'])),
                r['unit_name'], '{:,.0f}'.format(num(r['total_local'])), '{:,.0f}'.format(num(r['run']))]
               for r in rows]
        if summary:
            out.append(['', '', '', '', '', '', 'الرصيد النهائي', '{:,.0f}'.format(summary['balance'])])
            out.append(['', '', '', '', '', '', 'إجمالي التالف (كمية/قيمة)', '{:,.0f} / {:,.0f}'.format(summary['dmg_qty'], summary['dmg_val'])])
        headers = ['التاريخ', 'المخزن', 'النوع الفرعي', 'الحركة', 'الكمية', 'الوحدة', 'القيمة (محلي)', 'الرصيد الجاري']
        title = 'حركة المادة: {} ({} → {})'.format((db_query('SELECT name_ar FROM materials WHERE id=%s', (mid,), one=True) or {}).get('name_ar', ''), frm, to)
        if export == 'pdf':
            buf = exporters.make_pdf(title, headers, out, landscape=True)
            return send_file(buf, mimetype='application/pdf', as_attachment=True, download_name='material_statement.pdf')
        buf = exporters.make_xlsx(title, headers, out)
        return send_file(buf, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                         as_attachment=True, download_name='material_statement.xlsx')
    return render_template('reports/material.html', materials=materials, warehouses=warehouses,
                           mid=mid, wid=wid, frm=frm, to=to, rows=rows, summary=summary,
                           label={'in': 'إدخال', 'out': 'صرف', 'return': 'إرجاع', 'damage': 'تالف'})


# ---------------- تقرير التالف ----------------
@reports_bp.route('/reports/damaged')
@require_roles('admin', 'supervisor')
def damaged_report():
    spid = scope_project_id()
    frm = request.args.get('from') or (date.today() - timedelta(days=90)).isoformat()
    to = request.args.get('to') or date.today().isoformat()
    rows = db_query(
        """SELECT d.*, wh.name AS warehouse_name, m.name_ar AS material_name, mt.name_ar AS type_name,
                  u.name_ar AS unit_name, u2.full_name AS by_name
           FROM damaged_goods d
           JOIN warehouses wh ON wh.id=d.warehouse_id
           JOIN materials m ON m.id=d.material_id
           LEFT JOIN material_types mt ON mt.id=d.material_type_id
           JOIN units u ON u.id=d.unit_id
           LEFT JOIN users u2 ON u2.id=d.created_by
           WHERE d.damage_date BETWEEN %s AND %s""", (frm, to))
    if spid:
        rows = [r for r in rows if (db_query("SELECT project_id FROM warehouses WHERE id=%s", (r['warehouse_id'],), one=True) or {}).get('project_id') == spid]
    totals = dict(qty=sum(num(r['quantity']) for r in rows), val=sum(num(r['value_local']) for r in rows))
    export = request.args.get('export')
    if export in ('pdf', 'xlsx'):
        out = [[r['damage_date'], r['warehouse_name'], r['material_name'], r['type_name'] or '—',
                '{:,.0f}'.format(num(r['quantity'])), r['unit_name'], '{:,.0f}'.format(num(r['value_local'])),
                r['reason'] or '—', r['by_name'] or '—'] for r in rows]
        out.append(['', '', '', '', '', '', '{:,.0f}'.format(totals['val']), 'الإجمالي', ''])
        headers = ['التاريخ', 'المخزن', 'المادة', 'النوع', 'الكمية', 'الوحدة', 'القيمة (محلي)', 'السبب', 'بواسطة']
        title = 'تقرير التالف ({} → {})'.format(frm, to)
        if export == 'pdf':
            buf = exporters.make_pdf(title, headers, out, landscape=True)
            return send_file(buf, mimetype='application/pdf', as_attachment=True, download_name='damaged_report.pdf')
        buf = exporters.make_xlsx(title, headers, out)
        return send_file(buf, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                         as_attachment=True, download_name='damaged_report.xlsx')
    return render_template('reports/damaged.html', rows=rows, totals=totals, frm=frm, to=to)


# ---------------- التقرير المالي الشامل ----------------
@reports_bp.route('/reports/financial')
@require_roles('admin', 'supervisor')
def financial_report():
    spid = scope_project_id()
    sql = """SELECT p.id, p.name,
                    (SELECT COALESCE(SUM(amount_local),0) FROM budgets b WHERE b.project_id=p.id AND b.level IN ('project','phase')) budget_p,
                    (SELECT COALESCE(SUM(amount_local),0) FROM funder_deposits d WHERE d.project_id=p.id) funding,
                    (SELECT COALESCE(SUM(amount_local),0) FROM expenses e WHERE e.project_id=p.id) expenses,
                    (SELECT COALESCE(SUM(amount_local),0) FROM withdrawals w WHERE w.project_id=p.id) withdrawals,
                    (SELECT COALESCE(SUM(total_local),0) FROM supplier_deliveries sd JOIN warehouses wh ON wh.id=sd.warehouse_id WHERE wh.project_id=p.id) supplies,
                    (SELECT COALESCE(SUM(e.amount_local),0) FROM account_entries e JOIN accounts a ON a.id=e.account_id WHERE a.project_id=p.id AND a.acc_type='creditor') creditors,
                    (SELECT COALESCE(SUM(e.amount_local),0) FROM account_entries e JOIN accounts a ON a.id=e.account_id WHERE a.project_id=p.id AND a.acc_type='debtor' AND e.direction='debit') debtors
             FROM projects p WHERE 1=1"""
    params = []
    if spid:
        sql += " AND p.id=%s"; params.append(spid)
    sql += " ORDER BY p.name"
    rows = db_query(sql, params)
    for r in rows:
        r['remaining'] = num(r['budget_p']) + num(r['funding']) - num(r['expenses']) - num(r['withdrawals']) - num(r['creditors'])
    owner = db_query("SELECT COALESCE(SUM(amount_local),0) t FROM budgets WHERE level='owner'")[0]['t']
    export = request.args.get('export')
    if export in ('pdf', 'xlsx'):
        out = [[r['name'], '{:,.0f}'.format(num(r['budget_p'])), '{:,.0f}'.format(num(r['funding'])),
                '{:,.0f}'.format(num(r['expenses'])), '{:,.0f}'.format(num(r['withdrawals'])),
                '{:,.0f}'.format(num(r['supplies'])), '{:,.0f}'.format(num(r['creditors'])),
                '{:,.0f}'.format(num(r['debtors'])), '{:,.0f}'.format(num(r['remaining']))] for r in rows]
        headers = ['المشروع', 'الميزانية', 'تمويل الممولين', 'المصاريف', 'المسحوبات', 'توريدات مواد',
                   'دائن (مخصوم فوراً)', 'مدين (محصل)', 'المتبقي']
        title = 'التقرير المالي الشامل - رأس مال المالك: {:,.0f}'.format(num(owner))
        if export == 'pdf':
            buf = exporters.make_pdf(title, headers, out, landscape=True)
            return send_file(buf, mimetype='application/pdf', as_attachment=True, download_name='financial_report.pdf')
        buf = exporters.make_xlsx(title, headers, out)
        return send_file(buf, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                         as_attachment=True, download_name='financial_report.xlsx')
    return render_template('reports/financial.html', rows=rows, owner=owner)

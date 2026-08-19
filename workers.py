# -*- coding: utf-8 -*-
"""إدارة العمال: الدوام، الخصومات، السحوبات، واحتساب الإجمالي بعد الخصومات"""
from datetime import date, datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, g

from db import db_query, db_exec, esc, num, today, month_start, notify_admins
from auth import require_roles, is_admin, scope_project_id

workers_bp = Blueprint('workers', __name__)


def _phases_in_scope():
    """المراحل المسموح للمستخدم الحالي التعامل معها."""
    spid = scope_project_id()
    if not spid:
        return db_query("SELECT ph.*, p.name AS project_name FROM phases ph JOIN projects p ON p.id=ph.project_id ORDER BY p.name, ph.name")
    return db_query(
        """SELECT ph.*, p.name AS project_name FROM phases ph JOIN projects p ON p.id=ph.project_id
           WHERE ph.project_id=%s ORDER BY p.name, ph.name""", (spid,))


@workers_bp.route('/workers')
@require_roles('admin', 'supervisor')
def list_workers():
    spid = scope_project_id()
    sql = """SELECT w.*, wt.name_ar AS type_name, c.code AS cur_code,
                    ph.name AS phase_name, p.name AS project_name,
                    (SELECT COUNT(*) FROM worker_attendance a WHERE a.worker_id=w.id) AS days_n,
                    (SELECT COALESCE(SUM(amount),0) FROM worker_deductions d WHERE d.worker_id=w.id) AS total_ded,
                    (SELECT COALESCE(SUM(amount),0) FROM worker_withdrawals x WHERE x.worker_id=w.id) AS total_wd
             FROM workers w
             JOIN worker_types wt ON wt.id=w.worker_type_id
             JOIN currencies c ON c.id=w.currency_id
             JOIN phases ph ON ph.id=w.phase_id
             JOIN projects p ON p.id=ph.project_id
             WHERE 1=1"""
    params = []
    if spid:
        sql += " AND ph.project_id=%s"
        params.append(spid)
    st = request.args.get('status')
    if st in ('active', 'stopped'):
        sql += " AND w.status=%s"
        params.append(st)
    sql += " ORDER BY p.name, ph.name, w.name"
    items = db_query(sql, params)
    return render_template('workers/list.html', items=items)


@workers_bp.route('/workers/add', methods=['GET', 'POST'])
@require_roles('admin', 'supervisor')
def add_worker():
    if request.method == 'POST':
        name = esc(request.form.get('name'))
        phase_id = request.form.get('phase_id', type=int)
        wtype = request.form.get('worker_type_id', type=int)
        wage = num(request.form.get('wage_per_day'))
        currency_id = request.form.get('currency_id', type=int) or 1
        if not name or not phase_id or not wtype or wage <= 0:
            flash('يرجى تعبئة البيانات بشكل صحيح', 'danger')
        else:
            db_exec(
                """INSERT INTO workers (phase_id,name,phone,worker_type_id,wage_per_day,currency_id,status,joined_date)
                   VALUES (%s,%s,%s,%s,%s,%s,'active',%s)""",
                (phase_id, name, esc(request.form.get('phone')), wtype, wage,
                 currency_id, request.form.get('joined_date') or today()))
            if not is_admin():
                ph = db_query("SELECT project_id FROM phases WHERE id=%s", (phase_id,), one=True)
                notify_admins('عامل جديد',
                              'أضاف المشرف {} العامل: {}'.format(g.current_user['full_name'], name),
                              url_for('projects.view_project', pid=ph['project_id'] if ph else None))
            flash('تمت إضافة العامل', 'success')
            return redirect(url_for('workers.list_workers'))
    phases = _phases_in_scope()
    types = db_query("SELECT * FROM worker_types ORDER BY name_ar")
    currencies = db_query("SELECT * FROM currencies ORDER BY is_local DESC, name_ar")
    return render_template('workers/form.html', item=None, phases=phases, types=types, currencies=currencies)


@workers_bp.route('/workers/<int:wid>/edit', methods=['GET', 'POST'])
@require_roles('admin', 'supervisor')
def edit_worker(wid):
    item = db_query("SELECT w.*, ph.project_id FROM workers w JOIN phases ph ON ph.id=w.phase_id WHERE w.id=%s", (wid,), one=True)
    if not item:
        flash('العامل غير موجود', 'warning')
        return redirect(url_for('workers.list_workers'))
    spid = scope_project_id()
    if spid and spid != item['project_id']:
        flash('ليست لديك صلاحية', 'warning')
        return redirect(url_for('workers.list_workers'))
    if request.method == 'POST':
        db_exec(
            """UPDATE workers SET name=%s, phone=%s, worker_type_id=%s, wage_per_day=%s,
               currency_id=%s, status=%s, joined_date=%s WHERE id=%s""",
            (esc(request.form.get('name')), esc(request.form.get('phone')),
             request.form.get('worker_type_id', type=int), num(request.form.get('wage_per_day')),
             request.form.get('currency_id', type=int) or 1, request.form.get('status') or 'active',
             request.form.get('joined_date') or today(), wid))
        flash('تم تحديث بيانات العامل', 'success')
        return redirect(url_for('workers.worker_detail', wid=wid))
    phases = _phases_in_scope()
    types = db_query("SELECT * FROM worker_types ORDER BY name_ar")
    currencies = db_query("SELECT * FROM currencies ORDER BY is_local DESC, name_ar")
    return render_template('workers/form.html', item=item, phases=phases, types=types, currencies=currencies)


@workers_bp.route('/workers/<int:wid>/delete', methods=['POST'])
@require_roles('admin')
def delete_worker(wid):
    db_exec("DELETE FROM workers WHERE id=%s", (wid,))
    flash('تم حذف العامل', 'success')
    return redirect(url_for('workers.list_workers'))


@workers_bp.route('/workers/<int:wid>')
@require_roles('admin', 'supervisor')
def worker_detail(wid):
    item = db_query(
        """SELECT w.*, wt.name_ar AS type_name, c.code AS cur_code, ph.name AS phase_name,
                  p.name AS project_name, p.id AS project_id
           FROM workers w
           JOIN worker_types wt ON wt.id=w.worker_type_id
           JOIN currencies c ON c.id=w.currency_id
           JOIN phases ph ON ph.id=w.phase_id
           JOIN projects p ON p.id=ph.project_id
           WHERE w.id=%s""", (wid,), one=True)
    if not item:
        flash('العامل غير موجود', 'warning')
        return redirect(url_for('workers.list_workers'))
    spid = scope_project_id()
    if spid and spid != item['project_id']:
        flash('ليست لديك صلاحية', 'warning')
        return redirect(url_for('workers.list_workers'))

    month = request.args.get('month') or today().strftime('%Y-%m')
    ym = month + '-01'
    attendance = db_query(
        "SELECT * FROM worker_attendance WHERE worker_id=%s AND work_date>=%s AND work_date<=LAST_DAY(%s) ORDER BY work_date",
        (wid, ym, ym))
    ded_sql = """SELECT d.*, c.code AS cur_code FROM worker_deductions d JOIN currencies c ON c.id=d.currency_id
                 WHERE d.worker_id=%s and d.created_at >= %s ORDER BY d.id DESC"""
    ded_month = db_query(ded_sql, (wid, ym))
    wd_sql = """SELECT x.*, c.code AS cur_code FROM worker_withdrawals x JOIN currencies c ON c.id=x.currency_id
                WHERE x.worker_id=%s and x.created_at >= %s ORDER BY x.id DESC"""
    wd_month = db_query(wd_sql, (wid, ym))
    ded_all = num(db_query("SELECT COALESCE(SUM(d.amount*d2.rate_to_local),0) t FROM worker_deductions d JOIN currencies d2 ON d2.id=d.currency_id WHERE d.worker_id=%s", (wid,))[0]['t'])
    wd_all = num(db_query("SELECT COALESCE(SUM(x.amount*x2.rate_to_local),0) t FROM worker_withdrawals x JOIN currencies x2 ON x2.id=x.currency_id WHERE x.worker_id=%s", (wid,))[0]['t'])

    wage = num(item['wage_per_day'])
    days = len(attendance)
    # الأجر محفوظ بالعملة المختارة للعامل؛ نحوله للعملة المحلية عند الاحتساب
    rate = num((db_query("SELECT rate_to_local r FROM currencies WHERE id=%s", (item['currency_id'],), one=True) or {}).get('r', 1))
    gross_local = wage * days * rate
    ded_month_local = sum(num(d['amount']) * num((db_query("SELECT rate_to_local r FROM currencies WHERE id=%s", (d['currency_id'],), one=True) or {}).get('r', 1)) for d in ded_month)
    wd_month_local = sum(num(x['amount']) * num((db_query("SELECT rate_to_local r FROM currencies WHERE id=%s", (x['currency_id'],), one=True) or {}).get('r', 1)) for x in wd_month)
    ded_month_local = float(ded_month_local)
    wd_month_local = float(wd_month_local)
    net_month = gross_local - ded_month_local - wd_month_local
    net_all = gross_local - ded_all - wd_all

    try:
        ym_d = datetime.strptime(month, '%Y-%m').replace(day=1)
    except ValueError:
        ym_d = datetime.today().replace(day=1)
    prev_month = (ym_d - timedelta(days=1)).strftime('%Y-%m')
    next_month = (ym_d.replace(day=28) + timedelta(days=7)).strftime('%Y-%m')
    currencies = db_query("SELECT * FROM currencies ORDER BY is_local DESC, name_ar")
    # صرفيات/مسحوبات العامل (ربط مع وحدة المصروفات والمسحوبات)
    worker_issues = db_query(
        """SELECT i.*, m.name_ar AS material_name, mt.name_ar AS type_name, u.name_ar AS unit_name,
                  c.code AS cur_code
           FROM issues i
           LEFT JOIN materials m ON m.id=i.material_id
           LEFT JOIN material_types mt ON mt.id=i.material_type_id
           LEFT JOIN units u ON u.id=i.unit_id
           JOIN currencies c ON c.id=i.currency_id
           WHERE i.beneficiary_type='worker' AND i.worker_id=%s
           ORDER BY i.issue_date DESC, i.id DESC LIMIT 25""", (wid,))
    worker_issues_total = sum(num(x['total_local']) for x in worker_issues)

    return render_template('workers/detail.html', item=item, month=month, attendance=attendance,
                           ded_month=ded_month, wd_month=wd_month, days=days,
                           gross_local=gross_local, ded_month_local=ded_month_local,
                           wd_month_local=wd_month_local, net_month=net_month,
                           ded_all=ded_all, wd_all=wd_all, net_all=net_all,
                           prev_month=prev_month, next_month=next_month, currencies=currencies,
                           worker_issues=worker_issues, worker_issues_total=worker_issues_total)


# ---------------- دوام ----------------
@workers_bp.route('/workers/<int:wid>/attendance/add', methods=['POST'])
@require_roles('admin', 'supervisor')
def add_attendance(wid):
    w = db_query("SELECT w.*, ph.project_id, p.name AS project_name FROM workers w JOIN phases ph ON ph.id=w.phase_id JOIN projects p ON p.id=ph.project_id WHERE w.id=%s", (wid,), one=True)
    if not w:
        flash('العامل غير موجود', 'warning')
        return redirect(url_for('workers.list_workers'))
    spid = scope_project_id()
    if spid and spid != w['project_id']:
        flash('ليست لديك صلاحية', 'warning')
        return redirect(url_for('workers.list_workers'))
    d = request.form.get('work_date') or today()
    exists = db_query("SELECT id FROM worker_attendance WHERE worker_id=%s AND work_date=%s", (wid, d), one=True)
    if exists:
        db_exec("UPDATE worker_attendance SET note=%s WHERE id=%s",
                (esc(request.form.get('note')), exists['id']))
        flash('تم تحديث يوم الدوام', 'success')
    else:
        db_exec("INSERT INTO worker_attendance (worker_id,work_date,note) VALUES (%s,%s,%s)",
                (wid, d, esc(request.form.get('note'))))
        flash('تم تسجيل يوم الدوام', 'success')
    return redirect(url_for('workers.worker_detail', wid=wid, month=(d[:7])))


@workers_bp.route('/workers/<int:wid>/attendance/<int:aid>/delete', methods=['POST'])
@require_roles('admin', 'supervisor')
def delete_attendance(wid, aid):
    db_exec("DELETE FROM worker_attendance WHERE id=%s", (aid,))
    flash('تم حذف يوم الدوام', 'success')
    month = request.form.get('month') or ''
    return redirect(url_for('workers.worker_detail', wid=wid, month=month))


# ---------------- خصومات ----------------
@workers_bp.route('/workers/<int:wid>/deductions/add', methods=['POST'])
@require_roles('admin', 'supervisor')
def add_deduction(wid):
    amount = num(request.form.get('amount'))
    if amount > 0:
        db_exec("INSERT INTO worker_deductions (worker_id,amount,currency_id,reason) VALUES (%s,%s,%s,%s)",
                (wid, amount, request.form.get('currency_id', type=int) or 1, esc(request.form.get('reason'))))
        flash('تم تسجيل الخصم', 'success')
    else:
        flash('المبلغ يجب أن يكون أكبر من صفر', 'danger')
    return redirect(url_for('workers.worker_detail', wid=wid))


# ---------------- سحوبات العمال ----------------
@workers_bp.route('/workers/<int:wid>/withdrawals/add', methods=['POST'])
@require_roles('admin', 'supervisor')
def add_worker_withdrawal(wid):
    amount = num(request.form.get('amount'))
    if amount > 0:
        db_exec("INSERT INTO worker_withdrawals (worker_id,amount,currency_id,note) VALUES (%s,%s,%s,%s)",
                (wid, amount, request.form.get('currency_id', type=int) or 1, esc(request.form.get('note'))))
        flash('تم تسجيل السحب', 'success')
    else:
        flash('المبلغ يجب أن يكون أكبر من صفر', 'danger')
    return redirect(url_for('workers.worker_detail', wid=wid))

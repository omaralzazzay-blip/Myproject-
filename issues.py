# -*- coding: utf-8 -*-
"""المصروفات والمسحوبات (صرف مواد أو مبالغ) على مستوى العامل والمشرف والمادة
   مع الخصم التلقائي من حساب العامل أو المشرف المعني."""
from flask import Blueprint, render_template, request, redirect, url_for, flash, g

from db import (db_query, db_exec, esc, num, today, make_tx, cur_list,
                stock_balance_row, ensure_worker_account, ensure_supervisor_account,
                post_account_entry, notify_admins, notify_supervisors)
from auth import require_roles, is_admin, scope_project_id

issues_bp = Blueprint('issues', __name__)


def form_data():
    spid = scope_project_id()
    if spid:
        projects = db_query("SELECT id, name FROM projects WHERE id=%s", (spid,))
        warehouses = db_query(
            """SELECT w.*, p.name AS pname FROM warehouses w JOIN projects p ON p.id=w.project_id
               WHERE w.project_id=%s ORDER BY p.name""", (spid,))
    else:
        projects = db_query("SELECT id, name FROM projects ORDER BY name")
        warehouses = db_query(
            """SELECT w.*, p.name AS pname FROM warehouses w JOIN projects p ON p.id=w.project_id
               ORDER BY p.name""")
    materials = db_query("SELECT m.*, u.name_ar AS unit_name FROM materials m JOIN units u ON u.id=m.unit_id ORDER BY m.name_ar")
    material_types = db_query("SELECT * FROM material_types ORDER BY material_id, name_ar")
    material_units = db_query(
        """SELECT mu.*, u.name_ar AS unit_name FROM material_units mu JOIN units u ON u.id=mu.unit_id
           ORDER BY mu.material_id, u.name_ar""")
    units = db_query("SELECT * FROM units ORDER BY name_ar")
    workers = db_query(
        """SELECT w.*, p.name AS project_name FROM workers w
           JOIN phases ph ON ph.id=w.phase_id JOIN projects p ON p.id=ph.project_id
           WHERE w.status='active' ORDER BY w.name""")
    supervisors = db_query("SELECT id, full_name, project_id FROM users WHERE role='supervisor' AND is_active=1 ORDER BY full_name")
    currencies = cur_list()
    return dict(projects=projects, warehouses=warehouses, materials=materials,
                material_types=material_types, material_units=material_units, units=units,
                workers=workers, supervisors=supervisors, currencies=currencies)


@issues_bp.route('/issues')
@require_roles('admin', 'supervisor')
def list_issues():
    spid = scope_project_id()
    sql = """SELECT i.*, p.name AS project_name, w.name AS warehouse_name,
                    m.name_ar AS material_name, mt.name_ar AS type_name, u.name_ar AS unit_name,
                    c.code AS cur_code, wk.name AS worker_name, u2.full_name AS supervisor_name
             FROM issues i
             JOIN projects p ON p.id=i.project_id
             LEFT JOIN warehouses w ON w.id=i.warehouse_id
             LEFT JOIN materials m ON m.id=i.material_id
             LEFT JOIN material_types mt ON mt.id=i.material_type_id
             LEFT JOIN units u ON u.id=i.unit_id
             JOIN currencies c ON c.id=i.currency_id
             LEFT JOIN workers wk ON wk.id=i.worker_id
             LEFT JOIN users u2 ON u2.id=i.supervisor_user_id
             WHERE 1=1"""
    params = []
    if spid:
        sql += " AND i.project_id=%s"; params.append(spid)
    wid = request.args.get('worker_id', type=int)
    if wid:
        sql += " AND i.worker_id=%s"; params.append(wid)
    frm = request.args.get('from')
    to = request.args.get('to')
    if frm:
        sql += " AND i.issue_date>=%s"; params.append(frm)
    if to:
        sql += " AND i.issue_date<=%s"; params.append(to)
    sql += " ORDER BY i.issue_date DESC, i.id DESC LIMIT 300"
    items = db_query(sql, params)
    workers = db_query("SELECT id, name FROM workers ORDER BY name")
    total = sum(num(x['total_local']) for x in items)
    return render_template('issues/list.html', items=items, workers=workers, total=total,
                           frm=frm or '', to=to or '')


@issues_bp.route('/issues/add', methods=['GET', 'POST'])
@require_roles('admin', 'supervisor')
def add_issue():
    spid = scope_project_id()
    if request.method == 'POST':
        project_id = request.form.get('project_id', type=int)
        if spid:
            project_id = spid
        btype = request.form.get('beneficiary_type')
        worker_id = request.form.get('worker_id', type=int) or None
        sup_id = request.form.get('supervisor_user_id', type=int) or None
        kind = request.form.get('issue_kind') or 'material'
        warehouse_id = request.form.get('warehouse_id', type=int) or None
        material_id = request.form.get('material_id', type=int) or None
        material_type_id = request.form.get('material_type_id', type=int) or None
        unit_id = request.form.get('unit_id', type=int) or None
        quantity = num(request.form.get('quantity'))
        price = num(request.form.get('unit_price'))
        amount = num(request.form.get('amount'))
        currency_id = request.form.get('currency_id', type=int) or 1
        issue_date = request.form.get('issue_date') or today()
        effective_unit = None
        if kind == 'material':
            if not warehouse_id or not material_id or quantity <= 0:
                flash('اختر المخزن والمادة وأدخل كمية صحيحة', 'danger')
                return render_template('issues/form.html', **form_data())
            m = db_query("SELECT * FROM materials WHERE id=%s", (material_id,), one=True)
            effective_unit = unit_id or m['unit_id']
            cur = stock_balance_row(warehouse_id, material_id, material_type_id, effective_unit)
            if cur < quantity:
                flash('الرصيد غير كافٍ في المخزن ({:,.0f})'.format(cur), 'danger')
                return render_template('issues/form.html', **form_data())
            amount = quantity * price
        else:
            if amount <= 0:
                flash('أدخل المبلغ النقدي', 'danger')
                return render_template('issues/form.html', **form_data())
            quantity = 0
        if not project_id or (btype == 'worker' and not worker_id) or (btype == 'supervisor' and not sup_id):
            flash('اختر نوع المستفيد والمستفيد نفسه', 'danger')
            return render_template('issues/form.html', **form_data())
        rate, total_local = make_tx(currency_id, amount)
        desc = esc(request.form.get('description'))
        iid = db_exec(
            """INSERT INTO issues (project_id,warehouse_id,material_id,material_type_id,unit_id,quantity,unit_price,currency_id,exchange_rate,total_local,beneficiary_type,worker_id,supervisor_user_id,issue_kind,description,issue_date,created_by)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (project_id, warehouse_id, material_id, material_type_id, effective_unit,
             quantity, price, currency_id, rate, total_local, btype, worker_id, sup_id, kind,
             desc, issue_date, g.current_user['id']), fetch_id=True)
        # حركة مخزنية مرتبطة (صرف) عند صرف مواد
        if kind == 'material':
            db_exec(
                """INSERT INTO stock_movements (warehouse_id,material_id,material_type_id,unit_id,movement_type,quantity,price_per_unit,currency_id,exchange_rate,total_local,issue_id,movement_date,note,created_by)
                   VALUES (%s,%s,%s,%s,'out',%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (warehouse_id, material_id, material_type_id, effective_unit, quantity, price,
                 currency_id, rate, total_local, iid, issue_date,
                 'صرف: ' + (desc or ''), g.current_user['id']))
        # الخصم التلقائي من حساب المستفيد
        if btype == 'worker':
            acc_id = ensure_worker_account(worker_id, project_id)
            who = db_query("SELECT name FROM workers WHERE id=%s", (worker_id,), one=True)['name']
        else:
            acc_id = ensure_supervisor_account(sup_id, project_id)
            who = db_query("SELECT full_name FROM users WHERE id=%s", (sup_id,), one=True)['full_name']
        post_account_entry(acc_id, project_id, 'debit', amount, currency_id, total_local,
                           'issue', iid, 'خصم تلقائي - ' + (desc or 'صرف مواد'), issue_date,
                           g.current_user['id'])
        if is_admin():
            notify_supervisors(project_id, 'صرف / مسحوبات',
                               'صُرف على {} بمبلغ {:,.0f}'.format(who, total_local),
                               url_for('issues.list_issues'))
        else:
            notify_admins('صرف / مسحوبات جديد',
                          'سجّل المشرف {} صرفاً على {} بمبلغ {:,.0f}'.format(
                              g.current_user['full_name'], who, total_local),
                          url_for('issues.list_issues'))
        flash('تم التسجيل وخصمه تلقائياً من حساب {}'.format(who), 'success')
        return redirect(url_for('issues.list_issues'))
    return render_template('issues/form.html', **form_data())


@issues_bp.route('/issues/<int:iid>')
@require_roles('admin', 'supervisor')
def issue_detail(iid):
    item = db_query(
        """SELECT i.*, p.name AS project_name, w.name AS warehouse_name,
                  m.name_ar AS material_name, mt.name_ar AS type_name, u.name_ar AS unit_name,
                  c.code AS cur_code, wk.name AS worker_name, u2.full_name AS supervisor_name
           FROM issues i
           JOIN projects p ON p.id=i.project_id
           LEFT JOIN warehouses w ON w.id=i.warehouse_id
           LEFT JOIN materials m ON m.id=i.material_id
           LEFT JOIN material_types mt ON mt.id=i.material_type_id
           LEFT JOIN units u ON u.id=i.unit_id
           JOIN currencies c ON c.id=i.currency_id
           LEFT JOIN workers wk ON wk.id=i.worker_id
           LEFT JOIN users u2 ON u2.id=i.supervisor_user_id
           WHERE i.id=%s""", (iid,), one=True)
    if not item:
        flash('القيد غير موجود', 'warning')
        return redirect(url_for('issues.list_issues'))
    acc = None
    if item['beneficiary_type'] == 'worker' and item['worker_id']:
        acc = db_query("SELECT * FROM accounts WHERE acc_type='worker' AND party_type='worker' AND party_id=%s",
                       (item['worker_id'],), one=True)
    elif item['supervisor_user_id']:
        acc = db_query("SELECT * FROM accounts WHERE acc_type='supervisor' AND party_type='user' AND party_id=%s",
                       (item['supervisor_user_id'],), one=True)
    return render_template('issues/detail.html', item=item, acc=acc)


@issues_bp.route('/issues/<int:iid>/delete', methods=['POST'])
@require_roles('admin')
def delete_issue(iid):
    it = db_query("SELECT * FROM issues WHERE id=%s", (iid,), one=True)
    if it:
        db_exec("DELETE FROM stock_movements WHERE issue_id=%s", (iid,))
        db_exec("DELETE FROM account_entries WHERE ref_type='issue' AND ref_id=%s", (iid,))
        db_exec("DELETE FROM issues WHERE id=%s", (iid,))
        flash('تم حذف القيد وكل ما يرتبط به', 'success')
    return redirect(url_for('issues.list_issues'))

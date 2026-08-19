# -*- coding: utf-8 -*-
"""الوحدات المالية: الميزانيات، الممولون، الموردون، المصاريف، المسحوبات"""
from datetime import date
from flask import Blueprint, render_template, request, redirect, url_for, flash, g

from db import db_query, db_exec, esc, num, today, make_tx, notify_admins, notify_supervisors
from auth import require_roles, is_admin, scope_project_id
from attachments import save_attachment

finance_bp = Blueprint('finance', __name__)


def _projects_in_scope():
    spid = scope_project_id()
    if spid:
        return db_query("SELECT * FROM projects WHERE id=%s ORDER BY name", (spid,))
    return db_query("SELECT * FROM projects ORDER BY name")


# ================== الميزانيات ==================
@finance_bp.route('/budgets')
@require_roles('admin', 'supervisor')
def list_budgets():
    spid = scope_project_id()
    sql = """SELECT b.*, p.name AS project_name, ph.name AS phase_name, c.code AS cur_code
             FROM budgets b
             LEFT JOIN projects p ON p.id=b.project_id
             LEFT JOIN phases ph ON ph.id=b.phase_id
             JOIN currencies c ON c.id=b.currency_id WHERE 1=1"""
    params = []
    if spid:
        sql += " AND (b.project_id=%s OR b.level='owner')"
        params.append(spid)
    lvl = request.args.get('level')
    if lvl in ('owner', 'project', 'phase'):
        sql += " AND b.level=%s"
        params.append(lvl)
    sql += " ORDER BY b.id DESC"
    items = db_query(sql, params)
    totals = db_query(
        """SELECT level, COALESCE(SUM(amount_local),0) t FROM budgets GROUP BY level""")
    total_map = {r['level']: r['t'] for r in totals}
    total_all = sum(total_map.values())
    return render_template('budgets/list.html', items=items, total_map=total_map, total_all=total_all)


@finance_bp.route('/budgets/add', methods=['GET', 'POST'])
@require_roles('admin')
def add_budget():
    if request.method == 'POST':
        level = request.form.get('level') or 'project'
        project_id = request.form.get('project_id', type=int) or None
        phase_id = request.form.get('phase_id', type=int) or None
        amount = num(request.form.get('amount'))
        currency_id = request.form.get('currency_id', type=int) or 1
        rate, amount_local = make_tx(currency_id, amount)
        if amount <= 0:
            flash('المبلغ يجب أن يكون أكبر من صفر', 'danger')
        else:
            db_exec(
                """INSERT INTO budgets (level,project_id,phase_id,source,amount,currency_id,exchange_rate,amount_local,note)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (level, project_id, phase_id, esc(request.form.get('source')), amount,
                 currency_id, rate, amount_local, esc(request.form.get('note'))))
            # إشعار للمشرفين المرتبطين بالمشروع
            if project_id:
                notify_supervisors(project_id, 'إضافة ميزانية',
                                   'أضاف المدير ميزانية ({}): {}'.format(level,
                                       '{:,.0f}'.format(amount_local)),
                                   url_for('finance.list_budgets'))
            else:
                notify_admins('إضافة ميزانية', 'أضيفت ميزانية مالك بمبلغ {:,.0f}'.format(amount_local),
                              url_for('finance.list_budgets'))
            flash('تمت إضافة الميزانية (ما يعادلها بالعملة المحلية: {:,.0f})'.format(amount_local), 'success')
            return redirect(url_for('finance.list_budgets'))
    projects = _projects_in_scope()
    phases = db_query("SELECT ph.id, ph.name, p.name AS pname FROM phases ph JOIN projects p ON p.id=ph.project_id ORDER BY p.name, ph.name")
    currencies = db_query("SELECT * FROM currencies ORDER BY is_local DESC, name_ar")
    return render_template('budgets/form.html', projects=projects, phases=phases, currencies=currencies)


# ================== الممولون ==================
@finance_bp.route('/funders')
@require_roles('admin')
def list_funders():
    items = db_query(
        """SELECT f.*, (SELECT COALESCE(SUM(d.amount_local),0) FROM funder_deposits d WHERE d.funder_id=f.id) AS total
           FROM funders f ORDER BY f.name""")
    return render_template('funders/list.html', items=items)


@finance_bp.route('/funders/add', methods=['GET', 'POST'])
@require_roles('admin')
def add_funder():
    if request.method == 'POST':
        name = esc(request.form.get('name'))
        if not name:
            flash('يرجى إدخال اسم الممول', 'danger')
        else:
            db_exec("INSERT INTO funders (name,phone,notes) VALUES (%s,%s,%s)",
                    (name, esc(request.form.get('phone')), esc(request.form.get('notes'))))
            flash('تمت إضافة الممول', 'success')
            return redirect(url_for('finance.list_funders'))
    return render_template('funders/form.html', item=None)


@finance_bp.route('/funders/<int:fid>/edit', methods=['GET', 'POST'])
@require_roles('admin')
def edit_funder(fid):
    item = db_query("SELECT * FROM funders WHERE id=%s", (fid,), one=True)
    if not item:
        flash('الممول غير موجود', 'warning')
        return redirect(url_for('finance.list_funders'))
    if request.method == 'POST':
        db_exec("UPDATE funders SET name=%s, phone=%s, notes=%s WHERE id=%s",
                (esc(request.form.get('name')), esc(request.form.get('phone')), esc(request.form.get('notes')), fid))
        flash('تم تحديث بيانات الممول', 'success')
        return redirect(url_for('finance.list_funders'))
    return render_template('funders/form.html', item=item)


@finance_bp.route('/funders/<int:fid>/delete', methods=['POST'])
@require_roles('admin')
def delete_funder(fid):
    db_exec("DELETE FROM funders WHERE id=%s", (fid,))
    flash('تم حذف الممول', 'success')
    return redirect(url_for('finance.list_funders'))


@finance_bp.route('/funders/<int:fid>/deposit', methods=['POST'])
@require_roles('admin')
def add_funder_deposit(fid):
    amount = num(request.form.get('amount'))
    project_id = request.form.get('project_id', type=int)
    currency_id = request.form.get('currency_id', type=int) or 1
    if amount <= 0 or not project_id:
        flash('يرجى إدخال المبلغ واختيار المشروع', 'danger')
    else:
        rate, amount_local = make_tx(currency_id, amount)
        db_exec(
            """INSERT INTO funder_deposits (funder_id,project_id,amount,currency_id,exchange_rate,amount_local,note)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (fid, project_id, amount, currency_id, rate, amount_local, esc(request.form.get('note'))))
        notify_supervisors(project_id, 'تمويل جديد',
                           'تم إضافة تمويل للمشروع بمبلغ {:,.0f}'.format(amount_local),
                           url_for('finance.list_funders'))
        flash('تم تسجيل التمويل وإضافته لميزانية المشروع (ما يعادله: {:,.0f})'.format(amount_local), 'success')
    return redirect(url_for('finance.funder_detail', fid=fid))


@finance_bp.route('/funders/<int:fid>')
@require_roles('admin')
def funder_detail(fid):
    item = db_query("SELECT * FROM funders WHERE id=%s", (fid,), one=True)
    if not item:
        flash('الممول غير موجود', 'warning')
        return redirect(url_for('finance.list_funders'))
    deposits = db_query(
        """SELECT d.*, p.name AS project_name, c.code AS cur_code
           FROM funder_deposits d JOIN projects p ON p.id=d.project_id JOIN currencies c ON c.id=d.currency_id
           WHERE d.funder_id=%s ORDER BY d.id DESC""", (fid,))
    projects = _projects_in_scope()
    currencies = db_query("SELECT * FROM currencies ORDER BY is_local DESC, name_ar")
    return render_template('funders/detail.html', item=item, deposits=deposits,
                           projects=projects, currencies=currencies)


# ================== الموردون ==================
@finance_bp.route('/suppliers')
@require_roles('admin')
def list_suppliers():
    items = db_query(
        """SELECT s.*,
                  (SELECT COALESCE(SUM(d.total_local),0) FROM supplier_deliveries d WHERE d.supplier_id=s.id) AS goods_total,
                  (SELECT COALESCE(SUM(m.amount_local),0) FROM supplier_money m WHERE m.supplier_id=s.id) AS money_total
           FROM suppliers s ORDER BY s.name""")
    return render_template('suppliers/list.html', items=items)


@finance_bp.route('/suppliers/add', methods=['GET', 'POST'])
@require_roles('admin')
def add_supplier():
    if request.method == 'POST':
        name = esc(request.form.get('name'))
        if not name:
            flash('يرجى إدخال اسم المورد', 'danger')
        else:
            db_exec("INSERT INTO suppliers (name,phone,notes) VALUES (%s,%s,%s)",
                    (name, esc(request.form.get('phone')), esc(request.form.get('notes'))))
            flash('تمت إضافة المورد', 'success')
            return redirect(url_for('finance.list_suppliers'))
    return render_template('suppliers/form.html', item=None)


@finance_bp.route('/suppliers/<int:sid>/delete', methods=['POST'])
@require_roles('admin')
def delete_supplier(sid):
    db_exec("DELETE FROM suppliers WHERE id=%s", (sid,))
    flash('تم حذف المورد', 'success')
    return redirect(url_for('finance.list_suppliers'))


@finance_bp.route('/suppliers/<int:sid>')
@require_roles('admin')
def supplier_detail(sid):
    item = db_query("SELECT * FROM suppliers WHERE id=%s", (sid,), one=True)
    if not item:
        flash('المورد غير موجود', 'warning')
        return redirect(url_for('finance.list_suppliers'))
    deliveries = db_query(
        """SELECT d.*, p.name AS project_name, w.name AS warehouse_name, m.name_ar AS material_name,
                  mt.name_ar AS type_name, u.name_ar AS unit_name, c.code AS cur_code
           FROM supplier_deliveries d
           JOIN warehouses w ON w.id=d.warehouse_id
           JOIN projects p ON p.id=w.project_id
           JOIN materials m ON m.id=d.material_id
           LEFT JOIN material_types mt ON mt.id=d.material_type_id
           JOIN units u ON u.id=d.unit_id
           JOIN currencies c ON c.id=d.currency_id
           WHERE d.supplier_id=%s ORDER BY d.id DESC""", (sid,))
    money_records = db_query(
        """SELECT m.*, p.name AS project_name, c.code AS cur_code
           FROM supplier_money m JOIN projects p ON p.id=m.project_id JOIN currencies c ON c.id=m.currency_id
           WHERE m.supplier_id=%s ORDER BY m.id DESC""", (sid,))
    projects = _projects_in_scope()
    warehouses = db_query("SELECT w.*, p.name AS pname FROM warehouses w JOIN projects p ON p.id=w.project_id ORDER BY p.name")
    materials = db_query("SELECT m.*, u.name_ar AS unit_name FROM materials m JOIN units u ON u.id=m.unit_id ORDER BY m.name_ar")
    material_types = db_query("SELECT * FROM material_types ORDER BY material_id, name_ar")
    currencies = db_query("SELECT * FROM currencies ORDER BY is_local DESC, name_ar")
    return render_template('suppliers/detail.html', item=item, deliveries=deliveries, money_records=money_records,
                           projects=projects, warehouses=warehouses, materials=materials,
                           material_types=material_types, currencies=currencies)


@finance_bp.route('/suppliers/<int:sid>/money', methods=['POST'])
@require_roles('admin')
def add_supplier_money(sid):
    amount = num(request.form.get('amount'))
    project_id = request.form.get('project_id', type=int)
    currency_id = request.form.get('currency_id', type=int) or 1
    if amount <= 0 or not project_id:
        flash('يرجى إدخال المبلغ واختيار المشروع', 'danger')
    else:
        rate, amount_local = make_tx(currency_id, amount)
        db_exec(
            """INSERT INTO supplier_money (supplier_id,project_id,amount,currency_id,exchange_rate,amount_local,note)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (sid, project_id, amount, currency_id, rate, amount_local, esc(request.form.get('note'))))
        notify_supervisors(project_id, 'توريد مالي',
                           'وصل توريد مالي من المورد بمبلغ {:,.0f}'.format(amount_local),
                           url_for('finance.supplier_detail', sid=sid))
        flash('تم تسجيل التوريد المالي', 'success')
    return redirect(url_for('finance.supplier_detail', sid=sid))


@finance_bp.route('/suppliers/<int:sid>/deliver', methods=['POST'])
@require_roles('admin')
def add_supplier_delivery(sid):
    warehouse_id = request.form.get('warehouse_id', type=int)
    material_id = request.form.get('material_id', type=int)
    material_type_id = request.form.get('material_type_id', type=int) or None
    quantity = num(request.form.get('quantity'))
    price = num(request.form.get('price_per_unit'))
    currency_id = request.form.get('currency_id', type=int) or 1
    if not warehouse_id or not material_id or quantity <= 0:
        flash('يرجى اختيار المخزن والمادة وإدخال كمية صحيحة', 'danger')
    else:
        rate, total_local = make_tx(currency_id, quantity * price)
        wh = db_query("SELECT * FROM warehouses WHERE id=%s", (warehouse_id,), one=True)
        m = db_query("SELECT * FROM materials WHERE id=%s", (material_id,), one=True)
        note = esc(request.form.get('note'))
        did = db_exec(
            """INSERT INTO supplier_deliveries (supplier_id,warehouse_id,material_id,material_type_id,unit_id,quantity,price_per_unit,currency_id,exchange_rate,total_local,note)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (sid, warehouse_id, material_id, material_type_id, m['unit_id'], quantity, price, currency_id,
             rate, total_local, note))
        # إدخال تلقائي إلى المخزن مع النوع الفرعي
        db_exec(
            """INSERT INTO stock_movements (warehouse_id,material_id,material_type_id,unit_id,movement_type,quantity,price_per_unit,currency_id,exchange_rate,total_local,movement_date,note)
               VALUES (%s,%s,%s,%s,'in',%s,%s,%s,%s,%s,%s,%s)""",
            (warehouse_id, material_id, material_type_id, m['unit_id'], quantity, price, currency_id, rate,
             total_local, today(), 'توريد من المورد: {}'.format(note or '')))
        # إرفاق فاتورة التوريد إن وُجدت
        save_attachment(request.files.get('invoice_file'), wh['project_id'], 'supplier_delivery', did,
                        'فاتورة توريد: ' + (note or ''))
        notify_supervisors(wh['project_id'], 'توريد مواد',
                           'تم توريد {} من {} إلى مخزن {}'.format(m['name_ar'], item_name(sid), wh['name']),
                           url_for('stock.warehouse_view', wid=warehouse_id))
        flash('تم تسجيل التوريد وإدخال المادة إلى المخزن' + (' ورفع الفاتورة' if request.files.get('invoice_file') and request.files['invoice_file'].filename else ''), 'success')
    return redirect(url_for('finance.supplier_detail', sid=sid))


def item_name(sid):
    r = db_query("SELECT name FROM suppliers WHERE id=%s", (sid,), one=True)
    return r['name'] if r else 'المورد'


# ================== المصاريف ==================
@finance_bp.route('/expenses')
@require_roles('admin', 'supervisor')
def list_expenses():
    spid = scope_project_id()
    sql = """SELECT e.*, p.name AS project_name, ph.name AS phase_name, c.code AS cur_code,
                    u.full_name AS created_by_name
             FROM expenses e
             JOIN projects p ON p.id=e.project_id
             LEFT JOIN phases ph ON ph.id=e.phase_id
             JOIN currencies c ON c.id=e.currency_id
             LEFT JOIN users u ON u.id=e.created_by
             WHERE 1=1"""
    params = []
    if spid:
        sql += " AND e.project_id=%s"
        params.append(spid)
    sql += " ORDER BY e.expense_date DESC, e.id DESC"
    items = db_query(sql, params)
    return render_template('expenses/list.html', items=items)


@finance_bp.route('/expenses/add', methods=['GET', 'POST'])
@require_roles('admin', 'supervisor')
def add_expense():
    spid = scope_project_id()
    if request.method == 'POST':
        project_id = request.form.get('project_id', type=int)
        if spid:
            project_id = spid
        phase_id = request.form.get('phase_id', type=int) or None
        amount = num(request.form.get('amount'))
        currency_id = request.form.get('currency_id', type=int) or 1
        rate, amount_local = make_tx(currency_id, amount)
        if amount <= 0 or not project_id:
            flash('يرجى إدخال المبلغ واختيار المشروع', 'danger')
        else:
            db_exec(
                """INSERT INTO expenses (project_id,phase_id,category,description,amount,currency_id,exchange_rate,amount_local,expense_date,created_by)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (project_id, phase_id, esc(request.form.get('category')), esc(request.form.get('description')),
                 amount, currency_id, rate, amount_local, request.form.get('expense_date') or today(),
                 g.current_user['id']))
            who = 'أضاف المدير' if is_admin() else 'أضاف المشرف {}'.format(
                g.current_user['full_name'] if 'full_name' in g.current_user else '')
            if is_admin():
                notify_supervisors(project_id, 'مصروف جديد',
                                   '{} مصروفاً بقيمة {:,.0f}'.format(who, amount_local),
                                   url_for('finance.list_expenses'))
            else:
                notify_admins('مصروف جديد',
                              'سجّل المشرف {} مصروفاً لمشروعه بقيمة {:,.0f}'.format(
                                  g.current_user['full_name'], amount_local),
                              url_for('finance.list_expenses'))
            flash('تم تسجيل المصروف (ما يعادله بالعملة المحلية: {:,.0f})'.format(amount_local), 'success')
            return redirect(url_for('finance.list_expenses'))
    projects = _projects_in_scope()
    phases = db_query("SELECT ph.*, p.name AS pname FROM phases ph JOIN projects p ON p.id=ph.project_id ORDER BY p.name")
    if spid:
        phases = [ph for ph in phases if ph['project_id'] == spid]
    currencies = db_query("SELECT * FROM currencies ORDER BY is_local DESC, name_ar")
    return render_template('expenses/form.html', projects=projects, phases=phases, currencies=currencies)


@finance_bp.route('/expenses/<int:eid>/delete', methods=['POST'])
@require_roles('admin')
def delete_expense(eid):
    db_exec("DELETE FROM expenses WHERE id=%s", (eid,))
    flash('تم حذف المصروف', 'success')
    return redirect(url_for('finance.list_expenses'))


# ================== المسحوبات ==================
@finance_bp.route('/withdrawals')
@require_roles('admin', 'supervisor')
def list_withdrawals():
    spid = scope_project_id()
    sql = """SELECT w.*, p.name AS project_name, ph.name AS phase_name, c.code AS cur_code,
                    u.full_name AS created_by_name
             FROM withdrawals w
             JOIN projects p ON p.id=w.project_id
             LEFT JOIN phases ph ON ph.id=w.phase_id
             JOIN currencies c ON c.id=w.currency_id
             LEFT JOIN users u ON u.id=w.created_by
             WHERE 1=1"""
    params = []
    if spid:
        sql += " AND w.project_id=%s"
        params.append(spid)
    sql += " ORDER BY w.withdraw_date DESC, w.id DESC"
    items = db_query(sql, params)
    return render_template('withdrawals/list.html', items=items)


@finance_bp.route('/withdrawals/add', methods=['GET', 'POST'])
@require_roles('admin', 'supervisor')
def add_withdrawal():
    spid = scope_project_id()
    if request.method == 'POST':
        project_id = request.form.get('project_id', type=int)
        if spid:
            project_id = spid
        phase_id = request.form.get('phase_id', type=int) or None
        amount = num(request.form.get('amount'))
        currency_id = request.form.get('currency_id', type=int) or 1
        rate, amount_local = make_tx(currency_id, amount)
        if amount <= 0 or not project_id:
            flash('يرجى إدخال المبلغ واختيار المشروع', 'danger')
        else:
            db_exec(
                """INSERT INTO withdrawals (project_id,phase_id,description,amount,currency_id,exchange_rate,amount_local,withdraw_date,created_by)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (project_id, phase_id, esc(request.form.get('description')), amount, currency_id,
                 rate, amount_local, request.form.get('withdraw_date') or today(), g.current_user['id']))
            if is_admin():
                notify_supervisors(project_id, 'سحب جديد',
                                   'سُحب مبلغ {:,.0f} من الميزانية'.format(amount_local),
                                   url_for('finance.list_withdrawals'))
            else:
                notify_admins('سحب جديد',
                              'سجّل المشرف {} سحباً بقيمة {:,.0f}'.format(g.current_user['full_name'], amount_local),
                              url_for('finance.list_withdrawals'))
            flash('تم تسجيل السحب (ما يعادله بالعملة المحلية: {:,.0f})'.format(amount_local), 'success')
            return redirect(url_for('finance.list_withdrawals'))
    projects = _projects_in_scope()
    phases = db_query("SELECT ph.*, p.name AS pname FROM phases ph JOIN projects p ON p.id=ph.project_id ORDER BY p.name")
    if spid:
        phases = [ph for ph in phases if ph['project_id'] == spid]
    currencies = db_query("SELECT * FROM currencies ORDER BY is_local DESC, name_ar")
    return render_template('withdrawals/form.html', projects=projects, phases=phases, currencies=currencies)


@finance_bp.route('/withdrawals/<int:wid>/delete', methods=['POST'])
@require_roles('admin')
def delete_withdrawal(wid):
    db_exec("DELETE FROM withdrawals WHERE id=%s", (wid,))
    flash('تم حذف السحب', 'success')
    return redirect(url_for('finance.list_withdrawals'))

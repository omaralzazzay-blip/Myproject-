# -*- coding: utf-8 -*-
"""إدارة المخازن وحركة المواد (إدخال / صرف / إرجاع / تالف) + قسم التالف"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, g

from db import (db_query, db_exec, esc, num, today, make_tx, stock_balance,
                stock_balance_row, damaged_list, damaged_totals, notify_admins)
from auth import require_roles, is_admin, scope_project_id

stock_bp = Blueprint('stock', __name__)

MOV_LABEL = {'in': ('إدخال', 'success'), 'out': ('صرف', 'danger'),
             'return': ('إرجاع', 'info'), 'damage': ('تالف', 'warning')}


@stock_bp.route('/stock')
@require_roles('admin', 'supervisor')
def overview():
    spid = scope_project_id()
    sql = """SELECT w.*, p.name AS project_name,
                    (SELECT COUNT(*) FROM stock_movements sm WHERE sm.warehouse_id=w.id) AS moves_n,
                    (SELECT COUNT(*) FROM damaged_goods d WHERE d.warehouse_id=w.id) AS damage_n
             FROM warehouses w JOIN projects p ON p.id=w.project_id WHERE 1=1"""
    params = []
    if spid:
        sql += " AND w.project_id=%s"
        params.append(spid)
    sql += " ORDER BY p.name, w.name"
    whs = db_query(sql, params)
    balances = stock_balance(project_id=spid)
    damages = damaged_totals(project_id=spid)
    low = [b for b in balances if num(b['balance']) <= 20]
    return render_template('stock/overview.html', warehouses=whs, balances=balances,
                           damages=damages, low=low)


@stock_bp.route('/stock/warehouse/<int:wid>')
@require_roles('admin', 'supervisor')
def warehouse_view(wid):
    wh = db_query("SELECT w.*, p.name AS project_name FROM warehouses w JOIN projects p ON p.id=w.project_id WHERE w.id=%s", (wid,), one=True)
    if not wh:
        flash('المخزن غير موجود', 'warning')
        return redirect(url_for('stock.overview'))
    spid = scope_project_id()
    if spid and spid != wh['project_id']:
        flash('ليست لديك صلاحية', 'warning')
        return redirect(url_for('stock.overview'))
    balances = stock_balance(warehouse_id=wid)
    movements = db_query(
        """SELECT sm.*, m.name_ar AS material_name, mt.name_ar AS type_name, u.name_ar AS unit_name,
                  c.code AS cur_code, u2.full_name AS by_name
           FROM stock_movements sm
           JOIN materials m ON m.id=sm.material_id
           LEFT JOIN material_types mt ON mt.id=sm.material_type_id
           JOIN units u ON u.id=sm.unit_id
           LEFT JOIN currencies c ON c.id=sm.currency_id
           LEFT JOIN users u2 ON u2.id=sm.created_by
           WHERE sm.warehouse_id=%s ORDER BY sm.movement_date DESC, sm.id DESC LIMIT 150""", (wid,))
    damages = damaged_list(warehouse_id=wid)
    materials = db_query("SELECT m.*, u.name_ar AS unit_name FROM materials m JOIN units u ON u.id=m.unit_id ORDER BY m.name_ar")
    material_types = db_query("SELECT * FROM material_types ORDER BY material_id, name_ar")
    material_units = db_query(
        """SELECT mu.*, u.name_ar AS unit_name FROM material_units mu JOIN units u ON u.id=mu.unit_id
           ORDER BY mu.material_id, u.name_ar""")
    units = db_query("SELECT * FROM units ORDER BY name_ar")
    currencies = db_query("SELECT * FROM currencies ORDER BY is_local DESC, name_ar")
    return render_template('stock/warehouse.html', wh=wh, balances=balances, movements=movements,
                           damages=damages, materials=materials, material_types=material_types,
                           material_units=material_units, units=units, currencies=currencies,
                           mov_label=MOV_LABEL)


@stock_bp.route('/stock/warehouse/<int:wid>/movement', methods=['POST'])
@require_roles('admin', 'supervisor')
def add_movement(wid):
    wh = db_query("SELECT * FROM warehouses WHERE id=%s", (wid,), one=True)
    if not wh:
        flash('المخزن غير موجود', 'warning')
        return redirect(url_for('stock.overview'))
    spid = scope_project_id()
    if spid and spid != wh['project_id']:
        flash('ليست لديك صلاحية', 'warning')
        return redirect(url_for('stock.overview'))
    mtype = request.form.get('movement_type')
    material_id = request.form.get('material_id', type=int)
    material_type_id = request.form.get('material_type_id', type=int) or None
    unit_id = request.form.get('unit_id', type=int) or None
    quantity = num(request.form.get('quantity'))
    price = num(request.form.get('price_per_unit'))
    currency_id = request.form.get('currency_id', type=int) or 1
    m = db_query("SELECT * FROM materials WHERE id=%s", (material_id,), one=True) if material_id else None
    if mtype not in MOV_LABEL or not m or quantity <= 0:
        flash('يرجى اختيار النوع والمادة والكمية بشكل صحيح', 'danger')
        return redirect(url_for('stock.warehouse_view', wid=wid))
    effective_unit = unit_id or m['unit_id']
    # التحقق من الرصيد عند الصرف أو التالف (يمنع الرصيد السالب)
    if mtype in ('out', 'damage'):
        cur = stock_balance_row(wid, material_id, material_type_id, effective_unit)
        if cur < quantity:
            flash('الكمية أكبر من الرصيد المتاح ({:,.0f})'.format(cur), 'danger')
            return redirect(url_for('stock.warehouse_view', wid=wid))
    rate, total_local = make_tx(currency_id, quantity * price)
    mov_id = db_exec(
        """INSERT INTO stock_movements (warehouse_id,material_id,material_type_id,unit_id,movement_type,quantity,price_per_unit,currency_id,exchange_rate,total_local,movement_date,note,created_by)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (wid, material_id, material_type_id, effective_unit, mtype, quantity, price, currency_id, rate,
         total_local, request.form.get('movement_date') or today(),
         esc(request.form.get('note')), g.current_user['id']), fetch_id=True)
    # التالف يُسجَّل أيضاً في قسم التالف المخصص داخل المخزن
    if mtype == 'damage':
        db_exec(
            """INSERT INTO damaged_goods (warehouse_id,material_id,material_type_id,unit_id,quantity,reason,value_local,damage_date,movement_id,created_by)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (wid, material_id, material_type_id, effective_unit, quantity,
             esc(request.form.get('reason')) or esc(request.form.get('note')) or 'تالف',
             total_local, request.form.get('movement_date') or today(), mov_id, g.current_user['id']))
    if not is_admin():
        notify_admins('حركة مخزون',
                      'سجّل المشرف {} حركة ({}) على {} في مخزن {}'.format(
                          g.current_user['full_name'], MOV_LABEL[mtype][0], m['name_ar'], wh['name']),
                      url_for('stock.warehouse_view', wid=wid))
    flash('تم تسجيل الحركة بنجاح', 'success')
    return redirect(url_for('stock.warehouse_view', wid=wid))


@stock_bp.route('/stock/damage/<int:did>/delete', methods=['POST'])
@require_roles('admin')
def delete_damage(did):
    d = db_query("SELECT * FROM damaged_goods WHERE id=%s", (did,), one=True)
    wid = d['warehouse_id'] if d else None
    if d and d['movement_id']:
        db_exec("DELETE FROM stock_movements WHERE id=%s", (d['movement_id'],))
    db_exec("DELETE FROM damaged_goods WHERE id=%s", (did,))
    flash('تم حذف قيد التالف وحركته المرتبطة', 'success')
    return redirect(url_for('stock.warehouse_view', wid=wid))


@stock_bp.route('/stock/movements/<int:mid>/delete', methods=['POST'])
@require_roles('admin')
def delete_movement(mid):
    m = db_query("SELECT * FROM stock_movements WHERE id=%s", (mid,), one=True)
    wid = m['warehouse_id'] if m else None
    db_exec("DELETE FROM damaged_goods WHERE movement_id=%s", (mid,))
    db_exec("DELETE FROM stock_movements WHERE id=%s", (mid,))
    flash('تم حذف الحركة', 'success')
    return redirect(url_for('stock.warehouse_view', wid=wid))

# -*- coding: utf-8 -*-
"""المواد الموسعة: أنواع المادة + وحدات قياس متعددة + التالف في المخازن"""
from datetime import date
from flask import Blueprint, render_template, request, redirect, url_for, flash, g

from db import db_query, db_exec, esc, num, today
from auth import require_roles, scope_project_id

materials_ext_bp = Blueprint('materials_ext', __name__, url_prefix='/materials-ext')


# ============== قائمة المواد مع الأنواع والوحدات والتالف ==============
@materials_ext_bp.route('/')
@require_roles('admin','supervisor')
def list_materials_ext():
    mats = db_query(
        """SELECT m.*, u.name_ar AS default_unit, c.code cur_code FROM materials m
           JOIN units u ON u.id=m.unit_id LEFT JOIN currencies c ON c.id=m.currency_id
           ORDER BY m.name_ar""")
    types_map = {}
    for r in db_query(
            """SELECT mt.*, COALESCE(SUM(d.quantity),0) damaged_qty
               FROM material_types mt LEFT JOIN damaged_stock d ON d.material_type_id=mt.id
               GROUP BY mt.id ORDER BY mt.material_id, mt.name_ar"""):
        types_map.setdefault(r['material_id'], []).append(r)
    units_map = {}
    for r in db_query(
            """SELECT mu.*, u.name_ar unit_name FROM material_units mu JOIN units u ON u.id=mu.unit_id
               ORDER BY mu.material_id, mu.is_default DESC"""):
        units_map.setdefault(r['material_id'], []).append(r)
    damaged_summary = {}
    for r in db_query(
            """SELECT warehouse_id, material_id, COALESCE(SUM(quantity),0) qty
               FROM damaged_stock GROUP BY warehouse_id, material_id"""):
        damaged_summary[(r['warehouse_id'], r['material_id'])] = num(r['qty'])
    return render_template('materials_ext/list.html', items=mats, types_map=types_map,
                           units_map=units_map, damaged_summary=damaged_summary)


# ============== إضافة مادة مع الأنواع والوحدات دفعة واحدة ==============
@materials_ext_bp.route('/add', methods=['GET','POST'])
@require_roles('admin','supervisor')
def add_material_ext():
    if request.method == 'POST':
        name = esc(request.form.get('name_ar'))
        if not name:
            flash('يرجى إدخال اسم المادة','danger')
        else:
            default_unit = request.form.get('default_unit_id', type=int)
            cid = request.form.get('currency_id', type=int) or 1
            price = num(request.form.get('price_per_unit'))
            mid = db_exec(
                "INSERT INTO materials (name_ar, unit_id, price_per_unit, currency_id) VALUES (%s,%s,%s,%s)",
                (name, default_unit, price, cid), fetch_id=True)
            # إدراج الوحدة الافتراضية في ربط الوحدات
            if default_unit:
                db_exec(
                    """INSERT IGNORE INTO material_units (material_id, unit_id, conversion_factor, is_default)
                       VALUES (%s,%s,1,1)""", (mid, default_unit))
            # الوحدات الإضافية
            for uid in request.form.getlist('extra_unit_id'):
                if not uid:
                    continue
                u = int(uid)
                if u == default_unit:
                    continue
                conv = num(request.form.get(f'extra_conv_{uid}'))
                if conv <= 0:
                    conv = 1
                db_exec(
                    """INSERT IGNORE INTO material_units (material_id, unit_id, conversion_factor, is_default)
                       VALUES (%s,%s,%s,0)""", (mid, u, conv))
            # الأنواع (حتى 10 أنواع)
            for i in range(1, 11):
                tname = esc(request.form.get(f'type_name_{i}'))
                if not tname:
                    continue
                exists = db_query(
                    "SELECT id FROM material_types WHERE material_id=%s AND name_ar=%s",
                    (mid, tname), one=True)
                if not exists:
                    db_exec(
                        "INSERT INTO material_types (material_id, name_ar, code, notes) VALUES (%s,%s,%s,%s)",
                        (mid, tname, esc(request.form.get(f'type_code_{i}')),
                         esc(request.form.get(f'type_notes_{i}'))))
            flash(f'تمت إضافة المادة "{name}" مع {len(request.form.getlist("type_name_1")) +sum(1 for i in range(2,11) if request.form.get(f"type_name_{i}"))+1 if request.form.get("type_name_1") else 0} نوع/أنواع ووحداتها','success')
            return redirect(url_for('materials_ext.list_materials_ext'))
    units = db_query("SELECT * FROM units ORDER BY name_ar")
    currencies = db_query("SELECT * FROM currencies ORDER BY is_local DESC, name_ar")
    return render_template('materials_ext/form.html', item=None, units=units, currencies=currencies)


@materials_ext_bp.route('/<int:mid>/edit', methods=['GET','POST'])
@require_roles('admin','supervisor')
def edit_material_ext(mid):
    item = db_query("SELECT * FROM materials WHERE id=%s", (mid,), one=True)
    if not item:
        flash('المادة غير موجودة','warning')
        return redirect(url_for('materials_ext.list_materials_ext'))
    if request.method == 'POST':
        default_unit = request.form.get('default_unit_id', type=int)
        db_exec(
            "UPDATE materials SET name_ar=%s, unit_id=%s, price_per_unit=%s, currency_id=%s WHERE id=%s",
            (esc(request.form.get('name_ar')), default_unit,
             num(request.form.get('price_per_unit')),
             request.form.get('currency_id', type=int) or 1, mid))
        flash('تم تحديث المادة الأساسية','success')
        return redirect(url_for('materials_ext.edit_material_ext', mid=mid))
    item_types = db_query("SELECT * FROM material_types WHERE material_id=%s ORDER BY id", (mid,))
    item_units = db_query(
        """SELECT mu.*, u.name_ar unit_name FROM material_units mu JOIN units u ON u.id=mu.unit_id
           WHERE mu.material_id=%s ORDER BY mu.is_default DESC, u.name_ar""", (mid,))
    units = db_query("SELECT * FROM units ORDER BY name_ar")
    currencies = db_query("SELECT * FROM currencies ORDER BY is_local DESC, name_ar")
    available_units = [u for u in units if u['id'] not in [iu['unit_id'] for iu in item_units]]
    return render_template('materials_ext/form.html', item=item, item_types=item_types,
                           item_units=item_units, units=units, available_units=available_units,
                           currencies=currencies)


# ============== إضافة نوع جديد لمادة ==============
@materials_ext_bp.route('/<int:mid>/types/add', methods=['POST'])
@require_roles('admin','supervisor')
def add_material_type(mid):
    name = esc(request.form.get('name_ar'))
    if not name:
        flash('اسم النوع مطلوب','danger')
    else:
        exists = db_query("SELECT id FROM material_types WHERE material_id=%s AND name_ar=%s",
                          (mid, name), one=True)
        if exists:
            flash('هذا النوع موجود للمادة','warning')
        else:
            db_exec("INSERT INTO material_types (material_id, name_ar, code, notes) VALUES (%s,%s,%s,%s)",
                    (mid, name, esc(request.form.get('code')), esc(request.form.get('notes'))))
            flash('تمت إضافة النوع','success')
    return redirect(request.referrer or url_for('materials_ext.edit_material_ext', mid=mid))


@materials_ext_bp.route('/types/<int:tid>/delete', methods=['POST'])
@require_roles('admin')
def delete_material_type(tid):
    row = db_query("SELECT material_id FROM material_types WHERE id=%s", (tid,), one=True)
    db_exec("DELETE FROM material_types WHERE id=%s", (tid,))
    flash('تم حذف النوع','success')
    if row:
        return redirect(url_for('materials_ext.edit_material_ext', mid=row['material_id']))
    return redirect(url_for('materials_ext.list_materials_ext'))


# ============== إضافة وحدة قياس للمادة ==============
@materials_ext_bp.route('/<int:mid>/units/add', methods=['POST'])
@require_roles('admin','supervisor')
def add_material_unit(mid):
    uid = request.form.get('unit_id', type=int)
    conv = num(request.form.get('conversion_factor'))
    if not uid:
        flash('اختر وحدة القياس','danger')
    elif conv <= 0:
        flash('معامل التحويل يجب أن يكون أكبر من صفر','danger')
    else:
        try:
            db_exec(
                "INSERT INTO material_units (material_id, unit_id, conversion_factor, is_default) VALUES (%s,%s,%s,0)",
                (mid, uid, conv))
            flash('تمت إضافة وحدة قياس للمادة','success')
        except Exception:
            flash('الوحدة مضافة مسبقاً','warning')
    return redirect(url_for('materials_ext.edit_material_ext', mid=mid))


@materials_ext_bp.route('/units/<int:muid>/delete', methods=['POST'])
@require_roles('admin')
def delete_material_unit(muid):
    row = db_query("SELECT * FROM material_units WHERE id=%s", (muid,), one=True)
    if row and row['is_default']:
        flash('لا يمكن حذف الوحدة الافتراضية','warning')
    else:
        db_exec("DELETE FROM material_units WHERE id=%s", (muid,))
        flash('تم حذف الوحدة','success')
    if row:
        return redirect(url_for('materials_ext.edit_material_ext', mid=row['material_id']))
    return redirect(url_for('materials_ext.list_materials_ext'))


# ============== التالف في المخزن ==============
@materials_ext_bp.route('/damaged/<int:wid>')
@require_roles('admin','supervisor')
def damaged_warehouse_index(wid):
    wh = db_query("SELECT * FROM warehouses WHERE id=%s", (wid,), one=True)
    if not wh:
        flash('المخزن غير موجود','warning')
        return redirect(url_for('stock.overview'))
    spid = scope_project_id()
    if spid and spid != wh['project_id']:
        flash('ليست لديك صلاحية','warning')
        return redirect(url_for('stock.overview'))
    items = db_query(
        """SELECT d.*, m.name_ar material_name, t.name_ar type_name, u.name_ar unit_name, usr.full_name reporter
           FROM damaged_stock d
           JOIN materials m ON m.id=d.material_id
           LEFT JOIN material_types t ON t.id=d.material_type_id
           JOIN units u ON u.id=d.unit_id
           LEFT JOIN users usr ON usr.id=d.reported_by
           WHERE d.warehouse_id=%s ORDER BY d.damaged_date DESC, d.id DESC""", (wid,))
    summary = {}
    for d in items:
        k = (d['material_id'], d['material_type_id'])
        summary[k] = summary.get(k, 0) + num(d['quantity'])
    return render_template('damaged/warehouse_index.html', wh=wh, items=items, summary=summary)


@materials_ext_bp.route('/damaged/<int:wid>/add', methods=['GET','POST'])
@require_roles('admin','supervisor')
def damaged_add(wid):
    wh = db_query("SELECT * FROM warehouses WHERE id=%s", (wid,), one=True)
    if not wh:
        flash('المخزن غير موجود','warning')
        return redirect(url_for('stock.overview'))
    spid = scope_project_id()
    if spid and spid != wh['project_id']:
        flash('ليست لديك صلاحية','warning')
        return redirect(url_for('stock.overview'))
    if request.method == 'POST':
        mid = request.form.get('material_id', type=int)
        tid = request.form.get('material_type_id', type=int) or None
        uid = request.form.get('unit_id', type=int)
        qty = num(request.form.get('quantity'))
        reason = esc(request.form.get('reason'))
        ddate = request.form.get('damaged_date') or today()
        if not mid or not uid or qty <= 0:
            flash('يرجى إدخال المادة والوحدة والكمية','danger')
        else:
            # التحقق من الرصيد
            cur = db_query(
                """SELECT COALESCE(SUM(CASE WHEN movement_type='in' THEN quantity ELSE -quantity END),0) b
                   FROM stock_movements WHERE warehouse_id=%s AND material_id=%s""",
                (wid, mid), one=True)['b']
            damaged_total = db_query(
                "SELECT COALESCE(SUM(quantity),0) t FROM damaged_stock WHERE warehouse_id=%s AND material_id=%s",
                (wid, mid))[0]['t']
            avail = num(cur) - num(damaged_total)
            if avail < qty:
                flash(f'الكمية المتاحة في المخزن: {avail:,.0f} فقط','danger')
                return redirect(request.url)
            # تسجيل التالف
            ds_id = db_exec(
                """INSERT INTO damaged_stock (warehouse_id,material_id,material_type_id,unit_id,quantity,reason,damaged_date,reported_by)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (wid, mid, tid, uid, qty, reason, ddate, g.current_user['id']), fetch_id=True)
            # حركة مخزن نوع damage تسجّل خروج فعلي
            db_exec(
                """INSERT INTO stock_movements
                   (warehouse_id,material_id,unit_id,movement_type,quantity,price_per_unit,currency_id,exchange_rate,total_local,movement_date,note,created_by)
                   VALUES (%s,%s,%s,'damage',%s,0,1,1,0,%s,%s,%s)""",
                (wid, mid, uid, qty, ddate, f'تالف - رقم {ds_id}: {reason or ""}', g.current_user['id']))
            flash('تم تسجيل التالف وخصمه من المخزن','success')
            return redirect(url_for('materials_ext.damaged_warehouse_index', wid=wid))
    materials = db_query(
        "SELECT m.*, u.name_ar unit_name FROM materials m JOIN units u ON u.id=m.unit_id ORDER BY m.name_ar")
    return render_template('damaged/add.html', wh=wh, materials=materials, today_str=today().isoformat())


@materials_ext_bp.route('/damaged/record/<int:did>/delete', methods=['POST'])
@require_roles('admin')
def damaged_delete(did):
    item = db_query("SELECT * FROM damaged_stock WHERE id=%s", (did,), one=True)
    wid = (item or {}).get('warehouse_id')
    if item:
        db_exec("DELETE FROM damaged_stock WHERE id=%s", (did,))
        flash('تم حذف سجل التالف (تبقى حركة المخزن كسجل تاريخي)','success')
    return redirect(url_for('materials_ext.damaged_warehouse_index', wid=wid or 0))


# ============== API: بيانات المادة وأنواعها ووحداتها ==============
@materials_ext_bp.route('/api/types/<int:mid>')
@require_roles('admin','supervisor')
def api_material_types(mid):
    types = db_query("SELECT id, name_ar, code FROM material_types WHERE material_id=%s ORDER BY name_ar", (mid,))
    return {'types': types}


@materials_ext_bp.route('/api/units/<int:mid>')
@require_roles('admin','supervisor')
def api_material_units(mid):
    rows = db_query(
        """SELECT mu.id, u.name_ar unit_name, mu.conversion_factor, mu.is_default
           FROM material_units mu JOIN units u ON u.id=mu.unit_id WHERE mu.material_id=%s""", (mid,))
    return {'units': rows}

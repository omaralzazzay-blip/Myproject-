# -*- coding: utf-8 -*-
"""المواد (مع أنواع فرعية ووحدات متعددة وقسم تالف)، أنواع العمال، وحدات القياس، العملات"""
from flask import Blueprint, render_template, request, redirect, url_for, flash

from db import db_query, db_exec, esc, num, material_types_of, material_units_of
from auth import require_roles, is_admin

catalog_bp = Blueprint('catalog', __name__)


# ================== المواد ==================
@catalog_bp.route('/materials')
@require_roles('admin', 'supervisor')
def list_materials():
    rows = db_query(
        """SELECT m.*, u.name_ar AS unit_name, c.code AS cur_code, c.name_ar AS cur_name,
                  (SELECT COUNT(*) FROM stock_movements sm WHERE sm.material_id=m.id) AS moves_n,
                  (SELECT COUNT(*) FROM material_types mt WHERE mt.material_id=m.id) AS types_n,
                  (SELECT COUNT(*) FROM material_units mu WHERE mu.material_id=m.id) AS units_n,
                  (SELECT COALESCE(SUM(d.quantity),0) FROM damaged_goods d WHERE d.material_id=m.id) AS dmg_qty
           FROM materials m
           JOIN units u ON u.id=m.unit_id
           LEFT JOIN currencies c ON c.id=m.currency_id
           ORDER BY m.name_ar""")
    return render_template('materials/list.html', items=rows)


def _save_material_types(mid, raw_names):
    """يحذف الأنواع القديمة ويضيف الجديدة (من مدخلات متعددة)."""
    if raw_names is None:
        return
    names = [esc(n) for n in raw_names if esc(n)]
    old = [t['id'] for t in material_types_of(mid)]
    # لا نحذف الأنواع المستخدمة في حركات — نُبقيها دون تغيير
    used = {r['material_type_id'] for r in db_query(
        "SELECT DISTINCT material_type_id FROM stock_movements WHERE material_type_id IS NOT NULL AND material_id=%s", (mid,))}
    keep = used | {r['material_type_id'] for r in db_query(
        "SELECT DISTINCT material_type_id FROM supplier_deliveries WHERE material_type_id IS NOT NULL AND material_id=%s", (mid,))}
    kept_names = {t['name_ar'] for t in material_types_of(mid) if t['id'] in keep}
    for t in material_types_of(mid):
        if t['id'] not in keep:
            db_exec("DELETE FROM material_types WHERE id=%s", (t['id'],))
    existing = kept_names | {t['name_ar'] for t in material_types_of(mid)}
    for n in names:
        if n not in existing:
            db_exec("INSERT INTO material_types (material_id,name_ar) VALUES (%s,%s)", (mid, n))
            existing.add(n)


@catalog_bp.route('/materials/add', methods=['GET', 'POST'])
@require_roles('admin', 'supervisor')
def add_material():
    if request.method == 'POST':
        name = esc(request.form.get('name_ar'))
        unit_id = request.form.get('unit_id', type=int)
        price = num(request.form.get('price_per_unit'))
        currency_id = request.form.get('currency_id', type=int) or 1
        has_damage = 1 if request.form.get('has_damage') else 0
        if not name or not unit_id:
            flash('يرجى تعبئة الاسم ووحدة القياس', 'danger')
        else:
            mid = db_exec(
                """INSERT INTO materials (name_ar,unit_id,price_per_unit,currency_id,has_damage)
                   VALUES (%s,%s,%s,%s,%s)""",
                (name, unit_id, price, currency_id, has_damage), fetch_id=True)
            _save_material_types(mid, request.form.getlist('type_name'))
            for uid in request.form.getlist('extra_unit'):
                uid = int(uid) if str(uid).isdigit() else None
                if uid and uid != unit_id:
                    db_exec("INSERT IGNORE INTO material_units (material_id,unit_id) VALUES (%s,%s)", (mid, uid))
            flash('تمت إضافة المادة بنجاح (قسم التالف: {})'.format('مفعل' if has_damage else 'معطّل'), 'success')
            return redirect(url_for('catalog.list_materials'))
    units = db_query("SELECT * FROM units ORDER BY name_ar")
    currencies = db_query("SELECT * FROM currencies ORDER BY is_local DESC, name_ar")
    return render_template('materials/form.html', item=None, units=units, currencies=currencies,
                           types=[], mat_units=[])


@catalog_bp.route('/materials/<int:mid>/edit', methods=['GET', 'POST'])
@require_roles('admin', 'supervisor')
def edit_material(mid):
    item = db_query("SELECT * FROM materials WHERE id=%s", (mid,), one=True)
    if not item:
        flash('المادة غير موجودة', 'warning')
        return redirect(url_for('catalog.list_materials'))
    if request.method == 'POST':
        has_damage = 1 if request.form.get('has_damage') else 0
        db_exec(
            """UPDATE materials SET name_ar=%s, unit_id=%s, price_per_unit=%s, currency_id=%s, has_damage=%s
               WHERE id=%s""",
            (esc(request.form.get('name_ar')), request.form.get('unit_id', type=int),
             num(request.form.get('price_per_unit')), request.form.get('currency_id', type=int) or 1,
             has_damage, mid))
        _save_material_types(mid, request.form.getlist('type_name'))
        for uid in request.form.getlist('extra_unit'):
            uid = int(uid) if str(uid).isdigit() else None
            if uid and uid != item['unit_id']:
                db_exec("INSERT IGNORE INTO material_units (material_id,unit_id) VALUES (%s,%s)", (mid, uid))
        flash('تم تحديث المادة', 'success')
        return redirect(url_for('catalog.list_materials'))
    units = db_query("SELECT * FROM units ORDER BY name_ar")
    currencies = db_query("SELECT * FROM currencies ORDER BY is_local DESC, name_ar")
    types = material_types_of(mid)
    mat_units = material_units_of(mid)
    return render_template('materials/form.html', item=item, units=units, currencies=currencies,
                           types=types, mat_units=mat_units)


@catalog_bp.route('/materials/<int:mid>/delete', methods=['POST'])
@require_roles('admin')
def delete_material(mid):
    for t in material_types_of(mid):
        db_exec("DELETE FROM material_types WHERE id=%s", (t['id'],))
    db_exec("DELETE FROM material_units WHERE material_id=%s", (mid,))
    db_exec("DELETE FROM materials WHERE id=%s", (mid,))
    flash('تم حذف المادة', 'success')
    return redirect(url_for('catalog.list_materials'))


# ================== وحدات القياس ==================
@catalog_bp.route('/units/add', methods=['POST'])
@require_roles('admin', 'supervisor')
def add_unit():
    name = esc(request.form.get('name_ar'))
    if name:
        exists = db_query("SELECT id FROM units WHERE name_ar=%s", (name,), one=True)
        if exists:
            flash('الوحدة موجودة مسبقاً', 'warning')
        else:
            db_exec("INSERT INTO units (name_ar) VALUES (%s)", (name,))
            flash('تمت إضافة وحدة القياس', 'success')
    return redirect(request.referrer or url_for('catalog.list_materials'))


@catalog_bp.route('/units/<int:uid>/delete', methods=['POST'])
@require_roles('admin')
def delete_unit(uid):
    used = db_query("SELECT COUNT(*) c FROM materials WHERE unit_id=%s", (uid,))[0]['c']
    used += db_query("SELECT COUNT(*) c FROM material_units WHERE unit_id=%s", (uid,))[0]['c']
    if used:
        flash('لا يمكن حذف وحدة مستخدمة في مواد', 'warning')
    else:
        db_exec("DELETE FROM units WHERE id=%s", (uid,))
        flash('تم حذف الوحدة', 'success')
    return redirect(request.referrer or url_for('catalog.list_materials'))


# ================== أنواع العمال ==================
@catalog_bp.route('/worker-types')
@require_roles('admin', 'supervisor')
def list_worker_types():
    rows = db_query(
        """SELECT wt.*, c.code AS cur_code FROM worker_types wt
           LEFT JOIN currencies c ON c.id=wt.currency_id ORDER BY wt.name_ar""")
    return render_template('worker_types/list.html', items=rows)


@catalog_bp.route('/worker-types/add', methods=['POST'])
@require_roles('admin', 'supervisor')
def add_worker_type():
    name = esc(request.form.get('name_ar'))
    if name:
        exists = db_query("SELECT id FROM worker_types WHERE name_ar=%s", (name,), one=True)
        if exists:
            flash('النوع موجود مسبقاً', 'warning')
        else:
            db_exec("INSERT INTO worker_types (name_ar,default_wage,currency_id) VALUES (%s,%s,%s)",
                    (name, num(request.form.get('default_wage')), request.form.get('currency_id', type=int) or 1))
            flash('تمت إضافة نوع العمالة', 'success')
    return redirect(request.referrer or url_for('catalog.list_worker_types'))


@catalog_bp.route('/worker-types/<int:tid>/edit', methods=['POST'])
@require_roles('admin', 'supervisor')
def edit_worker_type(tid):
    db_exec("UPDATE worker_types SET name_ar=%s, default_wage=%s, currency_id=%s WHERE id=%s",
            (esc(request.form.get('name_ar')), num(request.form.get('default_wage')),
             request.form.get('currency_id', type=int) or 1, tid))
    flash('تم تحديث نوع العمالة', 'success')
    return redirect(url_for('catalog.list_worker_types'))


@catalog_bp.route('/worker-types/<int:tid>/delete', methods=['POST'])
@require_roles('admin')
def delete_worker_type(tid):
    used = db_query("SELECT COUNT(*) c FROM workers WHERE worker_type_id=%s", (tid,))[0]['c']
    if used:
        flash('لا يمكن حذف نوع مستخدم لدى عمال', 'warning')
    else:
        db_exec("DELETE FROM worker_types WHERE id=%s", (tid,))
        flash('تم حذف النوع', 'success')
    return redirect(url_for('catalog.list_worker_types'))


# ================== العملات ==================
@catalog_bp.route('/currencies')
@require_roles('admin', 'supervisor')
def list_currencies():
    rows = db_query("SELECT * FROM currencies ORDER BY is_local DESC, name_ar")
    return render_template('currencies/list.html', items=rows)


@catalog_bp.route('/currencies/add', methods=['GET', 'POST'])
@require_roles('admin')
def add_currency():
    if request.method == 'POST':
        code = esc(request.form.get('code')).upper()
        name = esc(request.form.get('name_ar'))
        rate = num(request.form.get('rate_to_local'))
        if not code or not name or rate <= 0:
            flash('يرجى إدخال بيانات صحيحة (سعر أكبر من صفر)', 'danger')
        elif db_query("SELECT id FROM currencies WHERE code=%s", (code,), one=True):
            flash('رمز العملة موجود مسبقاً', 'danger')
        else:
            db_exec("INSERT INTO currencies (code,name_ar,rate_to_local,is_local) VALUES (%s,%s,%s,0)",
                    (code, name, rate))
            flash('تمت إضافة العملة', 'success')
            return redirect(url_for('catalog.list_currencies'))
    return render_template('currencies/form.html', item=None)


@catalog_bp.route('/currencies/<int:cid>/edit', methods=['GET', 'POST'])
@require_roles('admin')
def edit_currency(cid):
    item = db_query("SELECT * FROM currencies WHERE id=%s", (cid,), one=True)
    if not item:
        flash('العملة غير موجودة', 'warning')
        return redirect(url_for('catalog.list_currencies'))
    if request.method == 'POST':
        rate = num(request.form.get('rate_to_local'))
        if rate <= 0:
            flash('سعر الصرف يجب أن يكون أكبر من صفر', 'danger')
        else:
            db_exec("UPDATE currencies SET name_ar=%s, rate_to_local=%s WHERE id=%s",
                    (esc(request.form.get('name_ar')), rate, cid))
            flash('تم تحديث سعر العملة (سيُطبّق على المعاملات الجديدة)', 'success')
            return redirect(url_for('catalog.list_currencies'))
    return render_template('currencies/form.html', item=item)


@catalog_bp.route('/currencies/<int:cid>/delete', methods=['POST'])
@require_roles('admin')
def delete_currency(cid):
    item = db_query("SELECT * FROM currencies WHERE id=%s", (cid,), one=True)
    if item and item['is_local']:
        flash('لا يمكن حذف العملة المحلية', 'danger')
    else:
        db_exec("DELETE FROM currencies WHERE id=%s", (cid,))
        flash('تم حذف العملة', 'success')
    return redirect(url_for('catalog.list_currencies'))

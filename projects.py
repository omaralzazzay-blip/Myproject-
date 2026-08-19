# -*- coding: utf-8 -*-
"""المشاريع والمراحل والمخازن"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, g

from db import db_query, db_exec, esc, num, notify_admins, notify_supervisors
from auth import require_roles, is_admin, scope_project_id

projects_bp = Blueprint('projects', __name__)


# ================== المشاريع ==================
@projects_bp.route('/projects')
@require_roles('admin', 'supervisor')
def list_projects():
    if is_admin():
        rows = db_query(
            """SELECT p.*,
                      (SELECT COUNT(*) FROM phases ph WHERE ph.project_id=p.id) AS phases_n,
                      (SELECT COUNT(*) FROM warehouses w WHERE w.project_id=p.id) AS wh_n,
                      (SELECT COALESCE(SUM(amount_local),0) FROM budgets b WHERE b.project_id=p.id AND b.level='project') AS budget
               FROM projects p ORDER BY p.id DESC""")
    else:
        pid = scope_project_id()
        rows = db_query(
            """SELECT p.*,
                      (SELECT COUNT(*) FROM phases ph WHERE ph.project_id=p.id) AS phases_n,
                      (SELECT COUNT(*) FROM warehouses w WHERE w.project_id=p.id) AS wh_n
               FROM projects p WHERE p.id=%s ORDER BY p.id DESC""", (pid,))
    return render_template('projects/list.html', items=rows)


@projects_bp.route('/projects/add', methods=['GET', 'POST'])
@require_roles('admin')
def add_project():
    if request.method == 'POST':
        pid = db_exec(
            """INSERT INTO projects (name,code,location,start_date,end_date,status,description)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (esc(request.form.get('name')), esc(request.form.get('code')),
             esc(request.form.get('location')), request.form.get('start_date') or None,
             request.form.get('end_date') or None, request.form.get('status') or 'active',
             esc(request.form.get('description'))), fetch_id=True)
        notify_admins('مشروع جديد', 'تمت إضافة المشروع: {}'.format(esc(request.form.get('name'))),
                      url_for('projects.view_project', pid=pid))
        flash('تمت إضافة المشروع بنجاح', 'success')
        return redirect(url_for('projects.view_project', pid=pid))
    return render_template('projects/form.html', item=None, action=url_for('projects.add_project'))


@projects_bp.route('/projects/<int:pid>')
@require_roles('admin', 'supervisor')
def view_project(pid):
    item = db_query("SELECT * FROM projects WHERE id=%s", (pid,), one=True)
    if not item:
        flash('المشروع غير موجود', 'warning')
        return redirect(url_for('projects.list_projects'))
    spid = scope_project_id()
    if spid and spid != pid:
        flash('ليست لديك صلاحية الوصول لهذا المشروع', 'warning')
        return redirect(url_for('dashboard.index'))

    phases = db_query("SELECT * FROM phases WHERE project_id=%s ORDER BY id", (pid,))
    warehouses = db_query("SELECT * FROM warehouses WHERE project_id=%s ORDER BY id", (pid,))
    budget = db_query(
        """SELECT COALESCE(SUM(amount_local),0) t FROM budgets
           WHERE project_id=%s AND level IN ('project','phase')""", (pid,))[0]['t']
    expenses = db_query("SELECT COALESCE(SUM(amount_local),0) t FROM expenses WHERE project_id=%s", (pid,))[0]['t']
    withdrawals = db_query("SELECT COALESCE(SUM(amount_local),0) t FROM withdrawals WHERE project_id=%s", (pid,))[0]['t']
    workers = db_query(
        """SELECT COUNT(*) c FROM workers w JOIN phases ph ON ph.id=w.phase_id
           WHERE ph.project_id=%s AND w.status='active'""", (pid,))[0]['c']
    funders_money = db_query("SELECT COALESCE(SUM(amount_local),0) t FROM funder_deposits WHERE project_id=%s", (pid,))[0]['t']
    return render_template('projects/view.html', item=item, phases=phases, warehouses=warehouses,
                           budget=budget, expenses=expenses, withdrawals=withdrawals,
                           workers=workers, funders_money=funders_money)


@projects_bp.route('/projects/<int:pid>/edit', methods=['GET', 'POST'])
@require_roles('admin')
def edit_project(pid):
    item = db_query("SELECT * FROM projects WHERE id=%s", (pid,), one=True)
    if not item:
        flash('المشروع غير موجود', 'warning')
        return redirect(url_for('projects.list_projects'))
    if request.method == 'POST':
        db_exec(
            """UPDATE projects SET name=%s, code=%s, location=%s, start_date=%s, end_date=%s,
               status=%s, description=%s WHERE id=%s""",
            (esc(request.form.get('name')), esc(request.form.get('code')),
             esc(request.form.get('location')), request.form.get('start_date') or None,
             request.form.get('end_date') or None, request.form.get('status') or 'active',
             esc(request.form.get('description')), pid))
        flash('تم تحديث المشروع', 'success')
        return redirect(url_for('projects.view_project', pid=pid))
    return render_template('projects/form.html', item=item, action=url_for('projects.edit_project', pid=pid))


@projects_bp.route('/projects/<int:pid>/delete', methods=['POST'])
@require_roles('admin')
def delete_project(pid):
    db_exec("DELETE FROM projects WHERE id=%s", (pid,))
    flash('تم حذف المشروع وكل ما يرتبط به', 'success')
    return redirect(url_for('projects.list_projects'))


# ================== المراحل ==================
@projects_bp.route('/phases/add', methods=['GET', 'POST'])
@require_roles('admin')
def add_phase():
    if request.method == 'POST':
        project_id = request.form.get('project_id', type=int)
        name = esc(request.form.get('name'))
        if not project_id or not name:
            flash('يرجى اختيار المشروع وتعبئة اسم المرحلة', 'danger')
        else:
            db_exec(
                """INSERT INTO phases (project_id,name,description,start_date,end_date,status)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                (project_id, name, esc(request.form.get('description')),
                 request.form.get('start_date') or None, request.form.get('end_date') or None,
                 request.form.get('status') or 'active'))
            notify_supervisors(project_id, 'مرحلة جديدة',
                               'أضاف المدير المرحلة: {}'.format(name),
                               url_for('projects.view_project', pid=project_id))
            flash('تمت إضافة المرحلة', 'success')
            return redirect(url_for('projects.view_project', pid=project_id))
    projects = db_query("SELECT id, name FROM projects ORDER BY name")
    return render_template('phases/form.html', item=None, projects=projects)


@projects_bp.route('/phases/<int:phid>/edit', methods=['GET', 'POST'])
@require_roles('admin')
def edit_phase(phid):
    item = db_query("SELECT * FROM phases WHERE id=%s", (phid,), one=True)
    if not item:
        flash('المرحلة غير موجودة', 'warning')
        return redirect(url_for('dashboard.index'))
    if request.method == 'POST':
        db_exec(
            """UPDATE phases SET name=%s, description=%s, start_date=%s, end_date=%s, status=%s WHERE id=%s""",
            (esc(request.form.get('name')), esc(request.form.get('description')),
             request.form.get('start_date') or None, request.form.get('end_date') or None,
             request.form.get('status') or 'active', phid))
        flash('تم تحديث المرحلة', 'success')
        return redirect(url_for('projects.view_project', pid=item['project_id']))
    return render_template('phases/form.html', item=item, projects=[])


@projects_bp.route('/phases/<int:phid>/delete', methods=['POST'])
@require_roles('admin')
def delete_phase(phid):
    item = db_query("SELECT * FROM phases WHERE id=%s", (phid,), one=True)
    pid = item['project_id'] if item else None
    db_exec("DELETE FROM phases WHERE id=%s", (phid,))
    flash('تم حذف المرحلة', 'success')
    return redirect(url_for('projects.view_project', pid=pid))


# ================== المخازن ==================
@projects_bp.route('/warehouses/add', methods=['GET', 'POST'])
@require_roles('admin', 'supervisor')
def add_warehouse():
    spid = scope_project_id()
    if request.method == 'POST':
        project_id = request.form.get('project_id', type=int)
        if spid:
            project_id = spid
        name = esc(request.form.get('name'))
        if not project_id or not name:
            flash('يرجى تعبئة البيانات', 'danger')
        else:
            db_exec("INSERT INTO warehouses (project_id,name,location,manager_name) VALUES (%s,%s,%s,%s)",
                    (project_id, name, esc(request.form.get('location')), esc(request.form.get('manager_name'))))
            if is_admin():
                notify_supervisors(project_id, 'مخزن جديد',
                                   'تمت إضافة المخزن: {}'.format(name),
                                   url_for('projects.view_project', pid=project_id))
            else:
                notify_admins('مخزن جديد',
                              'أضاف المشرف {} المخزن: {} لمشروع {}.'.format(
                                  g.current_user['full_name'], name, project_id),
                              url_for('projects.view_project', pid=project_id))
            flash('تمت إضافة المخزن بنجاح', 'success')
            return redirect(url_for('projects.view_project', pid=project_id))
    if spid:
        projects = db_query("SELECT id, name FROM projects WHERE id=%s", (spid,))
    else:
        projects = db_query("SELECT id, name FROM projects ORDER BY name")
    return render_template('warehouses/form.html', item=None, projects=projects)


@projects_bp.route('/warehouses/<int:wid>/edit', methods=['GET', 'POST'])
@require_roles('admin', 'supervisor')
def edit_warehouse(wid):
    item = db_query("SELECT * FROM warehouses WHERE id=%s", (wid,), one=True)
    if not item:
        flash('المخزن غير موجود', 'warning')
        return redirect(url_for('dashboard.index'))
    spid = scope_project_id()
    if spid and spid != item['project_id']:
        flash('ليست لديك صلاحية', 'warning')
        return redirect(url_for('dashboard.index'))
    if request.method == 'POST':
        db_exec("UPDATE warehouses SET name=%s, location=%s, manager_name=%s WHERE id=%s",
                (esc(request.form.get('name')), esc(request.form.get('location')),
                 esc(request.form.get('manager_name')), wid))
        flash('تم تحديث المخزن', 'success')
        return redirect(url_for('projects.view_project', pid=item['project_id']))
    return render_template('warehouses/form.html', item=item, projects=[])


@projects_bp.route('/warehouses/<int:wid>/delete', methods=['POST'])
@require_roles('admin', 'supervisor')
def delete_warehouse(wid):
    item = db_query("SELECT * FROM warehouses WHERE id=%s", (wid,), one=True)
    spid = scope_project_id()
    if item and spid and spid != item['project_id']:
        flash('ليست لديك صلاحية', 'warning')
        return redirect(url_for('dashboard.index'))
    pid = item['project_id'] if item else None
    db_exec("DELETE FROM warehouses WHERE id=%s", (wid,))
    flash('تم حذف المخزن', 'success')
    return redirect(url_for('projects.view_project', pid=pid))

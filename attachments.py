# -*- coding: utf-8 -*-
"""المرفقات: رفع صور الفواتير وملفات PDF والمخططات الهندسية (JPG, PNG, PDF, DWG...)
   وربطها بالمشروع أو بعملية محددة (توريد، مصروف، سحب...)."""
import os
import uuid
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, send_from_directory
from werkzeug.utils import secure_filename

from db import db_query, db_exec, esc
from auth import require_roles, scope_project_id

attachments_bp = Blueprint('attachments', __name__)

ALLOWED = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.pdf', '.dwg', '.dxf', '.doc', '.docx',
           '.xls', '.xlsx', '.zip', '.dwg~', '.bak'}

REF_LABEL = {'general': 'عام', 'expense': 'مصروف', 'withdrawal': 'سحب', 'issue': 'صرف/مسحوبات',
             'supplier_delivery': 'توريد مواد', 'supplier_money': 'توريد مالي',
             'funder_deposit': 'تمويل', 'budget': 'ميزانية', 'project': 'مشروع'}


def upload_dir():
    from app import app
    d = app.config['UPLOAD_FOLDER']
    os.makedirs(d, exist_ok=True)
    return d


def save_attachment(file_storage, project_id, ref_type='general', ref_id=None, note='', user_id=None):
    """يحفظ ملفاً مرفوعاً ويسجله في جدول attachments. يعيد id أو None."""
    if not file_storage or not file_storage.filename:
        return None
    fname = secure_filename(file_storage.filename)
    ext = os.path.splitext(fname)[1].lower()
    if ext not in ALLOWED:
        return None
    stored = uuid.uuid4().hex + ext
    file_storage.save(os.path.join(upload_dir(), stored))
    return db_exec(
        """INSERT INTO attachments (project_id,ref_type,ref_id,file_name,stored_name,file_type,file_size,note,uploaded_by)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (project_id, ref_type, ref_id, fname, stored, file_storage.mimetype,
         file_storage.content_length, note, user_id or (g.current_user['id'] if g.get('current_user') else None)),
        fetch_id=True)


@attachments_bp.route('/attachments')
@require_roles('admin', 'supervisor')
def list_attachments():
    spid = scope_project_id()
    sql = """SELECT a.*, p.name AS project_name, u.full_name AS by_name FROM attachments a
             JOIN projects p ON p.id=a.project_id LEFT JOIN users u ON u.id=a.uploaded_by WHERE 1=1"""
    params = []
    if spid:
        sql += " AND a.project_id=%s"; params.append(spid)
    rtype = request.args.get('type')
    if rtype in REF_LABEL:
        sql += " AND a.ref_type=%s"; params.append(rtype)
    sql += " ORDER BY a.id DESC LIMIT 200"
    items = db_query(sql, params)
    projects = db_query("SELECT id, name FROM projects ORDER BY name")
    return render_template('attachments/list.html', items=items, projects=projects,
                           ref_label=REF_LABEL, rtype=rtype or '')


@attachments_bp.route('/attachments/upload', methods=['POST'])
@require_roles('admin', 'supervisor')
def upload_attachment():
    spid = scope_project_id()
    project_id = request.form.get('project_id', type=int)
    if spid:
        project_id = spid
    f = request.files.get('file')
    if not f or not f.filename:
        flash('اختر ملفاً للرفع', 'danger')
        return redirect(request.referrer or url_for('attachments.list_attachments'))
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ALLOWED:
        flash('صيغة الملف غير مدعومة (JPG, PNG, PDF, DWG, DOC, XLS...)', 'danger')
        return redirect(request.referrer or url_for('attachments.list_attachments'))
    ref_type = request.form.get('ref_type') or 'general'
    ref_id = request.form.get('ref_id', type=int) or None
    save_attachment(f, project_id, ref_type, ref_id, esc(request.form.get('note')))
    flash('تم رفع المرفق بنجاح', 'success')
    return redirect(request.referrer or url_for('attachments.list_attachments'))


@attachments_bp.route('/attachments/download/<int:aid>')
@require_roles('admin', 'supervisor')
def download_attachment(aid):
    a = db_query("SELECT * FROM attachments WHERE id=%s", (aid,), one=True)
    if not a:
        flash('المرفق غير موجود', 'warning')
        return redirect(url_for('attachments.list_attachments'))
    spid = scope_project_id()
    if spid and spid != a['project_id']:
        flash('ليست لديك صلاحية', 'warning')
        return redirect(url_for('attachments.list_attachments'))
    return send_from_directory(upload_dir(), a['stored_name'], as_attachment=True,
                               download_name=a['file_name'])


@attachments_bp.route('/attachments/<int:aid>/delete', methods=['POST'])
@require_roles('admin')
def delete_attachment(aid):
    a = db_query("SELECT * FROM attachments WHERE id=%s", (aid,), one=True)
    if a:
        try:
            os.remove(os.path.join(upload_dir(), a['stored_name']))
        except OSError:
            pass
        db_exec("DELETE FROM attachments WHERE id=%s", (aid,))
        flash('تم حذف المرفق', 'success')
    return redirect(url_for('attachments.list_attachments'))

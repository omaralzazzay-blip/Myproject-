# -*- coding: utf-8 -*-
"""
المصادقة وإدارة المستخدمين (المدير والمشرفون)
"""
from functools import wraps
from flask import (Blueprint, render_template, request, redirect, url_for,
                   session, flash, g)
from werkzeug.security import generate_password_hash, check_password_hash

from db import db_query, db_exec, esc

auth_bp = Blueprint('auth', __name__)


def current_user():
    uid = session.get('user_id')
    if not uid:
        return None
    return db_query("SELECT * FROM users WHERE id=%s", (uid,), one=True)


@auth_bp.before_app_request
def load_user():
    g.current_user = current_user()


def require_login(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('auth.login', next=request.path))
        return fn(*args, **kwargs)
    return wrapper


def require_roles(*roles):
    def deco(fn):
        @wraps(fn)
        @require_login
        def wrapper(*args, **kwargs):
            u = g.get('current_user')
            if not u or u['role'] not in roles:
                flash('ليست لديك صلاحية الوصول إلى هذه الصفحة', 'warning')
                return redirect(url_for('dashboard.index'))
            return fn(*args, **kwargs)
        return wrapper
    return deco


def is_admin():
    u = g.get('current_user')
    return bool(u and u['role'] == 'admin')


def scope_project_id():
    """معرّف المشروع الذي يعمل ضمنه المستخدم (None = كل المشاريع)."""
    u = g.get('current_user')
    if not u or u['role'] == 'admin':
        return None
    return u['project_id']


# ---------------- تسجيل الدخول / الخروج ----------------
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('user_id'):
        return redirect(url_for('dashboard.index'))
    if request.method == 'POST':
        username = esc(request.form.get('username'))
        password = request.form.get('password') or ''
        user = db_query("SELECT * FROM users WHERE username=%s", (username,), one=True)
        if user and user['is_active'] and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['role'] = user['role']
            flash('مرحباً بعودتك، {}'.format(user['full_name']), 'success')
            return redirect(url_for('dashboard.index'))
        flash('اسم المستخدم أو كلمة المرور غير صحيحة', 'danger')
    return render_template('login.html')


@auth_bp.route('/logout')
def logout():
    session.clear()
    flash('تم تسجيل الخروج بنجاح', 'info')
    return redirect(url_for('auth.login'))


# ---------------- إدارة المستخدمين (للمدير) ----------------
@auth_bp.route('/users')
@require_roles('admin')
def list_users():
    rows = db_query(
        """SELECT u.*, p.name AS project_name
           FROM users u LEFT JOIN projects p ON p.id = u.project_id
           ORDER BY u.role, u.id""")
    return render_template('users_list.html', items=rows)


@auth_bp.route('/users/add', methods=['GET', 'POST'])
@require_roles('admin')
def add_user():
    if request.method == 'POST':
        username = esc(request.form.get('username'))
        full_name = esc(request.form.get('full_name'))
        role = request.form.get('role') or 'supervisor'
        project_id = request.form.get('project_id') or None
        phone = esc(request.form.get('phone'))
        password = request.form.get('password') or ''
        if not username or not full_name or not password:
            flash('يرجى تعبئة الحقول الإلزامية', 'danger')
        elif db_query("SELECT id FROM users WHERE username=%s", (username,), one=True):
            flash('اسم المستخدم موجود مسبقاً', 'danger')
        else:
            db_exec(
                """INSERT INTO users (username,password_hash,full_name,role,project_id,phone)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                (username, generate_password_hash(password), full_name, role,
                 project_id, phone), fetch_id=True)
            flash('تمت إضافة المستخدم بنجاح', 'success')
            return redirect(url_for('auth.list_users'))
    projects = db_query("SELECT id, name FROM projects ORDER BY name")
    return render_template('user_form.html', item=None, projects=projects, is_add=True)


@auth_bp.route('/users/<int:uid>/edit', methods=['GET', 'POST'])
@require_roles('admin')
def edit_user(uid):
    item = db_query("SELECT * FROM users WHERE id=%s", (uid,), one=True)
    if not item:
        flash('المستخدم غير موجود', 'warning')
        return redirect(url_for('auth.list_users'))
    if request.method == 'POST':
        full_name = esc(request.form.get('full_name'))
        role = request.form.get('role') or item['role']
        project_id = request.form.get('project_id') or None
        phone = esc(request.form.get('phone'))
        is_active = 1 if request.form.get('is_active') else 0
        password = request.form.get('password') or ''
        db_exec(
            """UPDATE users SET full_name=%s, role=%s, project_id=%s, phone=%s, is_active=%s
               WHERE id=%s""",
            (full_name, role, project_id, phone, is_active, uid))
        if password:
            db_exec("UPDATE users SET password_hash=%s WHERE id=%s",
                    (generate_password_hash(password), uid))
        flash('تم تحديث بيانات المستخدم', 'success')
        return redirect(url_for('auth.list_users'))
    projects = db_query("SELECT id, name FROM projects ORDER BY name")
    return render_template('user_form.html', item=item, projects=projects, is_add=False)


@auth_bp.route('/users/<int:uid>/delete', methods=['POST'])
@require_roles('admin')
def delete_user(uid):
    if uid == session.get('user_id'):
        flash('لا يمكنك حذف حسابك الحالي', 'danger')
    else:
        db_exec("DELETE FROM users WHERE id=%s", (uid,))
        flash('تم حذف المستخدم', 'success')
    return redirect(url_for('auth.list_users'))

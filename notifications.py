# -*- coding: utf-8 -*-
"""الإشعارات الخاصة بالمدير والمشرفين"""
from flask import Blueprint, render_template, redirect, url_for, flash, session

from db import db_query, db_exec
from auth import require_login

notifications_bp = Blueprint('notifications', __name__)


@notifications_bp.route('/notifications')
@require_login
def list_notifications():
    items = db_query(
        "SELECT * FROM notifications WHERE user_id=%s ORDER BY is_read ASC, id DESC LIMIT 100",
        (session.get('user_id'),))
    return render_template('notifications/list.html', items=items)


@notifications_bp.route('/notifications/read-all', methods=['POST'])
@require_login
def read_all():
    db_exec("UPDATE notifications SET is_read=1 WHERE user_id=%s",
            (session.get('user_id'),))
    flash('تم تحديد جميع الإشعارات كمقروءة', 'info')
    return redirect(url_for('notifications.list_notifications'))


@notifications_bp.route('/notifications/<int:nid>/read', methods=['POST'])
@require_login
def read_one(nid):
    db_exec("UPDATE notifications SET is_read=1 WHERE id=%s AND user_id=%s",
            (nid, session.get('user_id')))
    n = db_query("SELECT * FROM notifications WHERE id=%s", (nid,), one=True)
    if n and n['link']:
        return redirect(n['link'])
    return redirect(url_for('notifications.list_notifications'))

# -*- coding: utf-8 -*-
"""
نظام إدارة المشاريع الإنشائية المتكامل
Flask + SQLite - نقطة الانطلاق الرئيسية
"""
from datetime import date

from flask import Flask, g

import db
from auth import auth_bp, is_admin, scope_project_id
from config import SECRET_KEY, UPLOAD_FOLDER, HOST, PORT, DEBUG, bootstrap_runtime

bootstrap_runtime()

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config['JSON_AS_ASCII'] = False
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

from dashboard import dashboard_bp
from projects import projects_bp
from catalog import catalog_bp
from workers import workers_bp
from attachments import attachments_bp
from finance import finance_bp
from stock import stock_bp
from issues import issues_bp
from accounts import accounts_bp
from reports import reports_bp
from notifications import notifications_bp

app.register_blueprint(auth_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(projects_bp)
app.register_blueprint(catalog_bp)
app.register_blueprint(workers_bp)
app.register_blueprint(attachments_bp)
app.register_blueprint(finance_bp)
app.register_blueprint(stock_bp)
app.register_blueprint(issues_bp)
app.register_blueprint(accounts_bp)
app.register_blueprint(reports_bp)
app.register_blueprint(notifications_bp)


@app.get('/health')
def healthcheck():
    return {
        'status': 'ok',
        'app': 'construction-management-system'
    }, 200


# ---------------- سياق عام للقوالب ----------------
@app.context_processor
def inject_globals():
    u = g.get('current_user')
    unread = 0
    if u:
        unread = db.db_query("SELECT COUNT(*) AS c FROM notifications WHERE user_id=%s AND is_read=0",
                             (u['id'],), one=True)['c']
    return {
        'cur_user': u,
        'is_admin': is_admin(),
        'scope_pid': scope_project_id(),
        'unread_count': unread,
        'today': date.today(),
        'money': db.money,
        'cur_name': lambda cid: (db.cur_by_id(cid) or {}).get('name_ar', ''),
        'cur_code': lambda cid: (db.cur_by_id(cid) or {}).get('code', ''),
        'APP_NAME': 'نظام إدارة المشاريع الإنشائية',
    }


@app.template_filter('money')
def money_filter(v):
    return db.money(v)


if __name__ == '__main__':
    app.run(debug=DEBUG, host=HOST, port=PORT)

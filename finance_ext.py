# -*- coding: utf-8 -*-
"""حسابات المشروع (مدين/دائن) + حسابات العمال والمشرفين"""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from db import db_query, db_exec, esc, num, today
from auth import require_roles, scope_project_id

accounts_bp = Blueprint('accounts', __name__)


def worker_balance(wid):
    op = db_query("SELECT opening_balance FROM worker_account WHERE worker_id=%s", (wid,), one=True)
    opening = num(op['opening_balance']) if op else 0
    s = db_query(
        """SELECT COALESCE(SUM(CASE WHEN move_type='credit' THEN amount ELSE -amount END),0) t
           FROM worker_account_moves WHERE worker_id=%s""", (wid,))[0]['t']
    return opening + num(s)


def supervisor_balance(uid):
    op = db_query("SELECT opening_balance FROM supervisor_account WHERE user_id=%s", (uid,), one=True)
    opening = num(op['opening_balance']) if op else 0
    s = db_query(
        """SELECT COALESCE(SUM(CASE WHEN move_type='credit' THEN amount ELSE -amount END),0) t
           FROM supervisor_account_moves WHERE user_id=%s""", (uid,))[0]['t']
    return opening + num(s)


# ==================== حسابات المشروع ====================
@accounts_bp.route('/project')
@require_roles('admin')
def project_accounts():
    pid = request.args.get('project_id', type=int)
    rows = db_query(
        """SELECT p.*, c.code cur_code, c.rate_to_local rate FROM project_account_entries p
           JOIN currencies c ON c.id=p.currency_id ORDER BY p.entry_date DESC, p.id DESC""")
    if pid:
        rows = [it for it in rows if it['project_id'] == pid]
    totals = {'receivable': 0, 'payable': 0, 'received': 0, 'paid': 0}
    for it in rows:
        if it['entry_type'] == 'receivable':
            totals['receivable'] += num(it['amount_local'])
            if it['is_recognized']:
                totals['received'] += num(it['recognized_amount_local'])
        else:
            totals['payable'] += num(it['amount_local'])
            if it['is_recognized']:
                totals['paid'] += num(it['recognized_amount_local'])
    # تأثير على الميزانية: المعترف به يخصم فعلاً، غير المعترف لا يُخصم
    remaining_to_be_deducted = totals['payable'] - totals['paid']
    projects = db_query("SELECT id, name FROM projects ORDER BY name")
    return render_template('accounts/project_list.html', items=rows, projects=projects,
                           selected_pid=pid, totals=totals, remaining_to_be_deducted=remaining_to_be_deducted)


@accounts_bp.route('/project/add', methods=['GET','POST'])
@require_roles('admin')
def add_account_entry():
    if request.method == 'POST':
        pid = request.form.get('project_id', type=int)
        etype = request.form.get('entry_type')
        party = esc(request.form.get('party_name'))
        desc = esc(request.form.get('description'))
        amount = num(request.form.get('amount'))
        cid = request.form.get('currency_id', type=int) or 1
        if not pid or etype not in ('receivable','payable') or not party or amount <= 0:
            flash('يرجى إدخال جميع الحقول بشكل صحيح','danger')
        else:
            cur = db_query("SELECT rate_to_local r FROM currencies WHERE id=%s", (cid,), one=True)
            rate = num(cur['r']) if cur else 1
            amount_local = round(amount * rate, 3)
            db_exec(
                """INSERT INTO project_account_entries
                  (project_id,entry_type,party_name,description,amount,currency_id,exchange_rate,amount_local,is_recognized,entry_date)
                  VALUES (%s,%s,%s,%s,%s,%s,%s,%s,0,%s)""",
                (pid, etype, party, desc, amount, cid, rate, amount_local,
                 request.form.get('entry_date') or today()))
            flash(f'تم تسجيل القيد (غير معترف به حتى التحصيل/الدفع) - القيمة المحلية: {amount_local:,.0f}','success')
            return redirect(url_for('accounts.project_accounts', project_id=pid))
    projects = db_query("SELECT id, name FROM projects ORDER BY name")
    currencies = db_query("SELECT * FROM currencies ORDER BY is_local DESC, name_ar")
    return render_template('accounts/project_form.html', projects=projects, currencies=currencies)


@accounts_bp.route('/project/<int:eid>/recognize', methods=['POST'])
@require_roles('admin')
def recognize_entry(eid):
    item = db_query("SELECT * FROM project_account_entries WHERE id=%s", (eid,), one=True)
    if not item:
        flash('القيد غير موجود','warning')
    elif item['is_recognized']:
        flash('هذا القيد معترف به مسبقاً','info')
    else:
        amt_local = num(item['amount_local'])
        db_exec(
            "UPDATE project_account_entries SET is_recognized=1, recognized_date=%s, recognized_amount_local=%s WHERE id=%s",
            (request.form.get('recognized_date') or today(), amt_local, eid))
        flash('تم الاعتراف بالقيد وخصمه من ميزانية المشروع','success')
    pid = (item or {}).get('project_id')
    return redirect(url_for('accounts.project_accounts', project_id=pid))


@accounts_bp.route('/project/<int:eid>/delete', methods=['POST'])
@require_roles('admin')
def delete_account_entry(eid):
    item = db_query("SELECT * FROM project_account_entries WHERE id=%s", (eid,), one=True)
    pid = (item or {}).get('project_id')
    db_exec("DELETE FROM project_account_entries WHERE id=%s", (eid,))
    flash('تم حذف القيد','success')
    return redirect(url_for('accounts.project_accounts', project_id=pid))


# ==================== حسابات العمال ====================
@accounts_bp.route('/workers')
@require_roles('admin','supervisor')
def workers_accounts():
    spid = scope_project_id()
    sql = """SELECT w.id, w.name, p.name project_name, ph.name phase_name, wt.name_ar type_name,
                    (SELECT COALESCE(SUM(CASE WHEN m.move_type='credit' THEN m.amount ELSE -m.amount END),0) FROM worker_account_moves m WHERE m.worker_id=w.id) AS balance
             FROM workers w
             JOIN phases ph ON ph.id=w.phase_id
             JOIN projects p ON p.id=ph.project_id
             JOIN worker_types wt ON wt.id=w.worker_type_id
             WHERE 1=1"""
    params = []
    if spid:
        sql += " AND ph.project_id=%s"
        params.append(spid)
    sql += " ORDER BY p.name, ph.name, w.name"
    rows = db_query(sql, params)
    # إضافة الرصيد الافتتاحي
    for r in rows:
        op = db_query("SELECT opening_balance FROM worker_account WHERE worker_id=%s", (r['id'],), one=True)
        r['opening'] = num(op['opening_balance']) if op else 0
        r['balance'] = num(r['balance'] or 0) + r['opening']
    return render_template('accounts/worker_list.html', items=rows)


@accounts_bp.route('/worker/<int:wid>')
@require_roles('admin','supervisor')
def worker_account_view(wid):
    w = db_query(
        """SELECT w.*, ph.project_id, p.name project_name, ph.name phase_name
           FROM workers w JOIN phases ph ON ph.id=w.phase_id
           JOIN projects p ON p.id=ph.project_id WHERE w.id=%s""", (wid,), one=True)
    if not w:
        flash('العامل غير موجود','warning')
        return redirect(url_for('accounts.workers_accounts'))
    spid = scope_project_id()
    if spid and spid != w['project_id']:
        flash('ليست لديك صلاحية','warning')
        return redirect(url_for('accounts.workers_accounts'))
    moves = db_query(
        """SELECT m.*, c.code cur_code FROM worker_account_moves m
           JOIN currencies c ON c.id=m.currency_id WHERE m.worker_id=%s
           ORDER BY m.move_date DESC, m.id DESC LIMIT 150""", (wid,))
    bal = worker_balance(wid)
    # مجموع حسب النوع
    debits = db_query(
        """SELECT COALESCE(SUM(amount),0) t FROM worker_account_moves WHERE worker_id=%s AND move_type='debit'""",
        (wid,))[0]['t']
    credits = db_query(
        """SELECT COALESCE(SUM(amount),0) t FROM worker_account_moves WHERE worker_id=%s AND move_type='credit'""",
        (wid,))[0]['t']
    currencies = db_query("SELECT * FROM currencies ORDER BY is_local DESC, name_ar")
    return render_template('accounts/worker_account.html', w=w, moves=moves, balance=bal,
                           debits=num(debits), credits=num(credits), currencies=currencies)


@accounts_bp.route('/worker/<int:wid>/add', methods=['POST'])
@require_roles('admin','supervisor')
def add_worker_move(wid):
    mtype = request.form.get('move_type')
    amount = num(request.form.get('amount'))
    cid = request.form.get('currency_id', type=int) or 1
    ref = esc(request.form.get('reference_type')) or 'manual'
    note = esc(request.form.get('note'))
    if mtype not in ('debit','credit') or amount <= 0:
        flash('نوع أو مبلغ غير صحيح','danger')
    else:
        # ضمان وجود صف worker_account
        if not db_query("SELECT id FROM worker_account WHERE worker_id=%s", (wid,), one=True):
            db_exec("INSERT INTO worker_account (worker_id, opening_balance, notes) VALUES (%s, 0, 'إنشاء تلقائي')", (wid,))
        db_exec(
            """INSERT INTO worker_account_moves (worker_id,move_type,amount,currency_id,reference_type,note,move_date)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (wid, mtype, amount, cid, ref, note, request.form.get('move_date') or today()))
        flash('تم تسجيل الحركة على حساب العامل','success')
    return redirect(url_for('accounts.worker_account_view', wid=wid))


@accounts_bp.route('/worker/<int:wid>/opening', methods=['POST'])
@require_roles('admin')
def set_worker_opening(wid):
    op = num(request.form.get('opening_balance'))
    if not db_query("SELECT id FROM worker_account WHERE worker_id=%s", (wid,), one=True):
        db_exec("INSERT INTO worker_account (worker_id, opening_balance, notes) VALUES (%s, %s, %s)",
                (wid, op, esc(request.form.get('notes'))))
    else:
        db_exec("UPDATE worker_account SET opening_balance=%s, notes=%s WHERE worker_id=%s",
                (op, esc(request.form.get('notes')), wid))
    flash('تم تحديث الرصيد الافتتاحي للعامل','success')
    return redirect(url_for('accounts.worker_account_view', wid=wid))


# ==================== حسابات المشرفين ====================
@accounts_bp.route('/supervisors')
@require_roles('admin')
def supervisors_accounts():
    rows = db_query(
        """SELECT u.id, u.full_name, u.username,
                  (SELECT COALESCE(SUM(CASE WHEN m.move_type='credit' THEN m.amount ELSE -m.amount END),0)
                   FROM supervisor_account_moves m WHERE m.user_id=u.id) AS balance
           FROM users u WHERE u.role='supervisor' AND u.is_active=1 ORDER BY u.full_name""")
    for r in rows:
        op = db_query("SELECT opening_balance FROM supervisor_account WHERE user_id=%s", (r['id'],), one=True)
        r['opening'] = num(op['opening_balance']) if op else 0
        r['balance'] = num(r['balance'] or 0) + r['opening']
        r['pid'] = None
        pm = db_query("SELECT p.name FROM users u LEFT JOIN projects p ON p.id=u.project_id WHERE u.id=%s", (r['id'],), one=True)
        r['project_name'] = pm['name'] if pm else '-'
    return render_template('accounts/supervisor_list.html', rows=rows)


@accounts_bp.route('/supervisor/<int:uid>')
@require_roles('admin')
def supervisor_account_view(uid):
    u = db_query("SELECT * FROM users WHERE id=%s", (uid,), one=True)
    if not u:
        flash('المستخدم غير موجود','warning')
        return redirect(url_for('accounts.supervisors_accounts'))
    pm = db_query("SELECT * FROM projects WHERE id=%s", (u['project_id'],), one=True) if u['project_id'] else None
    moves = db_query(
        """SELECT m.*, c.code cur_code FROM supervisor_account_moves m
           JOIN currencies c ON c.id=m.currency_id WHERE m.user_id=%s
           ORDER BY m.move_date DESC, m.id DESC LIMIT 150""", (uid,))
    bal = supervisor_balance(uid)
    debits = db_query("SELECT COALESCE(SUM(amount),0) t FROM supervisor_account_moves WHERE user_id=%s AND move_type='debit'", (uid,))[0]['t']
    credits = db_query("SELECT COALESCE(SUM(amount),0) t FROM supervisor_account_moves WHERE user_id=%s AND move_type='credit'", (uid,))[0]['t']
    currencies = db_query("SELECT * FROM currencies ORDER BY is_local DESC, name_ar")
    return render_template('accounts/supervisor_account.html', u=u, pm=pm, moves=moves,
                           balance=bal, debits=num(debits), credits=num(credits), currencies=currencies)


@accounts_bp.route('/supervisor/<int:uid>/add', methods=['POST'])
@require_roles('admin')
def add_supervisor_move(uid):
    mtype = request.form.get('move_type')
    amount = num(request.form.get('amount'))
    cid = request.form.get('currency_id', type=int) or 1
    note = esc(request.form.get('note'))
    if mtype not in ('debit','credit') or amount <= 0:
        flash('نوع أو مبلغ غير صحيح','danger')
    else:
        if not db_query("SELECT id FROM supervisor_account WHERE user_id=%s", (uid,), one=True):
            db_exec("INSERT INTO supervisor_account (user_id, opening_balance) VALUES (%s, 0)", (uid,))
        db_exec(
            """INSERT INTO supervisor_account_moves (user_id,move_type,amount,currency_id,note,move_date)
               VALUES (%s,%s,%s,%s,%s,%s)""",
            (uid, mtype, amount, cid, note, request.form.get('move_date') or today()))
        flash('تم تسجيل الحركة على حساب المشرف','success')
    return redirect(url_for('accounts.supervisor_account_view', uid=uid))


@accounts_bp.route('/supervisor/<int:uid>/opening', methods=['POST'])
@require_roles('admin')
def set_supervisor_opening(uid):
    op = num(request.form.get('opening_balance'))
    if not db_query("SELECT id FROM supervisor_account WHERE user_id=%s", (uid,), one=True):
        db_exec("INSERT INTO supervisor_account (user_id, opening_balance, notes) VALUES (%s, %s, %s)",
                (uid, op, esc(request.form.get('notes'))))
    else:
        db_exec("UPDATE supervisor_account SET opening_balance=%s, notes=%s WHERE user_id=%s",
                (op, esc(request.form.get('notes')), uid))
    flash('تم تحديث الرصيد الافتتاحي للمشرف','success')
    return redirect(url_for('accounts.supervisor_account_view', uid=uid))

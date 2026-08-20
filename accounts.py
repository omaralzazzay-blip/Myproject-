# -*- coding: utf-8 -*-
"""قائمة الحسابات (مدين / دائن) وربطها بحساب المشروع الرئيسي
   - المدين: يُعترف به عند تحصيله فعلياً (أساس الاستحقاق النقدي للمدين)
   - الدائن: يُخصم مباشرة من ميزانية المشروع"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, g

from db import (db_query, db_exec, esc, num, today, make_tx, cur_list,
                main_account, account_balance, post_account_entry, notify_supervisors)
from auth import require_roles, scope_project_id

accounts_bp = Blueprint('accounts', __name__)

ACC_LABEL = {'project': ('مشروع رئيسي', 'primary'), 'worker': ('عامل', 'info'),
             'supervisor': ('مشرف', 'info'), 'debtor': ('مدين', 'success'),
             'creditor': ('دائن', 'danger')}


@accounts_bp.route('/accounts')
@require_roles('admin', 'supervisor')
def list_accounts():
    spid = scope_project_id()
    tp = request.args.get('type')
    sql = """SELECT a.*, p.name AS project_name FROM accounts a JOIN projects p ON p.id=a.project_id WHERE 1=1"""
    params = []
    if spid:
        sql += """ ORDER BY a.project_id, 
          CASE a.acc_type 
              WHEN 'project' THEN 1
              WHEN 'creditor' THEN 2
              WHEN 'debtor' THEN 3
              WHEN 'worker' THEN 4
              WHEN 'supervisor' THEN 5
              ELSE 6
          END, a.name"""
    if tp in ACC_LABEL:
        sql += " AND a.acc_type=%s"; params.append(tp)
    sql += " ORDER BY a.project_id, FIELD(a.acc_type,'project','creditor','debtor','worker','supervisor'), a.name"
    rows = db_query(sql, params)
    for r in rows:
        r['balance'] = account_balance(r['id'])
    totals = {}
    for r in rows:
        t = totals.setdefault(r['project_id'], {'name': r['project_name'], 'debit': 0, 'credit': 0})
        if r['acc_type'] == 'creditor':
            t['credit'] += r['balance']
        elif r['acc_type'] == 'debtor':
            t['debit'] += r['balance']
    return render_template('accounts/list.html', items=rows, totals=totals,
                           acc_label=ACC_LABEL, tp=tp or '')


@accounts_bp.route('/accounts/add', methods=['GET', 'POST'])
@require_roles('admin')
def add_account():
    if request.method == 'POST':
        project_id = request.form.get('project_id', type=int)
        name = esc(request.form.get('name'))
        acc_type = request.form.get('acc_type')
        amount = num(request.form.get('amount'))
        collected = 1 if request.form.get('collected') else 0
        currency_id = request.form.get('currency_id', type=int) or 1
        if not project_id or not name or acc_type not in ACC_LABEL:
            flash('يرجى تعبئة البيانات بشكل صحيح', 'danger')
        else:
            aid = db_exec(
                """INSERT INTO accounts (project_id,name,acc_type,collected,description) VALUES (%s,%s,%s,%s,%s)""",
                (project_id, name, acc_type, collected, esc(request.form.get('description'))), fetch_id=True)
            rate, local = make_tx(currency_id, amount)
            main = main_account(project_id)
            if acc_type == 'creditor' and amount > 0:
                # الدائن: يُخصم مباشرة من ميزانية المشروع
                if main:
                    post_account_entry(main['id'], project_id, 'debit', amount, currency_id, local,
                                       'creditor', aid, 'خصم مباشر من ميزانية المشروع (دائن)', today(),
                                       g.current_user['id'])
                post_account_entry(aid, project_id, 'credit', amount, currency_id, local,
                                   'creditor', aid, 'قيد دائن - التزام على المشروع', today(),
                                   g.current_user['id'])
                notify_supervisors(project_id, 'قيد دائن',
                                   'أُضيف دائن: {} بمبلغ {:,.0f} (خُصم من الميزانية)'.format(name, local),
                                   url_for('accounts.list_accounts'))
            elif acc_type == 'debtor':
                # المدين: يُعترف به عند تحصيله فعلياً فقط
                if collected and amount > 0 and main:
                    post_account_entry(main['id'], project_id, 'credit', amount, currency_id, local,
                                       'collection', aid, 'تحصيل مدين - دخول للميزانية', today(),
                                       g.current_user['id'])
                    post_account_entry(aid, project_id, 'debit', amount, currency_id, local,
                                       'collection', aid, 'تحصيل مدين (اعتراف فعلي)', today(),
                                       g.current_user['id'])
            flash('تمت إضافة الحساب', 'success')
            return redirect(url_for('accounts.list_accounts'))
    projects = db_query("SELECT id, name FROM projects ORDER BY name")
    currencies = cur_list()
    return render_template('accounts/form.html', projects=projects, currencies=currencies,
                           acc_label=ACC_LABEL)


@accounts_bp.route('/accounts/<int:aid>')
@require_roles('admin', 'supervisor')
def account_detail(aid):
    item = db_query("""SELECT a.*, p.name AS project_name FROM accounts a
                       JOIN projects p ON p.id=a.project_id WHERE a.id=%s""", (aid,), one=True)
    if not item:
        flash('الحساب غير موجود', 'warning')
        return redirect(url_for('accounts.list_accounts'))
    spid = scope_project_id()
    if spid and spid != item['project_id']:
        flash('ليست لديك صلاحية', 'warning')
        return redirect(url_for('accounts.list_accounts'))
    entries = db_query(
        """SELECT e.*, c.code AS cur_code, u.full_name AS by_name FROM account_entries e
           JOIN currencies c ON c.id=e.currency_id LEFT JOIN users u ON u.id=e.created_by
           WHERE e.account_id=%s ORDER BY e.entry_date DESC, e.id DESC""", (aid,))
    balance = account_balance(aid)
    main = main_account(item['project_id'])
    currencies = cur_list()
    return render_template('accounts/detail.html', item=item, entries=entries, balance=balance,
                           main=main, currencies=currencies, acc_label=ACC_LABEL)


@accounts_bp.route('/accounts/<int:aid>/entry/add', methods=['POST'])
@require_roles('admin')
def add_entry(aid):
    item = db_query("SELECT * FROM accounts WHERE id=%s", (aid,), one=True)
    direction = request.form.get('direction')
    amount = num(request.form.get('amount'))
    currency_id = request.form.get('currency_id', type=int) or 1
    if not item or direction not in ('debit', 'credit') or amount <= 0:
        flash('بيانات القيد غير صحيحة', 'danger')
    else:
        rate, local = make_tx(currency_id, amount)
        post_account_entry(aid, item['project_id'], direction, amount, currency_id, local,
                           'manual', None, esc(request.form.get('note')),
                           request.form.get('entry_date') or today(), g.current_user['id'])
        flash('تم تسجيل القيد', 'success')
    return redirect(url_for('accounts.account_detail', aid=aid))


@accounts_bp.route('/accounts/<int:aid>/collect', methods=['POST'])
@require_roles('admin')
def collect_account(aid):
    item = db_query("SELECT * FROM accounts WHERE id=%s", (aid,), one=True)
    if not item:
        flash('الحساب غير موجود', 'warning')
        return redirect(url_for('accounts.list_accounts'))
    if item['acc_type'] != 'debtor':
        flash('التحصيل ينطبق فقط على الحسابات المدينة', 'warning')
        return redirect(url_for('accounts.account_detail', aid=aid))
    amount = num(request.form.get('amount'))
    if amount <= 0:
        flash('أدخل مبلغ التحصيل', 'danger')
        return redirect(url_for('accounts.account_detail', aid=aid))
    currency_id = request.form.get('currency_id', type=int) or 1
    rate, local = make_tx(currency_id, amount)
    main = main_account(item['project_id'])
    if main:
        post_account_entry(main['id'], item['project_id'], 'credit', amount, currency_id, local,
                           'collection', aid, 'تحصيل مدين - دخول للميزانية', today(), g.current_user['id'])
    post_account_entry(aid, item['project_id'], 'debit', amount, currency_id, local,
                       'collection', aid, 'تحصيل فعلي للمدين', today(), g.current_user['id'])
    if item['collected'] == 0:
        db_exec("UPDATE accounts SET collected=1, collection_date=%s WHERE id=%s", (today(), aid))
    flash('تم تسجيل التحصيل واعتماد المدين فعلياً', 'success')
    return redirect(url_for('accounts.account_detail', aid=aid))


@accounts_bp.route('/accounts/<int:aid>/delete', methods=['POST'])
@require_roles('admin')
def delete_account(aid):
    item = db_query("SELECT * FROM accounts WHERE id=%s", (aid,), one=True)
    if item and item['is_main']:
        flash('لا يمكن حذف حساب المشروع الرئيسي', 'danger')
    else:
        db_exec("DELETE FROM account_entries WHERE account_id=%s", (aid,))
        db_exec("DELETE FROM accounts WHERE id=%s", (aid,))
        flash('تم حذف الحساب وقيوده', 'success')
    return redirect(url_for('accounts.list_accounts'))

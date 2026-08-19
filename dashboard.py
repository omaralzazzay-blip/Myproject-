# -*- coding: utf-8 -*-
"""لوحة التحكم - المدير والمشرف"""
from flask import Blueprint, render_template

from db import db_query
from auth import require_login, is_admin, scope_project_id

dashboard_bp = Blueprint('dashboard', __name__)


@dashboard_bp.route('/')
@require_login
def index():
    u = scope_project_id()
    if is_admin():
        data = admin_dashboard()
        return render_template('dashboard/index.html', **data)
    return render_template('dashboard/supervisor.html', **supervisor_dashboard(u))


def admin_dashboard():
    stats = {}
    stats['projects'] = db_query("SELECT COUNT(*) c FROM projects")[0]['c']
    stats['active_projects'] = db_query("SELECT COUNT(*) c FROM projects WHERE status='active'")[0]['c']
    stats['phases'] = db_query("SELECT COUNT(*) c FROM phases")[0]['c']
    stats['workers'] = db_query("SELECT COUNT(*) c FROM workers WHERE status='active'")[0]['c']
    stats['materials'] = db_query("SELECT COUNT(*) c FROM materials")[0]['c']
    stats['warehouses'] = db_query("SELECT COUNT(*) c FROM warehouses")[0]['c']
    stats['supervisors'] = db_query("SELECT COUNT(*) c FROM users WHERE role='supervisor' AND is_active=1")[0]['c']

    # الميزانية الكلية بالعملة المحلية (كل المصادر)
    total_budget = db_query("SELECT COALESCE(SUM(amount_local),0) t FROM budgets")[0]['t']
    total_expenses = db_query("SELECT COALESCE(SUM(amount_local),0) t FROM expenses")[0]['t']
    total_withdrawals = db_query("SELECT COALESCE(SUM(amount_local),0) t FROM withdrawals")[0]['t']
    total_exp_wh = db_query("SELECT COALESCE(SUM(total_local),0) t FROM supplier_deliveries")[0]['t']

    recent_expenses = db_query(
        """SELECT e.*, p.name AS project_name, ph.name AS phase_name, c.code AS cur_code
           FROM expenses e
           JOIN projects p ON p.id=e.project_id
           LEFT JOIN phases ph ON ph.id=e.phase_id
           JOIN currencies c ON c.id=e.currency_id
           ORDER BY e.expense_date DESC, e.id DESC LIMIT 6""")
    recent_withdrawals = db_query(
        """SELECT w.*, p.name AS project_name, ph.name AS phase_name, c.code AS cur_code
           FROM withdrawals w
           JOIN projects p ON p.id=w.project_id
           LEFT JOIN phases ph ON ph.id=w.phase_id
           JOIN currencies c ON c.id=w.currency_id
           ORDER BY w.withdraw_date DESC, w.id DESC LIMIT 6""")
    recent_deliveries = db_query(
        """SELECT sd.*, s.name AS supplier_name, wh.name AS warehouse_name, m.name_ar AS material_name,
                  u.name_ar AS unit_name, c.code AS cur_code
           FROM supplier_deliveries sd
           JOIN suppliers s ON s.id=sd.supplier_id
           JOIN warehouses wh ON wh.id=sd.warehouse_id
           JOIN materials m ON m.id=sd.material_id
           JOIN units u ON u.id=sd.unit_id
           JOIN currencies c ON c.id=sd.currency_id
           ORDER BY sd.id DESC LIMIT 6""")
    low_stock = db_query(
        """SELECT wh.name AS warehouse_name, m.name_ar AS material_name, u.name_ar AS unit_name,
                  SUM(CASE WHEN sm.movement_type='in' THEN sm.quantity ELSE -sm.quantity END) AS balance
           FROM stock_movements sm
           JOIN warehouses wh ON wh.id=sm.warehouse_id
           JOIN materials m ON m.id=sm.material_id
           JOIN units u ON u.id=sm.unit_id
           GROUP BY sm.warehouse_id, sm.material_id
           HAVING balance <= 20 ORDER BY balance ASC LIMIT 6""")

    return dict(stats=stats, total_budget=total_budget, total_expenses=total_expenses,
                total_withdrawals=total_withdrawals, total_exp_wh=total_exp_wh,
                recent_expenses=recent_expenses, recent_withdrawals=recent_withdrawals,
                recent_deliveries=recent_deliveries, low_stock=low_stock)


def supervisor_dashboard(pid):
    project = db_query("SELECT * FROM projects WHERE id=%s", (pid,), one=True)
    phases = db_query("SELECT * FROM phases WHERE project_id=%s ORDER BY id", (pid,))
    phase_ids = [p['id'] for p in phases]
    stats = {'phases': len(phase_ids), 'workers': 0, 'materials': 0, 'warehouses': 0}
    stats['warehouses'] = db_query("SELECT COUNT(*) c FROM warehouses WHERE project_id=%s", (pid,))[0]['c']
    stats['materials'] = db_query("SELECT COUNT(*) c FROM materials")[0]['c']
    if phase_ids:
        ph = ','.join(str(i) for i in phase_ids)
        stats['workers'] = db_query(
            "SELECT COUNT(*) c FROM workers WHERE phase_id IN (%s) AND status='active'" % ph)[0]['c']

    # الميزانية المرصودة للمشروع (بما فيها مراحل المشروع)
    budget = db_query(
        """SELECT COALESCE(SUM(amount_local),0) t FROM budgets
           WHERE (level='project' AND project_id=%s) OR (level='phase' AND project_id=%s)""",
        (pid, pid))[0]['t']
    expenses = db_query("SELECT COALESCE(SUM(amount_local),0) t FROM expenses WHERE project_id=%s", (pid,))[0]['t']
    withdrawals = db_query("SELECT COALESCE(SUM(amount_local),0) t FROM withdrawals WHERE project_id=%s", (pid,))[0]['t']

    recent = db_query(
        """SELECT 'مصروف' AS kind, e.amount_local AS amt, e.expense_date AS d, e.description AS txt
           FROM expenses e WHERE e.project_id=%s
           UNION ALL
           SELECT 'سحب', w.amount_local, w.withdraw_date, w.description
           FROM withdrawals w WHERE w.project_id=%s
           ORDER BY d DESC LIMIT 8""", (pid, pid))
    low_stock = db_query(
        """SELECT wh.name AS warehouse_name, m.name_ar AS material_name, u.name_ar AS unit_name,
                  SUM(CASE WHEN sm.movement_type='in' THEN sm.quantity ELSE -sm.quantity END) AS balance
           FROM stock_movements sm
           JOIN warehouses wh ON wh.id=sm.warehouse_id
           JOIN materials m ON m.id=sm.material_id
           JOIN units u ON u.id=sm.unit_id
           WHERE wh.project_id=%s
           GROUP BY sm.warehouse_id, sm.material_id
           HAVING balance <= 20 ORDER BY balance ASC LIMIT 5""", (pid,))

    return dict(project=project, phases=phases, stats=stats, budget=budget,
                expenses=expenses, withdrawals=withdrawals, recent=recent, low_stock=low_stock)

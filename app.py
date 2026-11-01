import os
import secrets
import sqlite3
import calendar
import json
from contextlib import contextmanager
from datetime import date, datetime
from functools import wraps

from flask import Flask, abort, flash, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from integrations import send_sms
from init_db import get_conn, init_db

APP_ENV = os.environ.get("APP_ENV", "development").lower()
SECRET_KEY = os.environ.get("SECRET_KEY")
if APP_ENV == "production" and (not SECRET_KEY or len(SECRET_KEY) < 32):
    raise RuntimeError("Production requires SECRET_KEY with at least 32 characters.")

# ==========================================
# SINGLE FLASK APP INITIALIZATION
# ==========================================
app = Flask(__name__)
app.config.update(
    SECRET_KEY=SECRET_KEY or secrets.token_urlsafe(48),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="None" if APP_ENV == "production" else "Lax",
    SESSION_COOKIE_SECURE=APP_ENV == "production",
)

LOAN_INTEREST_RATE = 20.0
MONTHLY_FINE_RATE = float(os.environ.get("MONTHLY_FINE_RATE", "0.05"))
CHAMA_START_MONTH = 5
CHAMA_END_MONTH = 11
CHAMA_END_DAY = 30


@contextmanager
def database():
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def add_months(day, months=1):
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def member_cycle_status(date_joined, as_of=None):
    current_date = as_of or date.today()
    cycle_year = current_date.year if current_date.month >= CHAMA_START_MONTH else current_date.year - 1
    cycle_start = date(cycle_year, CHAMA_START_MONTH, 1)
    maturity_date = date(cycle_year, CHAMA_END_MONTH, CHAMA_END_DAY)
    return {
        "cycle_start": cycle_start,
        "maturity_date": maturity_date,
        "months_remaining": max(0, (maturity_date.year - current_date.year) * 12 + maturity_date.month - current_date.month - (current_date.day < maturity_date.day)),
        "cycle_complete": current_date >= maturity_date,
    }


def queue_notification(conn, user_id, message):
    user = conn.execute("SELECT phone FROM users WHERE id = ?", (user_id,)).fetchone()
    phone = user["phone"] if user else None
    status, reference = send_sms(phone, message)
    conn.execute(
        "INSERT INTO notifications (user_id, channel, message, status, provider_reference, created_at, sent_at) VALUES (?, 'sms', ?, ?, ?, ?, ?)",
        (user_id, message, status, reference, transaction_date(), transaction_date() if status == "sent" else None),
    )


@app.before_request
def prepare_request():
    g.csrf_token = session.setdefault("csrf_token", secrets.token_hex(32))
    if request.method == "POST":
        submitted = request.form.get("csrf_token", "")
        if not secrets.compare_digest(submitted, g.csrf_token):
            abort(400, description="Your session has expired. Refresh and try again.")
    user = current_user()
    if user and user["must_change_password"] and request.endpoint not in {"change_password", "logout", "static"}:
        return redirect(url_for("change_password"))


@app.context_processor
def inject_template_values():
    return {
        "csrf_token": g.csrf_token,
        "loan_interest_rate": LOAN_INTEREST_RATE,
        "display_user": current_user(),
        "is_super_admin": bool(current_user() and current_user()["is_super_admin"]),
    }


def current_user():
    if "user_id" not in session:
        return None
    if getattr(g, "user", None) is None:
        with database() as conn:
            g.user = conn.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    return g.user


def require_role(role):
    def decorate(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = current_user()
            if user is None:
                session.clear()
                flash("Please sign in to continue.", "error")
                return redirect(url_for("login"))
            allowed = user["role"] == role
            if role == "admin" and user["is_super_admin"]:
                allowed = True
            if not allowed:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorate


def as_money(value):
    return round(float(value), 2)


def parse_positive_amount(value, label):
    try:
        amount = round(float(value), 2)
    except (TypeError, ValueError):
        raise ValueError(f"Enter a valid {label}.")
    if not amount > 0 or amount != amount or amount == float("inf"):
        raise ValueError(f"{label.title()} must be greater than zero.")
    return amount


def member_financials(conn, user_id):
    savings = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM savings WHERE user_id = ?", (user_id,)
    ).fetchone()[0]
    active_balance = conn.execute(
        "SELECT COALESCE(SUM(balance_due), 0) FROM loans WHERE user_id = ? AND status = 'approved'",
        (user_id,),
    ).fetchone()[0]
    committed_principal = conn.execute(
        "SELECT COALESCE(SUM(CASE WHEN status = 'pending' THEN principal_amount ELSE principal_balance END), 0) FROM loans WHERE user_id = ? AND status IN ('pending', 'approved')",
        (user_id,),
    ).fetchone()[0]
    locked = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM guarantor_locks WHERE guarantor_id = ? AND status IN ('pending', 'active')",
        (user_id,),
    ).fetchone()[0]
    limit = max(0, float(savings) - float(locked)) * 3
    return {
        "savings": as_money(savings),
        "active_balance": as_money(active_balance),
        "limit": as_money(limit),
        "remaining": as_money(max(0, limit - float(committed_principal))),
        "committed_principal": as_money(committed_principal),
        "guarantor_locked": as_money(locked),
    }


def member_earnings_report(conn, member_id, year):
    today = date.today()
    accrual_end_month = 12 if year < today.year else today.month if year == today.year else 0
    cycle = member_cycle_status(None, today)
    for accrual_year in range(cycle["cycle_start"].year, min(year, today.year) + 1):
        last_month = accrual_end_month if accrual_year == year else (12 if accrual_year < year else today.month)
        for accrual_month in range(1, last_month + 1):
            materialize_interest_accruals(conn, accrual_year, accrual_month)

    months = []
    cumulative = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM member_interest_accruals WHERE user_id = ? AND period >= ? AND period < ?",
        (member_id, cycle["cycle_start"].strftime("%Y-%m"), f"{year:04d}-01"),
    ).fetchone()[0]
    for month in range(1, 13):
        month_start = date(year, month, 1)
        next_month = add_months(month_start)
        month_end = next_month.isoformat()
        period = month_start.strftime("%Y-%m")
        monthly_contribution = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM savings WHERE user_id = ? AND date >= ? AND date < ?",
            (member_id, month_start.isoformat(), month_end),
        ).fetchone()[0]
        member_savings = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM savings WHERE user_id = ? AND date < ?",
            (member_id, month_end),
        ).fetchone()[0]
        total_savings = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM savings WHERE date < ?",
            (month_end,),
        ).fetchone()[0]
        accrual = conn.execute(
            "SELECT interest_pool, savings_basis, total_savings_basis, share_percent, amount FROM member_interest_accruals WHERE user_id = ? AND period = ?",
            (member_id, period),
        ).fetchone()
        interest = float(accrual["interest_pool"]) if accrual else 0
        share_percent = float(accrual["share_percent"]) if accrual else 0
        share = as_money(accrual["amount"]) if accrual else 0
        member_interest_paid = conn.execute(
            "SELECT COALESCE(SUM(r.interest_paid), 0) FROM loan_repayments r JOIN loans l ON l.id = r.loan_id WHERE l.user_id = ? AND r.date >= ? AND r.date < ?",
            (member_id, month_start.isoformat(), month_end),
        ).fetchone()[0]
        member_repayments = conn.execute(
            "SELECT COALESCE(SUM(r.amount_paid), 0) FROM loan_repayments r JOIN loans l ON l.id = r.loan_id WHERE l.user_id = ? AND r.date >= ? AND r.date < ?",
            (member_id, month_start.isoformat(), month_end),
        ).fetchone()[0]
        if year < today.year or (year == today.year and month <= today.month):
            cumulative = as_money(float(cumulative) + share)
        months.append({
            "period": period,
            "month_label": month_start.strftime("%b %Y"),
            "contribution": as_money(monthly_contribution),
            "savings_at_month_end": as_money(member_savings),
            "total_savings_basis": as_money(accrual["total_savings_basis"]) if accrual else as_money(total_savings),
            "interest_income": as_money(interest),
            "share_percent": round(share_percent * 100, 2),
            "member_share": share,
            "cumulative_earned": as_money(cumulative),
            "member_interest_paid": as_money(member_interest_paid),
            "member_repayments": as_money(member_repayments),
        })
    return months


def materialize_interest_accruals(conn, year, month):
    month_start = date(year, month, 1)
    month_end = add_months(month_start)
    period = month_start.strftime("%Y-%m")
    interest_pool = conn.execute(
        "SELECT COALESCE(SUM(interest_paid), 0) FROM loan_repayments WHERE date >= ? AND date < ?",
        (month_start.isoformat(), month_end.isoformat()),
    ).fetchone()[0]
    members = conn.execute(
        "SELECT u.id, COALESCE(SUM(s.amount), 0) AS savings_basis FROM users u LEFT JOIN savings s ON s.user_id = u.id AND s.date < ? WHERE u.role = 'member' AND substr(u.date_joined, 1, 10) < ? GROUP BY u.id ORDER BY u.id",
        (month_end.isoformat(), month_end.isoformat()),
    ).fetchall()
    total_savings = sum(float(member["savings_basis"] or 0) for member in members)
    for member in members:
        savings_basis = float(member["savings_basis"] or 0)
        share_percent = savings_basis / total_savings if total_savings > 0 else 0
        amount = as_money(float(interest_pool) * share_percent)
        conn.execute(
            "INSERT INTO member_interest_accruals (user_id, period, interest_pool, savings_basis, total_savings_basis, share_percent, amount, calculated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(user_id, period) DO UPDATE SET interest_pool = excluded.interest_pool, savings_basis = excluded.savings_basis, total_savings_basis = excluded.total_savings_basis, share_percent = excluded.share_percent, amount = excluded.amount, calculated_at = excluded.calculated_at",
            (member["id"], period, as_money(interest_pool), as_money(savings_basis), as_money(total_savings), share_percent, amount, transaction_date()),
        )


def member_exit_estimate(conn, member):
    member_id = member["id"]
    financials = member_financials(conn, member_id)
    wallet_balance = conn.execute(
        "SELECT COALESCE(balance, 0) FROM wallet_accounts WHERE user_id = ?",
        (member_id,),
    ).fetchone()[0]
    cycle = member_cycle_status(member["date_joined"])
    today = date.today()
    final_period = today.strftime("%Y-%m")
    for accrual_year in range(cycle["cycle_start"].year, today.year + 1):
        last_month = today.month if accrual_year == today.year else 12
        for accrual_month in range(1, last_month + 1):
            materialize_interest_accruals(conn, accrual_year, accrual_month)
    accrued_interest = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM member_interest_accruals WHERE user_id = ? AND period >= ? AND period <= ?",
        (member_id, cycle["cycle_start"].strftime("%Y-%m"), final_period),
    ).fetchone()[0]
    own_loan_due = conn.execute(
        "SELECT COALESCE(SUM(balance_due), 0) FROM loans WHERE user_id = ? AND status = 'approved'",
        (member_id,),
    ).fetchone()[0]
    net_estimate = max(0, as_money(financials["savings"] + float(wallet_balance) + float(accrued_interest) - float(own_loan_due) - financials["guarantor_locked"]))
    payout_blocked = (
        not cycle["cycle_complete"]
        or float(own_loan_due) > 0
        or financials["guarantor_locked"] > 0
    )
    return {
        "savings": financials["savings"],
        "wallet_balance": as_money(wallet_balance),
        "accrued_interest": as_money(accrued_interest),
        "loan_deduction": as_money(own_loan_due),
        "guarantor_locked": financials["guarantor_locked"],
        "net_estimate": net_estimate,
        "cycle_start": cycle["cycle_start"],
        "maturity_date": cycle["maturity_date"],
        "months_remaining": cycle["months_remaining"],
        "cycle_complete": cycle["cycle_complete"],
        "payout_blocked": payout_blocked,
        "available_payout": 0 if payout_blocked else net_estimate,
        "held_for_guarantees": financials["guarantor_locked"] > 0,
    }


def transaction_date():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@app.get("/api/member/summary/<int:user_id>")
def api_member_summary(user_id):
    user = current_user()
    if user is None:
        return jsonify(status="error", message="Sign in first."), 401
    if user["must_change_password"]:
        return jsonify(status="error", message="Change your temporary password first."), 403
    if user["role"] != "admin" and not user["is_super_admin"] and user["id"] != user_id:
        return jsonify(status="error", message="You may only view your own member summary."), 403

    with database() as conn:
        user_row = conn.execute(
            "SELECT id, full_name FROM users WHERE id = ? AND role = 'member'",
            (user_id,),
        ).fetchone()
        if user_row is None:
            return jsonify(status="error", message="Member not found."), 404
        financials = member_financials(conn, user_id)
        loan_row = conn.execute(
            "SELECT COALESCE(SUM(principal_balance), 0) AS principal, COALESCE(SUM(balance_due), 0) AS balance_due FROM loans WHERE user_id = ? AND status = 'approved'",
            (user_id,),
        ).fetchone()

    active_loan = None
    if float(loan_row["principal"] or 0) > 0 or float(loan_row["balance_due"] or 0) > 0:
        active_loan = {
            "principal": as_money(loan_row["principal"]),
            "balance_due": as_money(loan_row["balance_due"]),
        }
    return jsonify({
        "status": "success",
        "user_id": user_id,
        "full_name": user_row["full_name"],
        "total_savings": financials["savings"],
        "max_loan_limit": financials["limit"],
        "remaining_loan_capacity": financials["remaining"],
        "active_loan": active_loan,
    })


@app.route("/", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("super_admin_dashboard" if current_user()["is_super_admin"] else "admin_dashboard" if session["role"] == "admin" else "member_dashboard"))
    if request.method == "POST":
        identity = request.form.get("identity", request.form.get("email", "")).strip().lower()
        password = request.form.get("password", "")
        with database() as conn:
            user = conn.execute("SELECT * FROM users WHERE lower(email) = ? OR lower(username) = ?", (identity, identity)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["role"] = "admin" if user["is_super_admin"] else user["role"]
            session["csrf_token"] = secrets.token_hex(32)
            if user["must_change_password"]:
                return redirect(url_for("change_password"))
            return redirect(url_for("super_admin_dashboard" if user["is_super_admin"] else "admin_dashboard" if user["role"] == "admin" else "member_dashboard"))
        flash("Email or password is incorrect.", "error")
    return render_template("login.html")


@app.route("/change-password", methods=["GET", "POST"])
def change_password():
    user = current_user()
    if user is None:
        flash("Sign in before changing your password.", "error")
        return redirect(url_for("login"))
    if request.method == "POST":
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")
        if not check_password_hash(user["password_hash"], current_password):
            flash("Your current or temporary password is incorrect.", "error")
        elif len(new_password) < 12:
            flash("Choose a password with at least 12 characters.", "error")
        elif new_password == current_password:
            flash("Your new password must be different from the temporary password.", "error")
        elif new_password != confirm_password:
            flash("The new passwords do not match.", "error")
        else:
            with database() as conn:
                conn.execute(
                    "UPDATE users SET password_hash = ?, must_change_password = 0 WHERE id = ?",
                    (generate_password_hash(new_password), user["id"]),
                )
            flash("Password updated. Your account is ready.", "success")
            if user["is_super_admin"]:
                return redirect(url_for("super_admin_dashboard"))
            return redirect(url_for("admin_dashboard" if user["role"] == "admin" else "member_dashboard"))
    return render_template("change_password.html", user=user)


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/member")
@require_role("member")
def member_dashboard():
    user = current_user()
    try:
        report_year = int(request.args.get("year", date.today().year))
        if report_year < 2000 or report_year > date.today().year:
            raise ValueError
    except ValueError:
        report_year = date.today().year
    with database() as conn:
        financials = member_financials(conn, user["id"])
        earnings = member_earnings_report(conn, user["id"], report_year)
        exit_estimate = member_exit_estimate(conn, user)
        loans = conn.execute(
            "SELECT * FROM loans WHERE user_id = ? ORDER BY applied_date DESC, id DESC", (user["id"],)
        ).fetchall()
        savings = conn.execute(
            "SELECT * FROM savings WHERE user_id = ? ORDER BY date DESC, id DESC", (user["id"],)
        ).fetchall()
        repayments = conn.execute(
            "SELECT r.*, l.user_id FROM loan_repayments r JOIN loans l ON l.id = r.loan_id WHERE l.user_id = ? ORDER BY r.date DESC, r.id DESC",
            (user["id"],),
        ).fetchall()
        guarantor_requests = conn.execute(
            "SELECT l.id, l.principal_amount, l.applied_date, u.full_name FROM loans l JOIN users u ON u.id = l.user_id JOIN guarantor_locks gl ON gl.loan_id = l.id WHERE gl.guarantor_id = ? AND gl.status = 'pending' ORDER BY l.applied_date",
            (user["id"],),
        ).fetchall()
        candidate_members = conn.execute(
            "SELECT id, full_name FROM users WHERE role = 'member' AND id != ? ORDER BY full_name",
            (user["id"],),
        ).fetchall()
        guarantors = []
        for candidate in candidate_members:
            candidate_finances = member_financials(conn, candidate["id"])
            if candidate_finances["savings"] > candidate_finances["guarantor_locked"]:
                guarantors.append({
                    "id": candidate["id"],
                    "full_name": candidate["full_name"],
                    "unlocked_savings": as_money(candidate_finances["savings"] - candidate_finances["guarantor_locked"]),
                })
    ledger = [{"date": row["date"], "label": row["transaction_type"].replace("_", " ").title(), "amount": row["amount"], "kind": "deposit" if row["amount"] >= 0 else "repayment"} for row in savings]
    ledger.extend({"date": row["date"], "label": f"Loan repayment · #{row['loan_id']}", "amount": row["amount_paid"], "kind": "repayment"} for row in repayments)
    ledger.sort(key=lambda item: item["date"], reverse=True)
    return render_template("member_dashboard.html", user=user, financials=financials, loans=loans, ledger=ledger, guarantor_requests=guarantor_requests, guarantors=guarantors, earnings=earnings, exit_estimate=exit_estimate, report_year=report_year, report_years=range(int(user["date_joined"][:4]), date.today().year + 1))


@app.post("/member/loans")
@require_role("member")
def apply_for_loan():
    try:
        principal = parse_positive_amount(request.form.get("principal"), "principal")
        guarantor_id = int(request.form.get("guarantor_id", ""))
        with database() as conn:
            conn.execute("BEGIN IMMEDIATE")
            financials = member_financials(conn, current_user()["id"])
            if financials["savings"] <= 0:
                raise ValueError("Build your locked savings balance before applying for a loan.")
            if principal > financials["remaining"]:
                raise ValueError(
                    f"This request exceeds your available KSh {financials['remaining']:,.2f} borrowing capacity."
                )
            if guarantor_id == current_user()["id"]:
                raise ValueError("Choose another member as guarantor.")
            guarantor = conn.execute("SELECT id FROM users WHERE id = ? AND role = 'member'", (guarantor_id,)).fetchone()
            if guarantor is None:
                raise ValueError("Choose a valid member guarantor.")
            guarantor_financials = member_financials(conn, guarantor_id)
            lock_amount = as_money(principal / 3)
            if guarantor_financials["savings"] - guarantor_financials["guarantor_locked"] < lock_amount:
                raise ValueError("The selected guarantor does not have enough uncommitted savings for this guarantee.")
            cursor = conn.execute(
                "INSERT INTO loans (user_id, principal_amount, interest_rate, duration_months, total_payable, balance_due, status, applied_date, principal_balance, interest_due, guarantor_id) VALUES (?, ?, ?, 1, 0, 0, 'pending', ?, ?, 0, ?)",
                (current_user()["id"], principal, LOAN_INTEREST_RATE, transaction_date(), principal, guarantor_id),
            )
            conn.execute("INSERT INTO guarantor_locks (loan_id, guarantor_id, amount, status, created_at) VALUES (?, ?, ?, 'pending', ?)", (cursor.lastrowid, guarantor_id, lock_amount, transaction_date()))
        flash("Loan request sent. The guarantor must consent before double approval.", "success")
    except (ValueError, sqlite3.Error) as error:
        flash(str(error) if isinstance(error, ValueError) else "The request could not be saved. Please try again.", "error")
    return redirect(url_for("member_dashboard"))


@app.post("/member/guarantees/<int:loan_id>")
@require_role("member")
def respond_to_guarantee(loan_id):
    decision = request.form.get("decision")
    if decision not in {"accept", "decline"}:
        abort(400)
    with database() as conn:
        lock = conn.execute("SELECT * FROM guarantor_locks WHERE loan_id = ? AND guarantor_id = ? AND status = 'pending'", (loan_id, current_user()["id"])).fetchone()
        if lock is None:
            flash("That guarantee request is no longer available.", "error")
        elif decision == "accept":
            financials = member_financials(conn, current_user()["id"])
            if financials["savings"] - financials["guarantor_locked"] < lock["amount"]:
                flash("Your uncommitted savings changed; this guarantee cannot be accepted.", "error")
            else:
                conn.execute("UPDATE guarantor_locks SET status = 'active' WHERE id = ?", (lock["id"],))
                flash("Guarantee accepted. The locked amount remains unavailable until settlement.", "success")
        else:
            conn.execute("UPDATE guarantor_locks SET status = 'declined' WHERE id = ?", (lock["id"],))
            flash("Guarantee declined. No savings were locked.", "success")
    return redirect(url_for("member_dashboard"))


def run_monthly_automation(period=None):
    period = period or date.today().strftime("%Y-%m")
    month_start = date.fromisoformat(f"{period}-01")
    totals = {"fines": 0}
    with database() as conn:
        conn.execute("BEGIN IMMEDIATE")
        overdue = conn.execute("SELECT id, balance_due, user_id FROM loans WHERE status = 'approved' AND cycle_due_date < ?", (month_start.isoformat(),)).fetchall()
        for loan in overdue:
            fine = as_money(float(loan["balance_due"]) * MONTHLY_FINE_RATE)
            inserted = conn.execute("INSERT OR IGNORE INTO loan_fines (loan_id, period, amount, date) VALUES (?, ?, ?, ?)", (loan["id"], period, fine, transaction_date()))
            if inserted.rowcount:
                conn.execute("UPDATE loans SET balance_due = balance_due + ? WHERE id = ?", (fine, loan["id"]))
                queue_notification(conn, loan["user_id"], f"Antiq Sacco: default fine KSh {fine:,.2f} applied to loan #{loan['id']} for {period}.")
                totals["fines"] += 1
    return {"period": period, **totals}


def start_automation_scheduler():
    from apscheduler.schedulers.background import BackgroundScheduler

    scheduler = BackgroundScheduler(timezone=os.environ.get("TZ", "Africa/Nairobi"))
    scheduler.add_job(run_monthly_automation, "cron", day=1, hour=1, minute=0, id="monthly-sacco-automation", replace_existing=True, max_instances=1)
    scheduler.start()
    return scheduler


@app.get("/staff")
@require_role("admin")
def admin_dashboard():
    report_period = request.args.get("period", date.today().strftime("%Y-%m"))
    try:
        report_month = date.fromisoformat(f"{report_period}-01")
    except ValueError:
        report_month = date.today().replace(day=1)
        report_period = report_month.strftime("%Y-%m")
    report_end = add_months(report_month).isoformat()
    with database() as conn:
        capital = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM savings").fetchone()[0]
        outstanding = conn.execute("SELECT COALESCE(SUM(balance_due), 0) FROM loans WHERE status = 'approved'").fetchone()[0]
        pending_count = conn.execute("SELECT COUNT(*) FROM loans WHERE status = 'pending'").fetchone()[0]
        members = conn.execute("SELECT id, full_name, email, phone, date_joined FROM users WHERE role = 'member' ORDER BY id").fetchall()
        pending = conn.execute(
            "SELECT l.*, u.full_name, u.email, g.full_name AS guarantor_name, COALESCE((SELECT SUM(s.amount) FROM savings s WHERE s.user_id = l.user_id), 0) AS savings_total, COALESCE((SELECT COUNT(*) FROM loan_approvals la WHERE la.loan_id = l.id AND la.decision = 'approved'), 0) AS approval_count, COALESCE((SELECT gl.status FROM guarantor_locks gl WHERE gl.loan_id = l.id), 'missing') AS guarantor_status FROM loans l JOIN users u ON u.id = l.user_id LEFT JOIN users g ON g.id = l.guarantor_id WHERE l.status = 'pending' ORDER BY l.applied_date, l.id"
        ).fetchall()
        interest_profit = conn.execute("SELECT COALESCE(SUM(interest_paid), 0) FROM loan_repayments").fetchone()[0]
        fine_profit = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM loan_fines").fetchone()[0]
        monthly_collection = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM savings WHERE substr(date, 1, 7) = ?", (date.today().strftime("%Y-%m"),)).fetchone()[0]
        annual_collection = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM savings WHERE substr(date, 1, 4) = ?", (str(date.today().year),)).fetchone()[0]
        wallet_total = conn.execute("SELECT COALESCE(SUM(balance), 0) FROM wallet_accounts").fetchone()[0]
        report_interest = conn.execute("SELECT COALESCE(SUM(interest_paid), 0) FROM loan_repayments WHERE date >= ? AND date < ?", (report_month.isoformat(), report_end)).fetchone()[0]
        report_fines = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM loan_fines WHERE date >= ? AND date < ?", (report_month.isoformat(), report_end)).fetchone()[0]
        report_members = conn.execute("SELECT u.id, u.full_name, COALESCE((SELECT SUM(s.amount) FROM savings s WHERE s.user_id = u.id AND s.date < ?), 0) AS savings FROM users u WHERE u.role = 'member' ORDER BY u.id", (report_end,)).fetchall()
        report_total_savings = sum(float(row["savings"]) for row in report_members)
        if report_month <= date.today().replace(day=1):
            materialize_interest_accruals(conn, report_month.year, report_month.month)
        accrual_rows = conn.execute("SELECT user_id, interest_pool, savings_basis, total_savings_basis, amount, share_percent FROM member_interest_accruals WHERE period = ?", (report_period,)).fetchall()
        accrual_by_member = {row["user_id"]: row for row in accrual_rows}
        member_monthly_report = [{"id": row["id"], "name": row["full_name"], "savings": as_money(accrual_by_member[row["id"]]["savings_basis"]) if row["id"] in accrual_by_member else 0, "total_savings_basis": as_money(accrual_by_member[row["id"]]["total_savings_basis"]) if row["id"] in accrual_by_member else 0, "interest_pool": as_money(accrual_by_member[row["id"]]["interest_pool"]) if row["id"] in accrual_by_member else 0, "share_percent": round(float(accrual_by_member[row["id"]]["share_percent"]) * 100, 2) if row["id"] in accrual_by_member else 0, "earned_interest": as_money(accrual_by_member[row["id"]]["amount"]) if row["id"] in accrual_by_member else 0} for row in report_members]
        report_accrued = as_money(sum(item["earned_interest"] for item in member_monthly_report))
        loan_records = conn.execute("SELECT l.*, u.full_name FROM loans l JOIN users u ON u.id = l.user_id WHERE l.status IN ('pending', 'approved') ORDER BY l.applied_date DESC, l.id DESC").fetchall()
    return render_template("admin_dashboard.html", capital=as_money(capital), outstanding=as_money(outstanding), pending_count=pending_count, members=members, pending=pending, interest_profit=as_money(interest_profit), fine_profit=as_money(fine_profit), monthly_collection=as_money(monthly_collection), annual_collection=as_money(annual_collection), wallet_total=as_money(wallet_total), report_period=report_period, report_interest=as_money(report_interest), report_accrued=report_accrued, member_monthly_report=member_monthly_report, loan_records=loan_records)


@app.get("/super-admin")
@require_role("admin")
def super_admin_dashboard():
    if not current_user()["is_super_admin"]:
        abort(403)
    with database() as conn:
        total_members = conn.execute("SELECT COUNT(*) FROM users WHERE role = 'member'").fetchone()[0]
        staff_accounts = conn.execute("SELECT id, username, full_name, email, date_joined FROM users WHERE role = 'admin' ORDER BY id").fetchall()
        monthly_savings = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM savings WHERE substr(date, 1, 7) = ?", (date.today().strftime("%Y-%m"),)).fetchone()[0]
        capital = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM savings").fetchone()[0]
        outstanding = conn.execute("SELECT COALESCE(SUM(balance_due), 0) FROM loans WHERE status = 'approved'").fetchone()[0]
        pending_loans = conn.execute("SELECT COUNT(*) FROM loans WHERE status = 'pending'").fetchone()[0]
    return render_template("super_admin.html", total_members=total_members, staff_accounts=staff_accounts, monthly_savings=as_money(monthly_savings), capital=as_money(capital), outstanding=as_money(outstanding), pending_loans=pending_loans)


@app.post("/super-admin/staff/register")
@require_role("admin")
def register_staff():
    if not current_user()["is_super_admin"]:
        abort(403)
    username = request.form.get("username", "").strip()
    full_name = request.form.get("full_name", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    try:
        if len(username) < 3 or not username.replace("_", "").isalnum():
            raise ValueError("Username must be at least 3 letters or numbers.")
        if len(full_name) < 3 or "@" not in email:
            raise ValueError("Enter the staff member's name and a valid email.")
        if len(password) < 12:
            raise ValueError("Staff passwords must be at least 12 characters.")
        with database() as conn:
            conn.execute(
                "INSERT INTO users (username, email, password_hash, full_name, role, date_joined) VALUES (?, ?, ?, ?, 'admin', ?)",
                (username, email, generate_password_hash(password), full_name, transaction_date()),
            )
        flash(f"Staff account created for {full_name}.", "success")
    except ValueError as error:
        flash(str(error), "error")
    except sqlite3.IntegrityError:
        flash("That username or email is already in use.", "error")
    return redirect(url_for("super_admin_dashboard"))


@app.post("/staff/members/register")
@require_role("admin")
def register_member():
    full_name = request.form.get("full_name", "").strip()
    email = request.form.get("email", "").strip().lower()
    phone = request.form.get("phone", "").strip()
    temporary_password = request.form.get("temporary_password", "")
    try:
        if len(full_name) < 3:
            raise ValueError("Enter the member's full name.")
        if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
            raise ValueError("Enter a valid member email address.")
        if len(temporary_password) < 12:
            raise ValueError("Set a temporary password with at least 12 characters.")
        with database() as conn:
            if conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
                raise ValueError("That email address is already registered.")
            now = transaction_date()
            cursor = conn.execute(
                "INSERT INTO users (email, password_hash, full_name, phone, role, must_change_password, date_joined, monthly_contribution) VALUES (?, ?, ?, ?, 'member', 1, ?, 5000)",
                (email, generate_password_hash(temporary_password), full_name, phone or None, now),
            )
            conn.execute("INSERT INTO wallet_accounts (user_id, balance, updated_at) VALUES (?, 0, ?)", (cursor.lastrowid, now))
        flash(f"Member account created for {full_name}. Give them the temporary password securely; they must change it at first sign-in.", "success")
    except (ValueError, sqlite3.IntegrityError) as error:
        flash(str(error) if isinstance(error, ValueError) else "That email address is already registered.", "error")
    return redirect(url_for("admin_dashboard") + "#members")


@app.get("/staff/members/<int:member_id>")
@require_role("admin")
def member_detail(member_id):
    with database() as conn:
        member = conn.execute("SELECT id, full_name, email, phone, date_joined FROM users WHERE id = ? AND role = 'member'", (member_id,)).fetchone()
        if member is None:
            abort(404)
        financials = member_financials(conn, member_id)
        savings = conn.execute("SELECT date, amount, transaction_type AS label FROM savings WHERE user_id = ? ORDER BY date DESC", (member_id,)).fetchall()
        loans = conn.execute("SELECT id, principal_amount, balance_due, status, applied_date FROM loans WHERE user_id = ? ORDER BY applied_date DESC", (member_id,)).fetchall()
        adjustments = conn.execute("SELECT a.loan_id, a.reason, a.old_values, a.new_values, a.adjusted_at, u.full_name AS adjusted_by_name FROM loan_adjustments a JOIN loans l ON l.id = a.loan_id JOIN users u ON u.id = a.adjusted_by WHERE l.user_id = ? ORDER BY a.adjusted_at DESC, a.id DESC", (member_id,)).fetchall()
    audit = [{**dict(row), "old_values": json.loads(row["old_values"]), "new_values": json.loads(row["new_values"])} for row in adjustments]
    return jsonify(member=dict(member), financials=financials, savings=[dict(row) for row in savings], loans=[dict(row) for row in loans], loan_adjustments=audit)


@app.post("/staff/deposits")
@require_role("admin")
def post_deposit():
    try:
        member_id = int(request.form.get("member_id", ""))
        amount = parse_positive_amount(request.form.get("amount"), "deposit amount")
        reference = request.form.get("reference", "").strip()
        with database() as conn:
            member = conn.execute("SELECT id FROM users WHERE id = ? AND role = 'member'", (member_id,)).fetchone()
            if member is None:
                raise ValueError("Enter a valid member ID.")
            if reference and conn.execute("SELECT 1 FROM savings WHERE reference = ? UNION SELECT 1 FROM loan_repayments WHERE reference = ?", (reference, reference)).fetchone():
                raise ValueError("That ledger reference has already been used.")
            conn.execute("INSERT INTO savings (user_id, date, amount, transaction_type, recorded_by, reference) VALUES (?, ?, ?, 'manual_deposit', ?, ?)", (member_id, transaction_date(), amount, current_user()["id"], reference or None))
            queue_notification(conn, member_id, f"Antiq Sacco: manual deposit of KSh {amount:,.2f} recorded. New locked savings KSh {member_financials(conn, member_id)['savings']:,.2f}.")
        flash(f"Manual deposit of KSh {amount:,.2f} posted to member #{member_id}.", "success")
    except (ValueError, sqlite3.Error) as error:
        flash(str(error) if isinstance(error, ValueError) else "The deposit could not be posted.", "error")
    return redirect(url_for("admin_dashboard"))


@app.post("/staff/loans/<int:loan_id>/review")
@require_role("admin")
def review_loan(loan_id):
    decision = request.form.get("decision")
    if decision not in {"approved", "rejected"}:
        abort(400)
    with database() as conn:
        conn.execute("BEGIN IMMEDIATE")
        loan = conn.execute("SELECT * FROM loans WHERE id = ? AND status = 'pending'", (loan_id,)).fetchone()
        if loan is None:
            flash("That request has already been reviewed.", "error")
            return redirect(url_for("admin_dashboard"))
        if conn.execute("SELECT 1 FROM loan_approvals WHERE loan_id = ? AND official_id = ?", (loan_id, current_user()["id"])).fetchone():
            flash("A different elected official must provide the second signature.", "error")
            return redirect(url_for("admin_dashboard"))
        conn.execute("INSERT INTO loan_approvals (loan_id, official_id, decision, date) VALUES (?, ?, ?, ?)", (loan_id, current_user()["id"], decision, transaction_date()))
        if decision == "rejected":
            conn.execute("UPDATE loans SET status = 'rejected', reviewed_by = ? WHERE id = ?", (current_user()["id"], loan_id))
            conn.execute("UPDATE guarantor_locks SET status = 'released' WHERE loan_id = ?", (loan_id,))
            flash("Loan request rejected and guarantor lock released.", "success")
            return redirect(url_for("admin_dashboard"))
        approvals = conn.execute("SELECT COUNT(*) FROM loan_approvals WHERE loan_id = ? AND decision = 'approved'", (loan_id,)).fetchone()[0]
        if approvals < 2:
            flash("First approval recorded. A second elected official must sign before disbursement.", "success")
            return redirect(url_for("admin_dashboard"))
        financials = member_financials(conn, loan["user_id"])
        other_committed = financials["committed_principal"] - float(loan["principal_amount"])
        if loan["principal_amount"] > max(0, financials["limit"] - other_committed):
            conn.execute("DELETE FROM loan_approvals WHERE loan_id = ? AND decision = 'approved'", (loan_id,))
            flash("Approval blocked: the member's 3× borrowing capacity changed.", "error")
            return redirect(url_for("admin_dashboard"))
        guarantee = conn.execute("SELECT status FROM guarantor_locks WHERE loan_id = ?", (loan_id,)).fetchone()
        if guarantee is None or guarantee["status"] != "active":
            conn.execute("DELETE FROM loan_approvals WHERE loan_id = ? AND decision = 'approved'", (loan_id,))
            flash("Approval blocked: guarantor consent and an active savings lock are required.", "error")
            return redirect(url_for("admin_dashboard"))
        principal = as_money(loan["principal_amount"])
        interest = as_money(principal * (LOAN_INTEREST_RATE / 100))
        due = add_months(date.today()).isoformat()
        conn.execute("UPDATE loans SET status = 'approved', interest_rate = ?, duration_months = 1, total_payable = ?, balance_due = ?, principal_balance = ?, interest_due = ?, cycle_due_date = ?, reviewed_by = ? WHERE id = ?", (LOAN_INTEREST_RATE, principal + interest, principal + interest, principal, interest, due, current_user()["id"], loan_id))
        queue_notification(conn, loan["user_id"], f"Antiq Sacco: loan #{loan_id} approved. Principal KSh {principal:,.2f}; 20% cycle charge KSh {interest:,.2f}; due {due}.")
    flash("Second signature recorded. Loan approved for disbursement.", "success")
    return redirect(url_for("admin_dashboard"))


@app.post("/staff/repayments")
@require_role("admin")
def post_repayment():
    try:
        loan_id = int(request.form.get("loan_id", ""))
        amount = parse_positive_amount(request.form.get("amount"), "repayment amount")
        payment_type = request.form.get("payment_type", "full")
        reference = request.form.get("reference", "").strip()
        with database() as conn:
            conn.execute("BEGIN IMMEDIATE")
            loan = conn.execute("SELECT * FROM loans WHERE id = ? AND status = 'approved'", (loan_id,)).fetchone()
            if loan is None:
                raise ValueError("Enter an approved, active loan ID.")
            if reference and conn.execute("SELECT 1 FROM savings WHERE reference = ? UNION SELECT 1 FROM loan_repayments WHERE reference = ?", (reference, reference)).fetchone():
                raise ValueError("That ledger reference has already been used.")
            apply_loan_payment(conn, loan, amount, payment_type, current_user()["id"], reference)
        flash(f"Manual repayment of KSh {amount:,.2f} posted to loan #{loan_id}.", "success")
    except (ValueError, sqlite3.Error) as error:
        flash(str(error) if isinstance(error, ValueError) else "The repayment could not be posted.", "error")
    return redirect(url_for("admin_dashboard"))


@app.post("/staff/loans/<int:loan_id>/adjust")
@require_role("admin")
def adjust_loan_record(loan_id):
    reason = request.form.get("reason", "").strip()
    if len(reason) < 8:
        flash("Enter a correction reason with at least 8 characters.", "error")
        return redirect(url_for("admin_dashboard") + "#loan-corrections")
    fields = ("principal_amount", "interest_rate", "principal_balance", "interest_due", "total_payable", "balance_due")
    try:
        corrected = {}
        for field in fields:
            raw_value = request.form.get(field, "").strip()
            value = float(raw_value)
            if value < 0 or value != value or value == float("inf"):
                raise ValueError(f"{field.replace('_', ' ').title()} must be a non-negative number.")
            corrected[field] = as_money(value)
        if corrected["interest_rate"] > 1000:
            raise ValueError("Interest rate cannot exceed 1000%.")
        with database() as conn:
            conn.execute("BEGIN IMMEDIATE")
            loan = conn.execute("SELECT * FROM loans WHERE id = ? AND status IN ('pending', 'approved')", (loan_id,)).fetchone()
            if loan is None:
                raise ValueError("Only a pending or active loan can be corrected here.")
            old_values = {field: as_money(loan[field]) for field in fields}
            conn.execute(
                "UPDATE loans SET principal_amount = ?, interest_rate = ?, principal_balance = ?, interest_due = ?, total_payable = ?, balance_due = ? WHERE id = ?",
                (*[corrected[field] for field in fields], loan_id),
            )
            conn.execute(
                "INSERT INTO loan_adjustments (loan_id, adjusted_by, reason, old_values, new_values, adjusted_at) VALUES (?, ?, ?, ?, ?, ?)",
                (loan_id, current_user()["id"], reason, json.dumps(old_values, sort_keys=True), json.dumps(corrected, sort_keys=True), transaction_date()),
            )
        flash(f"Loan #{loan_id} corrected and audit history recorded.", "success")
    except (ValueError, sqlite3.Error) as error:
        message = str(error) if isinstance(error, ValueError) else "The loan correction could not be saved."
        flash(message, "error")
    return redirect(url_for("admin_dashboard") + "#loan-corrections")


def apply_loan_payment(conn, loan, amount, payment_type, recorded_by=None, reference=None):
    if payment_type not in {"full", "rollover"}:
        raise ValueError("Choose full repayment or rollover.")
    principal = as_money(loan["principal_balance"] or loan["principal_amount"])
    interest = as_money(loan["interest_due"])
    due = as_money(loan["balance_due"])
    if payment_type == "full":
        if amount != due:
            raise ValueError(f"Full settlement must equal KSh {due:,.2f}.")
        interest_paid = interest
        principal_paid = as_money(amount - interest_paid)
        remaining_principal = 0
        remaining_due = 0
    else:
        minimum_payment = as_money(interest + principal * 0.5)
        if amount < minimum_payment:
            raise ValueError(f"Rollover requires at least KSh {minimum_payment:,.2f}: cycle interest plus 50% principal.")
        if amount >= due:
            raise ValueError("Use full repayment when paying the entire balance.")
        interest_paid = interest
        principal_paid = as_money(amount - interest_paid)
        remaining_principal = as_money(principal - principal_paid)
        if remaining_principal <= 0:
            raise ValueError("The rollover must leave principal outstanding.")
        next_interest = as_money(remaining_principal * LOAN_INTEREST_RATE / 100)
        remaining_due = as_money(remaining_principal + next_interest)
        next_due = add_months(date.today()).isoformat()
        conn.execute("INSERT INTO loan_rollovers (loan_id, date, interest_paid, principal_paid, principal_remaining, new_due_date, recorded_by) VALUES (?, ?, ?, ?, ?, ?, ?)", (loan["id"], transaction_date(), interest_paid, principal_paid, remaining_principal, next_due, recorded_by))
        conn.execute("UPDATE loans SET principal_balance = ?, interest_due = ?, balance_due = ?, total_payable = ?, cycle_due_date = ?, rollover_count = rollover_count + 1 WHERE id = ?", (remaining_principal, next_interest, remaining_due, remaining_due, next_due, loan["id"]))
    conn.execute("INSERT INTO loan_repayments (loan_id, date, amount_paid, recorded_by, interest_paid, principal_paid, payment_type, reference) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (loan["id"], transaction_date(), amount, recorded_by, interest_paid, principal_paid, payment_type, reference))
    if payment_type == "full":
        conn.execute("UPDATE loans SET principal_balance = 0, interest_due = 0, balance_due = 0, status = 'fully_paid' WHERE id = ?", (loan["id"],))
        conn.execute("UPDATE guarantor_locks SET status = 'released' WHERE loan_id = ?", (loan["id"],))
    queue_notification(conn, loan["user_id"], f"Antiq Sacco: manual KSh {amount:,.2f} {payment_type} repayment recorded for loan #{loan['id']}. Remaining balance KSh {remaining_due:,.2f}.")


@app.template_filter("ksh")
def format_ksh(value):
    return f"KSh {float(value or 0):,.2f}"


@app.template_filter("date_label")
def format_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").strftime("%d %b %Y")
    except (TypeError, ValueError):
        return value


init_db()

if __name__ == "__main__":
    scheduler = start_automation_scheduler()
    try:
        app.run(debug=False, use_reloader=False)
    finally:
        scheduler.shutdown(wait=False)
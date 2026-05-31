import logging
from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from app.extensions import db
from app.models import BrokerAccount, BrokerPosition, BrokerOperation
from app.services.sync_service import sync_user_tinvest
from app.services.accounting_service import calculate_xirr, process_fifo_sales
from decimal import Decimal

logger = logging.getLogger(__name__)
tinvest_bp = Blueprint("tinvest", __name__)

@tinvest_bp.route("/api/tinvest/sync", methods=["POST"])
@login_required
def sync_tinvest():
    """Trigger manual sync with T-Invest API."""
    try:
        sync_user_tinvest(current_user.id)
        return jsonify({"status": "success", "message": "Synchronized successfully"})
    except Exception as e:
        logger.error(f"Sync error: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500

@tinvest_bp.route("/api/tinvest/portfolio", methods=["GET"])
@login_required
def get_tinvest_portfolio():
    """Get aggregated portfolio and individual account portfolios."""
    accounts = BrokerAccount.query.filter_by(user_id=current_user.id).all()
    
    portfolios = []
    total_value = Decimal('0.0')
    all_operations = []

    for acc in accounts:
        positions = BrokerPosition.query.filter_by(account_id=acc.id).all()
        ops = BrokerOperation.query.filter_by(account_id=acc.id).order_by(BrokerOperation.date).all()
        
        all_operations.extend(ops)
        
        acc_value = Decimal('0.0')
        pos_list = []
        
        # Calculate XIRR for each position
        for p in positions:
            p_ops = [op for op in ops if op.figi == p.figi]
            cashflows = []
            for op in p_ops:
                if op.type == "BUY":
                    cashflows.append((op.date.date(), -float(op.payment + (op.commission or 0))))
                elif op.type in ("SELL", "COUPON", "AMORTIZATION"):
                    cashflows.append((op.date.date(), float(op.payment - (op.commission or 0))))
            
            # Current value is a positive cashflow for XIRR snapshot
            cv = float(p.quantity * p.current_price)
            if cv > 0:
                import datetime
                cashflows.append((datetime.date.today(), cv))
            
            xirr = calculate_xirr(cashflows) if cashflows else 0.0
            
            pos_list.append({
                "figi": p.figi,
                "ticker": p.ticker,
                "name": p.name,
                "quantity": float(p.quantity),
                "average_price": float(p.average_price),
                "current_price": float(p.current_price),
                "current_value": float(p.quantity * p.current_price),
                "expected_yield": float(p.expected_yield or 0.0),
                "xirr": round(xirr * 100, 2),
                "currency": p.currency
            })
            acc_value += p.quantity * p.current_price
            
        total_value += acc_value
        
        # Account-level XIRR
        acc_cashflows = []
        for op in ops:
            if op.type == "INPUT":
                acc_cashflows.append((op.date.date(), -float(op.payment)))
            elif op.type == "OUTPUT":
                acc_cashflows.append((op.date.date(), float(op.payment)))
        if float(acc_value) > 0:
            import datetime
            acc_cashflows.append((datetime.date.today(), float(acc_value)))
            
        acc_xirr = calculate_xirr(acc_cashflows) if acc_cashflows else 0.0
        
        portfolios.append({
            "account_id": acc.id,
            "name": acc.name,
            "type": acc.type,
            "status": acc.status,
            "total_value": float(acc_value),
            "xirr": round(acc_xirr * 100, 2),
            "positions": pos_list
        })
        
    return jsonify({
        "status": "success",
        "data": {
            "total_value": float(total_value),
            "portfolios": portfolios
        }
    })

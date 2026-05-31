from datetime import datetime, date
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)

def money_value_to_float(mv: dict) -> float:
    if not mv:
        return 0.0
    units = int(mv.get("units") or 0)
    nano = int(mv.get("nano") or 0)
    return float(units) + float(nano) / 1_000_000_000

def _xirr_npv(rate, cashflows):
    """
    Calculate Net Present Value for a given rate and cashflows.
    Cashflows is a list of tuples (date, amount).
    """
    if rate <= -1.0:
        return float('inf')
    t0 = cashflows[0][0]
    npv = 0.0
    for t, amt in cashflows:
        # Years since t0
        years = (t - t0).days / 365.0
        npv += amt / ((1.0 + rate) ** years)
    return npv

def calculate_xirr(cashflows: list) -> float:
    """
    Calculate the Extended Internal Rate of Return (XIRR).
    cashflows: list of tuples (date: datetime.date, amount: float).
    Returns XIRR as a decimal (e.g. 0.15 for 15%).
    Returns 0.0 if calculation fails or cashflows are invalid.
    """
    if not cashflows:
        return 0.0

    # Ensure cashflows are sorted by date
    cashflows = sorted(cashflows, key=lambda x: x[0])
    
    amounts = [cf[1] for cf in cashflows]
    if min(amounts) >= 0 or max(amounts) <= 0:
        # XIRR requires at least one positive and one negative cashflow
        return 0.0

    # Bisection method
    low = -0.9999
    high = 100.0
    
    for _ in range(100):
        guess = (low + high) / 2.0
        npv = _xirr_npv(guess, cashflows)
        if abs(npv) < 1e-5:
            return guess
        if npv > 0:
            low = guess
        else:
            high = guess

    return (low + high) / 2.0

def process_fifo_sales(operations: list) -> list:
    """
    Calculate realized P&L based on FIFO queue of operations.
    Operations must be sorted by date.
    Returns a list of tax reports for each SELL operation.
    """
    queue = []
    reports = []
    
    for op in operations:
        op_type = op.type
        qty = float(op.quantity)
        price = float(op.price)
        payment = float(op.payment)
        comm = float(op.commission or 0.0)
        
        if op_type == "BUY":
            queue.append({
                "date": op.date,
                "qty": qty,
                "price": price,
                "payment": payment,
                "comm": comm,
                "nkd": float(op.nkd or 0.0)
            })
        elif op_type == "SELL":
            remaining_to_sell = qty
            sell_payment_allocated = payment
            sell_comm_allocated = comm
            
            cost_basis = 0.0
            
            while remaining_to_sell > 0 and queue:
                oldest_buy = queue[0]
                sell_qty = min(remaining_to_sell, oldest_buy["qty"])
                
                # Pro-rata cost basis
                buy_ratio = sell_qty / oldest_buy["qty"]
                cost_basis += (oldest_buy["payment"] + oldest_buy["comm"]) * buy_ratio
                
                oldest_buy["qty"] -= sell_qty
                oldest_buy["payment"] -= oldest_buy["payment"] * buy_ratio
                oldest_buy["comm"] -= oldest_buy["comm"] * buy_ratio
                
                if oldest_buy["qty"] <= 1e-6:
                    queue.pop(0)
                    
                remaining_to_sell -= sell_qty
            
            pnl = sell_payment_allocated - sell_comm_allocated - cost_basis
            reports.append({
                "sell_date": op.date,
                "figi": op.figi,
                "qty_sold": qty,
                "pnl": pnl,
                "cost_basis": cost_basis
            })
            
    return reports

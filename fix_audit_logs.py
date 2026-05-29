from app.app import create_app
from app.extensions import db
from app.models import AuditLog

app = create_app()
with app.app_context():
    logs = AuditLog.query.filter(AuditLog.action.in_(['portfolio_import', 'portfolio_add_bond', 'bond_add', 'bond_sell', 'bond_delete', 'portfolio_reset'])).all()
    count = 0
    for log in logs:
        if log.category != 'portfolio':
            log.category = 'portfolio'
            count += 1
    db.session.commit()
    print(f"Updated {count} logs to portfolio category.")

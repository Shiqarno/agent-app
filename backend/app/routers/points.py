from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import reward_operations
from app.db import get_db
from app.identity import get_current_user
from app.models import PointTransaction, User
from app.schemas import BalanceResponse, PointTransactionResponse

router = APIRouter(prefix="/api/points", tags=["points"])


@router.get("/balance", response_model=BalanceResponse)
def get_balance(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> BalanceResponse:
    # Same COALESCE(SUM(amount)) query as reward_operations.get_balance
    # (Issue #26) -- reused directly rather than duplicated (Issue #31).
    return BalanceResponse(balance=reward_operations.get_balance(db, user.id))


@router.get("/history", response_model=list[PointTransactionResponse])
def get_history(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[PointTransaction]:
    stmt = (
        select(PointTransaction)
        .where(PointTransaction.user_id == user.id)
        .order_by(PointTransaction.created_at.desc(), PointTransaction.id.desc())
    )
    return list(db.scalars(stmt))

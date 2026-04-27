from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/db")
async def health_db(session: AsyncSession = Depends(get_db_session)) -> dict[str, str]:
    result = await session.execute(text("SELECT 1"))
    value = result.scalar_one()
    return {"status": "ok" if value == 1 else "error", "db": "reachable"}

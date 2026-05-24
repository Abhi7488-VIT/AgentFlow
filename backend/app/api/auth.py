"""Auth API routes — placeholder for future JWT login/signup."""

from fastapi import APIRouter

router = APIRouter()


@router.post("/login")
async def login():
    return {"message": "Auth not yet implemented. Using demo user."}


@router.post("/register")
async def register():
    return {"message": "Auth not yet implemented. Using demo user."}

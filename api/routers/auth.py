from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from typing import Optional

from api.auth import Role, UserContext, get_current_user, require_roles
from api.auth_db import create_user, authenticate_user, create_session_token, list_users, update_user_role

router = APIRouter(prefix="/auth", tags=["auth"])


class SignupRequest(BaseModel):
    username: str
    email: str
    password: str
    role: Role = Role.TECHNICIAN


class LoginRequest(BaseModel):
    username: str
    password: str


class RoleUpdateRequest(BaseModel):
    role: Role


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


@router.post("/signup", response_model=AuthResponse)
async def signup(request: SignupRequest):
    if len(request.username.strip()) < 3:
        raise HTTPException(status_code=400, detail="Username must be at least 3 characters long")
    if len(request.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters long")

    try:
        user = create_user(
            username=request.username.strip(),
            email=request.email.strip(),
            password=request.password,
            role=Role(request.role),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    token = create_session_token(user)
    return AuthResponse(access_token=token, user=user)


@router.post("/login", response_model=AuthResponse)
async def login(request: LoginRequest):
    user = authenticate_user(request.username.strip(), request.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = create_session_token(user)
    return AuthResponse(access_token=token, user=user)


@router.get("/me")
async def me(current_user: UserContext = Depends(get_current_user)):
    return {
        "identity": current_user.identity,
        "role": current_user.role.value,
        "tenant_id": current_user.tenant_id,
    }


@router.get("/users")
async def get_users(_user: UserContext = Depends(require_roles(Role.ADMIN))):
    """List all registered users. Admin only."""
    return {"users": list_users()}


@router.patch("/users/{user_id}/role")
async def change_user_role(
    user_id: str,
    request: RoleUpdateRequest,
    _user: UserContext = Depends(require_roles(Role.ADMIN))
):
    """Update a user's role. Admin only."""
    if not update_user_role(user_id, request.role):
        raise HTTPException(status_code=404, detail="User not found")
    return {"status": "success", "message": f"User role updated to {request.role.value}"}


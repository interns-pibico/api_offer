"""Auth endpoints — register, login, me."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordRequestFormStrict
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy import select
from fastapi import Depends

from src.core.dependencies import CurrentUser, DbSession
from src.core.security import create_access_token, hash_password, verify_password
from src.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


# -- Schemas --

class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 3:
            raise ValueError("El nombre de usuario debe tener al menos 3 caracteres")
        if len(v) > 100:
            raise ValueError("El nombre de usuario es demasiado largo")
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("La contraseña debe tener al menos 6 caracteres")
        return v

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        v = v.strip().lower()
        if "@" not in v or "." not in v.split("@")[-1]:
            raise ValueError("Email inválido")
        return v


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None


# -- Endpoints --

@router.post("/register", response_model=TokenResponse, summary="Register new user")
async def register(body: RegisterRequest, db: DbSession):
    # Check duplicate username
    existing = await db.execute(select(User).where(User.username == body.username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="El nombre de usuario ya existe")

    # Check duplicate email
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="El email ya está registrado")

    user = User(
        username=body.username,
        email=body.email,
        hashed_password=hash_password(body.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token(user.id)
    logger.info("User registered: %s (id=%d)", user.username, user.id)
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse, summary="Login with username+password")
async def login(form: OAuth2PasswordRequestForm = Depends(), db: DbSession = None):
    # OAuth2 form uses 'username' field
    result = await db.execute(select(User).where(User.username == form.username))
    user = result.scalar_one_or_none()

    if not user or not verify_password(form.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Credenciales inválidas")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Cuenta desactivada")

    # Update last login
    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()

    token = create_access_token(user.id)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserResponse, summary="Get current user info")
async def me(user: CurrentUser):
    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        is_active=user.is_active,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )


# -- Account management --

class UpdateUsernameRequest(BaseModel):
    username: str

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 3:
            raise ValueError("El nombre de usuario debe tener al menos 3 caracteres")
        if len(v) > 100:
            raise ValueError("El nombre de usuario es demasiado largo")
        return v


class UpdatePasswordRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("La nueva contraseña debe tener al menos 6 caracteres")
        return v


class DeleteAccountRequest(BaseModel):
    password: str


@router.put("/me/username", response_model=UserResponse, summary="Change username")
async def update_username(body: UpdateUsernameRequest, user: CurrentUser, db: DbSession):
    if body.username == user.username:
        raise HTTPException(status_code=400, detail="El nombre de usuario es el mismo")
    existing = await db.execute(select(User).where(User.username == body.username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="El nombre de usuario ya existe")
    user.username = body.username
    await db.commit()
    await db.refresh(user)
    logger.info("User %d changed username to %s", user.id, user.username)
    return UserResponse(
        id=user.id, username=user.username, email=user.email,
        is_active=user.is_active, created_at=user.created_at, last_login_at=user.last_login_at,
    )


@router.put("/me/password", summary="Change password")
async def update_password(body: UpdatePasswordRequest, user: CurrentUser, db: DbSession):
    if not verify_password(body.current_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="La contraseña actual es incorrecta")
    user.hashed_password = hash_password(body.new_password)
    await db.commit()
    logger.info("User %d changed password", user.id)
    return {"detail": "Contraseña actualizada"}


@router.delete("/me", summary="Delete account and all data")
async def delete_account(body: DeleteAccountRequest, user: CurrentUser, db: DbSession):
    if not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="La contraseña es incorrecta")
    # Delete shopping lists + items (cascade should handle items)
    from src.models.shopping_list import ShoppingList
    from sqlalchemy import delete
    await db.execute(delete(ShoppingList).where(ShoppingList.user_id == user.id))
    await db.delete(user)
    await db.commit()
    logger.info("User %d deleted account", user.id)
    return {"detail": "Cuenta eliminada"}

"""Shopping lists CRUD — persistent user lists (requires auth)."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from src.core.dependencies import CurrentUser, DbSession
from src.models.shopping_list import ShoppingList, ShoppingListItem

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/lists", tags=["lists"])

MAX_LISTS_PER_USER = 4
MAX_ITEMS_PER_LIST = 30


# -- Schemas --

class ListItemCreate(BaseModel):
    ingredient_name: str
    quantity: str | None = None
    unit: str | None = None


class ListCreate(BaseModel):
    name: str
    description: str | None = None
    items: list[ListItemCreate] = []

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 1:
            raise ValueError("El nombre no puede estar vacío")
        if len(v) > 100:
            raise ValueError("El nombre es demasiado largo (max 100)")
        return v


class ListUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class ListItemResponse(BaseModel):
    id: int
    ingredient_name: str
    quantity: str | None
    unit: str | None


class ListResponse(BaseModel):
    id: int
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime
    item_count: int


class ListDetailResponse(BaseModel):
    id: int
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime
    items: list[ListItemResponse]


# -- Endpoints --

@router.get("", response_model=list[ListResponse], summary="Get user's shopping lists")
async def get_lists(user: CurrentUser, db: DbSession):
    result = await db.execute(
        select(ShoppingList)
        .where(ShoppingList.user_id == user.id)
        .options(selectinload(ShoppingList.items))
        .order_by(ShoppingList.updated_at.desc())
    )
    lists = result.scalars().all()
    return [
        ListResponse(
            id=sl.id,
            name=sl.name,
            description=sl.description,
            created_at=sl.created_at,
            updated_at=sl.updated_at,
            item_count=len(sl.items),
        )
        for sl in lists
    ]


@router.post("", response_model=ListDetailResponse, status_code=201, summary="Create shopping list")
async def create_list(body: ListCreate, user: CurrentUser, db: DbSession):
    # Check limit
    count_result = await db.execute(
        select(func.count()).select_from(ShoppingList).where(ShoppingList.user_id == user.id)
    )
    count = count_result.scalar()
    if count >= MAX_LISTS_PER_USER:
        raise HTTPException(
            status_code=400,
            detail=f"Máximo {MAX_LISTS_PER_USER} listas permitidas. Elimina una existente.",
        )

    if len(body.items) > MAX_ITEMS_PER_LIST:
        raise HTTPException(
            status_code=400,
            detail=f"Máximo {MAX_ITEMS_PER_LIST} ingredientes por lista.",
        )

    shopping_list = ShoppingList(
        user_id=user.id,
        name=body.name,
        description=body.description,
    )
    db.add(shopping_list)
    await db.flush()

    for item in body.items:
        db.add(ShoppingListItem(
            list_id=shopping_list.id,
            ingredient_name=item.ingredient_name,
            quantity=item.quantity,
            unit=item.unit,
        ))

    await db.commit()
    await db.refresh(shopping_list)

    # Reload with items
    result = await db.execute(
        select(ShoppingList)
        .where(ShoppingList.id == shopping_list.id)
        .options(selectinload(ShoppingList.items))
    )
    shopping_list = result.scalar_one()

    return _detail_response(shopping_list)


@router.get("/{list_id}", response_model=ListDetailResponse, summary="Get list with items")
async def get_list(list_id: int, user: CurrentUser, db: DbSession):
    shopping_list = await _get_user_list(list_id, user.id, db)
    return _detail_response(shopping_list)


@router.put("/{list_id}", response_model=ListDetailResponse, summary="Update list name/description")
async def update_list(list_id: int, body: ListUpdate, user: CurrentUser, db: DbSession):
    shopping_list = await _get_user_list(list_id, user.id, db)

    if body.name is not None:
        shopping_list.name = body.name.strip()
    if body.description is not None:
        shopping_list.description = body.description.strip() or None

    shopping_list.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(shopping_list)

    # Reload with items
    result = await db.execute(
        select(ShoppingList)
        .where(ShoppingList.id == shopping_list.id)
        .options(selectinload(ShoppingList.items))
    )
    shopping_list = result.scalar_one()
    return _detail_response(shopping_list)


@router.delete("/{list_id}", status_code=204, summary="Delete shopping list")
async def delete_list(list_id: int, user: CurrentUser, db: DbSession):
    shopping_list = await _get_user_list(list_id, user.id, db)
    await db.delete(shopping_list)
    await db.commit()


@router.delete("/{list_id}/items/{item_id}", status_code=204, summary="Remove single item")
async def delete_item(list_id: int, item_id: int, user: CurrentUser, db: DbSession):
    # Verify ownership
    await _get_user_list(list_id, user.id, db)

    result = await db.execute(
        select(ShoppingListItem).where(
            ShoppingListItem.id == item_id,
            ShoppingListItem.list_id == list_id,
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Ingrediente no encontrado")

    await db.delete(item)
    await db.commit()


# -- Helpers --

async def _get_user_list(list_id: int, user_id: int, db) -> ShoppingList:
    result = await db.execute(
        select(ShoppingList)
        .where(ShoppingList.id == list_id, ShoppingList.user_id == user_id)
        .options(selectinload(ShoppingList.items))
    )
    shopping_list = result.scalar_one_or_none()
    if not shopping_list:
        raise HTTPException(status_code=404, detail="Lista no encontrada")
    return shopping_list


def _detail_response(sl: ShoppingList) -> ListDetailResponse:
    return ListDetailResponse(
        id=sl.id,
        name=sl.name,
        description=sl.description,
        created_at=sl.created_at,
        updated_at=sl.updated_at,
        items=[
            ListItemResponse(
                id=item.id,
                ingredient_name=item.ingredient_name,
                quantity=item.quantity,
                unit=item.unit,
            )
            for item in sl.items
        ],
    )

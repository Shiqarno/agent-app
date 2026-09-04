import re
import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import AvatarId, PointTransactionReason, TaskExecutionStatus, UserRole

_PIN_PATTERN = re.compile(r"^[0-9]{4}$")


def _validate_pin_format(value: str) -> str:
    if not _PIN_PATTERN.fullmatch(value):
        raise ValueError("pin must be exactly 4 digits")
    return value


class ActivationStatus(StrEnum):
    ACTIVE = "ACTIVE"
    PENDING = "PENDING"


class ProjectBase(BaseModel):
    name: str
    description: str | None = None

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("name must not be empty or whitespace-only")
        return stripped


class ProjectCreate(ProjectBase):
    pass


class ProjectUpdate(ProjectBase):
    pass


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime


class TaskCreate(BaseModel):
    title: str
    description: str | None = None
    assigned_to: uuid.UUID | None = None
    reward_points: int = Field(gt=0)

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("title must not be empty or whitespace-only")
        return stripped


class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    reward_points: int | None = Field(default=None, gt=0)
    is_active: bool | None = None

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return value
        stripped = value.strip()
        if not stripped:
            raise ValueError("title must not be empty or whitespace-only")
        return stripped


class TaskReassign(BaseModel):
    assigned_to: uuid.UUID


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str | None
    reward_points: int
    is_active: bool
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime


class TaskExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_id: uuid.UUID
    user_id: uuid.UUID
    status: TaskExecutionStatus
    reward_points: int
    created_at: datetime
    updated_at: datetime


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    role: UserRole
    avatar_id: AvatarId
    # Derived from UserCredential.pin_hash (a separate table -- User carries
    # no credential fields of its own), so every endpoint returning this
    # must build it explicitly rather than relying on from_attributes to
    # pull it off a bare User object (Issue #22).
    pin_configured: bool


class UserListItemResponse(BaseModel):
    id: uuid.UUID
    name: str
    role: UserRole
    avatar_id: AvatarId
    activation_status: ActivationStatus


class UserCreate(BaseModel):
    name: str
    role: UserRole

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("name must not be empty or whitespace-only")
        return stripped


class UserCreateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    role: UserRole
    avatar_id: AvatarId
    created_at: datetime
    updated_at: datetime
    activation_token: str


class UserAvatarUpdate(BaseModel):
    avatar_id: AvatarId


class RewardCreate(BaseModel):
    name: str
    description: str | None = None
    cost_points: int = Field(gt=0)

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("name must not be empty or whitespace-only")
        return stripped


class RewardUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    cost_points: int | None = Field(default=None, gt=0)

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return value
        stripped = value.strip()
        if not stripped:
            raise ValueError("name must not be empty or whitespace-only")
        return stripped


class RewardResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    cost_points: int
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime


class RewardRedemptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    reward_id: uuid.UUID
    user_id: uuid.UUID
    cost_points: int
    created_at: datetime


class BalanceResponse(BaseModel):
    balance: int


class PointTransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    amount: int
    reason: PointTransactionReason
    task_execution_id: uuid.UUID | None
    redemption_id: uuid.UUID | None
    created_at: datetime


class LoginRequest(BaseModel):
    email: str
    password: str


class SetupRequest(BaseModel):
    name: str
    email: str
    pin: str
    password: str | None = Field(default=None, min_length=12)

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("name must not be empty or whitespace-only")
        return stripped

    @field_validator("pin")
    @classmethod
    def pin_must_be_four_digits(cls, value: str) -> str:
        return _validate_pin_format(value)


class ActivateRequest(BaseModel):
    token: str
    email: str
    pin: str
    password: str | None = Field(default=None, min_length=12)

    @field_validator("pin")
    @classmethod
    def pin_must_be_four_digits(cls, value: str) -> str:
        return _validate_pin_format(value)


class ActivationRegenerateResponse(BaseModel):
    activation_token: str
    expires_at: datetime


class ProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    avatar_id: AvatarId


class PinLoginRequest(BaseModel):
    user_id: uuid.UUID
    pin: str

    @field_validator("pin")
    @classmethod
    def pin_must_be_four_digits(cls, value: str) -> str:
        return _validate_pin_format(value)


class PinSetupRequest(BaseModel):
    pin: str

    @field_validator("pin")
    @classmethod
    def pin_must_be_four_digits(cls, value: str) -> str:
        return _validate_pin_format(value)

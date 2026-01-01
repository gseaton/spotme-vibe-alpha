from pydantic import BaseModel, Field, EmailStr, field_validator, model_validator
from pydantic_core import core_schema
from typing import Optional, Any, Dict, List
from datetime import datetime
from bson import ObjectId
from enum import Enum


class PyObjectId(str):
    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        _source_type: Any,
        _handler: Any,
    ) -> core_schema.CoreSchema:
        return core_schema.json_or_python_schema(
            json_schema=core_schema.str_schema(),
            python_schema=core_schema.union_schema([
                core_schema.is_instance_schema(ObjectId),
                core_schema.chain_schema([
                    core_schema.str_schema(),
                    core_schema.no_info_plain_validator_function(cls.validate),
                ])
            ]),
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda x: str(x)
            ),
        )

    @classmethod
    def validate(cls, v):
        if isinstance(v, ObjectId):
            return v
        if isinstance(v, str):
            if not ObjectId.is_valid(v):
                raise ValueError("Invalid ObjectId")
            return ObjectId(v)
        raise ValueError("Invalid ObjectId")


class UserBase(BaseModel):
    email: EmailStr
    full_name: str
    tenant_id: str


class UserCreate(UserBase):
    password: str


class UserInDB(UserBase):
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    hashed_password: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    is_active: bool = True
    is_admin: bool = False

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}


class User(UserBase):
    id: str
    created_at: datetime
    is_active: bool


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    email: Optional[str] = None
    tenant_id: Optional[str] = None


class NoteBase(BaseModel):
    title: str
    content: str
    tags: list[str] = []


class NoteCreate(NoteBase):
    pass


class NoteUpdate(NoteBase):
    pass


class NoteInDB(NoteBase):
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    user_id: str
    tenant_id: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}


class Note(NoteBase):
    id: str
    created_at: datetime
    updated_at: datetime


# Function models

class FunctionType(str, Enum):
    CONSTRAINTS = "constraints"
    PREDICATES = "predicates"
    RESOLUTION = "resolution"
    LAMBDAS = "lambdas"
    GENERATED = "generated"
    CUSTOM = "custom"


class FunctionScope(str, Enum):
    TENANT = "tenant"
    GLOBAL = "global"


class CodeSource(str, Enum):
    TEMPLATE = "template"
    PYTHON = "python"


class ReturnType(str, Enum):
    BOOLEAN = "boolean"
    STRING = "string"
    NUMBER = "number"
    OBJECT = "object"
    ANY = "any"


class FunctionBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    function_type: FunctionType
    scope: FunctionScope = FunctionScope.TENANT
    tags: List[str] = Field(default_factory=list)

    # Code input - at least one must be provided
    code_template: Optional[str] = None
    code_python: Optional[str] = None

    # Metadata
    parameter_schema: Optional[Dict[str, Any]] = None
    return_type: ReturnType = ReturnType.ANY
    is_active: bool = True


class FunctionCreate(FunctionBase):
    """Creation model - users provide either template or Python code"""

    @model_validator(mode='after')
    def validate_code_provided(self):
        if not self.code_template and not self.code_python:
            raise ValueError("Either code_template or code_python must be provided")
        if self.code_template and self.code_python:
            raise ValueError("Provide only one of code_template or code_python, not both")
        return self


class FunctionUpdate(BaseModel):
    """Update model - all fields optional"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    function_type: Optional[FunctionType] = None
    tags: Optional[List[str]] = None
    code_template: Optional[str] = None
    code_python: Optional[str] = None
    parameter_schema: Optional[Dict[str, Any]] = None
    return_type: Optional[ReturnType] = None
    is_active: Optional[bool] = None


class FunctionInDB(FunctionBase):
    """Database model with all computed fields"""
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    tenant_id: Optional[str] = None  # NULL for global functions
    user_id: str  # Creator

    # Derived fields
    code_source: CodeSource
    compiled_code: str
    compiled_bytecode: Optional[bytes] = None
    compilation_error: Optional[str] = None
    referenced_functions: List[str] = Field(default_factory=list)

    # Audit fields
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    created_by_user_id: str
    last_executed_at: Optional[datetime] = None
    execution_count: int = 0
    version: int = 1

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str, bytes: lambda v: None}  # Don't serialize bytecode


class Function(FunctionBase):
    """Response model - what API returns"""
    id: str
    tenant_id: Optional[str]
    user_id: str
    code_source: CodeSource
    compiled_code: str
    compilation_error: Optional[str]
    referenced_functions: List[str]
    created_at: datetime
    updated_at: datetime
    created_by_user_id: str
    last_executed_at: Optional[datetime]
    execution_count: int


class FunctionExecuteRequest(BaseModel):
    """Request to execute a function"""
    context: Dict[str, Any] = Field(..., description="Context dictionary for function execution")


class FunctionExecuteResponse(BaseModel):
    """Response from function execution"""
    result: Any
    execution_time_ms: float
    error: Optional[str] = None


# Voucher models
from decimal import Decimal


class VoucherStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    EXPIRED = "expired"
    DEPLETED = "depleted"


class TransactionType(str, Enum):
    CREDIT = "credit"  # Adds to balance
    DEBIT = "debit"    # Subtracts from balance


class MessageType(str, Enum):
    USER = "user"                 # User-to-user message
    SYSTEM = "system"             # System-generated message
    FUNDER_INVITATION = "funder_invitation"  # Invitation to be a funder


class TransactionRecord(BaseModel):
    """Transaction history record"""
    transaction_id: str
    amount: Decimal
    type: TransactionType
    balance_after: Decimal
    description: str
    performed_by: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class VoucherBase(BaseModel):
    """Base voucher fields"""
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    starting_balance: Decimal = Field(..., gt=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    tags: List[str] = Field(default_factory=list)
    expires_at: Optional[datetime] = None
    validation_function_id: Optional[str] = None


class VoucherCreate(VoucherBase):
    """Voucher creation request"""
    code: Optional[str] = None  # Auto-generated if not provided
    recipient_ids: Optional[List[str]] = None  # Initial recipients
    funder_ids: Optional[List[str]] = None  # Initial funders

    @field_validator('code')
    @classmethod
    def validate_code(cls, v):
        if v is not None:
            # Validate code format (alphanumeric, hyphens, underscores)
            import re
            if not re.match(r'^[A-Z0-9_-]+$', v):
                raise ValueError("Code must contain only uppercase letters, numbers, hyphens, and underscores")
            if len(v) < 6 or len(v) > 50:
                raise ValueError("Code must be between 6 and 50 characters")
        return v


class VoucherUpdate(BaseModel):
    """Voucher update request - all fields optional"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    tags: Optional[List[str]] = None
    status: Optional[VoucherStatus] = None
    expires_at: Optional[datetime] = None
    validation_function_id: Optional[str] = None
    recipient_ids: Optional[List[str]] = None  # Update recipients
    funder_ids: Optional[List[str]] = None  # Update funders


class VoucherBalanceAdjustment(BaseModel):
    """Balance adjustment request"""
    amount: Decimal = Field(..., description="Amount to add (credit) or subtract (debit)")
    type: TransactionType
    description: str = Field(..., min_length=1, max_length=200)

    @model_validator(mode='after')
    def validate_amount(self):
        if self.amount <= 0:
            raise ValueError("Amount must be positive")
        return self


class VoucherShareRequest(BaseModel):
    """Request to share voucher with users"""
    user_ids: List[str] = Field(..., min_length=1)
    role: str = Field(..., pattern="^(owner|manager|viewer|recipient)$")


class VoucherUnshareRequest(BaseModel):
    """Request to remove users from voucher sharing"""
    user_ids: List[str] = Field(..., min_length=1)
    role: str = Field(..., pattern="^(owner|manager|viewer|recipient)$")


class VoucherInDB(VoucherBase):
    """Database model for vouchers"""
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    tenant_id: str
    user_id: str  # Creator
    code: str
    balance: Decimal
    status: VoucherStatus = VoucherStatus.ACTIVE

    # Role lists
    owners: List[str] = Field(default_factory=list)
    managers: List[str] = Field(default_factory=list)
    viewers: List[str] = Field(default_factory=list)
    recipient_ids: List[str] = Field(default_factory=list)  # Users allowed to receive payments
    funder_ids: List[str] = Field(default_factory=list)  # Users allowed to fund/send payments
    accepted_funder_ids: List[str] = Field(default_factory=list)  # Subset of funders who have accepted

    # Transaction history (limited to last 50)
    transaction_history: List[TransactionRecord] = Field(default_factory=list)

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    last_transaction_at: Optional[datetime] = None

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str, Decimal: str}


class Voucher(VoucherBase):
    """Response model for vouchers"""
    id: str
    code: str
    balance: Decimal
    status: VoucherStatus
    owners: List[str]
    managers: List[str]
    viewers: List[str]
    recipient_ids: List[str]
    funder_ids: List[str]
    accepted_funder_ids: List[str]
    transaction_history: List[TransactionRecord]
    created_at: datetime
    updated_at: datetime
    last_transaction_at: Optional[datetime]

    # Computed field for current user's role
    user_role: Optional[str] = None

# ==================== Messages ====================

class MessageBase(BaseModel):
    """Base message fields"""
    subject: str = Field(..., min_length=1, max_length=200)
    content: str = Field(..., min_length=1, max_length=5000)
    message_type: MessageType = MessageType.USER


class MessageCreate(MessageBase):
    """Message creation request"""
    recipient_ids: List[str] = Field(..., min_length=1)  # At least one recipient
    related_voucher_id: Optional[str] = None  # For funder invitations, etc.


class MessageInDB(MessageBase):
    """Database model for messages"""
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    tenant_id: str
    sender_id: str
    recipient_ids: List[str]
    read_by: List[str] = Field(default_factory=list)  # User IDs who have read this
    related_voucher_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}


class Message(MessageBase):
    """Response model for messages"""
    id: str
    sender_id: str
    sender_email: Optional[str] = None  # Populated for display
    recipient_ids: List[str]
    read_by: List[str]
    related_voucher_id: Optional[str] = None
    created_at: datetime
    is_read: bool = False  # Computed field for current user

from sqlalchemy import Enum
from enum import StrEnum

class ProfileType(str, Enum):
    outreach = "outreach"
    target = "target"

class CampaignStatus(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    SUCCESSFUL = "successful"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELED = "canceled"
    PAUSED = "paused"
    PENDING = "pending"
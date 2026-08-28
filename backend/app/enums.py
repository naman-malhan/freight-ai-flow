import enum


class DraftStatus(str, enum.Enum):
    NEW = "NEW"
    MISSING_INFO = "MISSING_INFO"
    READY_TO_CONFIRM = "READY_TO_CONFIRM"
    CREATED = "CREATED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class TripIntent(str, enum.Enum):
    CREATE_TRIP = "create_trip"
    EDIT_TRIP = "edit_trip"
    CANCEL_TRIP = "cancel_trip"
    UNKNOWN = "unknown"


class MessageDirection(str, enum.Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"

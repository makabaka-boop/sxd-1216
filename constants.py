import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

JWT_SECRET = "call-qa-secret-change-in-production"
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24

HOST = "0.0.0.0"
PORT = 8148


class Role:
    ADMIN = "admin"
    INSPECTOR = "inspector"
    TEAM_LEAD = "team_lead"

    ALL = (ADMIN, INSPECTOR, TEAM_LEAD)
    LABELS = {
        ADMIN: "管理员",
        INSPECTOR: "质检员",
        TEAM_LEAD: "客服组长",
    }


class Status:
    PENDING_INSPECTION = "pending_inspection"
    INSPECTING = "inspecting"
    PENDING_APPEAL = "pending_appeal"
    APPEAL_PROCESSING = "appeal_processing"
    PENDING_REVIEW = "pending_review"
    CLOSED = "closed"

    ALL = (
        PENDING_INSPECTION,
        INSPECTING,
        PENDING_APPEAL,
        APPEAL_PROCESSING,
        PENDING_REVIEW,
        CLOSED,
    )
    LABELS = {
        PENDING_INSPECTION: "待抽检",
        INSPECTING: "质检中",
        PENDING_APPEAL: "待申诉",
        APPEAL_PROCESSING: "申诉处理中",
        PENDING_REVIEW: "待复核",
        CLOSED: "已结案",
    }

    FLOW = {
        PENDING_INSPECTION: [INSPECTING],
        INSPECTING: [PENDING_APPEAL],
        PENDING_APPEAL: [APPEAL_PROCESSING, CLOSED],
        APPEAL_PROCESSING: [PENDING_REVIEW, CLOSED],
        PENDING_REVIEW: [CLOSED],
        CLOSED: [],
    }


class RectificationStatus:
    PENDING_RECTIFY = "pending_rectify"
    RECTIFYING = "rectifying"
    PENDING_ACCEPT = "pending_accept"
    COMPLETED = "completed"
    OVERDUE = "overdue"

    ALL = (
        PENDING_RECTIFY,
        RECTIFYING,
        PENDING_ACCEPT,
        COMPLETED,
        OVERDUE,
    )
    LABELS = {
        PENDING_RECTIFY: "待整改",
        RECTIFYING: "整改中",
        PENDING_ACCEPT: "待验收",
        COMPLETED: "已完成",
        OVERDUE: "已逾期",
    }
    FLOW = {
        PENDING_RECTIFY: [RECTIFYING, OVERDUE],
        RECTIFYING: [PENDING_ACCEPT, OVERDUE],
        PENDING_ACCEPT: [COMPLETED, RECTIFYING],
        COMPLETED: [],
        OVERDUE: [RECTIFYING, COMPLETED],
    }


class RectificationTrigger:
    LOW_SCORE = "low_score"
    KEY_DEDUCTION = "key_deduction"
    REVIEW_UPHELD = "review_upheld"
    MANUAL = "manual"

    ALL = (LOW_SCORE, KEY_DEDUCTION, REVIEW_UPHELD, MANUAL)
    LABELS = {
        LOW_SCORE: "分数低于阈值",
        KEY_DEDUCTION: "存在重点扣分项",
        REVIEW_UPHELD: "复核维持原结论",
        MANUAL: "手动发起",
    }


class RectificationAcceptResult:
    PASS = "pass"
    REJECT = "reject"

    ALL = (PASS, REJECT)
    LABELS = {
        PASS: "验收通过",
        REJECT: "验收驳回",
    }


DEFAULT_CONFIG = {
    "sampling_ratio": 0.1,
    "appeal_deadline_hours": 48,
    "review_deadline_hours": 72,
    "low_score_threshold": 80,
    "risk_low_score_ratio": 0.3,
    "risk_min_sample": 3,
    "frequent_item_threshold": 3,
    "rectify_deadline_hours": 72,
    "rectify_auto_trigger_low_score": True,
    "rectify_auto_trigger_key_deduction": True,
    "key_deduction_item_ids": [],
    "key_deduction_threshold_score": 5,
    "repeat_rectify_threshold": 2,
}

DATA_FILES = {
    "users": "users.json",
    "business_lines": "business_lines.json",
    "seat_groups": "seat_groups.json",
    "scoring_tables": "scoring_tables.json",
    "inspections": "inspections.json",
    "appeals": "appeals.json",
    "reviews": "reviews.json",
    "rectifications": "rectifications.json",
    "config": "config.json",
}

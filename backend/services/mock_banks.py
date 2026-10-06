"""
Context Guard — Mock Bank APIs

Simulates structured requests to banks and their responses.
Includes:
- Hospital payment scenario (₹3,00,000 with contextual explanation)
- Cross-bank coordinated activity scenario
- Normal low-risk scenario

In production, these would be real API calls to bank endpoints.
"""

import uuid
from datetime import datetime, timedelta


# ── Bank endpoints ───────────────────────────────────────────────────────────

MOCK_BANK_ENDPOINTS = {
    "bank_a": {
        "id": "bank_a",
        "name": "HDFC Bank",
        "api_base": "https://api.hdfcbank.com/v1/context-guard",
        "status": "active",
        "capabilities": ["context_verification", "entity_profile", "consent_check", "investigation"],
    },
    "bank_b": {
        "id": "bank_b",
        "name": "ICICI Bank",
        "api_base": "https://api.icicibank.com/v1/context-guard",
        "status": "active",
        "capabilities": ["context_verification", "entity_profile", "investigation"],
    },
    "bank_c": {
        "id": "bank_c",
        "name": "Axis Bank",
        "api_base": "https://api.axisbank.com/v1/context-guard",
        "status": "active",
        "capabilities": ["context_verification", "entity_profile", "consent_check", "investigation"],
    },
}


# ── Request builders ─────────────────────────────────────────────────────────

def create_context_request(transaction_id, requesting_bank, target_bank, entity_id, reason):
    """Create a structured context request to send to a bank."""
    return {
        "request_id": f"ctx_{uuid.uuid4().hex[:12]}",
        "type": "context_verification",
        "timestamp": datetime.utcnow().isoformat(),
        "from_bank": requesting_bank,
        "to_bank": target_bank,
        "transaction_id": transaction_id,
        "entity_id": entity_id,
        "reason": reason,
        "requested_fields": [
            "entity_relationship_status",
            "account_tenure",
            "recent_activity_summary",
            "consent_status",
            "purpose_of_transaction",
        ],
        "consent_required": True,
        "retention_policy": "30_days",
        "data_classification": "confidential",
    }


def create_investigation_request(entities, banks, reason, priority="high"):
    """Create a formal investigation request sent to multiple banks."""
    return {
        "request_id": f"inv_{uuid.uuid4().hex[:12]}",
        "type": "investigation",
        "timestamp": datetime.utcnow().isoformat(),
        "priority": priority,
        "reason": reason,
        "participating_banks": banks,
        "entities_under_review": entities,
        "requested_data": [
            "transaction_history_90d",
            "entity_network_map",
            "device_fingerprints",
            "ip_access_logs",
            "consent_audit_trail",
            "beneficial_ownership_records",
        ],
        "legal_basis": "Regulatory cooperation agreement",
        "response_deadline": (datetime.utcnow() + timedelta(hours=48)).isoformat(),
    }


# ── Mock responses ───────────────────────────────────────────────────────────

def get_mock_response(bank_id, request_type, request, entity_id=None):
    """Route to the appropriate mock bank handler."""
    if request_type == "context_verification":
        return _context_verification_response(bank_id, request, entity_id)
    elif request_type == "investigation":
        return _investigation_response(bank_id, request)
    return {"status": "error", "message": f"Unknown request type: {request_type}"}


def _context_verification_response(bank_id, request, entity_id):
    """Context verification responses — includes hospital payment scenario."""
    entity_id = entity_id or request.get("entity_id", "")

    # HDFC Bank responses
    if bank_id == "bank_a":
        if entity_id == "e_rajesh":
            # Hospital payment scenario — legitimate medical expense.
            # Keyed to e_rajesh because the ₹3,00,000 Apollo payment belongs to him
            # (both in the seed data and in the live-ingest scenario).
            return {
                "request_id": request["request_id"],
                "responding_bank": "bank_a",
                "status": "completed",
                "timestamp": datetime.utcnow().isoformat(),
                "data": {
                    "entity_relationship_status": "long_term_customer",
                    "account_tenure": "8 years, 4 months",
                    "recent_activity_summary": (
                        "Consistent salary credits (₹1,25,000/month) for 8 years. "
                        "Regular household expenses. First large medical payment in this account."
                    ),
                    "consent_status": "active_consent_given",
                    "kyc_status": "verified",
                    "risk_rating_internal": "low",
                    "additional_context": (
                        "Entity has a registered health insurance policy with Star Health "
                        "(Policy #SH-2024-88712). The ₹3,00,000 payment matches the co-pay "
                        "amount for a cardiac procedure at Apollo Hospital, Chennai. "
                        "Insurance claim ref: CLAIM-2026-09-1847 is already filed."
                    ),
                    "transaction_purpose": "Medical expense - cardiac procedure co-pay",
                    "supporting_documents": ["Insurance policy", "Hospital invoice", "Claim receipt"],
                },
            }
        elif entity_id == "e_priya":
            # Priya Sharma — salaried individual, routine activity
            return {
                "request_id": request["request_id"],
                "responding_bank": "bank_a",
                "status": "completed",
                "timestamp": datetime.utcnow().isoformat(),
                "data": {
                    "entity_relationship_status": "long_term_customer",
                    "account_tenure": "8 years, 4 months",
                    "recent_activity_summary": (
                        "Consistent salary credits (₹1,25,000/month) for 8 years with "
                        "regular household spending. No unexplained inflows."
                    ),
                    "consent_status": "active_consent_given",
                    "kyc_status": "verified",
                    "risk_rating_internal": "low",
                    "additional_context": (
                        "Salaried customer; activity matches a stable income and "
                        "everyday household expense pattern."
                    ),
                    "transaction_purpose": "Household expenditure",
                },
            }
        else:
            return {
                "request_id": request["request_id"],
                "responding_bank": "bank_a",
                "status": "completed",
                "timestamp": datetime.utcnow().isoformat(),
                "data": {
                    "entity_relationship_status": "standard_customer",
                    "account_tenure": "2 years",
                    "recent_activity_summary": "Regular domestic activity.",
                    "consent_status": "active_consent_given",
                    "kyc_status": "verified",
                    "risk_rating_internal": "low",
                },
            }

    # ICICI Bank responses
    elif bank_id == "bank_b":
        return {
            "request_id": request["request_id"],
            "responding_bank": "bank_b",
            "status": "completed",
            "timestamp": datetime.utcnow().isoformat(),
            "data": {
                "entity_relationship_status": "business_account",
                "account_tenure": "4 years",
                "recent_activity_summary": (
                    "Business account with regular trade payments. "
                    "Cross-border transactions to verified suppliers."
                ),
                "consent_status": "active_consent_given",
                "kyc_status": "verified",
                "risk_rating_internal": "low",
                "additional_context": (
                    "Entity is a registered partnership firm. "
                    "All transactions match invoiced trade."
                ),
            },
        }

    # Axis Bank responses
    elif bank_id == "bank_c":
        return {
            "request_id": request["request_id"],
            "responding_bank": "bank_c",
            "status": "completed",
            "timestamp": datetime.utcnow().isoformat(),
            "data": {
                "entity_relationship_status": "business_account",
                "account_tenure": "2 years, 6 months",
                "recent_activity_summary": (
                    "SME account with regular supplier payments. "
                    "Monthly volume ₹5-8 lakh."
                ),
                "consent_status": "active_consent_given",
                "kyc_status": "verified",
                "risk_rating_internal": "low",
                "additional_context": (
                    "Entity has a registered MSME certificate. "
                    "All payments are for verified business purposes."
                ),
            },
        }

    return {"status": "pending", "data": {}}


def _investigation_response(bank_id, request):
    """Investigation responses — detailed findings for coordinated activity."""
    if bank_id == "bank_a":
        return {
            "status": "completed",
            "data": {
                "entities_linked": ["e_rajesh", "e_priya", "e_ananya", "e_corp_x"],
                "transaction_count_90d": 156,
                "device_profiles": [
                    {"device_id": "d1", "owner": "e_priya", "first_seen": "2024-01-15", "trusted": True},
                    {"device_id": "d4", "owner": "e_rajesh", "first_seen": "2023-06-20", "trusted": True},
                    {"device_id": "d5", "owner": "e_ananya", "first_seen": "2026-09-15", "trusted": False},
                ],
                "cross_border_transactions": 5,
                "crypto_related_transactions": 0,
                "shared_address_flag": False,
                "beneficial_ownership_link": False,
            },
        }
    elif bank_id == "bank_b":
        return {
            "status": "completed",
            "data": {
                "entities_linked": ["e_corp_y", "e_vikram"],
                "transaction_count_90d": 89,
                "device_profiles": [
                    {"device_id": "d2", "owner": "e_vikram", "first_seen": "2024-03-10", "trusted": True},
                ],
                "cross_border_transactions": 8,
                "crypto_related_transactions": 0,
                "shared_address_flag": True,
                "beneficial_ownership_link": False,
            },
        }
    elif bank_id == "bank_c":
        return {
            "status": "completed",
            "data": {
                "entities_linked": ["e_meera", "e_sharma_co"],
                "transaction_count_90d": 134,
                "device_profiles": [
                    {"device_id": "d3", "owner": "e_meera", "first_seen": "2024-11-01", "trusted": True},
                    {"device_id": "d6", "owner": "e_sharma_co", "first_seen": "2025-06-15", "trusted": True},
                ],
                "cross_border_transactions": 12,
                "crypto_related_transactions": 2,
                "shared_address_flag": False,
                "beneficial_ownership_link": True,
            },
        }

    return {"status": "pending", "data": {}}

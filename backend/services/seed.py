"""
Context Guard — Seed Data

Creates the initial demo data in MongoDB:
1. Normal low-risk activity (routine spending)
2. Hospital payment with contextual explanation (₹3,00,000)
3. Cross-bank coordinated activity leading to investigation
"""

import uuid
from datetime import datetime, timedelta


# ── Entities ─────────────────────────────────────────────────────────────────

ENTITIES = [
    # Scenario 1: Normal activity
    {
        "id": "e_priya",
        "name": "Priya Sharma",
        "type": "individual",
        "bank_id": "bank_a",
        "country": "IN",
        "occupation": "Software Engineer",
        "annual_income": 1500000,
    },
    # Scenario 2: Hospital payment context
    {
        "id": "e_rajesh",
        "name": "Rajesh Kumar",
        "type": "individual",
        "bank_id": "bank_a",
        "country": "IN",
        "occupation": "Business Owner",
        "annual_income": 1200000,
    },
    # Scenario 3: Cross-bank network
    {
        "id": "e_vikram",
        "name": "Vikram Patel",
        "type": "individual",
        "bank_id": "bank_b",
        "country": "IN",
        "occupation": "Consultant",
    },
    {
        "id": "e_meera",
        "name": "Meera Reddy",
        "type": "individual",
        "bank_id": "bank_c",
        "country": "IN",
        "occupation": "Trader",
    },
    {
        "id": "e_ananya",
        "name": "Ananya Singh",
        "type": "individual",
        "bank_id": "bank_a",
        "country": "IN",
        "occupation": "Freelancer",
    },
    # Business entities
    {
        "id": "e_corp_x",
        "name": "TechVision Solutions Pvt Ltd",
        "type": "business",
        "bank_id": "bank_a",
        "country": "IN",
        "gst_number": "27AABCT1234F1Z5",
    },
    {
        "id": "e_corp_y",
        "name": "GlobalTrade Exports",
        "type": "business",
        "bank_id": "bank_b",
        "country": "IN",
        "gst_number": "29AABCG5678G1Z3",
    },
    {
        "id": "e_sharma_co",
        "name": "Sharma & Associates",
        "type": "business",
        "bank_id": "bank_c",
        "country": "IN",
        "gst_number": "07AABCS9012H1Z1",
    },
    # Hospital
    {
        "id": "e_apollo",
        "name": "Apollo Hospitals Enterprise Ltd",
        "type": "business",
        "bank_id": "bank_a",
        "country": "IN",
        "gst_number": "33AABCA3456I1Z9",
    },
]

DEVICES = [
    {"id": "d1", "os": "iOS 17", "browser": "Safari", "location": "Mumbai, IN"},
    {"id": "d2", "os": "Windows 11", "browser": "Chrome", "location": "Delhi, IN"},
    {"id": "d3", "os": "Android 14", "browser": "Chrome", "location": "Bangalore, IN"},
    {"id": "d4", "os": "macOS 14", "browser": "Safari", "location": "Chennai, IN"},
    {"id": "d5", "os": "Linux", "browser": "Firefox", "location": "Pune, IN"},
    {"id": "d6", "os": "iOS 17", "browser": "Safari", "location": "Hyderabad, IN"},
]


# ── Transaction generators ───────────────────────────────────────────────────

def _gen_normal_transactions(now):
    """Scenario 1: Priya Sharma — routine salary and expenses."""
    txns = []
    base = now - timedelta(days=7)

    # Salary credit
    txns.append({
        "id": f"txn_n1_{uuid.uuid4().hex[:8]}",
        "timestamp": (base + timedelta(days=1, hours=9)).isoformat(),
        "entity_id": "e_priya",
        "bank_id": "bank_a",
        "type": "credit",
        "amount": 125000,
        "currency": "INR",
        "description": "Salary credit - TechCorp India",
        "category": "salary",
        "counterparty": "TechCorp India",
        "device_id": "d1",
        "country": "IN",
        "consent_given": True,
    })

    # Regular expenses
    expenses = [
        ("Amazon India", "shopping", 2800, "d1"),
        ("Swiggy", "food_drink", 450, "d1"),
        ("Netflix", "entertainment", 649, "d1"),
        ("Uber", "transport", 320, "d1"),
        ("BigBasket", "groceries", 1850, "d1"),
        ("Electricity Bill", "utilities", 2200, "d4"),
        ("Mobile Recharge", "utilities", 599, "d1"),
    ]

    for i, (desc, cat, amount, device) in enumerate(expenses):
        txns.append({
            "id": f"txn_n2_{uuid.uuid4().hex[:8]}",
            "timestamp": (base + timedelta(days=i + 2, hours=14 + i)).isoformat(),
            "entity_id": "e_priya",
            "bank_id": "bank_a",
            "type": "debit",
            "amount": amount,
            "currency": "INR",
            "description": desc,
            "category": cat,
            "counterparty": desc,
            "device_id": device,
            "country": "IN",
            "consent_given": True,
        })

    return txns


def _gen_hospital_transactions(now):
    """Scenario 2: Rajesh Kumar — ₹3,00,000 hospital payment."""
    txns = []
    base = now - timedelta(days=5)

    # Normal business expenses
    business_expenses = [
        ("Office Supplies", "business", 8500, "d4"),
        ("Internet Bill", "utilities", 1200, "d4"),
        ("Client Dinner", "food_drink", 3200, "d4"),
        ("Software License", "business", 15000, "d4"),
    ]

    for i, (desc, cat, amount, device) in enumerate(business_expenses):
        txns.append({
            "id": f"txn_h1_{uuid.uuid4().hex[:8]}",
            "timestamp": (base + timedelta(days=i, hours=10)).isoformat(),
            "entity_id": "e_rajesh",
            "bank_id": "bank_a",
            "type": "debit",
            "amount": amount,
            "currency": "INR",
            "description": desc,
            "category": cat,
            "counterparty": desc,
            "device_id": device,
            "country": "IN",
            "consent_given": True,
        })

    # The flagged transaction: ₹3,00,000 hospital payment
    txns.append({
        "id": f"txn_h2_{uuid.uuid4().hex[:8]}",
        "timestamp": (now - timedelta(hours=2)).isoformat(),
        "entity_id": "e_rajesh",
        "bank_id": "bank_a",
        "type": "debit",
        "amount": 300000,
        "currency": "INR",
        "description": "Apollo Hospitals - Cardiac Procedure Co-pay",
        "category": "medical",
        "counterparty": "Apollo Hospitals Enterprise Ltd",
        "device_id": "d4",
        "country": "IN",
        "consent_given": True,
        "metadata": {
            "hospital": "Apollo Hospitals, Chennai",
            "procedure": "Cardiac catheterization",
            "insurance_claim": "CLAIM-2026-09-1847",
            "co_pay_amount": 300000,
        },
    })

    return txns


def _gen_crossbank_transactions(now):
    """Scenario 3: Coordinated cross-bank activity."""
    txns = []
    base = now - timedelta(days=3)

    # Phase 1: Initial deposits
    txns.extend([
        {
            "id": f"txn_c1_{uuid.uuid4().hex[:8]}",
            "timestamp": (base + timedelta(hours=9)).isoformat(),
            "entity_id": "e_corp_y",
            "bank_id": "bank_b",
            "type": "credit",
            "amount": 850000,
            "currency": "INR",
            "description": "Inward wire - GlobalTrade Exports",
            "category": "business_transfer",
            "counterparty": "Overseas Client",
            "device_id": "d2",
            "country": "IN",
            "consent_given": True,
        },
        {
            "id": f"txn_c2_{uuid.uuid4().hex[:8]}",
            "timestamp": (base + timedelta(hours=9, minutes=5)).isoformat(),
            "entity_id": "e_sharma_co",
            "bank_id": "bank_c",
            "type": "credit",
            "amount": 620000,
            "currency": "INR",
            "description": "Inward wire - Sharma & Associates",
            "category": "business_transfer",
            "counterparty": "Domestic Client",
            "device_id": "d6",
            "country": "IN",
            "consent_given": True,
        },
    ])

    # Phase 2: Rapid transfers between entities
    txns.extend([
        {
            "id": f"txn_c3_{uuid.uuid4().hex[:8]}",
            "timestamp": (base + timedelta(hours=14)).isoformat(),
            "entity_id": "e_corp_y",
            "bank_id": "bank_b",
            "type": "debit",
            "amount": 780000,
            "currency": "INR",
            "description": "Payment to Sharma & Associates",
            "category": "business_transfer",
            "counterparty": "Sharma & Associates",
            "device_id": "d2",
            "country": "IN",
            "consent_given": True,
        },
        {
            "id": f"txn_c4_{uuid.uuid4().hex[:8]}",
            "timestamp": (base + timedelta(hours=14, minutes=20)).isoformat(),
            "entity_id": "e_sharma_co",
            "bank_id": "bank_c",
            "type": "debit",
            "amount": 580000,
            "currency": "INR",
            "description": "Payment to GlobalTrade Exports",
            "category": "business_transfer",
            "counterparty": "GlobalTrade Exports",
            "device_id": "d6",
            "country": "IN",
            "consent_given": True,
        },
    ])

    # Phase 3: Layering through individual accounts
    txns.extend([
        {
            "id": f"txn_c5_{uuid.uuid4().hex[:8]}",
            "timestamp": (base + timedelta(hours=20)).isoformat(),
            "entity_id": "e_vikram",
            "bank_id": "bank_b",
            "type": "credit",
            "amount": 250000,
            "currency": "INR",
            "description": "Transfer from GlobalTrade",
            "category": "business_transfer",
            "counterparty": "GlobalTrade Exports",
            "device_id": "d2",
            "country": "IN",
            "consent_given": True,
        },
        {
            "id": f"txn_c6_{uuid.uuid4().hex[:8]}",
            "timestamp": (base + timedelta(hours=20, minutes=30)).isoformat(),
            "entity_id": "e_meera",
            "bank_id": "bank_c",
            "type": "credit",
            "amount": 320000,
            "currency": "INR",
            "description": "Transfer from Sharma & Associates",
            "category": "business_transfer",
            "counterparty": "Sharma & Associates",
            "device_id": "d3",
            "country": "IN",
            "consent_given": True,
        },
    ])

    # Phase 4: Withdrawals
    txns.extend([
        {
            "id": f"txn_c7_{uuid.uuid4().hex[:8]}",
            "timestamp": (now - timedelta(hours=6)).isoformat(),
            "entity_id": "e_vikram",
            "bank_id": "bank_b",
            "type": "debit",
            "amount": 240000,
            "currency": "INR",
            "description": "Cash withdrawal",
            "category": "cash",
            "counterparty": "ATM",
            "device_id": "d2",
            "country": "IN",
            "consent_given": True,
        },
        {
            "id": f"txn_c8_{uuid.uuid4().hex[:8]}",
            "timestamp": (now - timedelta(hours=5, minutes=45)).isoformat(),
            "entity_id": "e_meera",
            "bank_id": "bank_c",
            "type": "debit",
            "amount": 300000,
            "currency": "INR",
            "description": "NEFT to unknown account",
            "category": "transfer",
            "counterparty": "Unknown Recipient",
            "device_id": "d3",
            "country": "IN",
            "consent_given": True,
        },
    ])

    return txns


# ── Cases ────────────────────────────────────────────────────────────────────

def generate_cases(now):
    """Create the three demo cases."""
    return [
        {
            "id": "case_1",
            "title": "Normal Salary & Expenses",
            "description": "Priya Sharma — routine salary credit and household expenses",
            "entity_ids": ["e_priya"],
            "bank_ids": ["bank_a"],
            "status": "normal",
            "created_at": (now - timedelta(days=7)).isoformat(),
            "score": 0.05,
        },
        {
            "id": "case_2",
            "title": "₹3L Hospital Payment — Context Required",
            "description": "Rajesh Kumar — ₹3,00,000 payment to Apollo Hospitals flagged for context verification",
            "entity_ids": ["e_rajesh", "e_apollo"],
            "bank_ids": ["bank_a"],
            "status": "context_verification",
            "created_at": (now - timedelta(days=2)).isoformat(),
            "score": 0.42,
        },
        {
            "id": "case_3",
            "title": "Cross-Bank Coordinated Activity",
            "description": "Multi-entity, multi-bank fund movement — layering pattern detected",
            "entity_ids": ["e_corp_y", "e_sharma_co", "e_vikram", "e_meera", "e_ananya"],
            "bank_ids": ["bank_a", "bank_b", "bank_c"],
            "status": "investigation",
            "created_at": (now - timedelta(days=1)).isoformat(),
            "score": 0.87,
        },
    ]


# ── Main seed function ───────────────────────────────────────────────────────

def seed_database(db):
    """Seed the database with demo data."""
    now = datetime.utcnow()

    # Clear existing data
    db.entities.delete_many({})
    db.devices.delete_many({})
    db.transactions.delete_many({})
    db.cases.delete_many({})
    db.bank_reports.delete_many({})
    db.decisions.delete_many({})
    db.graph_edges.delete_many({})

    # Insert entities
    for entity in ENTITIES:
        db.entities.insert_one(entity)
    print(f"  Seeded {len(ENTITIES)} entities")

    # Insert devices
    for device in DEVICES:
        db.devices.insert_one(device)
    print(f"  Seeded {len(DEVICES)} devices")

    # Generate and insert transactions
    all_txns = []
    all_txns.extend(_gen_normal_transactions(now))
    all_txns.extend(_gen_hospital_transactions(now))
    all_txns.extend(_gen_crossbank_transactions(now))

    for txn in all_txns:
        db.transactions.insert_one(txn)
    print(f"  Seeded {len(all_txns)} transactions")

    # Insert cases
    cases = generate_cases(now)
    for case in cases:
        db.cases.insert_one(case)
    print(f"  Seeded {len(cases)} cases")

    return {
        "entities": len(ENTITIES),
        "devices": len(DEVICES),
        "transactions": len(all_txns),
        "cases": len(cases),
    }

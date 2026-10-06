"""
Context Guard — Behavioral Graph Engine

Tracks entity-to-entity, entity-to-device, and entity-to-bank relationships
over time. Builds behavioral profiles from transaction patterns. Supports
network intelligence queries across banks and accounts.

This is the core feature that enables:
1. Relationship tracking: who transacts with whom, when, how often
2. Behavioral profiling: normal vs abnormal patterns per entity
3. Network intelligence: cross-bank, multi-account relationship mapping
4. Temporal analysis: how relationships evolve over time
"""

from datetime import datetime, timedelta
from collections import defaultdict
import math


# ── Edge types ───────────────────────────────────────────────────────────────

EDGE_TYPES = {
    "transaction": "Direct transaction between entities",
    "shared_device": "Same device used by multiple entities",
    "shared_counterparty": "Entities sharing a counterparty",
    "shared_address": "Entities at the same registered address",
    "beneficial_ownership": "Beneficial ownership link between entities",
    "cross_bank_flow": "Fund flow across bank boundaries",
    "temporal_pattern": "Entities with synchronized transaction timing",
}


# ── Graph building ───────────────────────────────────────────────────────────

def build_entity_graph(db, entity_ids=None, lookback_days=90):
    """Build a behavioral graph for the given entities (or all if None).

    Returns nodes (entities + devices + counterparties) and edges
    (relationships with metadata).
    """
    cutoff = datetime.utcnow() - timedelta(days=lookback_days)
    query = {"timestamp": {"$gte": cutoff.isoformat()}}
    if entity_ids:
        query["entity_id"] = {"$in": entity_ids}

    transactions = list(db.transactions.find(query).sort("timestamp", 1))
    if not transactions:
        return {"nodes": [], "edges": [], "metadata": {}}

    nodes = {}
    edges = []
    edge_set = set()  # Deduplicate edges

    def add_node(node_id, label, node_type, **kwargs):
        if node_id not in nodes:
            nodes[node_id] = {
                "id": node_id,
                "label": label,
                "type": node_type,
                "transaction_count": 0,
                "total_volume": 0,
                "first_seen": None,
                "last_seen": None,
                **kwargs,
            }
        nodes[node_id]["transaction_count"] += 1
        nodes[node_id]["total_volume"] += kwargs.get("amount", 0)

    def add_edge(source, target, edge_type, **kwargs):
        key = (source, target, edge_type)
        if key in edge_set:
            # Update existing edge
            for e in edges:
                if (e["source"], e["target"], e["edge_type"]) == key:
                    e["weight"] = e.get("weight", 1) + 1
                    e["total_amount"] = e.get("total_amount", 0) + kwargs.get("amount", 0)
                    e["last_seen"] = datetime.utcnow().isoformat()
                    return
        edge_set.add(key)
        edges.append({
            "source": source,
            "target": target,
            "edge_type": edge_type,
            "weight": 1,
            "total_amount": kwargs.get("amount", 0),
            "currency": kwargs.get("currency", "INR"),
            "first_seen": kwargs.get("timestamp", datetime.utcnow().isoformat()),
            "last_seen": kwargs.get("timestamp", datetime.utcnow().isoformat()),
            **kwargs,
        })

    # Process transactions
    for txn in transactions:
        entity_id = txn["entity_id"]
        counterparty = txn.get("counterparty", "Unknown")
        device_id = txn.get("device_id")
        bank_id = txn["bank_id"]
        amount = txn.get("amount", 0)
        currency = txn.get("currency", "INR")
        timestamp = txn.get("timestamp", datetime.utcnow().isoformat())

        # Add entity node
        entity = db.entities.find_one({"id": entity_id}) or {}
        add_node(
            entity_id,
            entity.get("name", entity_id),
            entity.get("type", "individual"),
            bank_id=bank_id,
            country=entity.get("country", ""),
            amount=amount,
        )

        # Update timestamps
        if nodes[entity_id]["first_seen"] is None or timestamp < nodes[entity_id]["first_seen"]:
            nodes[entity_id]["first_seen"] = timestamp
        if nodes[entity_id]["last_seen"] is None or timestamp > nodes[entity_id]["last_seen"]:
            nodes[entity_id]["last_seen"] = timestamp

        # Add counterparty node and edge
        if counterparty and counterparty != "Unknown":
            add_node(
                f"cp_{counterparty}",
                counterparty,
                "counterparty",
                amount=amount,
            )
            add_edge(
                entity_id,
                f"cp_{counterparty}",
                "transaction",
                amount=amount,
                currency=currency,
                txn_type=txn.get("type", "debit"),
                timestamp=timestamp,
                bank_id=bank_id,
            )

        # Add device relationship
        if device_id:
            device = db.devices.find_one({"id": device_id}) if hasattr(db, 'devices') else None
            add_node(
                f"dev_{device_id}",
                f"Device {device_id}",
                "device",
                os=device.get("os", "") if device else "",
                location=device.get("location", "") if device else "",
            )
            add_edge(
                entity_id,
                f"dev_{device_id}",
                "shared_device",
                device_id=device_id,
                timestamp=timestamp,
            )

    # Detect shared counterparties (cross-entity relationships)
    counterparty_entities = defaultdict(set)
    for edge in edges:
        if edge["edge_type"] == "transaction":
            counterparty_entities[edge["target"]].add(edge["source"])

    for cp_id, entities in counterparty_entities.items():
        entities = list(entities)
        if len(entities) > 1:
            for i in range(len(entities)):
                for j in range(i + 1, len(entities)):
                    add_edge(
                        entities[i],
                        entities[j],
                        "shared_counterparty",
                        shared_with=cp_id,
                    )

    # Detect cross-bank flows
    bank_entities = defaultdict(set)
    for txn in transactions:
        bank_entities[txn["bank_id"]].add(txn["entity_id"])

    for entity_id in nodes:
        entity_bank = nodes[entity_id].get("bank_id")
        if entity_bank:
            for other_bank, other_entities in bank_entities.items():
                if other_bank != entity_bank and entity_id in other_entities:
                    for other_id in other_entities:
                        if other_id != entity_id:
                            add_edge(
                                entity_id,
                                other_id,
                                "cross_bank_flow",
                                from_bank=entity_bank,
                                to_bank=other_bank,
                            )

    # Build metadata
    metadata = {
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "entity_count": sum(1 for n in nodes.values() if n["type"] in ("individual", "business")),
        "bank_count": len(set(n.get("bank_id") for n in nodes.values() if n.get("bank_id"))),
        "lookback_days": lookback_days,
        "generated_at": datetime.utcnow().isoformat(),
    }

    return {
        "nodes": list(nodes.values()),
        "edges": edges,
        "metadata": metadata,
    }


# How far a network is walked by default, and how far it may be walked. Depth is a
# judgement about how much scope a case is allowed to take on, so it is bounded rather
# than open-ended: an investigator can widen the walk, but not by accident.
DEFAULT_MAX_HOPS = 2
MAX_HOPS_CAP = 5


def resolve_depth(value, default=None):
    """Clamp a requested graph depth to something a case can safely be widened to."""
    if value is None or value == "":
        value = DEFAULT_MAX_HOPS if default is None else default
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = DEFAULT_MAX_HOPS
    return max(1, min(value, MAX_HOPS_CAP))


def expand_network(db, entity_ids, max_hops=2, lookback_days=180):
    """Walk outward from a set of entities to find the network they sit in.

    A case starts from the subject, but the banks that hold relevant evidence are
    not only the subject's own bank — they are every bank holding an account the
    evidence connects to the subject. Without this step a cross-bank case opened
    from a single transaction would contact one bank and see one bank's data.

    Two link types are followed, both readable from the transaction record alone
    (no external data source, no assumption of wrongdoing):

      * counterparty    — a transaction whose counterparty name matches a known entity
      * shared device   — another entity transacting from a device this one also used

    Every addition is returned with the link that justifies it, so the caller can
    state *why* an account entered the case rather than silently widening scope.

    Returns:
        {
            "entity_ids": [...],   # the input set plus everything reached
            "subject_ids": [...],  # the input set, unchanged
            "added": [...],        # just the entities reached
            "links": [...],        # [{"from", "to", "via", "detail"}]
            "banks": [...],        # banks holding any entity in the expanded set
            "hops": int,
        }
    """
    subject_ids = [e for e in (entity_ids or []) if e]
    if not subject_ids:
        return {"entity_ids": [], "subject_ids": [], "added": [], "links": [], "banks": [], "hops": 0}

    all_entities = list(db.entities.find())
    by_name = {e.get("name"): e.get("id") for e in all_entities if e.get("name")}
    bank_of = {e.get("id"): e.get("bank_id") for e in all_entities}
    # Link descriptions are read by an investigator, so name the parties rather than
    # printing internal ids like e_vikram.
    display = {e.get("id"): (e.get("name") or e.get("id")) for e in all_entities}

    seen = set(subject_ids)
    frontier = list(subject_ids)
    links = []
    hops = 0

    for hop in range(1, max_hops + 1):
        if not frontier:
            break
        hops = hop

        txns = list(db.transactions.find({"entity_id": {"$in": frontier}}))
        devices = {}
        for txn in txns:
            device_id = txn.get("device_id")
            if device_id:
                devices.setdefault(device_id, txn["entity_id"])

        reached = []

        # Link 1: a counterparty that resolves to a known entity.
        for txn in txns:
            target = by_name.get(txn.get("counterparty"))
            if not target or target in seen:
                continue
            seen.add(target)
            reached.append(target)
            links.append({
                "from": txn["entity_id"],
                "to": target,
                "via": "counterparty",
                "hop": hop,
                "detail": f"{txn.get('counterparty')} pays or is paid by "
                          f"{display.get(txn['entity_id'], txn['entity_id'])} "
                          f"({txn.get('id', 'a recorded transaction')})",
            })

        # Link 2: another entity that transacted from a device this set used.
        if devices:
            others = db.transactions.find({
                "device_id": {"$in": list(devices)},
                "entity_id": {"$nin": list(seen)},
            })
            for txn in others:
                target = txn["entity_id"]
                if target in seen:
                    continue
                seen.add(target)
                reached.append(target)
                links.append({
                    "from": devices[txn["device_id"]],
                    "to": target,
                    "via": "shared_device",
                    "hop": hop,
                    "detail": f"device {txn['device_id']} is used by both "
                              f"{display.get(devices[txn['device_id']], devices[txn['device_id']])} "
                              f"and {display.get(target, target)}",
                })

        frontier = reached

    added = [e for e in seen if e not in set(subject_ids)]
    banks = sorted({bank_of.get(e) for e in seen if bank_of.get(e)})

    return {
        "entity_ids": subject_ids + added,
        "subject_ids": subject_ids,
        "added": added,
        "links": links,
        "banks": banks,
        "hops": hops,
    }


# ── Behavioral profiling ─────────────────────────────────────────────────────

def build_behavioral_profile(db, entity_id, lookback_days=90):
    """Build a behavioral profile for an entity based on historical transactions.

    This tracks:
    - Normal transaction amounts and frequency
    - Typical counterparties and devices
    - Time-of-day and day-of-week patterns
    - Geographic patterns
    """
    cutoff = datetime.utcnow() - timedelta(days=lookback_days)
    txns = list(db.transactions.find({
        "entity_id": entity_id,
        "timestamp": {"$gte": cutoff.isoformat()},
    }).sort("timestamp", 1))

    if not txns:
        return {"entity_id": entity_id, "profile": "insufficient_data"}

    # Amount analysis
    amounts = [t.get("amount", 0) for t in txns]
    avg_amount = sum(amounts) / len(amounts) if amounts else 0
    std_amount = math.sqrt(sum((a - avg_amount) ** 2 for a in amounts) / len(amounts)) if len(amounts) > 1 else 0

    # Frequency analysis
    if len(txns) >= 2:
        timestamps = [datetime.fromisoformat(t["timestamp"]) for t in txns]
        gaps = [(timestamps[i+1] - timestamps[i]).total_seconds() / 3600
                for i in range(len(timestamps) - 1)]
        avg_gap_hours = sum(gaps) / len(gaps) if gaps else 0
    else:
        avg_gap_hours = 0

    # Counterparty analysis
    counterparties = defaultdict(int)
    for t in txns:
        cp = t.get("counterparty", "Unknown")
        if cp != "Unknown":
            counterparties[cp] += 1

    # Device analysis
    devices = defaultdict(int)
    for t in txns:
        d = t.get("device_id")
        if d:
            devices[d] += 1

    # Time-of-day analysis
    hour_distribution = [0] * 24
    for t in txns:
        try:
            hour = datetime.fromisoformat(t["timestamp"]).hour
            hour_distribution[hour] += 1
        except (ValueError, KeyError):
            pass

    # Day-of-week analysis
    dow_distribution = [0] * 7
    for t in txns:
        try:
            dow = datetime.fromisoformat(t["timestamp"]).weekday()
            dow_distribution[dow] += 1
        except (ValueError, KeyError):
            pass

    # Geographic analysis
    countries = defaultdict(int)
    for t in txns:
        c = t.get("country", "unknown")
        countries[c] += 1

    return {
        "entity_id": entity_id,
        "transaction_count": len(txns),
        "amount_stats": {
            "mean": round(avg_amount, 2),
            "std": round(std_amount, 2),
            "min": min(amounts) if amounts else 0,
            "max": max(amounts) if amounts else 0,
            "total": round(sum(amounts), 2),
        },
        "frequency": {
            "avg_hours_between": round(avg_gap_hours, 2),
            "transactions_per_day": round(len(txns) / max(lookback_days, 1), 2),
        },
        "counterparties": dict(sorted(counterparties.items(), key=lambda x: -x[1])[:10]),
        "devices": dict(devices),
        "time_distribution": {
            "hourly": hour_distribution,
            "daily": dow_distribution,
        },
        "geographic": dict(countries),
        "profile_generated_at": datetime.utcnow().isoformat(),
    }


def detect_anomalies_against_profile(profile, new_txn):
    """Compare a new transaction against the entity's behavioral profile.

    Returns a list of anomalies detected.
    """
    if profile.get("profile") == "insufficient_data":
        return []

    anomalies = []
    amount_stats = profile.get("amount_stats", {})

    # Amount anomaly
    if amount_stats.get("std", 0) > 0:
        z_score = (new_txn.get("amount", 0) - amount_stats["mean"]) / amount_stats["std"]
        if z_score > 2.5:
            anomalies.append({
                "type": "amount_anomaly",
                "severity": "high" if z_score > 4 else "medium",
                "description": f"Transaction is {z_score:.1f} std deviations above the entity's mean",
                "details": {
                    "amount": new_txn.get("amount", 0),
                    "mean": amount_stats["mean"],
                    "z_score": round(z_score, 2),
                },
            })

    # New counterparty
    known_cps = set(profile.get("counterparties", {}).keys())
    new_cp = new_txn.get("counterparty")
    if new_cp and new_cp != "Unknown" and new_cp not in known_cps:
        anomalies.append({
            "type": "new_counterparty",
            "severity": "low",
            "description": f"First transaction with counterparty '{new_cp}'",
            "details": {"counterparty": new_cp},
        })

    # New device
    known_devices = set(profile.get("devices", {}).keys())
    new_device = new_txn.get("device_id")
    if new_device and new_device not in known_devices:
        anomalies.append({
            "type": "new_device",
            "severity": "low",
            "description": f"First use of device {new_device}",
            "details": {"device_id": new_device},
        })

    # Unusual time
    try:
        hour = datetime.fromisoformat(new_txn.get("timestamp", "")).hour
        hourly = profile.get("time_distribution", {}).get("hourly", [0] * 24)
        if hourly[hour] == 0 and sum(hourly) > 10:
            anomalies.append({
                "type": "unusual_time",
                "severity": "low",
                "description": f"Transaction at hour {hour} not seen in historical pattern",
                "details": {"hour": hour},
            })
    except (ValueError, KeyError):
        pass

    return anomalies


# ── Network intelligence ─────────────────────────────────────────────────────

def find_network_clusters(graph):
    """Find connected clusters in the entity graph.

    Returns groups of entities that are connected through transactions,
    shared devices, or other relationships.
    """
    adjacency = defaultdict(set)
    for edge in graph["edges"]:
        adjacency[edge["source"]].add(edge["target"])
        adjacency[edge["target"]].add(edge["source"])

    visited = set()
    clusters = []

    def bfs(start):
        cluster = set()
        queue = [start]
        while queue:
            node = queue.pop(0)
            if node in visited:
                continue
            visited.add(node)
            cluster.add(node)
            for neighbor in adjacency[node]:
                if neighbor not in visited:
                    queue.append(neighbor)
        return cluster

    for node in graph["nodes"]:
        if node["id"] not in visited:
            cluster = bfs(node["id"])
            if len(cluster) > 1:  # Only meaningful clusters
                clusters.append({
                    "cluster_id": f"cluster_{len(clusters) + 1}",
                    "entities": list(cluster),
                    "size": len(cluster),
                })

    return clusters


def calculate_centrality(graph):
    """Calculate degree centrality for each node (who is most connected)."""
    degree = defaultdict(int)
    for edge in graph["edges"]:
        degree[edge["source"]] += 1
        degree[edge["target"]] += 1

    max_degree = max(degree.values()) if degree else 1

    return {
        node_id: round(count / max_degree, 3)
        for node_id, count in degree.items()
    }


def find_shortest_path(graph, source, target):
    """Find shortest path between two entities in the graph."""
    adjacency = defaultdict(list)
    for edge in graph["edges"]:
        adjacency[edge["source"]].append(edge["target"])
        adjacency[edge["target"]].append(edge["source"])

    visited = {source: None}
    queue = [source]

    while queue:
        current = queue.pop(0)
        if current == target:
            # Reconstruct path
            path = []
            node = target
            while node is not None:
                path.append(node)
                node = visited.get(node)
            return list(reversed(path))

        for neighbor in adjacency[current]:
            if neighbor not in visited:
                visited[neighbor] = current
                queue.append(neighbor)

    return None  # No path found


def detect_circular_flows(graph):
    """Detect circular fund flows in the graph."""
    cycles = []
    visited = set()

    def dfs(node, path):
        if node in path:
            cycle_start = path.index(node)
            cycles.append(path[cycle_start:])
            return
        if node in visited:
            return
        path.append(node)
        for edge in graph["edges"]:
            if edge["source"] == node and edge["edge_type"] == "transaction":
                dfs(edge["target"], path)
        path.pop()
        visited.add(node)

    for node in graph["nodes"]:
        if node["type"] in ("individual", "business"):
            dfs(node["id"], [])

    return cycles

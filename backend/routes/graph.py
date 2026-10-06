"""
Context Guard — Graph Routes

Flask blueprint for behavioral graph engine and network intelligence.
"""

from flask import Blueprint, jsonify, request

from config import get_db
from middleware import current_user, load_case, login_required, visible_case_ids
from models import serialize_doc, get_all_entities
from services import access as access_service, audit
from services.graph_engine import (
    DEFAULT_MAX_HOPS,
    MAX_HOPS_CAP,
    build_entity_graph,
    build_behavioral_profile,
    detect_anomalies_against_profile,
    expand_network,
    find_network_clusters,
    calculate_centrality,
    find_shortest_path,
    detect_circular_flows,
    resolve_depth,
)
from services.settings import get_settings

graph_bp = Blueprint("graph", __name__)


RESTRICTED_LABEL = "🔒 Restricted Information"


@graph_bp.route("/api/graph/expansion", methods=["GET"])
@login_required
def network_expansion():
    """Walk a case's network at a chosen depth, so scope can be explored not assumed.

    How far the walk runs decides which accounts end up in a case, so widening it is a
    scope decision: it is bounded, the administrator sets the default, and the caller is
    told both what was asked for and how far the recorded evidence actually reaches.
    Every entity reached comes back with the link that put it there.
    """
    db = get_db()
    user = current_user()
    case_id = request.args.get("case_id")
    if not case_id:
        return jsonify({"error": "case_id is required"}), 400
    case, error = load_case(case_id)
    if error:
        return jsonify(error[0]), error[1]

    depth = resolve_depth(request.args.get("max_hops"),
                          default=get_settings(db).get("graph_max_hops", DEFAULT_MAX_HOPS))
    network = expand_network(db, case.get("entity_ids", []), max_hops=depth)

    audit.record(db, user, "graph_viewed", target=case_id, case_id=case_id,
                 resource_type="investigation_case",
                 detail=(f"Explored the network to {depth} hop(s) — reached "
                         f"{len(network['added'])} further entity(ies) in "
                         f"{network['hops']} hop(s), putting {len(network['banks'])} bank(s) in scope"))

    return jsonify({
        "case_id": case_id,
        "requested_max_hops": depth,
        "hops": network["hops"],
        "default_max_hops": get_settings(db).get("graph_max_hops", DEFAULT_MAX_HOPS),
        "max_allowed_hops": MAX_HOPS_CAP,
        "subject_entity_ids": network["subject_ids"],
        "added_entity_ids": network["added"],
        "entity_ids": network["entity_ids"],
        "links": network["links"],
        "banks": network["banks"],
        "scope_unchanged": network["entity_ids"] == network["subject_ids"],
    })


def _restricted_index(db):
    """entity_id and legal name -> the case whose restricted record covers them."""
    by_id, by_name = {}, {}
    for doc in db.restricted_subject_information.find({}, {"subject_id": 1, "case_id": 1, "value": 1}):
        if doc.get("subject_id"):
            by_id[doc["subject_id"]] = doc["case_id"]
        legal_name = (doc.get("value") or {}).get("legal_name")
        if legal_name:
            by_name[legal_name] = doc["case_id"]
    return by_id, by_name


def _apply_restricted_masking(db, graph, user):
    """Show a locked placeholder instead of a subject's details without an authorisation.

    The relationship itself is not hidden — a graph that silently omits links would
    misrepresent the network. What is withheld is who the node is and what it moved.
    """
    by_id, by_name = _restricted_index(db)
    if not by_id and not by_name:
        graph["restricted"] = {"masked": 0, "authorized": 0}
        return graph

    masked_ids, masked, authorized = set(), 0, 0
    for node in graph.get("nodes", []):
        case_id = by_id.get(node.get("id")) or by_name.get(node.get("label"))
        if not case_id:
            continue

        authorization = access_service.active_authorization(db, user["id"], case_id)
        node["restricted"] = True
        node["case_id"] = case_id
        if authorization:
            node["authorized"] = True
            node["access_state"] = "authorized"
            node["authorized_under"] = authorization["request_id"]
            node["access_expires"] = authorization["expires_at"]
            node["access_label"] = "🔓 Authorized Information"
            authorized += 1
            continue

        node["authorized"] = False
        node["access_state"] = ("expired"
                                 if access_service.expired_authorization(db, user["id"], case_id)
                                 else "locked")
        node["access_label"] = RESTRICTED_LABEL
        node["label"] = RESTRICTED_LABEL
        # Withhold everything that describes the subject.
        for field in ("transaction_count", "total_volume", "first_seen", "last_seen",
                      "centrality", "bank_id", "type_label"):
            node.pop(field, None)
        masked_ids.add(node.get("id"))
        masked += 1

    for edge in graph.get("edges", []):
        if edge.get("source") in masked_ids or edge.get("target") in masked_ids:
            edge.pop("total_amount", None)
            edge["restricted"] = True
            edge["label"] = RESTRICTED_LABEL

    for cluster in graph.get("clusters", []):
        cluster["entities"] = ["restricted" if e in masked_ids else e
                               for e in cluster.get("entities", [])]
    for cycle in graph.get("circular_flows", []):
        for index, node_id in enumerate(cycle):
            if node_id in masked_ids:
                cycle[index] = "restricted"

    graph["restricted"] = {"masked": masked, "authorized": authorized}
    graph["notice"] = ("Nodes marked as restricted subject information require an approved, "
                       "time-limited authorisation to open.")
    return graph


def _scoped_entity_ids(db, user):
    """None means the whole network (compliance/admin); a set means this analyst's cases."""
    if visible_case_ids(db, user) is None:
        return None
    ids = set()
    for case in db.cases.find({"assigned_to": user["id"]}, {"entity_ids": 1}):
        ids.update(case.get("entity_ids", []))
    return ids


@graph_bp.route("/api/graph/entity", methods=["GET"])
@login_required
def entity_graph():
    """Build the behavioral entity graph, scoped to the caller's cases."""
    db = get_db()
    user = current_user()
    entity_ids = request.args.get("entity_ids")
    lookback = int(request.args.get("lookback_days", 90))
    scope = _scoped_entity_ids(db, user)

    if entity_ids:
        entity_ids = entity_ids.split(",")
    else:
        entity_ids = None

    if scope is not None:
        if entity_ids:
            entity_ids = [e for e in entity_ids if e in scope]
        else:
            entity_ids = list(scope)
        if not entity_ids:
            return jsonify({"nodes": [], "edges": [], "clusters": [], "circular_flows": [],
                            "scope": "assigned",
                            "note": "No graph entities on your assigned cases."})

    graph = build_entity_graph(db, entity_ids, lookback)

    # Add centrality scores
    centrality = calculate_centrality(graph)
    for node in graph["nodes"]:
        node["centrality"] = centrality.get(node["id"], 0)

    # Detect clusters
    clusters = find_network_clusters(graph)
    graph["clusters"] = clusters

    # Detect circular flows
    cycles = detect_circular_flows(graph)
    graph["circular_flows"] = cycles

    graph = _apply_restricted_masking(db, graph, user)
    graph["scope"] = "all" if scope is None else "assigned"
    graph["viewer"] = {"name": user.get("name"), "role": user.get("role")}

    audit.record(db, user, "graph_viewed", target="network_graph",
                 resource_type="network_graph",
                 detail=(f"Viewed the network graph ({len(graph['nodes'])} node(s), "
                         f"{graph['restricted']['masked']} restricted node(s) withheld)"))
    return jsonify(graph)


@graph_bp.route("/api/graph/entity/<entity_id>/profile", methods=["GET"])
@login_required
def entity_profile(entity_id):
    """Get behavioral profile for an entity."""
    db = get_db()
    lookback = int(request.args.get("lookback_days", 90))
    profile = build_behavioral_profile(db, entity_id, lookback)
    return jsonify(profile)


@graph_bp.route("/api/graph/entity/<entity_id>/anomalies", methods=["POST"])
@login_required
def check_anomalies(entity_id):
    """Check a transaction against the entity's behavioral profile."""
    db = get_db()
    transaction = request.json or {}
    lookback = int(request.args.get("lookback_days", 90))

    profile = build_behavioral_profile(db, entity_id, lookback)
    anomalies = detect_anomalies_against_profile(profile, transaction)

    return jsonify({
        "entity_id": entity_id,
        "anomalies": anomalies,
        "profile_summary": {
            "transaction_count": profile.get("transaction_count", 0),
            "avg_amount": profile.get("amount_stats", {}).get("mean", 0),
        },
    })


@graph_bp.route("/api/graph/path", methods=["GET"])
@login_required
def shortest_path():
    """Find shortest path between two entities."""
    db = get_db()
    source = request.args.get("source")
    target = request.args.get("target")

    if not source or not target:
        return jsonify({"error": "source and target required"}), 400

    graph = build_entity_graph(db)
    path = find_shortest_path(graph, source, target)

    if path:
        return jsonify({"path": path, "length": len(path) - 1})
    return jsonify({"path": None, "message": "No path found"})


@graph_bp.route("/api/graph/clusters", methods=["GET"])
@login_required
def network_clusters():
    """Find connected clusters in the caller's entity network."""
    db = get_db()
    graph = build_entity_graph(db)
    clusters = find_network_clusters(graph)
    return jsonify(clusters)

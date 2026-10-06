"""
Context Guard — List Pagination

Lists grow. A case accumulates transactions, the trail accumulates years, and an inbox
accumulates notifications, so "return everything the caller may see" stops being a
kind answer long before it becomes a slow one.

Two shapes, because two kinds of endpoint already exist and changing either would break
every caller:

  * endpoints that return a **bare array** are windowed and carry the counts in
    response headers (`X-Total-Count`, `X-Limit`, `X-Offset`, `X-Has-More`), so the
    body stays exactly what it was;
  * endpoints that return an **object** gain a `pagination` block alongside their items.

Both read `?limit=` and `?offset=`, clamped so a client cannot ask for a million rows.
"""

DEFAULT_LIMIT = 50
MAX_LIMIT = 500


def window(args, default_limit=DEFAULT_LIMIT, max_limit=MAX_LIMIT):
    """Read `limit` and `offset` from query arguments, clamped to something sane."""
    try:
        limit = int(args.get("limit", default_limit))
    except (TypeError, ValueError):
        limit = default_limit
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    return max(1, min(limit, max_limit)), max(0, offset)


def envelope(items, total, limit, offset):
    """The metadata an object-shaped list carries back to its caller."""
    return {
        "limit": limit,
        "offset": offset,
        "total": total,
        "returned": len(items),
        "has_more": offset + len(items) < total,
    }


def slice_page(items, limit, offset):
    """Window a materialised list, and say how many there were in total."""
    total = len(items)
    return items[offset:offset + limit], total


def page_headers(total, limit, offset, returned):
    """Headers for a bare-array endpoint that has been windowed."""
    return {
        "X-Total-Count": str(total),
        "X-Limit": str(limit),
        "X-Offset": str(offset),
        "X-Returned": str(returned),
        "X-Has-More": "true" if offset + returned < total else "false",
    }

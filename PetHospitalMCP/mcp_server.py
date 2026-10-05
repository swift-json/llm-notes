#!/usr/bin/env python3
"""Pet Hospital MCP Server (MVP).

Only exposes `list_pets` (GET /api/v1/pets: filter + sort + pagination).
Transport: Streamable HTTP, supporting both:
  - Old protocol (<= 2025-11-25): initialize handshake + stateful session
  - New protocol (2026-07-28): stateless, no handshake, no long-link

Run:  py -3.13 mcp_server.py
"""

import json

import httpx2 as httpx
from mcp.server import MCPServer

PET_API = "http://127.0.0.1:8080/api/v1/pets"

mcp = MCPServer(name="pet-hospital", version="0.1.0")


@mcp.tool()
async def list_pets(
    q: str | None = None,
    name: str | None = None,
    owner_name: str | None = None,
    owner_phone: str | None = None,
    species: str | None = None,
    doctor: str | None = None,
    disease: str | None = None,
    status: str | None = None,
    min_cost: float | None = None,
    max_cost: float | None = None,
    sort_by: str | None = None,
    order: str | None = None,
    page: int | None = None,
    page_size: int | None = None,
) -> str:
    """Query the pet hospital's pet list with filtering, sorting, and pagination.

    All parameters are optional. Without any, returns the first page of all pets.

    Args:
        q: Full-text search across multiple fields (space-separated AND).
        name: Filter by pet name.
        owner_name: Filter by owner name.
        owner_phone: Filter by owner phone.
        species: Filter by species (e.g. 犬, 猫, 兔, 鸟, 仓鼠, 龟, 蛇).
        doctor: Filter by attending doctor.
        disease: Filter by disease.
        status: Filter by visit status (待就诊/就诊中/住院中/已康复/慢性病随访).
        min_cost: Minimum total cost (inclusive).
        max_cost: Maximum total cost (inclusive).
        sort_by: Sort field (e.g. name, totalCost, ageMonths, createdAt).
        order: Sort order: "asc" or "desc".
        page: Page number, 1-based. Default 1.
        page_size: Page size. Default 20.

    Returns:
        JSON string: {items[], total, page, pageSize, totalPages, totalCost}.
    """
    params = {
        k: v
        for k, v in {
            "q": q,
            "name": name,
            "ownerName": owner_name,
            "ownerPhone": owner_phone,
            "species": species,
            "doctor": doctor,
            "disease": disease,
            "status": status,
            "min": min_cost,
            "max": max_cost,
            "sortBy": sort_by,
            "order": order,
            "page": page,
            "pageSize": page_size,
        }.items()
        if v is not None
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(PET_API, params=params, timeout=30.0)
        resp.raise_for_status()
        return json.dumps(resp.json()["data"], ensure_ascii=False)


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="127.0.0.1", port=9000)

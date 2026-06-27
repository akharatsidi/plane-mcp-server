"""Export tools for Plane MCP Server.

These tools are CLIENT-SIDE AGGREGATIONS: they page through the existing
work-item list endpoint (N server round-trips, one per page) and render the
collected items into a single document string. There is no dedicated backend
"export" endpoint and no SDK export resource — everything here is built on top
of ``client.work_items.list`` with cursor pagination.
"""

from typing import Any

from fastmcp import FastMCP
from fastmcp.utilities.logging import get_logger
from plane.models.query_params import WorkItemQueryParams

from plane_mcp.client import get_plane_client_context

logger = get_logger(__name__)

# Hard cap on the number of pages we will fetch, so a runaway / malformed
# next_cursor can never loop forever. 100 pages * per_page 100 = 10k items.
_MAX_PAGES = 100
_PER_PAGE = 100


def _item_to_dict(item: Any) -> dict[str, Any]:
    """Normalize a work item (pydantic model or raw dict) to a plain dict."""
    if hasattr(item, "model_dump"):
        return item.model_dump()
    if isinstance(item, dict):
        return item
    return {}


def _state_name(state: Any) -> str:
    """Best-effort state label.

    ``state`` may be a bare id string, an expanded ``{name, ...}`` dict, or
    missing. Return the name when expanded, the id when it is just a string,
    or an empty string when unset.
    """
    if isinstance(state, dict):
        return str(state.get("name") or state.get("id") or "")
    if isinstance(state, str):
        return state
    return ""


def _assignee_names(assignees: Any) -> list[str]:
    """Best-effort list of assignee labels from an expanded assignees field.

    Each entry may be an expanded user dict (display_name / first+last / email)
    or a bare id string. Entries that yield no usable label are skipped.
    """
    names: list[str] = []
    if not isinstance(assignees, list):
        return names
    for a in assignees:
        if isinstance(a, dict):
            label = (
                a.get("display_name")
                or " ".join(p for p in (a.get("first_name"), a.get("last_name")) if p).strip()
                or a.get("email")
                or a.get("id")
            )
            if label:
                names.append(str(label))
        elif isinstance(a, str) and a:
            names.append(a)
    return names


def _csv_field(value: Any) -> str:
    """Render one CSV field, quoting/escaping per RFC 4180 when needed."""
    text = "" if value is None else str(value)
    if any(ch in text for ch in (",", '"', "\n", "\r")):
        text = '"' + text.replace('"', '""') + '"'
    return text


def _collect_work_items(client: Any, workspace_slug: str, project_id: str) -> list[dict[str, Any]]:
    """Page through every work item in a project and return them as dicts.

    Walks ``client.work_items.list`` following ``next_cursor`` until it is
    falsy (or the page cap is hit). State and assignees are expanded so the
    rendered output can include human-readable labels.
    """
    collected: list[dict[str, Any]] = []
    cursor: str | None = None
    for _ in range(_MAX_PAGES):
        response = client.work_items.list(
            workspace_slug=workspace_slug,
            project_id=project_id,
            params=WorkItemQueryParams(
                per_page=_PER_PAGE,
                cursor=cursor,
                expand="state,assignees",
            ),
        )
        for item in response.results or []:
            collected.append(_item_to_dict(item))
        # The backend always emits a non-empty next_cursor string (e.g. "100:1:0")
        # even past the last page, so terminate on the next_page_results flag —
        # the canonical signal used by every other paginated MCP tool.
        cursor = getattr(response, "next_cursor", None)
        if not getattr(response, "next_page_results", False):
            break
    return collected


def _project_name(client: Any, workspace_slug: str, project_id: str) -> str:
    """Resolve the project's display name, falling back to its id."""
    try:
        project = client.projects.retrieve(workspace_slug=workspace_slug, project_id=project_id)
        name = getattr(project, "name", None)
        if name:
            return str(name)
    except Exception as e:  # noqa: BLE001 - the export should not fail over a label
        logger.warning("export: could not resolve project name for %s → %s", project_id, e)
    return project_id


def _render_markdown(project_name: str, items: list[dict[str, Any]]) -> str:
    """Render collected items as a markdown document.

    Each line: ``- [STATE] NAME (sequence_id)`` with priority and assignees
    appended when present.
    """
    lines = [f"# {project_name} work items", ""]
    for it in items:
        state = _state_name(it.get("state"))
        name = it.get("name") or ""
        sequence_id = it.get("sequence_id")
        line = f"- [{state}] {name}"
        if sequence_id is not None:
            line += f" ({sequence_id})"
        priority = it.get("priority")
        if priority:
            line += f" — priority: {priority}"
        assignees = _assignee_names(it.get("assignees"))
        if assignees:
            line += f" — assignees: {', '.join(assignees)}"
        lines.append(line)
    return "\n".join(lines)


def _render_csv(items: list[dict[str, Any]]) -> str:
    """Render collected items as CSV with header id,sequence_id,name,priority,state."""
    rows = ["id,sequence_id,name,priority,state"]
    for it in items:
        rows.append(
            ",".join(
                _csv_field(v)
                for v in (
                    it.get("id"),
                    it.get("sequence_id"),
                    it.get("name"),
                    it.get("priority"),
                    _state_name(it.get("state")),
                )
            )
        )
    return "\n".join(rows)


def register_export_tools(mcp: FastMCP) -> None:
    """Register all export-related tools with the MCP server."""

    @mcp.tool()
    def export_project_work_items(project_id: str, format: str = "markdown") -> str:
        """
        Export every work item in a project as a single document string.

        CLIENT-SIDE AGGREGATION: this pages through the work-item list endpoint
        following next_cursor (one server request per page, up to 100 pages of
        100 items), collects the items, and renders them locally. It is not a
        dedicated server export — large projects mean many round-trips.

        Args:
            project_id: UUID of the project to export.
            format: Output format. "markdown" (default) produces a
                "# <project> work items" document with one
                "- [STATE] NAME (sequence_id)" line per item, including
                priority and assignees when present. "csv" produces a header
                row "id,sequence_id,name,priority,state" followed by one row
                per item (commas/quotes/newlines escaped per RFC 4180).

        Returns:
            The rendered document as a string.
        """
        client, workspace_slug = get_plane_client_context()

        normalized_format = (format or "markdown").strip().lower()
        if normalized_format not in ("markdown", "csv"):
            raise ValueError(f"Unsupported format {format!r}. Use 'markdown' or 'csv'.")

        items = _collect_work_items(client, workspace_slug, project_id)

        if normalized_format == "csv":
            return _render_csv(items)

        project_name = _project_name(client, workspace_slug, project_id)
        return _render_markdown(project_name, items)

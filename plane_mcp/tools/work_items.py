"""Work item-related tools for Plane MCP Server."""

import re
from html import escape
from typing import Annotated, Any, get_args

from fastmcp import FastMCP
from fastmcp.utilities.logging import get_logger
from plane.errors.errors import HttpError
from plane.models.enums import PriorityEnum
from plane.models.query_params import RetrieveQueryParams, WorkItemCountQueryParams, WorkItemQueryParams
from plane.models.work_items import (
    CreateWorkItem,
    PaginatedWorkItemResponse,
    UpdateWorkItem,
    WorkItem,
    WorkItemDetail,
    WorkItemGroupedCountResponse,
    WorkItemSearch,
)
from pydantic import Field

from plane_mcp.client import get_plane_client_context
from plane_mcp.tools.pql_reference import PQL_FIELD_HINT, PQL_FULL_REFERENCE

logger = get_logger(__name__)


def _md_inline(text: str) -> str:
    """Convert inline markdown (escaped HTML) for **bold**, *italic*, `code`.

    The input is escaped first so any literal HTML the caller typed is rendered
    as text, then a small set of inline markers are turned into tags. Inline
    code is handled before bold/italic so emphasis markers inside backticks are
    left untouched.
    """
    out = escape(text)
    # Inline code first: `code` -> <code>code</code>
    out = re.sub(r"`([^`]+)`", lambda m: f"<code>{m.group(1)}</code>", out)
    # Bold: **text** -> <strong>text</strong>
    out = re.sub(r"\*\*(.+?)\*\*", lambda m: f"<strong>{m.group(1)}</strong>", out)
    # Italic: *text* -> <em>text</em> (remaining single asterisks)
    out = re.sub(r"\*(.+?)\*", lambda m: f"<em>{m.group(1)}</em>", out)
    return out


def _markdown_to_html(markdown: str) -> str:
    """Convert a small, safe subset of markdown to sanitized HTML.

    No external dependency. The source is HTML-escaped before any tags are
    emitted, so only the tags this converter produces (<h1..3>, <p>, <ul>,
    <li>, <strong>, <em>, <code>) ever reach the output — caller-supplied HTML
    is rendered as inert text. Supported block constructs:

      * `#`, `##`, `###` headings -> <h1>..<h3>
      * lines starting with `- ` or `* ` -> <ul><li>...</li></ul>
      * blank-line-separated runs of text -> <p>...</p>
    Inline `**bold**`, `*italic*` and `` `code` `` are handled within blocks.
    """
    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    html_parts: list[str] = []
    paragraph: list[str] = []
    list_items: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            html_parts.append("<p>" + "<br/>".join(_md_inline(line) for line in paragraph) + "</p>")
            paragraph.clear()

    def flush_list() -> None:
        if list_items:
            html_parts.append("<ul>" + "".join(f"<li>{item}</li>" for item in list_items) + "</ul>")
            list_items.clear()

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            flush_paragraph()
            flush_list()
            continue

        heading = re.match(r"^(#{1,3})\s+(.*)$", line)
        if heading:
            flush_paragraph()
            flush_list()
            level = len(heading.group(1))
            html_parts.append(f"<h{level}>{_md_inline(heading.group(2).strip())}</h{level}>")
            continue

        bullet = re.match(r"^[-*]\s+(.*)$", line)
        if bullet:
            flush_paragraph()
            list_items.append(_md_inline(bullet.group(1).strip()))
            continue

        # Plain text line accumulates into the current paragraph.
        flush_list()
        paragraph.append(line)

    flush_paragraph()
    flush_list()
    return "".join(html_parts)


def _resolve_description_html(
    description_html: str | None,
    description_stripped: str | None,
    description_markdown: str | None = None,
) -> str | None:
    """Resolve the description_html to persist.

    Plane recomputes description_stripped server-side from description_html on
    every save, so a stripped value sent on write is silently discarded. When the
    caller supplies only plain text, wrap it into minimal HTML so the description
    actually lands. description_html always wins when both are given.

    Precedence: description_html > description_markdown > description_stripped.
    description_markdown is converted to sanitized HTML via _markdown_to_html.
    """
    if description_html is not None:
        return description_html
    if description_markdown is not None:
        return _markdown_to_html(description_markdown)
    if description_stripped is not None:
        return "<p>" + escape(description_stripped).replace("\n", "<br/>") + "</p>"
    return None


def register_work_item_tools(mcp: FastMCP) -> None:
    """Register all work item-related tools with the MCP server."""

    @mcp.tool()
    def list_work_items(
        project_id: str | None = None,
        pql: Annotated[str | None, Field(description=PQL_FIELD_HINT)] = None,
        order_by: str | None = None,
        per_page: int | None = None,
        cursor: str | None = None,
        expand: str | None = None,
        fields: str | None = None,
        external_id: str | None = None,
        external_source: str | None = None,
    ) -> dict[str, Any]:
        """
        List work items with optional PQL filtering.

        Omit project_id to list across the entire workspace.
        Pass project_id to scope results to a single project.

        For UUID fields (assignee, state, label, cycle, module, type,
        milestone) call the relevant list tool first to get the UUID.

        Args:
            project_id: UUID of the project. Omit for workspace-wide results.
            pql: PQL filter. See field description for syntax.
            order_by: Sort field; prefix `-` for descending (e.g. `-created_at`).
            per_page: 1-100, default 25.
            cursor: From previous response's next_cursor.
            expand: Comma-separated relations to expand (e.g. assignees,labels,state).
            fields: Sparse fieldset — id, name, sequence_id, priority, state,
                project, assignees, labels, type_id, description_html, start_date,
                target_date, created_at, updated_at, created_by, is_draft. Use
                `project` (not `project_id`) and `description_html` (there is no
                `description` field). Any field you omit or misname comes back
                null — a null here does NOT mean the item lacks that value; it
                means it was not requested. To read the description, include
                description_html; for the type, include type_id.
            external_id / external_source: Filter by external system.

        Returns:
            results: Paginated list of work items.
            total_count: True DB total, not page-bounded — use for counts.
            next_cursor: Cursor for the next page.
            prev_cursor: Cursor for the previous page.
        """
        client, workspace_slug = get_plane_client_context()

        params = WorkItemQueryParams(
            pql=pql,
            order_by=order_by,
            per_page=per_page,
            cursor=cursor,
            expand=expand,
            fields=fields,
            external_id=external_id,
            external_source=external_source,
        )

        try:
            if project_id:
                response: PaginatedWorkItemResponse = client.work_items.list(
                    workspace_slug=workspace_slug,
                    project_id=project_id,
                    params=params,
                )
            else:
                response = client.work_items.list_workspace(
                    workspace_slug=workspace_slug,
                    params=params,
                )
        except HttpError as e:
            if pql and e.status_code == 400 and isinstance(e.response, dict) and "pql" in e.response:
                logger.warning("list_work_items: invalid PQL %r → %s", pql, e.response)
                return {
                    "error": e.response["pql"],
                    "failed_pql": pql,
                    "pql_reference": PQL_FULL_REFERENCE,
                    "hint": "The PQL above failed. Fix it using the reference and retry list_work_items.",
                }
            raise

        return {
            "results": [
                item.model_dump() if hasattr(item, "model_dump") else item for item in (response.results or [])
            ],
            "total_count": response.total_count,
            "count": response.count,
            "next_cursor": response.next_cursor,
            "prev_cursor": response.prev_cursor,
            "next_page_results": response.next_page_results,
            "prev_page_results": response.prev_page_results,
        }

    @mcp.tool()
    def count_work_items(
        pql: Annotated[str | None, Field(description=PQL_FIELD_HINT)] = None,
        group_by: str | None = None,
        sub_group_by: str | None = None,
    ) -> dict[str, Any]:
        """
        Count work items across the workspace with optional grouping.

        Use this for analytics — "how many urgent items?", "distribution by state?" —
        without fetching full work item payloads.

        Args:
            pql: PQL filter to scope the count (e.g. 'priority = "urgent"').
            group_by: Dimension to group counts by. Supported values:
                state_id, state__group, priority, project_id, type_id,
                labels__id, assignees__id, issue_module__module_id,
                release_work_items__release_id, cycle_id, milestone_id,
                created_by, target_date, start_date.
            sub_group_by: Second dimension for nested grouping (requires group_by).

        Returns:
            grouped_by: The group_by field used (null if none).
            sub_grouped_by: The sub_group_by field used (null if none).
            total_count: Total matching work items.
            grouped_counts: Dict of group_key → {count} or
                {total_count, sub_grouped_counts} when sub_group_by is set.
                Keys are UUIDs for FK fields, plain strings for priority/state__group,
                ISO dates for target_date/start_date, "None" for unset values.
        """
        client, workspace_slug = get_plane_client_context()
        params = WorkItemCountQueryParams(pql=pql, group_by=group_by, sub_group_by=sub_group_by)
        try:
            response: WorkItemGroupedCountResponse = client.work_items.count_workspace(
                workspace_slug=workspace_slug,
                params=params,
            )
        except HttpError as e:
            if pql and e.status_code == 400 and isinstance(e.response, dict) and "pql" in e.response:
                logger.warning("count_work_items: invalid PQL %r → %s", pql, e.response)
                return {
                    "error": e.response["pql"],
                    "failed_pql": pql,
                    "pql_reference": PQL_FULL_REFERENCE,
                    "hint": "The PQL above failed. Fix it using the reference and retry count_work_items.",
                }
            raise
        return response.model_dump()

    @mcp.tool()
    def create_work_item(
        project_id: str,
        name: str,
        assignees: list[str] | None = None,
        labels: list[str] | None = None,
        type_id: str | None = None,
        point: int | None = None,
        description_html: str | None = None,
        description_stripped: str | None = None,
        description_markdown: str | None = None,
        priority: str | None = None,
        start_date: str | None = None,
        target_date: str | None = None,
        sort_order: float | None = None,
        is_draft: bool | None = None,
        external_source: str | None = None,
        external_id: str | None = None,
        parent: str | None = None,
        state: str | None = None,
        estimate_point: str | None = None,
        type: str | None = None,
        module_id: str | None = None,
        cycle_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Create a new work item, optionally attaching it to a module and/or cycle.

        Args:
            project_id: UUID of the project
            name: Work item name (required)
            assignees: List of user IDs to assign to the work item
            labels: List of label IDs to attach to the work item
            type_id: UUID of the work item type
            point: Story point value
            description_html: HTML description of the work item
            description_stripped: Plain text description. Convenience only — it is
                wrapped into HTML and stored as description_html (Plane derives
                description_stripped server-side). Ignored if description_html is set.
            description_markdown: Markdown description. Convenience only — converted
                to sanitized HTML and stored as description_html. Supports #/##/###
                headings, blank-line-separated paragraphs, `-`/`*` bullet lists,
                **bold**, *italic*, and `inline code`. Ignored if description_html is
                set; wins over description_stripped.
            priority: Priority level (urgent, high, medium, low, none)
            start_date: Start date (ISO 8601 format)
            target_date: Target/end date (ISO 8601 format)
            sort_order: Sort order value
            is_draft: Whether the work item is a draft
            external_source: External system source name
            external_id: External system identifier
            parent: UUID of the parent work item
            state: UUID of the state
            estimate_point: Estimate point value
            type: Work item type identifier
            module_id: UUID of a module to attach the new item to (optional). The
                item is created first, then attached in a separate server call; if
                the attach fails the created item is still returned.
            cycle_id: UUID of a cycle to attach the new item to (optional). Same
                create-then-attach behaviour as module_id.

        Returns:
            A dict with:
              work_item: the created WorkItem (model_dump).
              module_attach: {attempted, ok, error} when module_id was given, else null.
              cycle_attach: {attempted, ok, error} when cycle_id was given, else null.
        """
        client, workspace_slug = get_plane_client_context()

        validated_priority: PriorityEnum | None = (
            priority if priority in get_args(PriorityEnum) else None  # type: ignore[assignment]
        )

        data = CreateWorkItem(
            name=name,
            assignees=assignees,
            labels=labels,
            type_id=type_id,
            point=point,
            description_html=_resolve_description_html(
                description_html, description_stripped, description_markdown
            ),
            priority=validated_priority,
            start_date=start_date,
            target_date=target_date,
            sort_order=sort_order,
            is_draft=is_draft,
            external_source=external_source,
            external_id=external_id,
            parent=parent,
            state=state,
            estimate_point=estimate_point,
            type=type,
        )

        created: WorkItem = client.work_items.create(
            workspace_slug=workspace_slug, project_id=project_id, data=data
        )

        # CreateWorkItem has extra="ignore" and drops any module/cycle fields, so
        # attach explicitly via the same SDK paths used by manage_module_work_items
        # and manage_cycle_work_items. A failed attach must not lose the created item.
        new_id = created.id
        module_attach: dict[str, Any] | None = None
        cycle_attach: dict[str, Any] | None = None

        if module_id is not None:
            module_attach = {"attempted": True, "ok": False, "error": None}
            if not new_id:
                module_attach["error"] = "created work item has no id; cannot attach to module"
            else:
                try:
                    client.modules.add_work_items(
                        workspace_slug=workspace_slug,
                        project_id=project_id,
                        module_id=module_id,
                        issue_ids=[new_id],
                    )
                    module_attach["ok"] = True
                except Exception as e:  # noqa: BLE001 - report, never lose the item
                    logger.warning("create_work_item: module attach failed for %s → %s", new_id, e)
                    module_attach["error"] = str(e)

        if cycle_id is not None:
            cycle_attach = {"attempted": True, "ok": False, "error": None}
            if not new_id:
                cycle_attach["error"] = "created work item has no id; cannot attach to cycle"
            else:
                try:
                    client.cycles.add_work_items(
                        workspace_slug=workspace_slug,
                        project_id=project_id,
                        cycle_id=cycle_id,
                        issue_ids=[new_id],
                    )
                    cycle_attach["ok"] = True
                except Exception as e:  # noqa: BLE001 - report, never lose the item
                    logger.warning("create_work_item: cycle attach failed for %s → %s", new_id, e)
                    cycle_attach["error"] = str(e)

        return {
            "work_item": created.model_dump() if hasattr(created, "model_dump") else created,
            "module_attach": module_attach,
            "cycle_attach": cycle_attach,
        }

    @mcp.tool()
    def retrieve_work_item(
        project_id: str,
        work_item_id: str,
        expand: str | None = None,
        fields: str | None = None,
        external_id: str | None = None,
        external_source: str | None = None,
        order_by: str | None = None,
    ) -> WorkItemDetail:
        """
        Retrieve a work item by ID.

        Args:
            project_id: UUID of the project
            work_item_id: UUID of the work item
            expand: Comma-separated fields to expand (e.g., "assignees,labels,state")
            fields: Comma-separated fields to include in response
            external_id: External system identifier for filtering
            external_source: External system source name for filtering
            order_by: Field to order results by

        Returns:
            WorkItemDetail object with expanded relationships
        """
        client, workspace_slug = get_plane_client_context()

        params = RetrieveQueryParams(
            expand=expand,
            fields=fields,
            external_id=external_id,
            external_source=external_source,
            order_by=order_by,
        )

        return client.work_items.retrieve(
            workspace_slug=workspace_slug,
            project_id=project_id,
            work_item_id=work_item_id,
            params=params,
        )

    @mcp.tool()
    def retrieve_work_item_by_identifier(
        work_item_identifier: str,
        expand: str | None = None,
        fields: str | None = None,
        external_id: str | None = None,
        external_source: str | None = None,
        order_by: str | None = None,
    ) -> WorkItemDetail:
        """
        Retrieve a work item by its full identifier (project prefix + sequence number).

        The identifier must be in PROJECT-N format where PROJECT is the project's
        identifier string and N is the sequence number. Both parts are required.

        Valid sparse `fields` values include: id, name, sequence_id, priority,
        state, project, workspace, parent, assignees, labels, type_id,
        start_date, target_date, created_at, updated_at, created_by,
        updated_by, is_draft, external_source, external_id, estimate_point.
        Use `project` (not `project_id`) to get the project UUID.

        If you need the project UUID from a short identifier like "SHO",
        use `list_projects()` instead — it returns `id` and `identifier`
        for every project.

        Args:
            work_item_identifier: Full work item identifier in PROJECT-N format
            expand: Comma-separated fields to expand (e.g., "assignees,labels,state")
            fields: Comma-separated sparse fieldset (see valid values above)
            external_id: External system identifier for filtering
            external_source: External system source name for filtering
            order_by: Field to order results by

        Returns:
            WorkItemDetail object with expanded relationships
        """
        parts = work_item_identifier.rsplit("-", 1)
        if len(parts) != 2 or not parts[1].isdigit():
            raise ValueError(
                f"Invalid work item identifier {work_item_identifier!r}. "
                "Expected PROJECT-N format where N is the sequence number."
            )
        project_identifier, sequence_str = parts
        client, workspace_slug = get_plane_client_context()

        params = RetrieveQueryParams(
            expand=expand,
            fields=fields,
            external_id=external_id,
            external_source=external_source,
            order_by=order_by,
        )

        return client.work_items.retrieve_by_identifier(
            workspace_slug=workspace_slug,
            project_identifier=project_identifier,
            issue_identifier=int(sequence_str),
            params=params,
        )

    @mcp.tool()
    def update_work_item(
        project_id: str,
        work_item_id: str,
        name: str | None = None,
        assignees: list[str] | None = None,
        labels: list[str] | None = None,
        type_id: str | None = None,
        point: int | None = None,
        description_html: str | None = None,
        description_stripped: str | None = None,
        description_markdown: str | None = None,
        priority: str | None = None,
        start_date: str | None = None,
        target_date: str | None = None,
        sort_order: float | None = None,
        is_draft: bool | None = None,
        external_source: str | None = None,
        external_id: str | None = None,
        parent: str | None = None,
        state: str | None = None,
        estimate_point: str | None = None,
        type: str | None = None,
    ) -> WorkItem:
        """
        Update a work item by ID.

        Args:
            project_id: UUID of the project
            work_item_id: UUID of the work item
            name: Work item name
            assignees: List of user IDs to assign to the work item
            labels: List of label IDs to attach to the work item
            type_id: UUID of the work item type
            point: Story point value
            description_html: HTML description of the work item
            description_stripped: Plain text description. Convenience only — it is
                wrapped into HTML and stored as description_html (Plane derives
                description_stripped server-side). Ignored if description_html is set.
            description_markdown: Markdown description. Convenience only — converted
                to sanitized HTML and stored as description_html. Supports #/##/###
                headings, blank-line-separated paragraphs, `-`/`*` bullet lists,
                **bold**, *italic*, and `inline code`. Ignored if description_html is
                set; wins over description_stripped.
            priority: Priority level (urgent, high, medium, low, none)
            start_date: Start date (ISO 8601 format)
            target_date: Target/end date (ISO 8601 format)
            sort_order: Sort order value
            is_draft: Whether the work item is a draft
            external_source: External system source name
            external_id: External system identifier
            parent: UUID of the parent work item
            state: UUID of the state
            estimate_point: Estimate point value
            type: Work item type identifier

        Returns:
            Updated WorkItem object
        """
        client, workspace_slug = get_plane_client_context()

        validated_priority: PriorityEnum | None = (
            priority if priority in get_args(PriorityEnum) else None  # type: ignore[assignment]
        )

        data = UpdateWorkItem(
            name=name,
            assignees=assignees,
            labels=labels,
            type_id=type_id,
            point=point,
            description_html=_resolve_description_html(
                description_html, description_stripped, description_markdown
            ),
            priority=validated_priority,
            start_date=start_date,
            target_date=target_date,
            sort_order=sort_order,
            is_draft=is_draft,
            external_source=external_source,
            external_id=external_id,
            parent=parent,
            state=state,
            estimate_point=estimate_point,
            type=type,
        )

        return client.work_items.update(
            workspace_slug=workspace_slug,
            project_id=project_id,
            work_item_id=work_item_id,
            data=data,
        )

    @mcp.tool()
    def bulk_create_work_items(project_id: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Create many work items in one MCP call.

        This is a convenience wrapper: it is ONE MCP call but performs N server
        round-trips (one create per element), so it is not transactional —
        earlier items may succeed while a later one fails. Each element is
        processed independently and its outcome reported in order.

        Each element of `items` is a dict of work item fields. `name` is
        required; supported keys mirror create_work_item (excluding project_id,
        which comes from the top-level argument): name, assignees, labels,
        type_id, point, description_html, description_stripped,
        description_markdown, priority, start_date, target_date, sort_order,
        is_draft, external_source, external_id, parent, state, estimate_point,
        type. (Per-item module_id/cycle_id attach is not supported here — create
        the item then use manage_module_work_items / manage_cycle_work_items.)

        Args:
            project_id: UUID of the project all items are created in.
            items: List of work item field dicts (see above).

        Returns:
            A list of result dicts in input order, each:
              {index, ok: True, id: <new work item id>} on success, or
              {index, ok: False, error: <message>} on failure.
        """
        client, workspace_slug = get_plane_client_context()
        results: list[dict[str, Any]] = []
        for index, item in enumerate(items):
            try:
                fields = dict(item)
                fields.pop("project_id", None)
                fields.pop("module_id", None)
                fields.pop("cycle_id", None)
                priority = fields.pop("priority", None)
                validated_priority: PriorityEnum | None = (
                    priority if priority in get_args(PriorityEnum) else None  # type: ignore[assignment]
                )
                description_html = fields.pop("description_html", None)
                description_stripped = fields.pop("description_stripped", None)
                description_markdown = fields.pop("description_markdown", None)
                data = CreateWorkItem(
                    priority=validated_priority,
                    description_html=_resolve_description_html(
                        description_html, description_stripped, description_markdown
                    ),
                    **fields,
                )
                created: WorkItem = client.work_items.create(
                    workspace_slug=workspace_slug, project_id=project_id, data=data
                )
                results.append({"index": index, "ok": True, "id": created.id})
            except Exception as e:  # noqa: BLE001 - report per-item, keep going
                logger.warning("bulk_create_work_items: item %d failed → %s", index, e)
                results.append({"index": index, "ok": False, "error": str(e)})
        return results

    @mcp.tool()
    def bulk_update_work_items(updates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Update many work items in one MCP call.

        This is a convenience wrapper: it is ONE MCP call but performs N server
        round-trips (one update per element), so it is not transactional —
        earlier updates may succeed while a later one fails. Each element is
        processed independently and its outcome reported in order.

        Each element of `updates` is a dict that MUST contain `project_id` and
        `work_item_id`; the remaining keys are update fields mirroring
        update_work_item: name, assignees, labels, type_id, point,
        description_html, description_stripped, description_markdown, priority,
        start_date, target_date, sort_order, is_draft, external_source,
        external_id, parent, state, estimate_point, type.

        Args:
            updates: List of update dicts; each needs project_id + work_item_id.

        Returns:
            A list of result dicts in input order, each:
              {index, ok: True, id: <work item id>} on success, or
              {index, ok: False, error: <message>} on failure.
        """
        client, workspace_slug = get_plane_client_context()
        results: list[dict[str, Any]] = []
        for index, update in enumerate(updates):
            try:
                fields = dict(update)
                upd_project_id = fields.pop("project_id", None)
                work_item_id = fields.pop("work_item_id", None)
                if not upd_project_id or not work_item_id:
                    raise ValueError("each update must include project_id and work_item_id")
                priority = fields.pop("priority", None)
                validated_priority: PriorityEnum | None = (
                    priority if priority in get_args(PriorityEnum) else None  # type: ignore[assignment]
                )
                description_html = fields.pop("description_html", None)
                description_stripped = fields.pop("description_stripped", None)
                description_markdown = fields.pop("description_markdown", None)
                data = UpdateWorkItem(
                    priority=validated_priority,
                    description_html=_resolve_description_html(
                        description_html, description_stripped, description_markdown
                    ),
                    **fields,
                )
                client.work_items.update(
                    workspace_slug=workspace_slug,
                    project_id=upd_project_id,
                    work_item_id=work_item_id,
                    data=data,
                )
                results.append({"index": index, "ok": True, "id": work_item_id})
            except Exception as e:  # noqa: BLE001 - report per-item, keep going
                logger.warning("bulk_update_work_items: item %d failed → %s", index, e)
                results.append({"index": index, "ok": False, "error": str(e)})
        return results

    @mcp.tool()
    def delete_work_item(project_id: str, work_item_id: str) -> None:
        """
        Delete a work item by ID.

        Args:
            project_id: UUID of the project
            work_item_id: UUID of the work item
        """
        client, workspace_slug = get_plane_client_context()
        client.work_items.delete(workspace_slug=workspace_slug, project_id=project_id, work_item_id=work_item_id)

    @mcp.tool()
    def manage_work_item_assignee(
        project_id: str,
        work_item_id: str,
        add_user_id: str | None = None,
        remove_user_id: str | None = None,
    ) -> WorkItem:
        """
        Add or remove a single assignee on a work item without replacing the full list.

        Provide add_user_id, remove_user_id, or both. If both are given the
        removal is applied first, then the addition. Already-assigned users in
        add_user_id are silently skipped.

        Args:
            project_id: UUID of the project
            work_item_id: UUID of the work item
            add_user_id: UUID of the user to add as assignee
            remove_user_id: UUID of the user to remove from assignees

        Returns:
            Updated WorkItem object
        """
        client, workspace_slug = get_plane_client_context()
        current = client.work_items.retrieve(
            workspace_slug=workspace_slug, project_id=project_id, work_item_id=work_item_id
        )
        ids = [u.id for u in (current.assignees or []) if u.id]
        if remove_user_id:
            ids = [uid for uid in ids if uid != remove_user_id]
        if add_user_id and add_user_id not in ids:
            ids.append(add_user_id)
        return client.work_items.update(
            workspace_slug=workspace_slug,
            project_id=project_id,
            work_item_id=work_item_id,
            data=UpdateWorkItem(assignees=ids),
        )

    @mcp.tool()
    def manage_work_item_label(
        project_id: str,
        work_item_id: str,
        add_label_id: str | None = None,
        remove_label_id: str | None = None,
    ) -> WorkItem:
        """
        Add or remove a single label on a work item without replacing the full list.

        Provide add_label_id, remove_label_id, or both. If both are given the
        removal is applied first, then the addition. Already-attached labels in
        add_label_id are silently skipped.

        Args:
            project_id: UUID of the project
            work_item_id: UUID of the work item
            add_label_id: UUID of the label to add
            remove_label_id: UUID of the label to remove

        Returns:
            Updated WorkItem object
        """
        client, workspace_slug = get_plane_client_context()
        current = client.work_items.retrieve(
            workspace_slug=workspace_slug, project_id=project_id, work_item_id=work_item_id
        )
        ids = [lb.id for lb in (current.labels or []) if lb.id]
        if remove_label_id:
            ids = [lid for lid in ids if lid != remove_label_id]
        if add_label_id and add_label_id not in ids:
            ids.append(add_label_id)
        return client.work_items.update(
            workspace_slug=workspace_slug,
            project_id=project_id,
            work_item_id=work_item_id,
            data=UpdateWorkItem(labels=ids),
        )

    @mcp.tool()
    def list_archived_work_items(
        project_id: str,
        pql: Annotated[str | None, Field(description=PQL_FIELD_HINT)] = None,
        order_by: str | None = None,
        per_page: int | None = None,
        cursor: str | None = None,
        expand: str | None = None,
        fields: str | None = None,
    ) -> dict[str, Any]:
        """
        List archived work items in a project with optional PQL filtering.

        Args:
            project_id: UUID of the project
            pql: PQL filter expression. Omit to list all archived items.
            order_by: Field to sort by; prefix with `-` for descending
                (default `-archived_at`).
            per_page: Results per page, 1-100 (default 100).
            cursor: Pagination cursor from a previous response's `next_cursor`.
            expand: Comma-separated related fields to expand.
            fields: Comma-separated sparse fieldset.

        Returns:
            Paginated envelope with results, total_count, next_cursor, prev_cursor.
        """
        client, workspace_slug = get_plane_client_context()
        params = WorkItemQueryParams(
            pql=pql,
            order_by=order_by,
            per_page=per_page,
            cursor=cursor,
            expand=expand,
            fields=fields,
        )
        try:
            response = client.work_items.list_archived(
                workspace_slug=workspace_slug,
                project_id=project_id,
                params=params,
            )
        except HttpError as e:
            if pql and e.status_code == 400 and isinstance(e.response, dict) and "pql" in e.response:
                logger.warning("list_archived_work_items: invalid PQL %r → %s", pql, e.response)
                return {
                    "error": e.response["pql"],
                    "failed_pql": pql,
                    "pql_reference": PQL_FULL_REFERENCE,
                    "hint": "The PQL above failed. Fix it using the reference and retry list_archived_work_items.",
                }
            raise
        return {
            "results": [
                item.model_dump() if hasattr(item, "model_dump") else item for item in (response.results or [])
            ],
            "total_count": response.total_count,
            "count": response.count,
            "next_cursor": response.next_cursor,
            "prev_cursor": response.prev_cursor,
            "next_page_results": response.next_page_results,
            "prev_page_results": response.prev_page_results,
        }

    @mcp.tool()
    def manage_work_item_archive(project_id: str, work_item_id: str, archive: bool) -> None:
        """
        Archive or unarchive a work item.

        Only work items in a completed or cancelled state can be archived.
        Archived work items no longer appear in active work item lists.

        Args:
            project_id: UUID of the project
            work_item_id: UUID of the work item
            archive: True to archive the work item, False to unarchive it
        """
        client, workspace_slug = get_plane_client_context()
        if archive:
            client.work_items.archive(
                workspace_slug=workspace_slug,
                project_id=project_id,
                work_item_id=work_item_id,
            )
        else:
            client.work_items.unarchive(
                workspace_slug=workspace_slug,
                project_id=project_id,
                work_item_id=work_item_id,
            )

    @mcp.tool()
    def search_work_items(
        query: str,
        expand: str | None = None,
        fields: str | None = None,
        external_id: str | None = None,
        external_source: str | None = None,
        order_by: str | None = None,
    ) -> WorkItemSearch:
        """
        Search work items by text across a workspace.

        Use this for free-text name/description search. For structured
        filtering (priority, state, assignee, dates, etc.) use
        `list_work_items` with a PQL expression.

        Args:
            query: Free-text search string across work item name and description
            expand: Comma-separated list of related fields to expand in response
            fields: Comma-separated list of fields to include in response
            external_id: External system identifier for filtering
            external_source: External system source name for filtering
            order_by: Field to order results by. Prefix with '-' for descending

        Returns:
            WorkItemSearch object containing search results
        """
        client, workspace_slug = get_plane_client_context()

        params = RetrieveQueryParams(
            expand=expand,
            fields=fields,
            external_id=external_id,
            external_source=external_source,
            order_by=order_by,
        )

        return client.work_items.search(workspace_slug=workspace_slug, query=query, params=params)

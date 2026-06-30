"""View-related tools for Plane MCP Server.

Views are saved filters (work item / page filter configurations). A view may be
scoped to a single project or to the whole workspace. Pass ``project_id`` to
operate on a project view; omit it to operate on a workspace view.
"""

from typing import Any

from fastmcp import FastMCP
from plane.models.views import CreateView, UpdateView, View

from plane_mcp.client import get_plane_client_context


def register_view_tools(mcp: FastMCP) -> None:
    """Register all view-related tools with the MCP server."""

    @mcp.tool()
    def list_views(
        project_id: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> list[View]:
        """
        List views (saved filters).

        Lists a project's views if project_id is given, otherwise workspace-level
        views.

        Args:
            project_id: UUID of the project. Omit to list workspace views.
            params: Optional query parameters as a dictionary

        Returns:
            List of View objects
        """
        client, workspace_slug = get_plane_client_context()
        return client.views.list(
            workspace_slug=workspace_slug,
            project_id=project_id,
            params=params,
        )

    @mcp.tool()
    def create_view(
        name: str,
        filters: dict[str, Any] | None = None,
        rich_filters: dict[str, Any] | None = None,
        display_filters: dict[str, Any] | None = None,
        description: str | None = None,
        query: dict[str, Any] | None = None,
        access: int | None = None,
        project_id: str | None = None,
    ) -> View:
        """
        Create a view (saved filter).

        Creates a project view if project_id is given, otherwise a
        workspace-level view.

        Args:
            name: Name of the view
            filters: The saved filter — THIS is what makes a view non-empty. A dict
                mapping filter keys to LISTS of values (always lists, even for one
                value). Supported keys:
                  priority     -> list of "urgent"|"high"|"medium"|"low"|"none"
                  state        -> list of state UUIDs (see list_states)
                  state_group  -> list of "backlog"|"unstarted"|"started"|"completed"|"cancelled"
                  assignees    -> list of member UUIDs (see get_project_members)
                  created_by   -> list of member UUIDs
                  labels       -> list of label UUIDs (see list_labels)
                  cycle        -> list of cycle UUIDs;  module -> list of module UUIDs
                  type         -> list of work-item-type UUIDs (see list_work_item_types)
                  subscriber / mentions / parent -> list of UUIDs
                  start_date / target_date / created_at -> list of date terms
                Example: {"priority": ["urgent", "high"], "assignees": ["<member-uuid>"],
                          "labels": ["<label-uuid>"]}
                Omit or pass {} for a view with no filter (an "empty" view).
            rich_filters: THE field the Plane UI renders the work-item list from
                (`filters`/`query` are legacy and do NOT drive the UI list — a view
                with only `filters` shows up EMPTY in the UI). Use Django-ORM-style
                keys, e.g.:
                  {"priority__in": ["urgent","high"], "assignees__in": ["<member-uuid>"],
                   "state__group__in": ["backlog","unstarted","started"], "labels__in": ["<label-uuid>"]}
                If omitted it auto-derives from `filters`. To make a view that actually
                shows a filtered list in the UI, SET THIS (or `filters`).
            display_filters: Display/layout config dict (group_by, order_by, layout, etc.).
                Optional; controls presentation, not which items match.
            description: Description of the view
            query: IGNORED on write — the server computes the live `query` from `filters`
                automatically. Do NOT set this; set `filters` instead.
            access: Access level (0 = Private, 1 = Public)
            project_id: UUID of the project. Omit to create a workspace view.

        Returns:
            Created View object (its `filters` echoes what you sent; `query` is derived).
        """
        client, workspace_slug = get_plane_client_context()

        data_kwargs: dict[str, Any] = {"name": name}
        if filters is not None:
            data_kwargs["filters"] = filters
        # rich_filters is the field the Plane UI renders the work-item list from
        # (filters/query are legacy). Use the explicit value, else fall back to
        # `filters` so the view is not empty in the UI.
        effective_rich = rich_filters if rich_filters is not None else filters
        if effective_rich is not None:
            data_kwargs["rich_filters"] = effective_rich
        if display_filters is not None:
            data_kwargs["display_filters"] = display_filters
        if description is not None:
            data_kwargs["description"] = description
        if query is not None:
            data_kwargs["query"] = query
        if access is not None:
            data_kwargs["access"] = access

        return client.views.create(
            workspace_slug=workspace_slug,
            data=CreateView(**data_kwargs),
            project_id=project_id,
        )

    @mcp.tool()
    def retrieve_view(
        view_id: str,
        project_id: str | None = None,
    ) -> View:
        """
        Retrieve a view by ID.

        Retrieves a project view if project_id is given, otherwise a workspace
        view.

        Args:
            view_id: UUID of the view
            project_id: UUID of the project. Omit for a workspace view.

        Returns:
            View object
        """
        client, workspace_slug = get_plane_client_context()
        return client.views.retrieve(
            workspace_slug=workspace_slug,
            view_id=view_id,
            project_id=project_id,
        )

    @mcp.tool()
    def update_view(
        view_id: str,
        name: str | None = None,
        filters: dict[str, Any] | None = None,
        rich_filters: dict[str, Any] | None = None,
        display_filters: dict[str, Any] | None = None,
        description: str | None = None,
        query: dict[str, Any] | None = None,
        access: int | None = None,
        project_id: str | None = None,
    ) -> View:
        """
        Update a view (saved filter).

        Updates a project view if project_id is given, otherwise a workspace
        view.

        Args:
            view_id: UUID of the view
            name: Name of the view
            filters: The saved filter (same schema as create_view — a dict of filter
                keys to LISTS, e.g. {"priority": ["urgent"], "assignees": ["<uuid>"]}).
                This is what populates the view; passing it replaces the stored filter.
            rich_filters: THE field the Plane UI renders the list from (see create_view).
                Set this (ORM-style keys, e.g. {"priority__in": ["urgent"]}) to change
                what the view shows; auto-derives from `filters` if omitted.
            display_filters: Display/layout config dict (group_by, order_by, layout).
            description: Description of the view
            query: IGNORED on write — the server derives `query` from `filters`. Set
                `filters`, not `query`.
            access: Access level (0 = Private, 1 = Public)
            project_id: UUID of the project. Omit for a workspace view.

        Returns:
            Updated View object
        """
        client, workspace_slug = get_plane_client_context()

        data_kwargs: dict[str, Any] = {}
        if name is not None:
            data_kwargs["name"] = name
        if filters is not None:
            data_kwargs["filters"] = filters
        # rich_filters drives the Plane UI list (see create_view). Explicit value
        # wins; otherwise fall back to `filters` when that was supplied.
        effective_rich = rich_filters if rich_filters is not None else filters
        if effective_rich is not None:
            data_kwargs["rich_filters"] = effective_rich
        if display_filters is not None:
            data_kwargs["display_filters"] = display_filters
        if description is not None:
            data_kwargs["description"] = description
        if query is not None:
            data_kwargs["query"] = query
        if access is not None:
            data_kwargs["access"] = access

        return client.views.update(
            workspace_slug=workspace_slug,
            view_id=view_id,
            data=UpdateView(**data_kwargs),
            project_id=project_id,
        )

    @mcp.tool()
    def delete_view(
        view_id: str,
        project_id: str | None = None,
    ) -> None:
        """
        Delete a view (saved filter).

        Deletes a project view if project_id is given, otherwise a workspace
        view.

        Args:
            view_id: UUID of the view
            project_id: UUID of the project. Omit for a workspace view.
        """
        client, workspace_slug = get_plane_client_context()
        client.views.delete(
            workspace_slug=workspace_slug,
            view_id=view_id,
            project_id=project_id,
        )

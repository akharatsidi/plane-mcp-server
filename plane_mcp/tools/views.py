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
            filters: Filter configuration dictionary
            display_filters: Display filter configuration dictionary
            description: Description of the view
            query: Query configuration dictionary
            access: Access level (0 = Private, 1 = Public)
            project_id: UUID of the project. Omit to create a workspace view.

        Returns:
            Created View object
        """
        client, workspace_slug = get_plane_client_context()

        data_kwargs: dict[str, Any] = {"name": name}
        if filters is not None:
            data_kwargs["filters"] = filters
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
            filters: Filter configuration dictionary
            display_filters: Display filter configuration dictionary
            description: Description of the view
            query: Query configuration dictionary
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

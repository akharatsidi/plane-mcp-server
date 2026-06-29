"""Page-related tools for Plane MCP Server."""

from typing import Any, Literal

from fastmcp import FastMCP
from plane.models.pages import CreatePage, Page
from plane.models.work_item_pages import CreateWorkItemPage, WorkItemPage

from plane_mcp.client import get_plane_client_context


def register_page_tools(mcp: FastMCP) -> None:
    """Register all page-related tools with the MCP server."""

    @mcp.tool()
    def list_pages(
        project_id: str | None = None,
        params: dict[str, Any] | None = None,
        include_archived: bool = False,
    ) -> list[Page]:
        """
        List pages.

        Lists a project's pages if project_id is given, otherwise workspace-level pages.

        Args:
            project_id: UUID of the project. Omit to list workspace pages.
            params: Optional query parameters as a dictionary (e.g., per_page, cursor)
            include_archived: If True, also include archived pages
                (default False — only active pages).

        Returns:
            List of Page objects
        """
        client, workspace_slug = get_plane_client_context()
        if project_id is not None:
            response = client.pages.list_project_pages(
                workspace_slug=workspace_slug,
                project_id=project_id,
                params=params,
                include_archived=include_archived,
            )
        else:
            response = client.pages.list_workspace_pages(
                workspace_slug=workspace_slug, params=params, include_archived=include_archived
            )
        return response.results

    @mcp.tool()
    def attach_page_to_work_item(
        project_id: str,
        work_item_id: str,
        page_id: str,
    ) -> WorkItemPage:
        """
        Link a page to a work item.

        Args:
            project_id: UUID of the project
            work_item_id: UUID of the work item
            page_id: UUID of the page to link

        Returns:
            WorkItemPage link object
        """
        client, workspace_slug = get_plane_client_context()
        return client.work_items.pages.create(
            workspace_slug=workspace_slug,
            project_id=project_id,
            work_item_id=work_item_id,
            data=CreateWorkItemPage(page_id=page_id),
        )

    @mcp.tool()
    def list_work_item_pages(
        project_id: str,
        work_item_id: str,
    ) -> list[WorkItemPage]:
        """
        List all pages linked to a work item.

        Args:
            project_id: UUID of the project
            work_item_id: UUID of the work item

        Returns:
            List of WorkItemPage link objects
        """
        client, workspace_slug = get_plane_client_context()
        response = client.work_items.pages.list(
            workspace_slug=workspace_slug,
            project_id=project_id,
            work_item_id=work_item_id,
        )
        return response.results

    @mcp.tool()
    def detach_page_from_work_item(
        project_id: str,
        work_item_id: str,
        work_item_page_id: str,
    ) -> None:
        """
        Remove a page link from a work item.

        Args:
            project_id: UUID of the project
            work_item_id: UUID of the work item
            work_item_page_id: UUID of the LINK record (NOT the page_id). The link
                has its own UUID, returned by attach_page_to_work_item; find it via
                list_work_item_pages(work_item_id).
        """
        client, workspace_slug = get_plane_client_context()
        client.work_items.pages.delete(
            workspace_slug=workspace_slug,
            project_id=project_id,
            work_item_id=work_item_id,
            work_item_page_id=work_item_page_id,
        )

    @mcp.tool()
    def retrieve_page(
        page_id: str,
        project_id: str | None = None,
    ) -> Page:
        """
        Retrieve a page by ID.

        Retrieves a project page if project_id is given, otherwise a workspace page.

        Args:
            page_id: UUID of the page
            project_id: UUID of the project. Omit for a workspace page.

        Returns:
            Page object
        """
        client, workspace_slug = get_plane_client_context()

        if project_id is not None:
            return client.pages.retrieve_project_page(
                workspace_slug=workspace_slug,
                project_id=project_id,
                page_id=page_id,
            )
        return client.pages.retrieve_workspace_page(
            workspace_slug=workspace_slug,
            page_id=page_id,
        )

    @mcp.tool()
    def create_page(
        name: str,
        description_html: str,
        project_id: str | None = None,
        access: int | None = None,
        color: str | None = None,
        is_locked: bool | None = None,
        archived_at: str | None = None,
        view_props: dict[str, Any] | None = None,
        logo_props: dict[str, Any] | None = None,
        external_id: str | None = None,
        external_source: str | None = None,
    ) -> Page:
        """
        Create a page.

        Creates a project page if project_id is given, otherwise a
        workspace-level page.

        Args:
            name: Page name
            description_html: Page content in HTML. REQUIRED and must be non-empty
                (Plane rejects empty strings — pass "<p></p>" or " " for an empty page).
            project_id: UUID of the project. Omit to create a workspace page.
            access: Access level for the page (integer)
            color: Page color
            is_locked: Whether the page is locked
            archived_at: Archive timestamp (ISO 8601 format)
            view_props: View properties dictionary
            logo_props: Logo properties dictionary
            external_id: External system identifier
            external_source: External system source name

        Returns:
            Created Page object
        """
        client, workspace_slug = get_plane_client_context()

        data = CreatePage(
            name=name,
            description_html=description_html,
            access=access,
            color=color,
            is_locked=is_locked,
            archived_at=archived_at,
            view_props=view_props,
            logo_props=logo_props,
            external_id=external_id,
            external_source=external_source,
        )

        if project_id is not None:
            return client.pages.create_project_page(
                workspace_slug=workspace_slug,
                project_id=project_id,
                data=data,
            )
        return client.pages.create_workspace_page(
            workspace_slug=workspace_slug,
            data=data,
        )

    @mcp.tool()
    def update_page(
        project_id: str,
        page_id: str,
        name: str | None = None,
        description_html: str | None = None,
        access: int | None = None,
        is_locked: bool | None = None,
    ) -> Page:
        """
        Update a project page's title, content, access or lock state (PATCH).

        At least one of name / description_html / access / is_locked must be
        provided; omitted fields are left unchanged.

        Args:
            project_id: UUID of the project the page belongs to.
            page_id: UUID of the page to update.
            name: New title.
            description_html: New HTML content. Must be non-empty if provided.
            access: 0 = public (workspace), 1 = private (creator only).
            is_locked: If True, the page becomes read-only.

        Returns:
            Updated Page object.
        """
        client, workspace_slug = get_plane_client_context()
        body: dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if description_html is not None:
            if not description_html.strip():
                raise ValueError("description_html must be non-empty")
            body["description_html"] = description_html
        if access is not None:
            body["access"] = access
        if is_locked is not None:
            body["is_locked"] = is_locked
        if not body:
            raise ValueError("provide at least one field to update")
        return client.pages.update_project_page(
            workspace_slug=workspace_slug,
            project_id=project_id,
            page_id=page_id,
            data=body,
        )

    @mcp.tool()
    def delete_page(
        page_id: str,
        project_id: str | None = None,
    ) -> None:
        """
        Permanently delete a page. Irreversible — consider manage_page_archive
        (action='archive') if you might want to restore it.

        Deletes a project page if project_id is given, otherwise a workspace page.

        Args:
            page_id: UUID of the page to delete.
            project_id: UUID of the project. Omit for a workspace page.
        """
        client, workspace_slug = get_plane_client_context()
        if project_id is not None:
            client.pages.delete_project_page(
                workspace_slug=workspace_slug, project_id=project_id, page_id=page_id
            )
        else:
            client.pages.delete_workspace_page(workspace_slug=workspace_slug, page_id=page_id)

    @mcp.tool()
    def manage_page_archive(
        project_id: str,
        page_id: str,
        action: Literal["archive", "unarchive"],
    ) -> Any:
        """
        Archive or unarchive a project page (soft delete).

        Archived pages are hidden from list_pages() unless include_archived=True.
        Reversible via action='unarchive'.

        Args:
            project_id: UUID of the project.
            page_id: UUID of the page.
            action: 'archive' or 'unarchive'.

        Returns:
            {"archived_at": <date|null>}.
        """
        client, workspace_slug = get_plane_client_context()
        if action == "archive":
            return client.pages.archive_project_page(
                workspace_slug=workspace_slug, project_id=project_id, page_id=page_id
            )
        if action == "unarchive":
            return client.pages.unarchive_project_page(
                workspace_slug=workspace_slug, project_id=project_id, page_id=page_id
            )
        raise ValueError(f"action must be 'archive' or 'unarchive', got {action!r}")

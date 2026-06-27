"""Project member management tools for Plane MCP Server.

These tools write to a project's membership roster. They require the calling
PAT to hold the project ADMIN role; if it does not, the backend returns HTTP
403 which surfaces to the caller.

Role values are integers:
    ADMIN  = 20
    MEMBER = 15
    GUEST  = 5

UUID note:
    member_id  = the workspace user's id (the user you want to add to the project).
    member_pk  = the ProjectMember row id returned by add_project_member and by
                 listing project members. Use member_pk (NOT member_id) for the
                 update/remove operations.
"""

from typing import Any

from fastmcp import FastMCP

from plane_mcp.client import get_plane_client_context


def register_member_tools(mcp: FastMCP) -> None:
    """Register all project member-related tools with the MCP server."""

    @mcp.tool()
    def add_project_member(project_id: str, member_id: str, role: int) -> Any:
        """
        Add a workspace user to a project with a given role.

        Requires the PAT to hold the project ADMIN role (a 403 surfaces if it
        does not).

        Role values are integers:
            ADMIN  = 20
            MEMBER = 15
            GUEST  = 5

        Args:
            project_id: UUID of the project
            member_id: UUID of the workspace user to add (the user's id)
            role: Role to grant — ADMIN=20, MEMBER=15, GUEST=5

        Returns:
            The created ProjectMember record (dict). Its id is the member_pk to
            use for update_project_member_role / remove_project_member.
        """
        client, workspace_slug = get_plane_client_context()
        return client.projects.add_member(
            workspace_slug=workspace_slug,
            project_id=project_id,
            member_id=member_id,
            role=role,
        )

    @mcp.tool()
    def update_project_member_role(project_id: str, member_pk: str, role: int) -> Any:
        """
        Change the role of an existing project member.

        Requires the PAT to hold the project ADMIN role (a 403 surfaces if it
        does not).

        Role values are integers:
            ADMIN  = 20
            MEMBER = 15
            GUEST  = 5

        Args:
            project_id: UUID of the project
            member_pk: UUID of the ProjectMember row (returned by
                add_project_member or by listing project members — NOT the
                workspace user's id)
            role: New role — ADMIN=20, MEMBER=15, GUEST=5

        Returns:
            The updated ProjectMember record (dict).
        """
        client, workspace_slug = get_plane_client_context()
        return client.projects.update_member(
            workspace_slug=workspace_slug,
            project_id=project_id,
            member_pk=member_pk,
            role=role,
        )

    @mcp.tool()
    def remove_project_member(project_id: str, member_pk: str) -> Any:
        """
        Remove a member from a project.

        Requires the PAT to hold the project ADMIN role (a 403 surfaces if it
        does not).

        Role values are integers:
            ADMIN  = 20
            MEMBER = 15
            GUEST  = 5

        Args:
            project_id: UUID of the project
            member_pk: UUID of the ProjectMember row (returned by
                add_project_member or by listing project members — NOT the
                workspace user's id)
        """
        client, workspace_slug = get_plane_client_context()
        return client.projects.remove_member(
            workspace_slug=workspace_slug,
            project_id=project_id,
            member_pk=member_pk,
        )

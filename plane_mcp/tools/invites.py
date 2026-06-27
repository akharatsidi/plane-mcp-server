"""Workspace invitation tools for Plane MCP Server.

These tools manage pending invitations to the workspace. They require the
calling PAT to hold the workspace OWNER role; if it does not, the backend
returns HTTP 403 which surfaces to the caller.

Role values are integers:
    ADMIN  = 20
    MEMBER = 15
    GUEST  = 5
"""

from typing import Any

from fastmcp import FastMCP

from plane_mcp.client import get_plane_client_context


def register_invite_tools(mcp: FastMCP) -> None:
    """Register all workspace invitation-related tools with the MCP server."""

    @mcp.tool()
    def invite_workspace_member(email: str, role: int) -> Any:
        """
        Invite a user to the workspace by email with a given role.

        Requires the PAT to hold the workspace OWNER role (a 403 surfaces if it
        does not).

        Role values are integers:
            ADMIN  = 20
            MEMBER = 15
            GUEST  = 5

        Args:
            email: Email address of the person to invite
            role: Role to grant on acceptance — ADMIN=20, MEMBER=15, GUEST=5

        Returns:
            The created invitation record (dict). Its id is the invitation_id to
            pass to cancel_workspace_invite.
        """
        client, workspace_slug = get_plane_client_context()
        return client.workspaces.create_invite(
            workspace_slug=workspace_slug,
            email=email,
            role=role,
        )

    @mcp.tool()
    def list_workspace_invites() -> Any:
        """
        List pending invitations for the workspace.

        Requires the PAT to hold the workspace OWNER role (a 403 surfaces if it
        does not).

        Role values are integers:
            ADMIN  = 20
            MEMBER = 15
            GUEST  = 5

        Returns:
            A list of invitation records (dicts). Each record's id is the
            invitation_id to pass to cancel_workspace_invite.
        """
        client, workspace_slug = get_plane_client_context()
        return client.workspaces.list_invites(workspace_slug=workspace_slug)

    @mcp.tool()
    def cancel_workspace_invite(invitation_id: str) -> Any:
        """
        Cancel (delete) a pending workspace invitation.

        Requires the PAT to hold the workspace OWNER role (a 403 surfaces if it
        does not).

        Role values are integers:
            ADMIN  = 20
            MEMBER = 15
            GUEST  = 5

        Args:
            invitation_id: UUID of the invitation to cancel (from
                invite_workspace_member or list_workspace_invites)
        """
        client, workspace_slug = get_plane_client_context()
        return client.workspaces.delete_invite(
            workspace_slug=workspace_slug,
            invitation_id=invitation_id,
        )

from agent_engineering_kit.mcp_endpoint import resolved_endpoint


def test_endpoint_environment_overrides_public_default_without_embedding_credentials():
    item = {
        "endpoint_environment": "GITLAB_MCP_URL",
        "installation": {"endpoint": "https://gitlab.com/api/v4/mcp"},
    }
    assert resolved_endpoint(item, {"GITLAB_MCP_URL": "https://gitlab.example.test/api/v4/mcp"}) == "https://gitlab.example.test/api/v4/mcp"
    assert resolved_endpoint(item, {}) == "https://gitlab.com/api/v4/mcp"

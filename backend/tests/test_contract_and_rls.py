from io import BytesIO
from pathlib import Path
from uuid import UUID

import pytest
from starlette.datastructures import UploadFile

from app.main import _call_scope, _effective_seller_email, _upload_size, app
from app.models import Base, Role
from app.security import Principal


def test_calls_api_exposes_server_side_management_filters():
    operation = app.openapi()["paths"]["/api/v1/calls"]["get"]
    parameters = {item["name"] for item in operation["parameters"]}
    expected = {
        "page",
        "page_size",
        "sort",
        "order",
        "q",
        "date_from",
        "date_to",
        "seller",
        "customer",
        "company",
        "phone",
        "city",
        "province",
        "product",
        "product_category",
        "outcome",
        "sales_stage",
        "lead_temperature",
        "followup_required",
        "followup_overdue",
        "min_score",
        "max_score",
        "sentiment",
        "risk_flag",
        "status",
        "direction",
        "min_duration",
        "max_duration",
        "source_filename",
        "has_error",
        "manually_corrected",
    }
    assert expected <= parameters
    export_parameters = {
        item["name"]
        for item in app.openapi()["paths"]["/api/v1/exports/calls.xlsx"]["get"]["parameters"]
    }
    assert expected - {"page", "page_size"} <= export_parameters
    task_parameters = {
        item["name"] for item in app.openapi()["paths"]["/api/v1/tasks"]["get"]["parameters"]
    }
    assert {"bucket", "seller", "customer"} <= task_parameters
    assert "/api/v1/calls/{call_id}/speaker-roles" in app.openapi()["paths"]


def test_versioning_review_and_protected_artifact_contracts_exist():
    paths = app.openapi()["paths"]
    expected = {
        "/api/v1/calls/{call_id}/versions",
        "/api/v1/calls/{call_id}/transcript-versions",
        "/api/v1/calls/{call_id}/analysis-versions",
        "/api/v1/calls/{call_id}/versions/{version_id}/diff",
        "/api/v1/reviews",
        "/api/v1/reviews/{review_id}/assign",
        "/api/v1/reviews/{review_id}/approve",
        "/api/v1/reviews/{review_id}/reject",
        "/api/v1/reviews/{review_id}/request-changes",
        "/api/v1/reviews/{review_id}/publish",
        "/api/v1/calls/{call_id}/audio",
        "/api/v1/calls/{call_id}/export.txt",
        "/api/v1/calls/{call_id}/export.html",
        "/api/v1/calls/{call_id}/export.json",
        "/api/v1/reports/team",
    }
    assert expected <= set(paths)
    operation_ids = [
        operation["operationId"]
        for path in paths.values()
        for operation in path.values()
        if isinstance(operation, dict) and "operationId" in operation
    ]
    assert len(operation_ids) == len(set(operation_ids))


def test_issabel_settings_contract_is_explicitly_environment_read_only():
    schema = app.openapi()["paths"]["/api/v1/admin/issabel-settings"]
    assert set(schema) == {"get"}


def test_agent_call_scope_always_contains_identity_filter():
    tenant_id = UUID("11111111-1111-4111-8111-111111111111")
    agent = Principal("agent-1", "agent@example.com", tenant_id, Role.agent)
    admin = Principal("admin-1", "admin@example.com", tenant_id, Role.admin)
    agent_sql = " ".join(str(item) for item in _call_scope(agent))
    admin_sql = " ".join(str(item) for item in _call_scope(admin))
    assert "seller_email" in agent_sql
    assert "seller_email" not in admin_sql
    assert _effective_seller_email(agent, "other@example.com") == "agent@example.com"
    assert _effective_seller_email(admin, " Other@Example.com ") == "other@example.com"


@pytest.mark.asyncio
async def test_upload_size_does_not_materialize_entire_file():
    class NoReadBuffer(BytesIO):
        def read(self, *args, **kwargs):
            raise AssertionError("size validation must not read the full upload")

    upload = UploadFile(NoReadBuffer(b"x" * 4096), filename="call.wav", size=None)
    assert await _upload_size(upload) == 4096


def test_every_tenant_scoped_table_is_protected_by_rls_policy_file():
    policy = (Path(__file__).parents[1] / "sql" / "001_row_level_security.sql").read_text(
        encoding="utf-8"
    )
    tenant_tables = {
        table.name for table in Base.metadata.sorted_tables if "tenant_id" in table.columns
    }
    missing = sorted(table for table in tenant_tables if f"'{table}'" not in policy)
    assert missing == []
    assert "FORCE ROW LEVEL SECURITY" in policy
    assert "WITH CHECK" in policy

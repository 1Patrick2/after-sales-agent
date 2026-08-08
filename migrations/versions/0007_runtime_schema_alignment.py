"""align runtime ORM tables with the current Agent implementation

Revision ID: 0007_runtime_schema_alignment
Revises: 0006_knowledge_lifecycle
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0007_runtime_schema_alignment"
down_revision: str | None = "0006_knowledge_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """补齐当前 ORM 使用的确认、运行记录和用量字段。

    早期版本曾使用 ``thread_id``、``result_json`` 等临时字段；这里不删除旧字段，
    而是补充当前字段并迁移可复用的数据，避免已有环境升级时丢失确认记录。
    """
    op.add_column(
        "pending_actions",
        sa.Column("langgraph_thread_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "pending_actions",
        sa.Column("action_type", sa.String(length=64), nullable=False, server_default="tool"),
    )
    op.add_column(
        "pending_actions",
        sa.Column("risk_level", sa.String(length=32), nullable=False, server_default="low"),
    )
    op.add_column(
        "pending_actions",
        sa.Column(
            "confirmation_prompt",
            sa.Text(),
            nullable=False,
            server_default="请确认是否继续执行该操作。",
        ),
    )
    op.add_column("pending_actions", sa.Column("expire_at", sa.DateTime(timezone=True)))
    op.add_column("pending_actions", sa.Column("approved_at", sa.DateTime(timezone=True)))
    op.add_column("pending_actions", sa.Column("rejected_at", sa.DateTime(timezone=True)))
    op.add_column("pending_actions", sa.Column("executed_at", sa.DateTime(timezone=True)))
    op.add_column(
        "pending_actions",
        sa.Column(
            "execution_result_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("('{}')"),
        ),
    )
    op.add_column(
        "pending_actions",
        sa.Column(
            "idempotency_key",
            sa.String(length=200),
            nullable=False,
            server_default="legacy-pending-action",
        ),
    )
    op.add_column(
        "pending_actions",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.execute(
        sa.text(
            "UPDATE pending_actions "
            "SET langgraph_thread_id = thread_id "
            "WHERE langgraph_thread_id IS NULL AND thread_id IS NOT NULL"
        )
    )
    op.execute(
        sa.text(
            "UPDATE pending_actions "
            "SET execution_result_json = result_json "
            "WHERE result_json IS NOT NULL"
        )
    )
    op.execute(
        sa.text(
            "UPDATE pending_actions "
            "SET confirmation_prompt = COALESCE(comment, '请确认是否继续执行该操作。') "
            "WHERE confirmation_prompt IS NULL OR confirmation_prompt = ''"
        )
    )
    op.execute(
        sa.text(
            "UPDATE pending_actions "
            "SET idempotency_key = id "
            "WHERE idempotency_key IS NULL"
        )
    )
    op.create_index(
        "ix_pending_actions_langgraph_thread_id",
        "pending_actions",
        ["langgraph_thread_id"],
    )
    op.create_index(
        "ix_pending_actions_idempotency_key_v2",
        "pending_actions",
        ["idempotency_key"],
        unique=True,
    )

    op.add_column(
        "tenant_usage_daily",
        sa.Column("embedding_calls", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("conversation_id", sa.String(length=64), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="running"),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "response_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("('{}')"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "user_id",
            "request_id",
            name="uq_agent_run_idempotency_owner_key",
        ),
    )
    op.create_index("ix_agent_runs_tenant_id", "agent_runs", ["tenant_id"])
    op.create_index("ix_agent_runs_user_id", "agent_runs", ["user_id"])
    op.create_index("ix_agent_runs_conversation_id", "agent_runs", ["conversation_id"])
    op.create_index("ix_agent_runs_request_id", "agent_runs", ["request_id"])

    op.create_table(
        "agent_run_steps",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("stage", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("input_json", sa.JSON(), nullable=False),
        sa.Column("output_json", sa.JSON(), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_run_steps_run_id", "agent_run_steps", ["run_id"])
    op.create_index("ix_agent_run_steps_stage", "agent_run_steps", ["stage"])


def downgrade() -> None:
    """回滚本次新增的运行记录和当前字段，不触碰旧兼容字段。"""
    op.drop_index("ix_agent_run_steps_stage", table_name="agent_run_steps")
    op.drop_index("ix_agent_run_steps_run_id", table_name="agent_run_steps")
    op.drop_table("agent_run_steps")
    op.drop_index("ix_agent_runs_request_id", table_name="agent_runs")
    op.drop_index("ix_agent_runs_conversation_id", table_name="agent_runs")
    op.drop_index("ix_agent_runs_user_id", table_name="agent_runs")
    op.drop_index("ix_agent_runs_tenant_id", table_name="agent_runs")
    op.drop_table("agent_runs")
    op.drop_column("tenant_usage_daily", "embedding_calls")
    op.drop_index("ix_pending_actions_idempotency_key_v2", table_name="pending_actions")
    op.drop_index("ix_pending_actions_langgraph_thread_id", table_name="pending_actions")
    for column in (
        "updated_at",
        "idempotency_key",
        "execution_result_json",
        "executed_at",
        "rejected_at",
        "approved_at",
        "expire_at",
        "confirmation_prompt",
        "risk_level",
        "action_type",
        "langgraph_thread_id",
    ):
        op.drop_column("pending_actions", column)

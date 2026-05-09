def upgrade() -> None:
    op.create_index(
        "ix_tickets_status_sla_deadline",
        "tickets",
        ["status", "sla_deadline_at"],
    )
    op.create_index(
        "ix_tickets_department",
        "tickets",
        ["department"],
    )

def downgrade() -> None:
    op.drop_index("ix_tickets_status_sla_deadline", table_name="tickets")
    op.drop_index("ix_tickets_department", table_name="tickets")

    #пункт 2
    
    
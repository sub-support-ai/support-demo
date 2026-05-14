CONTEXT_HEADER = "Контекст обращения:"


def clean_optional_text(value: object) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def clean_text_with_fallback(value: object, fallback: str) -> str:
    return clean_optional_text(value) or fallback.strip()


def build_context_block(
    *,
    requester_name: str,
    requester_email: str,
    office: str | None,
    affected_item: str | None,
    creator_name: str | None = None,
    creator_email: str | None = None,
) -> str:
    lines = [
        CONTEXT_HEADER,
        f"Автор: {requester_name} <{requester_email}>",
    ]
    if creator_name and creator_email:
        lines.append(f"Создал: {creator_name} <{creator_email}>")
    lines.extend(
        [
            f"Офис: {office or 'не указан'}",
            f"Объект: {affected_item or 'не указан'}",
        ]
    )
    return "\n".join(lines)


def replace_context_block_if_present(
    body: str,
    *,
    requester_name: str,
    requester_email: str,
    office: str | None,
    affected_item: str | None,
    creator_name: str | None = None,
    creator_email: str | None = None,
) -> str:
    if not body.startswith(CONTEXT_HEADER):
        return body

    context_block = build_context_block(
        requester_name=requester_name,
        requester_email=requester_email,
        office=office,
        affected_item=affected_item,
        creator_name=creator_name,
        creator_email=creator_email,
    )
    separator_index = body.find("\n\n")
    if separator_index == -1:
        return context_block
    return f"{context_block}\n\n{body[separator_index + 2 :].lstrip()}"

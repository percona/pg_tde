def sql_literal(v: str | int | None) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, int):
        return str(v)
    return "'" + v.replace("'", "''") + "'"

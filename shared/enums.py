from django.db import connection

TABLE = "ENUMERATED_VALUES"
ORDER_COLUMNS = ("ordering", "order_id")


def order_column(using=None, connection_=None):
    """The ordering column name; some databases still use the legacy order_id."""
    conn = connection_ or connection
    with conn.cursor() as cursor:
        columns = {
            column.name
            for column in conn.introspection.get_table_description(cursor, TABLE)
        }
    for name in ORDER_COLUMNS:
        if name in columns:
            return name
    return None


def enum_rows(enum_type, values=None, connection_=None):
    """[(ordering, value)] for an enum type, whichever ordering column exists."""
    conn = connection_ or connection
    column = order_column(connection_=conn)
    if column is None:
        return []
    table = conn.ops.quote_name(TABLE)
    quoted = conn.ops.quote_name(column)
    sql = (
        f"SELECT {quoted}, value FROM {table} "
        f"WHERE LOWER(type) = LOWER(%s)"
    )
    params = [str(enum_type)]
    if values:
        placeholders = ", ".join(["%s"] * len(values))
        sql += f" AND LOWER(value) IN ({placeholders})"
        params.extend(str(item).lower() for item in values)
    sql += f" ORDER BY {quoted}"
    with conn.cursor() as cursor:
        cursor.execute(sql, params)
        return [(row[0], row[1]) for row in cursor.fetchall()]

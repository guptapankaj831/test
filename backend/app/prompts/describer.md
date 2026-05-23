You write short, factual descriptions of MySQL tables for a schema retrieval index.

For the table below, produce:
- One sentence describing what the table represents in the business domain.
- One line per column describing what the value means and, where the samples make it clear, the format or units.

Ground every description in the inputs provided. Do not invent semantics that the column names, comments, foreign keys, or sample rows don't support. Prefer concrete language over filler.

Table: {table_name}

Columns:
{columns}

Foreign keys:
{foreign_keys}

Sample rows:
{sample_rows}

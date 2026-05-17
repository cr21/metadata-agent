"""File kind classifier — maps a file path + content to an asset kind string."""

import re
from pathlib import Path

_PROCEDURE_RE = re.compile(
    r"create\s+(or\s+replace\s+)?procedure",
    re.IGNORECASE,
)
_AIRFLOW_RE = re.compile(r"^(?:import|from)\s+airflow", re.MULTILINE)
_PYSPARK_RE = re.compile(r"^(?:import|from)\s+pyspark", re.MULTILINE)
_PANDAS_RE = re.compile(r"^(?:import|from)\s+pandas", re.MULTILINE)


def classify(path: str | Path, content: str) -> str:
    """Return the asset kind for the given file.

    Classifier rules (applied in order):
      .sql  + CREATE [OR REPLACE] PROCEDURE  → bq_routine
      .sql  (other)                           → sql_file
      .py   importing airflow                 → airflow_dag
      .py   importing pyspark                 → pyspark_file
      .py   importing pandas (only)           → pandas_file
      anything else                           → unknown
    """
    suffix = Path(path).suffix.lower()

    if suffix == ".sql":
        if _PROCEDURE_RE.search(content):
            return "bq_routine"
        return "sql_file"

    if suffix == ".py":
        if _AIRFLOW_RE.search(content):
            return "airflow_dag"
        if _PYSPARK_RE.search(content):
            return "pyspark_file"
        if _PANDAS_RE.search(content):
            return "pandas_file"

    return "unknown"

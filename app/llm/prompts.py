"""Prompt builders for each asset kind."""

_STM_SYSTEM = """You are a data lineage expert. Analyse the SQL/stored-procedure source provided and produce
a Source-to-Target Mapping (STM) in the exact JSON schema requested.

Rules:
- Identify every table or view that is written to (INSERT, UPDATE, MERGE, CREATE TABLE AS, etc.).
- For each target column record all source columns it is derived from.
- If a column is a literal constant, set source_columns to [] and transformation_type to "constant".
- If the derivation is a straight column copy, use transformation_type "direct".
- If any computation or function is applied, use "derived".
- Mark is_pii=true for columns that appear to hold personal data (name, email, phone, ssn, dob, address, etc.).
- Be thorough; do not omit target tables or columns even if the transformation is trivial.
"""

_STM_RETRY_SYSTEM = """You are a data lineage expert. Your previous response was rejected because it did not
conform to the required JSON schema. Produce the STM again, strictly following the schema.
Pay particular attention to:
- Every column entry must include: column, datatype, source_columns (array), transformation (string),
  transformation_type (one of direct|derived|constant|unknown), is_pii (boolean).
- source_columns items must have exactly: table (string) and column (string).
- No extra keys anywhere (additionalProperties is false).
"""

_DAG_SYSTEM = """You are a data lineage expert specialising in Apache Airflow. Analyse the DAG source
and produce a DAG specification in the exact JSON schema requested.

Rules:
- dag_id should match the id string in the DAG constructor call.
- For each task, infer reads_hint / writes_hint from any SQL strings, file paths, table names, or
  variable names visible in the task's callable or operator arguments. Use empty arrays if nothing
  is identifiable — do not guess.
- dependencies lists the upstream task_ids (based on >> / set_upstream calls).
- operator is the class name of the Airflow operator used (e.g. PythonOperator, BashOperator).
"""

_DAG_RETRY_SYSTEM = """You are a data lineage expert specialising in Apache Airflow. Your previous
response was rejected. Produce the DAG spec again, strictly matching the schema:
- Every task must include: task_id, operator, reads_hint (array of strings), writes_hint (array of strings),
  dependencies (array of strings), description (string).
- No extra keys anywhere.
"""

_PYSPARK_SYSTEM = """You are a data lineage expert specialising in PySpark and Pandas. Analyse the script
and produce a Source-to-Target Mapping in the exact JSON schema requested.

Rules:
- Identify every DataFrame that is written out (saveAsTable, write.parquet, to_csv, to_bigquery, etc.).
- Infer the target_location_type from the write API used.
- write_mode is the mode argument (overwrite/append/merge) or "unknown".
- For each output column trace the source columns it came from.
- spark_function is the PySpark/Pandas function applied (e.g. col, withColumn, agg, groupBy); use "" if none.
- Mark is_pii=true for obvious personal-data columns.
"""

_PYSPARK_RETRY_SYSTEM = """You are a data lineage expert specialising in PySpark and Pandas. Your previous
response was rejected. Produce the PySpark STM again, strictly matching the schema:
- Every stm_entry must include: target_table, target_location_type (enum), write_mode (enum), columns (array).
- Every column must include: column, datatype, source_columns, transformation, transformation_type (enum),
  spark_function (string), is_pii (boolean).
- No extra keys anywhere.
"""

_USER_TEMPLATE = """File path: {path}

--- BEGIN SOURCE ---
{content}
--- END SOURCE ---

Extract the complete lineage for this file."""

_RETRY_USER_TEMPLATE = """File path: {path}

--- BEGIN SOURCE ---
{content}
--- END SOURCE ---

Your previous response contained schema errors. Produce a corrected response now.
Offending fields reported: {errors}"""


def build_prompts(kind: str, path: str, content: str) -> tuple[str, str]:
    """Return (system_prompt, user_prompt) for the given asset kind."""
    if kind in ("bq_table", "bq_view", "bq_routine", "sql_file"):
        system = _STM_SYSTEM
    elif kind == "airflow_dag":
        system = _DAG_SYSTEM
    else:
        system = _PYSPARK_SYSTEM

    user = _USER_TEMPLATE.format(path=path, content=content)
    return system, user


def build_retry_prompts(kind: str, path: str, content: str, errors: str) -> tuple[str, str]:
    """Return tightened (system_prompt, user_prompt) for the retry attempt."""
    if kind in ("bq_table", "bq_view", "bq_routine", "sql_file"):
        system = _STM_RETRY_SYSTEM
    elif kind == "airflow_dag":
        system = _DAG_RETRY_SYSTEM
    else:
        system = _PYSPARK_RETRY_SYSTEM

    user = _RETRY_USER_TEMPLATE.format(path=path, content=content, errors=errors)
    return system, user

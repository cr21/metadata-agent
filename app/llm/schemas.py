"""LLM output JSON schemas — STM, DAG spec, PySpark STM.

Each dict is passed directly as `json_schema` inside the OpenAI
`response_format` parameter with `strict: true`.
"""

# ---------------------------------------------------------------------------
# STM — SQL files, BQ tables/views/routines
# ---------------------------------------------------------------------------

STM_SCHEMA: dict = {
    "name": "stm",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "stm_entries": {
                "type": "array",
                "description": "One entry per target table written by this asset.",
                "items": {
                    "type": "object",
                    "properties": {
                        "target_table": {
                            "type": "string",
                            "description": "Fully-qualified target table name.",
                        },
                        "columns": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "column": {"type": "string"},
                                    "datatype": {"type": "string"},
                                    "source_columns": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "table": {"type": "string"},
                                                "column": {"type": "string"},
                                            },
                                            "required": ["table", "column"],
                                            "additionalProperties": False,
                                        },
                                    },
                                    "transformation": {
                                        "type": "string",
                                        "description": "Human-readable description of the transformation applied.",
                                    },
                                    "transformation_type": {
                                        "type": "string",
                                        "enum": ["direct", "derived", "constant", "unknown"],
                                    },
                                    "is_pii": {"type": "boolean"},
                                },
                                "required": [
                                    "column",
                                    "datatype",
                                    "source_columns",
                                    "transformation",
                                    "transformation_type",
                                    "is_pii",
                                ],
                                "additionalProperties": False,
                            },
                        },
                    },
                    "required": ["target_table", "columns"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["stm_entries"],
        "additionalProperties": False,
    },
}


# ---------------------------------------------------------------------------
# DAG_SPEC_SCHEMA — Airflow DAGs
# ---------------------------------------------------------------------------

DAG_SPEC_SCHEMA: dict = {
    "name": "dag_spec",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "dag_id": {"type": "string"},
            "description": {"type": "string"},
            "tasks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string"},
                        "operator": {
                            "type": "string",
                            "description": "Airflow operator class name, e.g. PythonOperator.",
                        },
                        "reads_hint": {
                            "type": "array",
                            "description": "Tables/paths this task reads from (best-effort, inferred from code).",
                            "items": {"type": "string"},
                        },
                        "writes_hint": {
                            "type": "array",
                            "description": "Tables/paths this task writes to (best-effort, inferred from code).",
                            "items": {"type": "string"},
                        },
                        "dependencies": {
                            "type": "array",
                            "description": "task_ids this task depends on (upstream tasks).",
                            "items": {"type": "string"},
                        },
                        "description": {"type": "string"},
                    },
                    "required": [
                        "task_id",
                        "operator",
                        "reads_hint",
                        "writes_hint",
                        "dependencies",
                        "description",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["dag_id", "description", "tasks"],
        "additionalProperties": False,
    },
}


# ---------------------------------------------------------------------------
# PYSPARK_STM_SCHEMA — PySpark / Pandas files
# ---------------------------------------------------------------------------

PYSPARK_STM_SCHEMA: dict = {
    "name": "pyspark_stm",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "stm_entries": {
                "type": "array",
                "description": "One entry per DataFrame write / target table.",
                "items": {
                    "type": "object",
                    "properties": {
                        "target_table": {"type": "string"},
                        "target_location_type": {
                            "type": "string",
                            "enum": [
                                "bigquery",
                                "hive",
                                "parquet",
                                "csv",
                                "json",
                                "delta",
                                "jdbc",
                                "unknown",
                            ],
                        },
                        "write_mode": {
                            "type": "string",
                            "enum": ["overwrite", "append", "merge", "unknown"],
                        },
                        "columns": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "column": {"type": "string"},
                                    "datatype": {"type": "string"},
                                    "source_columns": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "table": {"type": "string"},
                                                "column": {"type": "string"},
                                            },
                                            "required": ["table", "column"],
                                            "additionalProperties": False,
                                        },
                                    },
                                    "transformation": {"type": "string"},
                                    "transformation_type": {
                                        "type": "string",
                                        "enum": ["direct", "derived", "constant", "unknown"],
                                    },
                                    "spark_function": {
                                        "type": "string",
                                        "description": "PySpark/Pandas function used, e.g. withColumn, col, agg.",
                                    },
                                    "is_pii": {"type": "boolean"},
                                },
                                "required": [
                                    "column",
                                    "datatype",
                                    "source_columns",
                                    "transformation",
                                    "transformation_type",
                                    "spark_function",
                                    "is_pii",
                                ],
                                "additionalProperties": False,
                            },
                        },
                    },
                    "required": ["target_table", "target_location_type", "write_mode", "columns"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["stm_entries"],
        "additionalProperties": False,
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

KIND_TO_SCHEMA: dict[str, dict] = {
    "bq_table": STM_SCHEMA,
    "bq_view": STM_SCHEMA,
    "bq_routine": STM_SCHEMA,
    "sql_file": STM_SCHEMA,
    "airflow_dag": DAG_SPEC_SCHEMA,
    "pyspark_file": PYSPARK_STM_SCHEMA,
    "pandas_file": PYSPARK_STM_SCHEMA,
}

KIND_TO_SCHEMA_KIND: dict[str, str] = {
    "bq_table": "stm",
    "bq_view": "stm",
    "bq_routine": "stm",
    "sql_file": "stm",
    "airflow_dag": "dag_spec",
    "pyspark_file": "pyspark_stm",
    "pandas_file": "pyspark_stm",
}

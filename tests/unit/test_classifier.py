"""Unit tests for the file kind classifier — one test per classifier rule."""

from app.classifier import classify

# ---------------------------------------------------------------------------
# SQL rules
# ---------------------------------------------------------------------------

def test_sql_create_procedure_returns_bq_routine():
    content = "CREATE PROCEDURE my_dataset.my_proc() BEGIN SELECT 1; END"
    assert classify("path/to/proc.sql", content) == "bq_routine"


def test_sql_create_or_replace_procedure_returns_bq_routine():
    content = "CREATE OR REPLACE PROCEDURE ds.sp_transform() BEGIN SELECT 1; END"
    assert classify("proc.sql", content) == "bq_routine"


def test_sql_create_procedure_case_insensitive():
    content = "create or replace procedure ds.sp() begin select 1; end"
    assert classify("sp.sql", content) == "bq_routine"


def test_sql_without_procedure_returns_sql_file():
    content = "SELECT id, name FROM orders WHERE status = 'active'"
    assert classify("queries/report.sql", content) == "sql_file"


def test_sql_empty_content_returns_sql_file():
    assert classify("empty.sql", "") == "sql_file"


# ---------------------------------------------------------------------------
# Python — airflow
# ---------------------------------------------------------------------------

def test_py_import_airflow_returns_airflow_dag():
    content = "import airflow\nfrom airflow.operators.python import PythonOperator\n"
    assert classify("dags/my_dag.py", content) == "airflow_dag"


def test_py_from_airflow_returns_airflow_dag():
    content = "from airflow import DAG\nfrom airflow.operators.bash import BashOperator\n"
    assert classify("dags/etl_dag.py", content) == "airflow_dag"


def test_py_airflow_takes_precedence_over_pyspark():
    content = "import airflow\nimport pyspark\n"
    assert classify("hybrid.py", content) == "airflow_dag"


def test_py_airflow_takes_precedence_over_pandas():
    content = "from airflow import DAG\nimport pandas as pd\n"
    assert classify("dag_with_pandas.py", content) == "airflow_dag"


# ---------------------------------------------------------------------------
# Python — pyspark
# ---------------------------------------------------------------------------

def test_py_import_pyspark_returns_pyspark_file():
    content = "from pyspark.sql import SparkSession\n\nspark = SparkSession.builder.getOrCreate()\n"
    assert classify("jobs/transform.py", content) == "pyspark_file"


def test_py_from_pyspark_returns_pyspark_file():
    content = "from pyspark import SparkContext\n"
    assert classify("spark_job.py", content) == "pyspark_file"


def test_py_pyspark_takes_precedence_over_pandas():
    content = "import pyspark\nimport pandas as pd\n"
    assert classify("spark_pandas.py", content) == "pyspark_file"


# ---------------------------------------------------------------------------
# Python — pandas (only)
# ---------------------------------------------------------------------------

def test_py_import_pandas_returns_pandas_file():
    content = "import pandas as pd\n\ndf = pd.read_csv('data.csv')\n"
    assert classify("analysis.py", content) == "pandas_file"


def test_py_from_pandas_returns_pandas_file():
    content = "from pandas import DataFrame\n"
    assert classify("transform.py", content) == "pandas_file"


# ---------------------------------------------------------------------------
# Unknown / other extensions
# ---------------------------------------------------------------------------

def test_non_sql_non_py_returns_unknown():
    assert classify("README.md", "# Readme\n") == "unknown"


def test_py_no_known_imports_returns_unknown():
    content = "import os\nimport sys\n\nprint('hello')\n"
    assert classify("helper.py", content) == "unknown"


def test_yaml_returns_unknown():
    content = "name: my-dag\nschedule: daily\n"
    assert classify("dag.yaml", content) == "unknown"


def test_empty_py_returns_unknown():
    assert classify("empty.py", "") == "unknown"


# ---------------------------------------------------------------------------
# Path variants
# ---------------------------------------------------------------------------

def test_pathlib_path_accepted():
    from pathlib import Path
    content = "SELECT 1"
    assert classify(Path("query.sql"), content) == "sql_file"


def test_sql_extension_case_insensitive():
    content = "SELECT 1"
    assert classify("QUERY.SQL", content) == "sql_file"

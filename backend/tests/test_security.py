import asyncio
import sqlite3

import pytest

from app.errors import AppError
from app.security import check_outbound_url, resolve_in_sandbox
from app.services.connectors import (
    FilesystemConnector,
    HttpConnector,
    SqliteConnector,
    ensure_read_only_sql,
)


def test_sandbox_blocks_traversal(tmp_path):
    (tmp_path / "ok.txt").write_text("x")
    assert resolve_in_sandbox(tmp_path, "ok.txt").name == "ok.txt"
    for bad in ["../etc/passwd", "/etc/passwd", "a/../../x", "x\x00y"]:
        with pytest.raises(AppError):
            resolve_in_sandbox(tmp_path, bad)


def test_sandbox_blocks_symlink_escape(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "link").symlink_to(tmp_path)
    with pytest.raises(AppError):
        resolve_in_sandbox(root, "link/secret")


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM t",
        "select 1; drop table t",
        "UPDATE t SET a=1",
        "with x as (delete from t) select 1",
        "ATTACH DATABASE 'x' AS y",
    ],
)
def test_sql_write_rejected(sql):
    with pytest.raises(AppError):
        ensure_read_only_sql(sql)


def test_sql_select_ok():
    assert ensure_read_only_sql("SELECT * FROM t;") == "SELECT * FROM t"


def test_outbound_allowlist():
    assert check_outbound_url("https://a.com/x", [])
    with pytest.raises(AppError):
        check_outbound_url("file:///etc/passwd", [])
    with pytest.raises(AppError):
        check_outbound_url("https://b.com", ["a.com"])


def test_http_connector_rejects_absolute_path(settings):
    c = HttpConnector("api", {"base_url": "https://a.com"}, settings)
    with pytest.raises(AppError):
        asyncio.run(c.call("request", {"method": "GET", "path": "http://evil.com"}))
    with pytest.raises(AppError):
        asyncio.run(c.call("request", {"method": "DELETE", "path": "/x"}))


def test_filesystem_connector(tmp_path, settings):
    (tmp_path / "a.txt").write_text("hello")
    c = FilesystemConnector("fs", {"root": str(tmp_path)}, settings)
    assert [t.name for t in c.local_tools()] == ["list_dir", "read_file"]
    assert asyncio.run(c.run("read_file", {"path": "a.txt"})) == "hello"
    with pytest.raises(AppError):
        asyncio.run(c.run("write_file", {"path": "b.txt", "content": "x"}))
    with pytest.raises(AppError):
        asyncio.run(c.run("read_file", {"path": "../../etc/passwd"}))


def test_sqlite_connector_is_read_only(tmp_path, settings):
    db = tmp_path / "x.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE t (a INT)")
    con.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(500)])
    con.commit()
    con.close()
    c = SqliteConnector("db", {"path": str(db), "max_rows": 10}, settings)
    res = asyncio.run(c.call("query", {"sql": "SELECT a FROM t"}))
    assert len(res["rows"]) == 10
    with pytest.raises(AppError):
        asyncio.run(c.call("query", {"sql": "DELETE FROM t"}))

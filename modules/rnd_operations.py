import sqlite3
from config import SHADOW_DB


def get_total_tests():
    conn = sqlite3.connect(SHADOW_DB)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM test_logs")
    total = cursor.fetchone()[0]

    conn.close()
    return total


def get_passed_tests():
    conn = sqlite3.connect(SHADOW_DB)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT COUNT(*)
        FROM test_logs
        WHERE result = 'PASS'
    """)

    total = cursor.fetchone()[0]

    conn.close()
    return total


def get_failed_tests():
    conn = sqlite3.connect(SHADOW_DB)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT COUNT(*)
        FROM test_logs
        WHERE result = 'FAIL'
    """)

    total = cursor.fetchone()[0]

    conn.close()
    return total


def get_recent_tests():
    conn = sqlite3.connect(SHADOW_DB)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT test_name, result
        FROM test_logs
        ORDER BY id DESC
        LIMIT 5
    """)

    tests = cursor.fetchall()

    conn.close()
    return tests

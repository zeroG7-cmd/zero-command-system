from config import ZEROGRAVITY_DB
import sqlite3
from collections import Counter

def connect_zerogravity_db():
    return sqlite3.connect(ZEROGRAVITY_DB_PATH)


def count_multi_select_answers(values):
    counts = Counter()

    for value in values:
        if not value:
            continue

        answers = value.split(",")

        for answer in answers:
            clean_answer = answer.strip()

            if clean_answer:
                counts[clean_answer] += 1

    return dict(counts)


def get_total_survey_responses():
    conn = connect_zerogravity_db()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM customer_survey_responses")
    total = cursor.fetchone()[0]

    conn.close()
    return total


def get_service_interest_counts():
    conn = connect_zerogravity_db()
    cursor = conn.cursor()

    cursor.execute("SELECT service_interest FROM customer_survey_responses")
    rows = cursor.fetchall()

    conn.close()

    service_values = [row[0] for row in rows]
    return count_multi_select_answers(service_values)


def get_budget_range_counts():
    conn = connect_zerogravity_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT budget_range, COUNT(*)
        FROM customer_survey_responses
        GROUP BY budget_range
        ORDER BY COUNT(*) DESC
    """)

    budget_counts = dict(cursor.fetchall())

    conn.close()
    return budget_counts


def get_survey_summary():
    return {
        "total_responses": get_total_survey_responses(),
        "service_interest": get_service_interest_counts(),
        "budget_range": get_budget_range_counts(),
    }
from flask import Flask, render_template

from modules.rnd_operations import (
    get_total_tests,
    get_passed_tests,
    get_failed_tests,
    get_recent_tests
)

app = Flask(__name__)

@app.route("/")
def home():
    return render_template(
        "home.html",
        tests_completed=get_total_tests(),
        passed=get_passed_tests(),
        failed=get_failed_tests(),
        recent_tests=get_recent_tests()
    )

if __name__ == "__main__":
    app.run(debug=True)

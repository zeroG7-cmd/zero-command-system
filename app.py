from flask import Flask, render_template

from modules.research_development import (
    get_total_tests,
    get_passed_tests,
    get_failed_tests,
    get_recent_tests
)

from modules.zerogravity import (
    get_survey_summary
)

from modules.operator import operator_bp
from modules.research_development import rnd_bp
app = Flask(__name__)

# Register the Operator workspace routes.
app.register_blueprint(operator_bp)
app.register_blueprint(rnd_bp)

@app.route("/")
def home():
    return render_template(
        "home.html",
        tests_completed=get_total_tests(),
        passed=get_passed_tests(),
        failed=get_failed_tests(),
        recent_tests=get_recent_tests()
    )

@app.route("/zerogravity")
def zerogravity_dashboard():

    survey = get_survey_summary()

    return render_template(
        "workspaces/zerogravity/dashboard.html",
        survey=survey
    )



if __name__ == "__main__":
    app.run(debug=True)

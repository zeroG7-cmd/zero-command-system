import mimetypes
import os
import sys

from flask import Flask, render_template

# Windows machines sometimes have a stale/wrong registry association for
# .js (some other installed app can overwrite it), which makes Python's
# mimetypes guesser - and therefore Flask's static file serving - report
# .js files as the wrong Content-Type. Regular <script> tags tolerate
# that, but <script type="module"> is strictly validated per the HTML
# spec and refuses to execute at all if the MIME type isn't a JS type -
# which is exactly why the 3D room's module script was silently doing
# nothing. Registering it explicitly overrides whatever the OS guesses.
mimetypes.add_type('application/javascript', '.js')

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
from modules.operator_learning import operator_learning_bp
from modules.learning_events import learning_events_bp
from modules.operator_execution import bp as operator_execution_bp
from modules.tasks import bp as operator_tasks_bp
from modules.simulation_control import bp as simulation_control_bp
from modules.operator_fitness import operator_fitness_bp
from modules.operator_journal import operator_journal_bp
from flask import redirect, url_for


def _resource_base_path() -> str:
    """Where templates/ and static/ actually live.

    Under a normal `python app.py` run that's just this file's own folder.
    Under a PyInstaller-frozen build, this file is unpacked inside the
    bundle at runtime, so `__file__` no longer points at the real repo -
    sys._MEIPASS is PyInstaller's stand-in for "the bundle's root" and is
    where --add-data drops templates/static. See desktop/README.md.
    """
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


_BASE_PATH = _resource_base_path()

app = Flask(
    __name__,
    template_folder=os.path.join(_BASE_PATH, "templates"),
    static_folder=os.path.join(_BASE_PATH, "static"),
)

# Register the Operator workspace routes.
app.register_blueprint(operator_bp)
app.register_blueprint(operator_learning_bp)
app.register_blueprint(learning_events_bp)
app.register_blueprint(rnd_bp)
app.register_blueprint(operator_execution_bp)
app.register_blueprint(operator_tasks_bp)
app.register_blueprint(simulation_control_bp)
app.register_blueprint(operator_fitness_bp)
app.register_blueprint(operator_journal_bp)

@app.route("/")
def home():
    return render_template(
        "home.html",
        tests_completed=get_total_tests(),
        passed=get_passed_tests(),
        failed=get_failed_tests(),
        recent_tests=get_recent_tests()
    )


@app.route("/tasks")
def legacy_tasks_redirect():
    return redirect(url_for("operator_tasks.dashboard"), code=302)

@app.route("/zerogravity")
def zerogravity_dashboard():

    survey = get_survey_summary()

    return render_template(
        "workspaces/zerogravity/dashboard.html",
        survey=survey
    )


if __name__ == "__main__":
    # The Werkzeug reloader re-execs the process via sys.executable +
    # sys.argv, which makes no sense once this is a frozen .exe with no
    # script path to re-exec - so debug/reload switches off automatically
    # in the bundled build, and stays on for normal `python app.py` dev.
    app.run(host="127.0.0.1", port=5000, debug=not getattr(sys, "frozen", False))

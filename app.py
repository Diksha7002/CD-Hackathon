"""
app.py - the Flask web server for GrammarFix.

Routes:
    GET  /             -> the web page
    POST /api/analyze  -> body: {"code": "..."}   returns the analysis as JSON
    GET  /api/tests    -> runs all predefined test cases and returns the results

Run it with:   python app.py      then open  http://127.0.0.1:5000
"""

from flask import Flask, jsonify, render_template, request

from parser import ParseError, analyze, run_test_cases

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024      # reject request bodies bigger than 50 KB


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or "code" not in data:
        return jsonify({"ok": False, "error": "Send JSON like {\"code\": \"if (a) ...\"}."}), 400

    try:
        return jsonify(analyze(data["code"]))
    except ParseError as err:                      # problem with the user's input
        return jsonify({"ok": False, "error": str(err)}), 400
    except Exception:                              # a bug on our side - never crash the server
        app.logger.exception("Unexpected error while analysing")
        return jsonify({"ok": False, "error": "Something went wrong while analysing this input."}), 500


@app.route("/api/tests")
def api_tests():
    return jsonify({"ok": True, "tests": run_test_cases()})


@app.errorhandler(413)
def too_large(_err):
    return jsonify({"ok": False, "error": "The input is too large."}), 413


if __name__ == "__main__":
    app.run(debug=True)

import json
import os
import re
from functools import wraps

import numpy as np
import pandas as pd
import plotly.express as px  # Needs pandas
import plotly.graph_objects as go
import plotly.utils
import pyrankvote as prv
from flask import Flask, redirect, render_template, request, session, url_for
from flask.helpers import send_from_directory
from flask_breadcrumbs import Breadcrumbs, register_breadcrumb
from flask_dance.consumer import oauth_authorized
from flask_dance.contrib.google import google, make_google_blueprint
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from oauthlib.oauth2 import TokenExpiredError

import sankey_lib

QUESTION_PATTERN = re.compile("(?P<question>.*) \[(?P<option>.*)\]")

SCOPES = [
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/drive.metadata.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
]

app = Flask(__name__)
Breadcrumbs(app)
app.secret_key = os.environ["FLASK_SECRET_KEY"]
blueprint = make_google_blueprint(
    client_id=os.environ["GOOGLE_OAUTH_CLIENT_ID"],
    client_secret=os.environ["GOOGLE_OAUTH_CLIENT_SECRET"],
    scope=" ".join(SCOPES),
)
app.register_blueprint(blueprint, url_prefix="/login")


@oauth_authorized.connect
def redirect_to_next_url(blueprint, token):
    # set OAuth token in the token storage backend
    blueprint.token = token
    # retrieve `next_url` from Flask's session cookie
    next_url = session["next_url"]
    # redirect the user to `next_url`
    return redirect(next_url)


# Place @login_required after @app.route to secure endpoint
def login_required(f):
    @wraps(f)
    def wrap(*args, **kwargs):
        if not google.authorized:
            session["next_url"] = url_for(request.endpoint, **request.view_args)
            return redirect(url_for("google.login"))
        try:
            resp = google.get("/oauth2/v1/userinfo")
            email = resp.json()["email"]
            print(f"Login email: {email}")
            assert resp.ok, resp.text
        except TokenExpiredError:
            session["next_url"] = url_for(request.endpoint, **request.view_args)
            return redirect(url_for("google.login"))
        return f(*args, **kwargs)

    return wrap


@app.route("/static/<path:path>")
def send_static(path):
    return send_from_directory("static", path)


@app.route("/", methods=["GET"])
@register_breadcrumb(app, ".", "Home")
def index():
    return render_template("index.html")


@app.route("/terms_and_conditions", methods=["GET"])
@register_breadcrumb(app, ".terms_and_conditions", "Terms And Conditions")
def terms_and_conditions():
    return render_template("terms_and_conditions.html")


@app.route("/privacy", methods=["GET"])
@register_breadcrumb(app, ".privacy", "Privacy Policy")
def privacy():
    return render_template("privacy.html")


@app.route("/spreadsheet", methods=["GET", "POST"])
@register_breadcrumb(app, ".spreadsheet", "Analyze Spreadsheet")
@login_required
def spreadsheet():
    if request.method == "POST":
        spreadsheet_id = request.form.get("spreadsheet_id")
        return redirect(url_for("spreadsheet_question", spreadsheet_id=spreadsheet_id))

    drive_service = build("drive", "v3", credentials=make_credentials())
    resp = google.get("/oauth2/v1/userinfo")
    assert resp.ok, resp.text
    email = resp.json()["email"]

    spreadsheets = []
    page_token = None
    while True:
        response = (
            drive_service.files()
            .list(
                q=f"mimeType='application/vnd.google-apps.spreadsheet' and '{email}' in owners",
                orderBy="modifiedTime desc",
                fields="nextPageToken, files(id, name)",
                pageToken=page_token,
            )
            .execute()
        )
        files = response.get("files", [])
        page_token = response.get("nextPageToken", None)
        spreadsheets.extend([(f["name"], f["id"]) for f in files])
        if page_token is None:
            break

    return render_template("spreadsheet.html", spreadsheets=spreadsheets)


def ssq(*args, **kwargs):
    spreadsheet_id = request.view_args["spreadsheet_id"]
    service = build("sheets", "v4", credentials=make_credentials())
    spreadsheet = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    title = get_spreadsheet_title(spreadsheet)
    url = url_for("spreadsheet_question", spreadsheet_id=spreadsheet_id)
    return [{"text": title, "url": url}]


@app.route("/spreadsheet/<string:spreadsheet_id>/question", methods=["GET", "POST"])
@register_breadcrumb(app, ".spreadsheet.question", "", dynamic_list_constructor=ssq)
@login_required
def spreadsheet_question(spreadsheet_id):
    if request.method == "POST":
        question = request.form.get("spreadsheet_question")
        url = url_for(
            "spreadsheet_tabulate", spreadsheet_id=spreadsheet_id, question=question
        )
        return redirect(url)

    service = build("sheets", "v4", credentials=make_credentials())

    validate_spreadsheet(service, spreadsheet_id)

    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range="1:1")
        .execute()
    )
    rows = result.get("values", [[]])

    # TODO: Handle identical questions
    questions = []
    previous = None
    for col in rows[0]:
        match = QUESTION_PATTERN.match(col)
        if match:
            question = match.group("question")
            if question != previous:
                questions.append(question)
                previous = question
        else:
            previous = None

    return render_template("spreadsheet_question.html", questions=questions)


def ssqt(*args, **kwargs):
    spreadsheet_id = request.view_args["spreadsheet_id"]
    question = request.view_args["question"]
    url = url_for(
        "spreadsheet_tabulate", spreadsheet_id=spreadsheet_id, question=question
    )
    return [{"text": question, "url": url}]


@app.route("/spreadsheet/<string:spreadsheet_id>/<string:question>", methods=["GET"])
@register_breadcrumb(
    app, ".spreadsheet.question.tabulate", "", dynamic_list_constructor=ssqt
)
@login_required
def spreadsheet_tabulate(spreadsheet_id, question):
    service = build("sheets", "v4", credentials=make_credentials())

    spreadsheet = validate_spreadsheet(service, spreadsheet_id)
    range = spreadsheet["sheets"][0]["properties"]["title"]

    result_values = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=range)
        .execute()
    )
    rows = result_values.get("values")

    # Google returns short rows if they are empty values, so make all rows
    # the same length.
    row_len = len(rows[0])
    for row in rows:
        missing = row_len - len(row)
        row.extend([""] * missing)

    # TODO: Handle identical questions
    candidates = []
    col_indices = []
    for col_idx, col in enumerate(rows[0]):
        match = QUESTION_PATTERN.match(col)
        if match and match.group("question") == question:
            name = match.group("option")
            candidates.append(prv.Candidate(name))
            col_indices.append(col_idx)

    data = [[row[c] for c in col_indices] for row in rows[1:]]
    ballots = [make_ballot(row, candidates) for row in data]
    results = prv.single_transferable_vote(candidates, ballots, number_of_seats=1)

    sankey_data = sankey_lib.results_to_sankey(
        results,
        candidates,
        node_palette=px.colors.qualitative.Dark2,
        link_palette=px.colors.qualitative.Set2,
    )

    sankey = go.Sankey(
        node=dict(
            thickness=10,
            line=dict(color="black", width=1),
            label=sankey_data.labels,
            color=sankey_data.node_color,
        ),
        link=dict(
            source=sankey_data.source,
            target=sankey_data.target,
            value=sankey_data.value,
            color=sankey_data.link_color,
        ),
        visible=True,
    )

    results_by_round = []
    for rnd in results.rounds:
        counts = {r.candidate.name: r.number_of_votes for r in rnd.candidate_results}
        counts["-exhausted-"] = rnd.number_of_blank_votes
        results_by_round.append(counts)
    results_by_round = pd.DataFrame(results_by_round)
    results_by_round.index += 1
    results_by_round.index.name = "Round"

    spreadsheet_title = get_spreadsheet_title(spreadsheet)
    title_text = f"{spreadsheet_title}<br><sup>{question}</sup>"

    fig = go.Figure(data=[sankey])
    notes = [
        "Height of bars and traces is proportional to vote count.",
        "The '-exhausted-' label is legitimate and indicates ballots which chose not to rank all candidates.",
    ]
    fig.add_annotation(
        x=0,
        y=-0.2,
        xref="paper",
        yref="paper",
        text="<br>".join(notes),
        align="left",
        showarrow=False,
        font_size=15,
    )
    fig.update_layout(
        title_text=title_text,
        font_size=20,
        xaxis={"showgrid": False, "zeroline": False, "visible": False},
        yaxis={"showgrid": False, "zeroline": False, "visible": False},
    )
    fig_json = json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)

    return render_template(
        "spreadsheet_tabulate.html",
        fig_json=fig_json,
        results=results,
        results_by_round=results_by_round,
    )


def get_spreadsheet_title(spreadsheet):
    title = spreadsheet["properties"]["title"]
    end = " (Responses)"
    if title.endswith(end):
        title = title[: -len(end)]
    return title


def clean_ord(o):
    try:
        return int(o)
    except ValueError:
        return int(o[:-2]) if o else 0


def make_ballot(row, cands):
    row = np.array([clean_ord(e) for e in row])
    ranked = [cands[idx] for idx in row.argsort() if row[idx] != 0]
    return prv.Ballot(ranked_candidates=ranked)


def make_credentials():
    return Credentials(
        blueprint.token["access_token"],
        client_id=blueprint.client_id,
        client_secret=blueprint.client_secret,
        refresh_token=None,  # TODO: get refresh token?
    )


def validate_spreadsheet(sheet_service, spreadsheet_id):
    spreadsheet = (
        sheet_service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    )

    num_sheets = len(spreadsheet["sheets"])
    if num_sheets != 1:
        raise ValueError("Spreadsheet has unexpected # sheets: %d" % num_sheets)

    title = spreadsheet["sheets"][0]["properties"]["title"]
    if title != "Form Responses 1":
        raise ValueError("Spreadsheet has unexpected sheet: %s" % title)

    return spreadsheet


@app.route("/logout")
def logout():
    if blueprint.token is None:
        return redirect(url_for("index"))

    token = blueprint.token["access_token"]

    try:
        resp = google.post(
            "https://accounts.google.com/o/oauth2/revoke",
            params={"token": token},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert resp.ok, resp.text
    except TokenExpiredError:
        pass

    del blueprint.token
    return redirect(url_for("index"))

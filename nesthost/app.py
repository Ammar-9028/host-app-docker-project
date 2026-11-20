import re
import secrets
import shutil
import sqlite3
import tempfile
from functools import wraps
from pathlib import Path

from flask import (Flask, Response, abort, flash, g, jsonify, redirect, render_template, request, send_file,
                   session)
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

from . import db as dbm
from . import rdap
from . import sites as S
from .config import Config
from .security import RateLimiter, csrf_ok, csrf_token

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
QUIET = {"healthz"}


def _secret(cfg):
    f = cfg.data_dir / "secret_key"
    if not f.exists():
        f.write_text(secrets.token_hex(32))
        f.chmod(0o600)
    return f.read_text().strip()


def create_app(env=None):
    cfg = Config(env)
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    (cfg.data_dir / "sites").mkdir(exist_ok=True)
    db_path = str(cfg.data_dir / "nesthost.db")
    dbm.init(db_path)

    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=_secret(cfg),
        MAX_CONTENT_LENGTH=(cfg.max_site_mb + 2) * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_SECURE=cfg.secure,
        # __Host- cookies cannot be set or overwritten by user sites living on sibling subdomains
        SESSION_COOKIE_NAME="__Host-session" if cfg.secure else "session",
        PERMANENT_SESSION_LIFETIME=14 * 24 * 3600)
    if cfg.trust_proxy:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
    limiter = RateLimiter()
    app.teardown_appcontext(dbm.close)
    app.extensions["cfg"] = cfg

    def db():
        return dbm.get(db_path)

    # ------------------------------------------------------------------ virtual hosting
    def classify(host):
        base = cfg.base_domain
        if host in (base, "www." + base):
            return "platform", None
        if host.endswith("." + base):
            sub = host[: -len(base) - 1]
            row = db().execute("SELECT * FROM sites WHERE subdomain=?", (sub,)).fetchone() if "." not in sub else None
            return ("site", row) if row else ("missing", sub)
        row = db().execute("SELECT s.* FROM domains d JOIN sites s ON s.id=d.site_id WHERE d.domain=? AND d.verified=1",
                           (host,)).fetchone()
        return ("site", row) if row else ("platform", None)

    @app.before_request
    def vhost():
        if request.endpoint == "healthz":
            return None
        host = request.host.split(":")[0].lower().rstrip(".")
        kind, row = classify(host)
        g.host_kind = kind
        if kind == "platform":
            return None
        if kind == "missing":
            return Response(render_template("unclaimed.html", sub=row), 404)
        if request.method not in ("GET", "HEAD"):
            return Response("Method not allowed", 405)
        if row["status"] != "active":
            return Response(render_template("suspended.html"), 503)
        pub = S.public_dir(cfg, row["id"])
        f = S.resolve_file(pub, request.path)
        if f is None:
            nf = pub / "404.html"
            if nf.is_file():
                return Response(nf.read_bytes(), 404, mimetype="text/html")
            return Response(render_template("site404.html"), 404)
        resp = send_file(f, conditional=True, max_age=300)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return resp

    @app.before_request
    def platform_guard():
        g.user = None
        uid = session.get("uid")
        if uid:
            g.user = db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
            if g.user is None:
                session.clear()
        if request.method == "POST" and not csrf_ok():
            abort(400, "Session expire ho gaya. Page refresh karke dobara try karo.")

    @app.after_request
    def headers(r):
        r.headers.setdefault("X-Content-Type-Options", "nosniff")
        if getattr(g, "host_kind", "platform") == "platform":
            r.headers.setdefault("X-Frame-Options", "DENY")
            r.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return r

    @app.context_processor
    def ctx():
        return dict(cfg=cfg, base=cfg.base_domain, brand=cfg.brand, csrf=csrf_token, user=g.get("user"),
                    site_url=cfg.site_url, starters=S.STARTERS)

    def login_required(fn):
        @wraps(fn)
        def w(*a, **k):
            if not g.user:
                return redirect("/login?next=" + request.path)
            return fn(*a, **k)
        return w

    def admin_required(fn):
        @wraps(fn)
        @login_required
        def w(*a, **k):
            if not g.user["is_admin"]:
                abort(403)
            return fn(*a, **k)
        return w

    def own_site(sid):
        row = db().execute("SELECT * FROM sites WHERE id=? AND user_id=?", (sid, g.user["id"])).fetchone()
        if row is None:
            abort(404)
        return row

    def safe_next(n):
        return n if n and n.startswith("/") and not n.startswith("//") else "/dashboard"

    def limited(name, limit, window):
        return not limiter.allow(f"{name}:{request.remote_addr}", limit, window)

    def refresh_stats(sid):
        files, size = S.dir_stats(S.public_dir(cfg, sid))
        db().execute("UPDATE sites SET files=?, bytes=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (files, size, sid))
        db().commit()

    # ------------------------------------------------------------------ public pages
    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/domains")
    def domains_page():
        return render_template("domains.html")

    @app.get("/healthz")
    def healthz():
        return jsonify(status="ok")

    @app.get("/api/check")
    def api_check():
        if limited("check", 60, 60):
            return jsonify(error="Bahut zyada requests. Thodi der baad try karo."), 429
        name = (request.args.get("name") or "").strip().lower()
        ok, why = S.valid_subdomain(name)
        if ok and db().execute("SELECT 1 FROM sites WHERE subdomain=?", (name,)).fetchone():
            ok, why = False, "Ye naam pehle se le liya gaya hai."
        return jsonify(name=name, available=ok, reason=why, url=cfg.site_url(name) if ok else None,
                       host=f"{name}.{cfg.base_domain}")

    @app.get("/api/domain")
    def api_domain():
        if limited("rdap", 20, 60):
            return jsonify(error="Bahut zyada requests. Thodi der baad try karo."), 429
        d = rdap.normalize(request.args.get("d"))
        if not d:
            return jsonify(error="Valid domain likho, jaise example.com"), 400
        return jsonify(domain=d, status=rdap.status(d))

    @app.get("/internal/tls-check")
    def tls_check():
        # Caddy "ask" endpoint: only issue certificates for hostnames that really exist on this platform.
        if request.headers.get("X-Forwarded-For") or request.headers.get("X-Forwarded-Host"):
            abort(404)
        d = (request.args.get("domain") or "").lower().rstrip(".")
        base = cfg.base_domain
        ok = d in (base, "www." + base)
        if not ok and d.endswith("." + base):
            sub = d[: -len(base) - 1]
            ok = "." not in sub and db().execute("SELECT 1 FROM sites WHERE subdomain=? AND status='active'", (sub,)).fetchone() is not None
        if not ok:
            ok = db().execute("SELECT 1 FROM domains WHERE domain=? AND verified=1", (d,)).fetchone() is not None
        return ("ok", 200) if ok else ("no", 404)

    # ------------------------------------------------------------------ auth
    @app.route("/signup", methods=["GET", "POST"])
    def signup():
        if request.method == "POST":
            if limited("signup", 8, 3600):
                flash("Bahut zyada signups. Baad mein try karo.", "err")
                return redirect("/signup")
            if not cfg.signup_open:
                flash("Abhi naye signups band hain.", "err")
                return redirect("/signup")
            email = (request.form.get("email") or "").strip().lower()
            pw = request.form.get("password") or ""
            if not EMAIL_RE.match(email) or len(email) > 254:
                flash("Valid email daalo.", "err")
            elif len(pw) < 8:
                flash("Password kam se kam 8 characters ka hona chahiye.", "err")
            else:
                first = db().execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
                admin = 1 if (first or email == cfg.admin_email) else 0
                try:
                    cur = db().execute("INSERT INTO users(email,pw_hash,is_admin) VALUES(?,?,?)",
                                       (email, generate_password_hash(pw), admin))
                    db().commit()
                except sqlite3.IntegrityError:
                    flash("Is email se account pehle se hai. Login karo.", "err")
                    return redirect("/login")
                session.clear()
                session["uid"] = cur.lastrowid
                session.permanent = True
                return redirect(safe_next(request.args.get("next")))
        return render_template("auth.html", mode="signup")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            if limited("login", 10, 60):
                flash("Bahut zyada attempts. 1 minute baad try karo.", "err")
                return redirect("/login")
            email = (request.form.get("email") or "").strip().lower()
            row = db().execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
            if row and check_password_hash(row["pw_hash"], request.form.get("password") or ""):
                session.clear()
                session["uid"] = row["id"]
                session.permanent = True
                return redirect(safe_next(request.args.get("next")))
            flash("Email ya password galat hai.", "err")
        return render_template("auth.html", mode="login")

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect("/")

    # ------------------------------------------------------------------ dashboard + sites
    @app.get("/dashboard")
    @login_required
    def dashboard():
        rows = db().execute("SELECT * FROM sites WHERE user_id=? ORDER BY id DESC", (g.user["id"],)).fetchall()
        return render_template("dashboard.html", sites=rows)

    @app.post("/sites")
    @login_required
    def create_site():
        sub = (request.form.get("subdomain") or "").strip().lower()
        starter = request.form.get("starter") or "coming"
        ok, why = S.valid_subdomain(sub)
        if not ok:
            flash(why, "err")
            return redirect("/dashboard")
        n = db().execute("SELECT COUNT(*) FROM sites WHERE user_id=?", (g.user["id"],)).fetchone()[0]
        if n >= cfg.max_sites:
            flash(f"Free plan mein maximum {cfg.max_sites} sites allowed hain.", "err")
            return redirect("/dashboard")
        try:
            cur = db().execute("INSERT INTO sites(user_id,subdomain) VALUES(?,?)", (g.user["id"], sub))
            db().commit()
        except sqlite3.IntegrityError:
            flash("Ye naam pehle se le liya gaya hai.", "err")
            return redirect("/dashboard")
        sid = cur.lastrowid
        pub = S.public_dir(cfg, sid)
        pub.mkdir(parents=True, exist_ok=True)
        (pub / "index.html").write_text(S.render_starter(starter, {
            "title": sub.replace("-", " ").title(), "tagline": "Meri nayi website jald aa rahi hai.",
            "about": "Yahan apne baare mein likho. Ye text dashboard ke builder se badal sakte ho.", "email": g.user["email"]}),
            encoding="utf-8")
        refresh_stats(sid)
        flash(f"Site ban gayi: {cfg.site_url(sub)}", "ok")
        return redirect(f"/sites/{sid}")

    @app.get("/sites/<int:sid>")
    @login_required
    def manage(sid):
        site = own_site(sid)
        doms = db().execute("SELECT * FROM domains WHERE site_id=? ORDER BY id", (sid,)).fetchall()
        ip = cfg.server_ip or ", ".join(sorted(S.dns_ips(cfg.base_domain))) or "<server-ip>"
        return render_template("site.html", site=site, domains=doms, server_ip=ip, max_mb=cfg.max_site_mb)

    @app.post("/sites/<int:sid>/upload")
    @login_required
    def upload(sid):
        site = own_site(sid)
        f = request.files.get("zip")
        if not f or not f.filename.lower().endswith(".zip"):
            return jsonify(ok=False, message="Ek .zip file chuno."), 400
        tmp = Path(tempfile.mkdtemp(prefix="up_", dir=S.site_root(cfg, sid).parent))
        try:
            files, size, skipped, has_index = S.extract_zip(f.stream, tmp / "public", cfg.max_site_mb * 1048576, cfg.max_files)
            S.replace_public(tmp / "public", S.public_dir(cfg, sid))
        except S.SiteError as e:
            return jsonify(ok=False, message=str(e)), 400
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        refresh_stats(sid)
        msg = f"{files} files upload ho gayi."
        if not has_index:
            msg += " Dhyan do: ZIP ke root mein index.html nahi mili."
        return jsonify(ok=True, message=msg, skipped=skipped[:20], url=cfg.site_url(site["subdomain"]))

    @app.post("/sites/<int:sid>/publish")
    @login_required
    def publish(sid):
        own_site(sid)
        fields = {k: (request.form.get(k) or "").strip()[:600] for k in ("title", "tagline", "about", "email")}
        fields["title"] = fields["title"][:80] or "My website"
        pub = S.public_dir(cfg, sid)
        pub.mkdir(parents=True, exist_ok=True)
        (pub / "index.html").write_text(S.render_starter(request.form.get("starter", "coming"), fields), encoding="utf-8")
        refresh_stats(sid)
        flash("Site publish ho gayi.", "ok")
        return redirect(f"/sites/{sid}")

    @app.post("/sites/<int:sid>/delete")
    @login_required
    def delete_site(sid):
        own_site(sid)
        db().execute("DELETE FROM sites WHERE id=?", (sid,))
        db().commit()
        shutil.rmtree(S.site_root(cfg, sid), ignore_errors=True)
        flash("Site delete ho gayi.", "ok")
        return redirect("/dashboard")

    @app.post("/sites/<int:sid>/domain")
    @login_required
    def add_domain(sid):
        own_site(sid)
        d = rdap.normalize(request.form.get("domain"))
        if not d:
            flash("Valid domain likho, jaise mysite.com", "err")
        elif d == cfg.base_domain or d.endswith("." + cfg.base_domain):
            flash("Is platform ka domain use nahi kar sakte. Subdomain already milta hai.", "err")
        elif db().execute("SELECT COUNT(*) FROM domains WHERE site_id=?", (sid,)).fetchone()[0] >= 2:
            flash("Ek site par maximum 2 custom domains.", "err")
        else:
            try:
                db().execute("INSERT INTO domains(site_id,domain) VALUES(?,?)", (sid, d))
                db().commit()
                flash("Domain add ho gaya. DNS set karke Verify dabao.", "ok")
            except sqlite3.IntegrityError:
                flash("Ye domain pehle se kisi site se juda hai.", "err")
        return redirect(f"/sites/{sid}")

    @app.post("/sites/<int:sid>/domain/<int:did>/verify")
    @login_required
    def verify_domain(sid, did):
        own_site(sid)
        row = db().execute("SELECT * FROM domains WHERE id=? AND site_id=?", (did, sid)).fetchone()
        if row is None:
            abort(404)
        expected = {cfg.server_ip} if cfg.server_ip else S.dns_ips(cfg.base_domain)
        got = S.dns_ips(row["domain"])
        if expected and got & expected:
            db().execute("UPDATE domains SET verified=1 WHERE id=?", (did,))
            db().commit()
            flash(f"{row['domain']} verify ho gaya. HTTPS certificate pehli visit par ban jaata hai.", "ok")
        else:
            flash("DNS abhi sahi server par point nahi kar raha. 5-30 minute baad dobara try karo (propagation).", "err")
        return redirect(f"/sites/{sid}")

    @app.post("/sites/<int:sid>/domain/<int:did>/delete")
    @login_required
    def delete_domain(sid, did):
        own_site(sid)
        db().execute("DELETE FROM domains WHERE id=? AND site_id=?", (did, sid))
        db().commit()
        return redirect(f"/sites/{sid}")

    # ------------------------------------------------------------------ admin
    @app.get("/admin")
    @admin_required
    def admin():
        users = db().execute("SELECT u.*, (SELECT COUNT(*) FROM sites s WHERE s.user_id=u.id) AS n FROM users u ORDER BY id").fetchall()
        rows = db().execute("SELECT s.*, u.email FROM sites s JOIN users u ON u.id=s.user_id ORDER BY s.id DESC").fetchall()
        return render_template("admin.html", users=users, sites=rows)

    @app.post("/admin/sites/<int:sid>/<action>")
    @admin_required
    def admin_action(sid, action):
        if action in ("suspend", "unsuspend"):
            db().execute("UPDATE sites SET status=? WHERE id=?", ("suspended" if action == "suspend" else "active", sid))
        elif action == "delete":
            db().execute("DELETE FROM sites WHERE id=?", (sid,))
            shutil.rmtree(S.site_root(cfg, sid), ignore_errors=True)
        else:
            abort(404)
        db().commit()
        return redirect("/admin")

    @app.errorhandler(404)
    def nf(_e):
        return render_template("404.html"), 404

    @app.errorhandler(400)
    def bad(e):
        return render_template("error.html", code=400, msg=getattr(e, "description", "Bad request")), 400

    @app.errorhandler(403)
    def forbidden(_e):
        return render_template("error.html", code=403, msg="Aapko is page ki permission nahi hai."), 403

    @app.errorhandler(413)
    def big(_e):
        if request.path.endswith("/upload"):
            return jsonify(ok=False, message=f"File {cfg.max_site_mb} MB se badi hai."), 413
        return render_template("error.html", code=413, msg="File bahut badi hai."), 413

    return app


def wsgi():
    return create_app()

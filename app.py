from datetime import date, datetime, timedelta
import hashlib
import os
import re
import secrets
import pyodbc
from dotenv import load_dotenv
from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from pymongo import MongoClient
from pymongo.errors import PyMongoError, ServerSelectionTimeoutError
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash, generate_password_hash
import pickle as pkl
import numpy as np

from chatbot.engine import chatbot_reply


load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change-this-secret-key")
app.config["PROFILE_UPLOAD_FOLDER"] = os.path.join(
    "static", "uploads", "profile_pictures"
)
# NEW: product image upload folder
app.config["PRODUCT_UPLOAD_FOLDER"] = os.path.join(
    "static", "uploads", "products"
)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB (raised for product images)
ALLOWED_PROFILE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
ALLOWED_PRODUCT_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
os.makedirs(app.config["PROFILE_UPLOAD_FOLDER"], exist_ok=True)
os.makedirs(app.config["PRODUCT_UPLOAD_FOLDER"], exist_ok=True)

# Seasonal promotion used across the storefront, checkout and ApBot. Different
# products receive different discounts while the original catalog price remains
# available for comparison. The promotion becomes active every August.
AZAADI_SALE = {
    "name": "Azaadi Sale",
    "headline": "Celebrate freedom with smarter savings",
    "description": "Limited-time savings on selected electronics, home, sports and book essentials.",
    "code": "AZAADI14",
    "discounts": {
        1: 25,
        2: 20,
        3: 15,
        14: 18,
        31: 30,
        42: 22,
        57: 20,
        61: 25,
        87: 14,
        91: 18,
    },
}


def get_active_sale():
    """Return the active seasonal promotion, or None outside August."""
    today = date.today()
    if today.month != 8:
        return None
    return {
        **AZAADI_SALE,
        "ends_on": date(today.year, 8, 31),
        "max_discount": max(AZAADI_SALE["discounts"].values()),
    }


@app.context_processor
def inject_storefront_promotion():
    """Make promotion information available to every Jinja template."""
    return {"active_sale": get_active_sale()}


@app.errorhandler(404)
def handle_not_found(e):
    flash("That page doesn't exist.")
    return redirect(url_for("index"))
@app.errorhandler(413)
def handle_file_too_large(e):
    flash("That file is too large — images must be 5 MB or smaller.")
    return redirect(request.referrer or url_for("index"))


# ====================== DATABASE CONNECTIONS ======================
def get_db_connection():
    """Open a SQL Server connection using a context-manager-safe wrapper."""
    connection_string = os.getenv(
        "SQLSERVER_CONNECTION_STRING",
        "DRIVER={ODBC Driver 17 for SQL Server};"
        "SERVER=localhost;"
        "DATABASE=EcommerceDB;"
        "Trusted_Connection=yes;"
        "Encrypt=no;"
        "TrustServerCertificate=yes;",
    )
    return pyodbc.connect(connection_string)
def get_mongo_db():
    """Return MongoDB database or None if MongoDB is not running."""
    try:
        client = MongoClient(
            os.getenv("MONGODB_URI", "mongodb://localhost:27017/"),
            serverSelectionTimeoutMS=1000,
        )
        client.admin.command("ping")
        return client["ecommerce_logs"]
    except ServerSelectionTimeoutError:
        return None
mongo_db = get_mongo_db()
schema_checked = False
def ensure_database_schema():
    """Add columns and constraints introduced after the initial project setup."""
    global schema_checked
    if schema_checked:
        return
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            IF COL_LENGTH('Users', 'status') IS NULL
            BEGIN
                ALTER TABLE Users ADD status VARCHAR(20) NOT NULL CONSTRAINT DF_Users_Status DEFAULT 'active';
            END
            IF COL_LENGTH('Users', 'reset_token') IS NULL
            BEGIN
                ALTER TABLE Users ADD reset_token NVARCHAR(200) NULL;
            END
            IF COL_LENGTH('Users', 'reset_token_expires') IS NULL
            BEGIN
                ALTER TABLE Users ADD reset_token_expires DATETIME NULL;
            END
            IF COL_LENGTH('Users', 'profile_image') IS NULL
            BEGIN
                ALTER TABLE Users ADD profile_image NVARCHAR(500) NULL;
            END
            IF COL_LENGTH('Products', 'stock') IS NULL
            BEGIN
                ALTER TABLE Products ADD stock INT NOT NULL DEFAULT 100;
            END
            IF COL_LENGTH('Orders', 'address') IS NULL
            BEGIN
                ALTER TABLE Orders ADD address NVARCHAR(500) NULL;
            END
            IF COL_LENGTH('Orders', 'phone') IS NULL
            BEGIN
                ALTER TABLE Orders ADD phone NVARCHAR(30) NULL;
            END
            -- NEW: local uploaded product image path
            IF COL_LENGTH('Products', 'local_image') IS NULL
            BEGIN
                ALTER TABLE Products ADD local_image NVARCHAR(500) NULL;
            END
            -- NEW: extra product images (comma-separated paths/URLs for gallery)
            IF COL_LENGTH('Products', 'extra_images') IS NULL
            BEGIN
                ALTER TABLE Products ADD extra_images NVARCHAR(MAX) NULL;
            END
            IF NOT EXISTS (
                SELECT 1 FROM sys.indexes
                WHERE name = 'UQ_Reviews_UserProduct' AND object_id = OBJECT_ID('Reviews')
            )
            BEGIN
                ALTER TABLE Reviews ADD CONSTRAINT UQ_Reviews_UserProduct UNIQUE (user_id, product_id);
            END
            """)
        conn.commit()
    schema_checked = True
@app.before_request
def before_request():
    ensure_database_schema()


# ====================== SMALL HELPER FUNCTIONS ======================
def rows_to_dicts(cursor):
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]
def row_to_dict(cursor, row):
    if not row:
        return None
    columns = [column[0] for column in cursor.description]
    return dict(zip(columns, row))
def log_activity(action, **extra_data):
    """Store user behaviour in MongoDB for analytics and recommendations."""
    if mongo_db is None:
        return
    document = {
        "action": action,
        "user_id": session.get("user_id"),
        "timestamp": datetime.utcnow(),
        **extra_data,
    }
    try:
        mongo_db.activities.insert_one(document)
    except PyMongoError:
        pass
def hash_password_sha256(password):
    """Old project password format. Kept so existing demo users still login."""
    return hashlib.sha256(password.encode()).hexdigest()
def password_matches(saved_password, entered_password):
    """Support both SHA256 legacy hash and scrypt (Werkzeug) hashes."""
    if saved_password == hash_password_sha256(entered_password):
        return True
    try:
        return check_password_hash(saved_password, entered_password)
    except ValueError:
        return False
def login_required():
    if "user_id" not in session:
        flash("Please login first.")
        return False
    user = get_user_by_id(session["user_id"])
    if not is_user_active(user):
        session.clear()
        flash("Your account is banned. Please contact the administrator.")
        return False
    return True
def admin_required():
    if not login_required():
        return False
    if session.get("role") != "admin":
        flash("Admin access only.")
        return False
    return True
def get_all_products(limit=None):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        sql = "SELECT * FROM Products ORDER BY id DESC"
        if limit:
            sql = f"SELECT TOP {int(limit)} * FROM Products ORDER BY id DESC"
        cursor.execute(sql)
        products = rows_to_dicts(cursor)
    # Resolve effective image URL
    for p in products:
        prepare_product(p)
    return products
def get_product_by_id(product_id):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM Products WHERE id = ?", product_id)
        product = row_to_dict(cursor, cursor.fetchone())
    if product:
        prepare_product(product)
    return product
def resolve_product_image(product):
    """Return the primary display image (used for cards/listings)."""
    local = product.get("local_image")
    if local:
        # local_image may now be comma-separated; use the first
        first_local = local.split(",")[0].strip()
        return url_for("static", filename=first_local)
    image_url = product.get("image_url") or ""
    first_url = image_url.split(",")[0].strip() if image_url else ""
    return first_url or "https://placehold.co/400x400/f1f5f9/94a3b8?text=No+Image"


def apply_sale_pricing(product):
    """Add original/sale prices without changing the stored catalog price."""
    original_price = float(product.get("price") or 0)
    sale = get_active_sale()
    discount = sale["discounts"].get(int(product.get("id") or 0), 0) if sale else 0
    product["original_price"] = original_price
    product["discount_percent"] = discount
    product["on_sale"] = discount > 0
    product["sale_name"] = sale["name"] if discount else None
    product["sale_price"] = round(original_price * (1 - discount / 100), 2) if discount else original_price
    return product


def prepare_product(product):
    """Attach the effective image and active promotional price to a product."""
    if not product:
        return product
    product["image_url"] = resolve_product_image(product)
    return apply_sale_pricing(product)


def get_all_product_images(product):
    """Return ordered list of all image URLs for the gallery on product detail page."""
    images = []
    # Local uploads first (comma-separated static-relative paths)
    local = (product.get("local_image") or "").strip()
    if local:
        for p in local.split(","):
            p = p.strip()
            if p:
                images.append(url_for("static", filename=p))
    # Extra images column (comma-separated — can be URLs or static paths)
    extra = (product.get("extra_images") or "").strip()
    if extra:
        for e in extra.split(","):
            e = e.strip()
            if e:
                if e.startswith("http"):
                    images.append(e)
                else:
                    images.append(url_for("static", filename=e))
    # URL field (comma-separated fallback URLs)
    url_field = (product.get("image_url") or "").strip()
    if url_field:
        for u in url_field.split(","):
            u = u.strip()
            if u and u not in images:
                images.append(u)
    if not images:
        images.append("https://placehold.co/600x600/f1f5f9/94a3b8?text=No+Image")
    return images
def get_user_by_email(email):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM Users WHERE email = ?", email)
        return row_to_dict(cursor, cursor.fetchone())
def get_user_by_id(user_id):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM Users WHERE id = ?", user_id)
        return row_to_dict(cursor, cursor.fetchone())
def is_user_active(user):
    return user and user.get("status", "active") == "active"
def recalculate_product_rating(cursor, product_id):
    cursor.execute(
        """
        UPDATE Products
        SET rating = ISNULL((SELECT AVG(CAST(rating AS FLOAT)) FROM Reviews WHERE product_id = ?), 4.0)
        WHERE id = ?
        """,
        product_id,
        product_id,
    )
def allowed_profile_image(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_PROFILE_EXTENSIONS
    )
def allowed_product_image(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_PRODUCT_EXTENSIONS
    )
def save_profile_image(file_storage, user_id):
    if not file_storage or not file_storage.filename:
        return None
    if not allowed_profile_image(file_storage.filename):
        flash("Profile picture must be PNG, JPG, JPEG, GIF or WEBP.")
        return None
    extension = secure_filename(file_storage.filename).rsplit(".", 1)[1].lower()
    filename = f"user_{user_id}_{secrets.token_hex(8)}.{extension}"
    upload_path = os.path.join(app.config["PROFILE_UPLOAD_FOLDER"], filename)
    file_storage.save(upload_path)
    return f"uploads/profile_pictures/{filename}"
def save_product_image(file_storage, product_name="product"):
    """Save an uploaded product image and return the static-relative path."""
    if not file_storage or not file_storage.filename:
        return None
    if not allowed_product_image(file_storage.filename):
        flash("Product image must be PNG, JPG, JPEG, GIF or WEBP.")
        return None
    extension = secure_filename(file_storage.filename).rsplit(".", 1)[1].lower()
    safe_name = secure_filename(product_name.replace(" ", "_").lower())[:30]
    filename = f"{safe_name}_{secrets.token_hex(8)}.{extension}"
    upload_path = os.path.join(app.config["PRODUCT_UPLOAD_FOLDER"], filename)
    file_storage.save(upload_path)
    return f"uploads/products/{filename}"
def save_multiple_product_images(file_list, product_name="product"):
    """Save multiple uploaded images; return comma-separated static-relative paths."""
    saved = []
    for fs in file_list:
        if fs and fs.filename:
            path = save_product_image(fs, product_name)
            if path:
                saved.append(path)
    return ",".join(saved) if saved else None
def get_customer_purchased_items(user_id):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                o.id AS order_id,
                o.order_date,
                o.status,
                oi.quantity,
                oi.price AS purchase_price,
                p.id AS product_id,
                p.name,
                p.category,
                p.brand,
                p.description,
                p.image_url,
                p.local_image,
                p.rating
            FROM Orders o
            JOIN OrderItems oi ON o.id = oi.order_id
            JOIN Products p ON oi.product_id = p.id
            WHERE o.user_id = ?
            ORDER BY o.order_date DESC, o.id DESC
            """,
            user_id,
        )
        items = rows_to_dicts(cursor)
    for item in items:
        prepare_product(item)
    return items
def get_purchased_product_ids(user_id):
    """Return set of product IDs from DELIVERED orders only."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT DISTINCT oi.product_id
            FROM Orders o JOIN OrderItems oi ON o.id = oi.order_id
            WHERE o.user_id = ? AND o.status = 'Delivered'
            """,
            user_id,
        )
        return {row[0] for row in cursor.fetchall()}
def get_categories():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT category FROM Products ORDER BY category")
        return [row[0] for row in cursor.fetchall()]
def search_and_filter_products(
    query="",
    category="",
    brand="",
    min_price=None,
    max_price=None,
    min_rating=None,
    sort_by="name",
):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        sql = "SELECT * FROM Products WHERE 1=1"
        params = []
        if query:
            sql += " AND (name LIKE ? OR description LIKE ? OR brand LIKE ?)"
            keyword = f"%{query}%"
            params.extend([keyword, keyword, keyword])
            log_activity("search", query=query)
        if category:
            sql += " AND category = ?"
            params.append(category)
        if brand:
            sql += " AND brand LIKE ?"
            params.append(f"%{brand}%")
        if min_price is not None:
            sql += " AND price >= ?"
            params.append(min_price)
        if max_price is not None:
            sql += " AND price <= ?"
            params.append(max_price)
        if min_rating is not None:
            sql += " AND rating >= ?"
            params.append(min_rating)
        sort_options = {
            "price_low": "price ASC",
            "price_high": "price DESC",
            "rating": "rating DESC",
            "latest": "id DESC",
            "name": "name ASC",
        }
        sql += f" ORDER BY {sort_options.get(sort_by, 'name ASC')}"
        cursor.execute(sql, params)
        products = rows_to_dicts(cursor)
    for p in products:
        prepare_product(p)
    return products


# ====================== RECOMMENDATION ENGINE ======================
def get_trending_products(limit=4):
    """Return trending products.
    Improvement: uses recency-weighted scoring so a product viewed 10 times
    last week ranks above one viewed 20 times six months ago.
    Falls back to all-time counts, then to newest products.
    """
    if mongo_db is not None:
        try:
            # Recency-weighted: events in the last 7 days count double
            cutoff = datetime.utcnow() - timedelta(days=7)
            pipeline = [
                {"$match": {"product_id": {"$ne": None}}},
                {
                    "$group": {
                        "_id": "$product_id",
                        "total": {"$sum": 1},
                        "recent": {
                            "$sum": {
                                "$cond": [{"$gte": ["$timestamp", cutoff]}, 2, 1]
                            }
                        },
                    }
                },
                {"$addFields": {"score": "$recent"}},
                {"$sort": {"score": -1}},
                {"$limit": limit},
            ]
            product_ids_trending = [
                doc["_id"] for doc in mongo_db.activities.aggregate(pipeline)
            ]
            products = get_products_by_ids(product_ids_trending)
            if products:
                return products[:limit]
        except PyMongoError:
            pass
    return get_all_products(limit)
def get_products_by_ids(pid_list):
    if not pid_list:
        return []
    with get_db_connection() as conn:
        cursor = conn.cursor()
        placeholders = ",".join("?" for _ in pid_list)
        cursor.execute(f"SELECT * FROM Products WHERE id IN ({placeholders})", pid_list)
        products = rows_to_dicts(cursor)
    for p in products:
        prepare_product(p)
    product_map = {p["id"]: p for p in products}
    return [product_map[pid] for pid in pid_list if pid in product_map]


def get_sale_products(limit=6):
    """Return in-stock products included in the active seasonal sale."""
    sale = get_active_sale()
    if not sale:
        return []
    products = get_products_by_ids(list(sale["discounts"]))
    products = [product for product in products if product.get("stock", 0) > 0 and product.get("on_sale")]
    products.sort(key=lambda product: (-product["discount_percent"], product["sale_price"]))
    return products[:limit]


def get_content_based_recommendations(product, limit=4, reason="Similar products"):
    """Content-based KNN recommendations.
    Improvement: uses the blended feature matrix (TF-IDF + normalised rating/price)
    that the notebook now saves as tfidf_matrix.pkl, so results respect quality and
    budget tier, not just text similarity alone.
    """
    if not product:
        recs = get_trending_products(limit)
        for r in recs:
            r["rec_reason"] = "Popular now"
        return recs
    if knn_content is None or tfidf_matrix is None or product_ids is None:
        # SQL fallback when model files are missing
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT TOP (?) * FROM Products WHERE id <> ? AND (category = ? OR brand = ?) ORDER BY rating DESC",
                limit, product["id"], product["category"], product["brand"],
            )
            products = rows_to_dicts(cursor)
        for p in products:
            prepare_product(p)
            p["rec_reason"] = "More in this category"
        return products
    try:
        idx = product_ids.index(product["id"])
    except ValueError:
        recs = get_trending_products(limit)
        for r in recs:
            r["rec_reason"] = "Popular now"
        return recs
    # n_neighbors must not exceed matrix size; guard for very small catalogues
    n_neighbors = min(limit + 1, tfidf_matrix.shape[0])
    distances, indices = knn_content.kneighbors(tfidf_matrix[idx].reshape(1, -1), n_neighbors=n_neighbors)
    recommended_ids = [product_ids[i] for i in indices[0][1:]]
    if not recommended_ids:
        recs = get_trending_products(limit)
        for r in recs:
            r["rec_reason"] = "Popular now"
        return recs
    with get_db_connection() as conn:
        cursor = conn.cursor()
        placeholders = ",".join(["?" for _ in recommended_ids])
        cursor.execute(
            f"SELECT * FROM Products WHERE id IN ({placeholders})", recommended_ids
        )
        products = rows_to_dicts(cursor)
    for p in products:
        prepare_product(p)
        p["rec_reason"] = "Similar pick"
    return products
def get_collaborative_recommendations(user_id, limit=4):
    if knn_users is None or user_item_matrix is None:
        recs = get_trending_products(limit)
        for r in recs:
            r["rec_reason"] = "Popular now"
        return recs
    if user_id not in user_item_matrix.index:
        recs = get_trending_products(limit)
        for r in recs:
            r["rec_reason"] = "Popular now"
        return recs
    user_row_index = user_item_matrix.index.get_loc(user_id)
    user_vector = user_item_matrix.iloc[[user_row_index]]
    distances, indices = knn_users.kneighbors(user_vector)
    similar_user_indices = indices[0][1:]
    similar_user_ids = user_item_matrix.index[similar_user_indices]
    already_bought = set(user_item_matrix.columns[user_item_matrix.loc[user_id] > 0])
    recommendation_scores = {}
    for i, sim_user_id in enumerate(similar_user_ids):
        sim_score = 1 - distances[0][i + 1]
        if sim_score <= 0:
            continue
        for pid, qty in user_item_matrix.loc[sim_user_id].items():
            if qty > 0 and pid not in already_bought:
                recommendation_scores[pid] = recommendation_scores.get(pid, 0) + (qty * sim_score)
    sorted_recs = sorted(recommendation_scores.items(), key=lambda x: x[1], reverse=True)[:limit]
    if not sorted_recs:
        recs = get_trending_products(limit)
        for r in recs:
            r["rec_reason"] = "Popular now"
        return recs
    recommended_ids = [pid for pid, score in sorted_recs]
    with get_db_connection() as conn:
        cursor = conn.cursor()
        placeholders = ",".join(["?" for _ in recommended_ids])
        cursor.execute(
            f"SELECT * FROM Products WHERE id IN ({placeholders})", recommended_ids
        )
        products = rows_to_dicts(cursor)
    for p in products:
        prepare_product(p)
        p["rec_reason"] = "Recommended for you"
    return products
def get_personalized_recommendations(limit=4):
    """Homepage recommendations for the logged-in user.

    Improvement: now calls the hybrid model (content + collab) instead of
    pure collaborative, so cold-start users who have viewed products but not
    yet bought still get relevant suggestions rather than pure trending fallback.

    Priority order:
      1. Hybrid (collab + content from last viewed product) for known users
      2. Content-based from last viewed product for cold-start users
      3. Trending as final fill
    """
    user_id = session.get("user_id")
    recommendations = []
    content_w = hybrid_weights.get("content_w", 0.5)
    collab_w = hybrid_weights.get("collab_w", 0.5)

    # --- Part 1: collaborative signal ---
    if knn_users is not None and user_item_matrix is not None and user_id in (user_item_matrix.index if user_item_matrix is not None else []):
        collab = get_collaborative_recommendations(user_id, limit)
        recommendations.extend(collab)

    # --- Part 2: content signal from last viewed product ---
    last_product = None
    if mongo_db is not None and user_id:
        try:
            last_view = mongo_db.activities.find_one(
                {"user_id": user_id, "action": "view", "product_id": {"$ne": None}},
                sort=[("timestamp", -1)],
            )
            if last_view:
                last_product = get_product_by_id(last_view["product_id"])
        except PyMongoError:
            pass

    if last_product and len(recommendations) < limit:
        content_recs = get_content_based_recommendations(last_product, limit)
        for r in content_recs:
            r["rec_reason"] = "Inspired by your browsing"
        recommendations.extend(content_recs)

    # --- Part 3: trending fill ---
    trending = get_trending_products(limit)
    for t in trending:
        t.setdefault("rec_reason", "Popular now")

    # Deduplicate while preserving order
    seen_ids = set()
    unique = []
    for product in recommendations + trending:
        if product["id"] not in seen_ids:
            unique.append(product)
            seen_ids.add(product["id"])
        if len(unique) == limit:
            break
    return unique


# ====================== LOAD ML MODELS ======================
MODEL_DIR = os.path.dirname(os.path.abspath(__file__))
def _load_pickle(filename):
    """Load a single model file. Returns None (and prints a clear warning)
    if the file is missing or a required library isn't installed, instead
    of taking every other already-loaded model down with it."""
    path = os.path.join(MODEL_DIR, filename)
    try:
        with open(path, "rb") as f:
            return pkl.load(f)
    except FileNotFoundError:
        print(f"[ML] {filename} not found — related recommendations will fall back to SQL.")
        return None
    except Exception as e:
        print(f"[ML] {filename} could not be loaded ({type(e).__name__}: {e}) — related recommendations will fall back to SQL.")
        return None
knn_content = _load_pickle("knn_content.pkl")
tfidf_matrix = _load_pickle("tfidf_matrix.pkl")   # combined dense matrix (SVD + numeric)
product_ids = _load_pickle("product_ids.pkl")
feature_scaler = _load_pickle("feature_scaler.pkl")
numeric_weight = _load_pickle("numeric_weight.pkl") or 5
svd_model = _load_pickle("svd.pkl")               # NEW: TruncatedSVD for query transform
knn_users = _load_pickle("knn_users.pkl")
user_item_matrix = _load_pickle("user_item_matrix.pkl")
hybrid_weights = _load_pickle("hybrid_weights.pkl") or {"content_w": 0.5, "collab_w": 0.5}
if knn_content is not None and tfidf_matrix is not None and product_ids is not None:
    print("[ML] Content-based model loaded.")
if knn_users is not None and user_item_matrix is not None:
    print("[ML] Collaborative model loaded.")
if knn_content is None or knn_users is None:
    print(
        "[ML] WARNING: one or more models failed to load — check the messages above. "
        "Install requirements-app.txt so pandas is present and NumPy/scikit-learn "
        "match the saved model artifacts."
    )


# ====================== PUBLIC ROUTES ======================
@app.route("/")
def index():
    featured = get_all_products(6)
    trending = get_trending_products(4)
    recommended = get_personalized_recommendations(4)
    sale_products = get_sale_products(6)
    return render_template(
        "index.html",
        products=featured,
        trending=trending,
        recommended=recommended,
        sale_products=sale_products,
    )
@app.route("/products")
def products():
    query = request.args.get("search", "").strip()
    category = request.args.get("category", "").strip()
    brand = request.args.get("brand", "").strip()
    min_price = request.args.get("min_price", type=float)
    max_price = request.args.get("max_price", type=float)
    min_rating = request.args.get("min_rating", type=float)
    sort_by = request.args.get("sort", "name")
    filtered_products = search_and_filter_products(
        query, category, brand, min_price, max_price, min_rating, sort_by
    )
    return render_template(
        "products.html",
        products=filtered_products,
        categories=get_categories(),
        query=query,
        category=category,
        brand=brand,
        min_price=min_price,
        max_price=max_price,
        min_rating=min_rating,
        sort_by=sort_by,
    )
@app.route("/product/<int:product_id>")
def product_detail(product_id):
    product = get_product_by_id(product_id)
    if not product:
        flash("Product not found.")
        return redirect(url_for("products"))
    log_activity("view", product_id=product_id)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT r.rating, r.comment, r.created_at, u.name
            FROM Reviews r
            JOIN Users u ON r.user_id = u.id
            WHERE r.product_id = ?
            ORDER BY r.created_at DESC
            """,
            product_id,
        )
        reviews = rows_to_dicts(cursor)
    recommended = get_content_based_recommendations(product, 4)
    user_reviewed = False
    if session.get("user_id"):
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM Reviews WHERE user_id = ? AND product_id = ?",
                session["user_id"], product_id,
            )
            user_reviewed = cursor.fetchone() is not None
    user_purchased = False
    if session.get("user_id"):
        pid_set = get_purchased_product_ids(session["user_id"])
        user_purchased = product_id in pid_set
    return render_template(
        "product_detail.html",
        product=product,
        product_gallery_images=get_all_product_images(product),
        reviews=reviews,
        recommended=recommended,
        user_reviewed=user_reviewed,
        user_purchased=user_purchased,
    )
@app.route("/product/<int:product_id>/review", methods=["POST"])
def add_review(product_id):
    if not login_required():
        return redirect(url_for("login"))
    pid_set = get_purchased_product_ids(session["user_id"])
    if product_id not in pid_set:
        flash("You can only review products you have purchased.")
        return redirect(url_for("product_detail", product_id=product_id))
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM Reviews WHERE user_id = ? AND product_id = ?",
            session["user_id"], product_id,
        )
        if cursor.fetchone():
            flash("You have already reviewed this product.")
            return redirect(url_for("product_detail", product_id=product_id))
    rating = request.form.get("rating", type=int)
    comment = request.form.get("comment", "").strip()
    if rating is None or rating < 1 or rating > 5:
        flash("Rating must be between 1 and 5.")
        return redirect(url_for("product_detail", product_id=product_id))
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO Reviews (user_id, product_id, rating, comment) VALUES (?, ?, ?, ?)",
            session["user_id"], product_id, rating, comment,
        )
        recalculate_product_rating(cursor, product_id)
        conn.commit()
    log_activity("review", product_id=product_id, rating=rating)
    flash("Thanks for your review.")
    return redirect(url_for("product_detail", product_id=product_id))

# ====================== CHATBOT API ======================
CHAT_SEARCH_STOP_WORDS = {
    "about", "all", "any", "best", "buy", "can", "cheap", "do", "find",
    "for", "good", "have", "help", "item", "items", "looking", "me", "need",
    "please", "product", "products", "search", "show", "some", "the", "want",
    "with", "under", "below", "budget", "less", "than", "within", "upto", "up", "to", "rs", "pkr",
    "mujhe", "dikhao", "chahiye", "karo", "kro", "hai", "kya",
}


def serialize_chat_products(products, limit=3):
    """Return a small, browser-safe product payload for chat cards."""
    cards = []
    for product in products[:limit]:
        cards.append({
            "id": int(product["id"]),
            "name": product["name"],
            "brand": product.get("brand") or "",
            "category": product.get("category") or "",
            "price": float(product.get("sale_price") or product["price"]),
            "original_price": float(product.get("original_price") or product["price"]),
            "discount_percent": int(product.get("discount_percent") or 0),
            "sale_name": product.get("sale_name") or "",
            "rating": float(product.get("rating") or 0),
            "stock": int(product.get("stock") or 0),
            "description": (product.get("description") or "")[:180],
            "image_url": product.get("image_url") or resolve_product_image(product),
            "url": url_for("product_detail", product_id=product["id"]),
            "reason": product.get("rec_reason") or "",
        })
    return cards


def find_products_for_chat(message, limit=3):
    """Search live inventory using a category, budget and useful message words."""
    text = message.casefold()
    categories = get_categories()
    category = next((item for item in categories if item.casefold() in text), None)

    budget = None
    budget_match = re.search(
        r"(?:under|below|less than|within|up to|upto|budget(?: of)?)\s*(?:rs\.?|pkr)?\s*([\d,]+)\s*(k)?",
        text,
    )
    if budget_match:
        budget = float(budget_match.group(1).replace(",", ""))
        if budget_match.group(2):
            budget *= 1000

    keywords = []
    for word in re.findall(r"[a-z0-9]+", text):
        if len(word) > 2 and not word.isdigit() and word not in CHAT_SEARCH_STOP_WORDS:
            keywords.append(word)
    keywords = list(dict.fromkeys(keywords))[:4]

    sql = "SELECT TOP 3 * FROM Products WHERE stock > 0"
    params = []
    if category:
        sql += " AND category = ?"
        params.append(category)
    if budget is not None:
        sql += " AND price <= ?"
        params.append(budget)
    if keywords and not category:
        conditions = []
        for keyword in keywords:
            conditions.append("(name LIKE ? OR brand LIKE ? OR category LIKE ? OR description LIKE ?)")
            search_value = f"%{keyword}%"
            params.extend([search_value] * 4)
        sql += " AND (" + " OR ".join(conditions) + ")"
    sql += " ORDER BY rating DESC, price ASC"

    with get_db_connection() as conn:
        cursor = conn.cursor()
        if params:
            cursor.execute(sql, params)
        else:
            cursor.execute(sql)
        products = rows_to_dicts(cursor)

    for product in products:
        prepare_product(product)
    return products[:limit]


@app.route("/api/chat", methods=["POST"])
def chatbot_api():
    data = request.get_json(silent=True) or {}

    message = str(data.get("message", "")).strip()

    if not message:
        return jsonify({
            "reply": "Please enter a message.",
            "intent": "empty",
            "confidence": 0
        }), 400

    if len(message) > 500:
        return jsonify({
            "reply": "Your message is too long. Please use a shorter message.",
            "intent": "too_long",
            "confidence": 0
        }), 400

    result = chatbot_reply(message)
    intent = result.get("intent", "unknown")
    result["reply"] = result.get("reply", "").replace("Cartify", "ZiloCart")
    result["products"] = []

    if intent == "unknown":
        result["reply"] = (
            "That topic is outside my shopping support area. I can help you "
            "discover products, compare options, find current offers, track an "
            "order, or get help with delivery, returns and checkout."
        )

    elif intent == "recommendation":
        if session.get("user_id"):
            products = get_personalized_recommendations(3)
            result["reply"] = "Here are a few products selected for you."
        else:
            products = get_trending_products(3)
            result["reply"] = "Here are a few popular products to get you started. Sign in for personalised picks."
        result["products"] = serialize_chat_products(products)

    elif intent in {"product_search", "product_details", "similar_products", "product_comparison"}:
        products = find_products_for_chat(message, 3)
        if not products:
            products = get_trending_products(3)
            result["reply"] = "I could not find an exact match, but these popular products may help."
        elif intent == "similar_products":
            result["reply"] = "Here are some related options from the live catalog."
        elif intent == "product_comparison":
            result["reply"] = "Open these products to compare their price, rating, features and stock."
        else:
            result["reply"] = "Here are the closest matches from the live catalog."
        result["products"] = serialize_chat_products(products)

    elif intent == "offers":
        products = get_sale_products(3)
        sale = get_active_sale()
        if products and sale:
            result["reply"] = (
                f"The {sale['name']} is live with up to {sale['max_discount']}% off selected products. "
                f"The offer runs until {sale['ends_on'].strftime('%d %B')}."
            )
        else:
            products = search_and_filter_products(sort_by="price_low")[:3]
            result["reply"] = "There is no seasonal sale right now, but these are some affordable picks."
        result["products"] = serialize_chat_products(products)

    elif intent == "cart":
        cart = session.get("cart", [])
        if not session.get("user_id"):
            result["reply"] = "Please sign in to view and manage your cart."
        elif not cart:
            result["reply"] = "Your cart is currently empty."
        else:
            product_ids_in_cart = [item["id"] for item in cart]
            products = get_products_by_ids(product_ids_in_cart)
            quantity_total = sum(item.get("quantity", 0) for item in cart)
            result["reply"] = f"Your cart contains {quantity_total} item(s)."
            result["products"] = serialize_chat_products(products)

    elif intent == "order_tracking":
        if not session.get("user_id"):
            result["reply"] = "Please sign in to view your order status."
        else:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT TOP 1 id, status, order_date, total_amount
                    FROM Orders
                    WHERE user_id = ?
                    ORDER BY order_date DESC, id DESC
                    """,
                    session["user_id"],
                )
                order = cursor.fetchone()
            if order:
                order_date = order[2].strftime("%d %b %Y") if order[2] else "recently"
                result["reply"] = (
                    f"Your latest order #{order[0]}, placed {order_date}, is currently "
                    f"{order[1].lower()}. Total: Rs {float(order[3]):,.2f}."
                )
            else:
                result["reply"] = "You do not have any orders yet."

    elif intent == "checkout":
        if not session.get("user_id"):
            result["reply"] = "Please sign in before continuing to checkout."
        elif not session.get("cart"):
            result["reply"] = "Your cart is empty. Add a product before checking out."
        else:
            quantity_total = sum(item.get("quantity", 0) for item in session["cart"])
            result["reply"] = f"You have {quantity_total} item(s) ready for checkout."

    elif intent == "account":
        if not session.get("user_id"):
            result["reply"] = "Please sign in to view your account information."
        else:
            user = get_user_by_id(session["user_id"])
            result["reply"] = (
                f"You are signed in as {user['name']} ({user['email']}). "
                "Open your profile to manage your details and password."
            )

    # Customer privacy: ApBot can use the logged-in customer's own account,
    # cart and orders, but never exposes another user's personal information.
    return jsonify(result)


# ====================== AUTH ROUTES ======================
@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        return redirect(url_for("index"))
    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        if len(name) < 2:
            flash("Name must be at least 2 characters.")
            return redirect(url_for("register"))
        if len(password) < 6:
            flash("Password must be at least 6 characters.")
            return redirect(url_for("register"))
        if get_user_by_email(email):
            flash("Email already exists.")
            return redirect(url_for("register"))
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO Users (name, email, password, role) VALUES (?, ?, ?, ?)",
                name, email, generate_password_hash(password), "customer",
            )
            conn.commit()
        flash("Registration successful. Please login.")
        return redirect(url_for("login"))
    return render_template("register.html")
@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("index"))
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        user = get_user_by_email(email)
        if user and password_matches(user["password"], password):
            if not is_user_active(user):
                flash("Your account is banned. Please contact the administrator.")
                return redirect(url_for("login"))
            session.clear()
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            session["role"] = user.get("role", "customer")
            session["profile_image"] = user.get("profile_image")
            log_activity("login")
            flash("Login successful.")
            return redirect(url_for("index"))
        flash("Invalid email or password.")
    return render_template("login.html")
@app.route("/forgot_password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        user = get_user_by_email(email)
        if user and is_user_active(user):
            token = secrets.token_urlsafe(32)
            expires_at = datetime.now() + timedelta(hours=1)
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    UPDATE Users
                    SET reset_token = ?, reset_token_expires = ?
                    WHERE id = ?
                    """,
                    token, expires_at, user["id"],
                )
                conn.commit()
            reset_url = url_for("reset_password", token=token, _external=True)
            log_activity("password_reset_requested", user_id=user["id"])
            flash(
                f"Reset link (demo only — would be emailed in production): {reset_url}",
                "info",
            )
        else:
            flash("If that active account exists, a reset link has been sent.", "info")
        return redirect(url_for("forgot_password"))
    return render_template("forgot_password.html")
@app.route("/reset_password/<token>", methods=["GET", "POST"])
def reset_password(token):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM Users
            WHERE reset_token = ? AND reset_token_expires > GETDATE() AND status = 'active'
            """,
            token,
        )
        user = row_to_dict(cursor, cursor.fetchone())
    if not user:
        flash("This password reset link is invalid or expired.")
        return redirect(url_for("forgot_password"))
    if request.method == "POST":
        password = request.form["password"]
        confirm_password = request.form["confirm_password"]
        if password != confirm_password:
            flash("Passwords do not match.")
            return redirect(url_for("reset_password", token=token))
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE Users
                SET password = ?, reset_token = NULL, reset_token_expires = NULL
                WHERE id = ?
                """,
                generate_password_hash(password), user["id"],
            )
            conn.commit()
        flash("Password updated. Please login with your new password.")
        return redirect(url_for("login"))
    return render_template("reset_password.html")
@app.route("/profile", methods=["GET", "POST"])
def profile():
    if not login_required():
        return redirect(url_for("login"))
    user = get_user_by_id(session["user_id"])
    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")
        profile_image = save_profile_image(
            request.files.get("profile_image"), user["id"]
        )
        existing_user = get_user_by_email(email)
        if existing_user and existing_user["id"] != user["id"]:
            flash("Email already belongs to another account.")
            return redirect(url_for("profile"))
        with get_db_connection() as conn:
            cursor = conn.cursor()
            if new_password:
                if not password_matches(user["password"], current_password):
                    flash("Current password is incorrect.")
                    return redirect(url_for("profile"))
                if new_password != confirm_password:
                    flash("New passwords do not match.")
                    return redirect(url_for("profile"))
                if profile_image:
                    cursor.execute(
                        "UPDATE Users SET name = ?, email = ?, password = ?, profile_image = ? WHERE id = ?",
                        name, email, generate_password_hash(new_password), profile_image, user["id"],
                    )
                else:
                    cursor.execute(
                        "UPDATE Users SET name = ?, email = ?, password = ? WHERE id = ?",
                        name, email, generate_password_hash(new_password), user["id"],
                    )
            else:
                if profile_image:
                    cursor.execute(
                        "UPDATE Users SET name = ?, email = ?, profile_image = ? WHERE id = ?",
                        name, email, profile_image, user["id"],
                    )
                else:
                    cursor.execute(
                        "UPDATE Users SET name = ?, email = ? WHERE id = ?",
                        name, email, user["id"],
                    )
            conn.commit()
        session["user_name"] = name
        if profile_image:
            session["profile_image"] = profile_image
        flash("Profile updated.")
        return redirect(url_for("profile"))
    return render_template("profile.html", user=user)
@app.route("/logout")
def logout():
    log_activity("logout")
    session.clear()
    flash("Logged out.")
    return redirect(url_for("index"))
# ====================== CART AND ORDER ROUTES ======================
@app.route("/add_to_cart/<int:product_id>", methods=["POST", "GET"])
def add_to_cart(product_id):
    if not login_required():
        return redirect(url_for("login"))
    if session.get("role") == "admin":
        flash("Admins can manage products, but cannot add products to cart.")
        return redirect(
            request.referrer or url_for("product_detail", product_id=product_id)
        )
    cart = session.get("cart", [])
    product = get_product_by_id(product_id)
    if not product:
        flash("Product not found.")
        return redirect(url_for("products"))
    if product.get("stock", 100) < 1:
        flash("Sorry, this product is out of stock.")
        return redirect(request.referrer or url_for("product_detail", product_id=product_id))
    for item in cart:
        if item["id"] == product_id:
            if item["quantity"] + 1 > product.get("stock", 100):
                flash(f"Only {product.get('stock', 100)} unit(s) of '{product['name']}' are available.")
                return redirect(request.referrer or url_for("product_detail", product_id=product_id))
            item["quantity"] += 1
            item["price"] = float(product.get("sale_price") or product["price"])
            item["original_price"] = float(product.get("original_price") or product["price"])
            item["discount_percent"] = int(product.get("discount_percent") or 0)
            item["sale_name"] = product.get("sale_name")
            break
    else:
        cart.append(
            {
                "id": product["id"],
                "name": product["name"],
                "price": float(product.get("sale_price") or product["price"]),
                "original_price": float(product.get("original_price") or product["price"]),
                "discount_percent": int(product.get("discount_percent") or 0),
                "sale_name": product.get("sale_name"),
                "quantity": 1,
            }
        )
    session["cart"] = cart
    session.modified = True
    log_activity("add_to_cart", product_id=product_id)
    flash("Product added to cart.")
    return redirect(
        request.referrer or url_for("product_detail", product_id=product_id)
    )
@app.route("/cart")
def view_cart():
    if not login_required():
        return redirect(url_for("login"))
    cart_items = session.get("cart", [])
    # Refresh active promotional prices before displaying the cart.
    for item in cart_items:
        product = get_product_by_id(item["id"])
        if product:
            item["price"] = float(product.get("sale_price") or product["price"])
            item["original_price"] = float(product.get("original_price") or product["price"])
            item["discount_percent"] = int(product.get("discount_percent") or 0)
            item["sale_name"] = product.get("sale_name")
    session["cart"] = cart_items
    session.modified = True
    total = sum(item["price"] * item["quantity"] for item in cart_items)
    flat_items = get_customer_purchased_items(session["user_id"])
    purchased_orders = {}
    for item in flat_items:
        oid = item["order_id"]
        if oid not in purchased_orders:
            purchased_orders[oid] = {
                "order_id": oid,
                "order_date": item["order_date"],
                "status": item["status"],
                "products": [],
                "order_total": 0.0,
            }
        purchased_orders[oid]["products"].append(item)
        purchased_orders[oid]["order_total"] += float(item["purchase_price"]) * int(item["quantity"])
    purchased_orders_list = list(purchased_orders.values())
    return render_template(
        "cart.html",
        cart_items=cart_items,
        total=total,
        purchased_orders=purchased_orders_list,
    )
@app.route("/update_cart/<int:product_id>", methods=["POST"])
def update_cart(product_id):
    if not login_required():
        return redirect(url_for("login"))
    quantity = request.form.get("quantity", type=int)
    cart = session.get("cart", [])
    if quantity is None or quantity < 1:
        cart = [item for item in cart if item["id"] != product_id]
    else:
        # Cap quantity at available stock
        product = get_product_by_id(product_id)
        if product:
            max_stock = product.get("stock", 100)
            if quantity > max_stock:
                quantity = max_stock
                flash(f"Quantity capped at available stock ({max_stock}).")
        for item in cart:
            if item["id"] == product_id:
                item["quantity"] = quantity
    session["cart"] = cart
    session.modified = True
    flash("Cart updated.")
    return redirect(url_for("view_cart"))
@app.route("/remove_from_cart/<int:product_id>", methods=["POST"])
def remove_from_cart(product_id):
    if not login_required():
        return redirect(url_for("login"))
    session["cart"] = [
        item for item in session.get("cart", []) if item["id"] != product_id
    ]
    session.modified = True
    flash("Item removed from cart.")
    return redirect(url_for("view_cart"))
@app.route("/clear_cart", methods=["POST"])
def clear_cart():
    if not login_required():
        return redirect(url_for("login"))
    session["cart"] = []
    session.modified = True
    flash("Cart cleared.")
    return redirect(url_for("view_cart"))
@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    if not login_required():
        return redirect(url_for("login"))
    cart_items = session.get("cart", [])
    if not cart_items:
        flash("Your cart is empty.")
        return redirect(url_for("view_cart"))
    # Reconfirm sale prices when checkout is opened directly.
    for item in cart_items:
        product = get_product_by_id(item["id"])
        if product:
            item["price"] = float(product.get("sale_price") or product["price"])
            item["original_price"] = float(product.get("original_price") or product["price"])
            item["discount_percent"] = int(product.get("discount_percent") or 0)
            item["sale_name"] = product.get("sale_name")
    session["cart"] = cart_items
    session.modified = True
    total = sum(item["price"] * item["quantity"] for item in cart_items)
    if request.method == "POST":
        address = request.form.get("address", "").strip()
        phone = request.form.get("phone", "").strip()
        if not address or not phone:
            flash("Please provide delivery address and phone number.")
            return render_template("checkout.html", cart_items=cart_items, total=total)
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO Orders (user_id, total_amount, status, address, phone) OUTPUT INSERTED.id VALUES (?, ?, ?, ?, ?)",
                session["user_id"], total, "Placed", address, phone,
            )
            order_id = cursor.fetchone()[0]
            for item in cart_items:
                # Re-check live stock before inserting — cart may be stale
                cursor.execute("SELECT stock FROM Products WHERE id = ?", item["id"])
                stock_row = cursor.fetchone()
                available = stock_row[0] if stock_row else 0
                if available < item["quantity"]:
                    conn.rollback()
                    flash(
                        f"'{item['name']}' only has {available} unit(s) in stock "
                        f"but your cart has {item['quantity']}. Please update your cart."
                    )
                    return render_template("checkout.html", cart_items=cart_items, total=total)
                cursor.execute(
                    "INSERT INTO OrderItems (order_id, product_id, quantity, price) VALUES (?, ?, ?, ?)",
                    order_id, item["id"], item["quantity"], item["price"],
                )
                # Decrement stock so inventory stays accurate
                cursor.execute(
                    "UPDATE Products SET stock = stock - ? WHERE id = ?",
                    item["quantity"], item["id"],
                )
                log_activity(
                    "order_item",
                    product_id=item["id"],
                    order_id=order_id,
                    quantity=item["quantity"],
                )
            conn.commit()
        session["cart"] = []
        session.modified = True
        flash(f"Order #{order_id} placed successfully! We will deliver to your address.")
        return redirect(url_for("order_history"))
    return render_template("checkout.html", cart_items=cart_items, total=total)
@app.route("/order_history")
def order_history():
    if not login_required():
        return redirect(url_for("login"))
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                o.id,
                o.total_amount,
                o.order_date,
                o.status,
                o.address,
                o.phone,
                oi.quantity,
                oi.price AS item_price,
                p.id AS product_id,
                p.name AS product_name,
                p.description,
                p.brand,
                p.category,
                p.image_url,
                p.local_image,
                p.rating
            FROM Orders o
            LEFT JOIN OrderItems oi ON o.id = oi.order_id
            LEFT JOIN Products p ON oi.product_id = p.id
            WHERE o.user_id = ?
            ORDER BY o.order_date DESC, o.id DESC
            """,
            session["user_id"],
        )
        rows = rows_to_dicts(cursor)
    orders = []
    order_map = {}
    for row in rows:
        order = order_map.get(row["id"])
        if not order:
            order = {
                "id": row["id"],
                "total_amount": row["total_amount"],
                "order_date": row["order_date"],
                "status": row["status"],
                "address": row.get("address", ""),
                "phone": row.get("phone", ""),
                "order_items": [],
            }
            order_map[row["id"]] = order
            orders.append(order)
        if row["product_id"]:
            order["order_items"].append(
                {
                    "product_id": row["product_id"],
                    "name": row["product_name"],
                    "description": row["description"],
                    "brand": row["brand"],
                    "category": row["category"],
                    "image_url": resolve_product_image(row),
                    "rating": row["rating"],
                    "quantity": row["quantity"],
                    "price": row["item_price"],
                }
            )
    return render_template("order_history.html", orders=orders)
# ====================== ADMIN ROUTES ======================
@app.route("/admin")
def admin_dashboard():
    if not admin_required():
        return redirect(url_for("login"))
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM Products")
        total_products = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM Users")
        total_users = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM Orders")
        total_orders = cursor.fetchone()[0]
        cursor.execute("SELECT ISNULL(SUM(total_amount), 0) FROM Orders")
        total_sales = cursor.fetchone()[0]
        cursor.execute("""
            SELECT TOP 5 p.name, SUM(oi.quantity) AS sold
            FROM OrderItems oi
            JOIN Products p ON oi.product_id = p.id
            GROUP BY p.name
            ORDER BY sold DESC
            """)
        top_products = rows_to_dicts(cursor)
    return render_template(
        "admin/dashboard.html",
        total_products=total_products,
        total_users=total_users,
        total_orders=total_orders,
        total_sales=total_sales,
        top_products=top_products,
    )
@app.route("/admin/products")
def admin_products():
    if not admin_required():
        return redirect(url_for("login"))
    return render_template("admin/products.html", products=get_all_products())
@app.route("/admin/orders")
def admin_orders():
    if not admin_required():
        return redirect(url_for("login"))
    status_filter = request.args.get("status", "").strip()
    valid_statuses = {"Placed", "Processing", "Shipped", "Delivered", "Cancelled"}
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if status_filter and status_filter in valid_statuses:
            cursor.execute("""
                SELECT
                    o.id, o.total_amount, o.order_date, o.status,
                    o.address, o.phone,
                    u.name AS user_name, u.email AS user_email,
                    COUNT(oi.id) AS item_count
                FROM Orders o
                JOIN Users u ON o.user_id = u.id
                LEFT JOIN OrderItems oi ON o.id = oi.order_id
                WHERE o.status = ?
                GROUP BY o.id, o.total_amount, o.order_date, o.status,
                         o.address, o.phone, u.name, u.email
                ORDER BY o.order_date DESC
                """, status_filter)
        else:
            status_filter = ""
            cursor.execute("""
                SELECT
                    o.id, o.total_amount, o.order_date, o.status,
                    o.address, o.phone,
                    u.name AS user_name, u.email AS user_email,
                    COUNT(oi.id) AS item_count
                FROM Orders o
                JOIN Users u ON o.user_id = u.id
                LEFT JOIN OrderItems oi ON o.id = oi.order_id
                GROUP BY o.id, o.total_amount, o.order_date, o.status,
                         o.address, o.phone, u.name, u.email
                ORDER BY o.order_date DESC
                """)
        orders = rows_to_dicts(cursor)
    return render_template("admin/orders.html", orders=orders, status_filter=status_filter)
@app.route("/admin/orders/<int:order_id>/status", methods=["POST"])
def update_order_status(order_id):
    if not admin_required():
        return redirect(url_for("login"))
    status = request.form.get("status")
    valid_statuses = {"Placed", "Processing", "Shipped", "Delivered", "Cancelled"}
    if status not in valid_statuses:
        flash("Invalid order status.")
        return redirect(url_for("admin_orders"))
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE Orders SET status = ? WHERE id = ?", status, order_id)
        conn.commit()
    flash(f"Order #{order_id} status updated to {status}.", "success")
    status_filter = request.args.get("status", "")
    if status_filter:
        return redirect(url_for("admin_orders", status=status_filter))
    return redirect(url_for("admin_orders"))
@app.route("/admin/users")
def admin_users():
    if not admin_required():
        return redirect(url_for("login"))
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                u.id,
                u.name,
                u.email,
                u.role,
                u.status,
                u.profile_image,
                u.created_at,
                COUNT(DISTINCT o.id) AS order_count,
                COUNT(DISTINCT r.id) AS review_count
            FROM Users u
            LEFT JOIN Orders o ON u.id = o.user_id
            LEFT JOIN Reviews r ON u.id = r.user_id
            GROUP BY u.id, u.name, u.email, u.role, u.status, u.profile_image, u.created_at
            ORDER BY u.created_at DESC, u.id DESC
            """)
        users = rows_to_dicts(cursor)
    return render_template("admin/users.html", users=users)
@app.route("/admin/users/<int:user_id>/status", methods=["POST"])
def update_user_status(user_id):
    if not admin_required():
        return redirect(url_for("login"))
    status = request.form.get("status")
    if status not in {"active", "banned"}:
        flash("Invalid user status.")
        return redirect(url_for("admin_users"))
    if user_id == session.get("user_id"):
        flash("You cannot change your own account status.")
        return redirect(url_for("admin_users"))
    user = get_user_by_id(user_id)
    if not user:
        flash("User not found.")
        return redirect(url_for("admin_users"))
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE Users SET status = ? WHERE id = ?", status, user_id)
        conn.commit()
    flash(f"{user['name']} is now {status}.")
    return redirect(url_for("admin_users"))
@app.route("/admin/users/<int:user_id>/delete", methods=["POST"])
def delete_user(user_id):
    if not admin_required():
        return redirect(url_for("login"))
    if user_id == session.get("user_id"):
        flash("You cannot delete your own account.")
        return redirect(url_for("admin_users"))
    user = get_user_by_id(user_id)
    if not user:
        flash("User not found.")
        return redirect(url_for("admin_users"))
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT product_id FROM Reviews WHERE user_id = ?", user_id)
        affected_product_ids = [row[0] for row in cursor.fetchall()]
        cursor.execute(
            "DELETE oi FROM OrderItems oi JOIN Orders o ON oi.order_id = o.id WHERE o.user_id = ?",
            user_id,
        )
        cursor.execute("DELETE FROM Reviews WHERE user_id = ?", user_id)
        cursor.execute("DELETE FROM Orders WHERE user_id = ?", user_id)
        cursor.execute("DELETE FROM Users WHERE id = ?", user_id)
        for pid in affected_product_ids:
            recalculate_product_rating(cursor, pid)
        conn.commit()
    flash(f"User {user['email']} and all related data were deleted.")
    return redirect(url_for("admin_users"))
@app.route("/admin/reviews")
def admin_reviews():
    if not admin_required():
        return redirect(url_for("login"))
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                r.id, r.rating, r.comment, r.created_at, r.product_id,
                p.name AS product_name, u.name AS user_name, u.email AS user_email
            FROM Reviews r
            JOIN Products p ON r.product_id = p.id
            JOIN Users u ON r.user_id = u.id
            ORDER BY r.created_at DESC, r.id DESC
            """)
        reviews = rows_to_dicts(cursor)
    return render_template("admin/reviews.html", reviews=reviews)
@app.route("/admin/reviews/<int:review_id>/delete", methods=["POST"])
def delete_review(review_id):
    if not admin_required():
        return redirect(url_for("login"))
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT product_id FROM Reviews WHERE id = ?", review_id)
        row = cursor.fetchone()
        if not row:
            flash("Review not found.")
            return redirect(url_for("admin_reviews"))
        product_id = row[0]
        cursor.execute("DELETE FROM Reviews WHERE id = ?", review_id)
        recalculate_product_rating(cursor, product_id)
        conn.commit()
    flash("Review deleted.")
    return redirect(url_for("admin_reviews"))
@app.route("/admin/reviews/delete_all", methods=["POST"])
def delete_all_reviews():
    if not admin_required():
        return redirect(url_for("login"))
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM Reviews")
        cursor.execute("UPDATE Products SET rating = 4.0")
        conn.commit()
    flash("All reviews were deleted.")
    return redirect(url_for("admin_reviews"))
@app.route("/admin/reports")
def admin_reports():
    if not admin_required():
        return redirect(url_for("login"))
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT TOP 14
                CONVERT(VARCHAR(10), CAST(order_date AS DATE), 120) AS sale_date,
                COUNT(*) AS order_count,
                ISNULL(SUM(total_amount), 0) AS revenue
            FROM Orders
            GROUP BY CAST(order_date AS DATE)
            ORDER BY sale_date DESC
            """)
        daily_sales = rows_to_dicts(cursor)
        daily_sales.reverse()
        cursor.execute("""
            SELECT TOP 8
                p.category,
                SUM(oi.quantity) AS units_sold,
                ISNULL(SUM(oi.quantity * oi.price), 0) AS revenue
            FROM OrderItems oi
            JOIN Products p ON oi.product_id = p.id
            GROUP BY p.category
            ORDER BY revenue DESC
            """)
        category_sales = rows_to_dicts(cursor)
        cursor.execute("""
            SELECT TOP 12
                p.id, p.name, p.category, p.brand, p.price, p.rating,
                COUNT(DISTINCT oi.order_id) AS order_count,
                ISNULL(SUM(oi.quantity), 0) AS units_sold,
                ISNULL(SUM(oi.quantity * oi.price), 0) AS revenue,
                COUNT(DISTINCT r.id) AS review_count
            FROM Products p
            LEFT JOIN OrderItems oi ON p.id = oi.product_id
            LEFT JOIN Reviews r ON p.id = r.product_id
            GROUP BY p.id, p.name, p.category, p.brand, p.price, p.rating
            ORDER BY revenue DESC, units_sold DESC, p.rating DESC
            """)
        product_performance = rows_to_dicts(cursor)
        cursor.execute("SELECT COUNT(*) FROM Users WHERE status = 'active'")
        active_users = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM Users WHERE status = 'banned'")
        banned_users = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM Reviews")
        total_reviews = cursor.fetchone()[0]
        cursor.execute("SELECT ISNULL(AVG(CAST(rating AS FLOAT)), 0) FROM Reviews")
        average_review_rating = cursor.fetchone()[0]
    activity_summary = []
    recent_activities = []
    active_user_events = []
    mongo_available = mongo_db is not None
    if mongo_db is not None:
        try:
            activity_summary = list(
                mongo_db.activities.aggregate([
                    {"$group": {"_id": "$action", "count": {"$sum": 1}}},
                    {"$sort": {"count": -1}},
                    {"$limit": 10},
                ])
            )
            recent_activities = list(
                mongo_db.activities.find({}, {"_id": 0}).sort("timestamp", -1).limit(12)
            )
            active_user_events = list(
                mongo_db.activities.aggregate([
                    {"$match": {"user_id": {"$ne": None}}},
                    {"$group": {"_id": "$user_id", "events": {"$sum": 1}}},
                    {"$sort": {"events": -1}},
                    {"$limit": 8},
                ])
            )
        except PyMongoError:
            mongo_available = False
    return render_template(
        "admin/reports.html",
        daily_sales=daily_sales,
        category_sales=category_sales,
        product_performance=product_performance,
        activity_summary=activity_summary,
        recent_activities=recent_activities,
        active_user_events=active_user_events,
        active_users=active_users,
        banned_users=banned_users,
        total_reviews=total_reviews,
        average_review_rating=average_review_rating,
        mongo_available=mongo_available,
    )
@app.route("/admin/add_product", methods=["GET", "POST"])
def add_product():
    if not admin_required():
        return redirect(url_for("login"))
    if request.method == "POST":
        save_product()
        flash("Product added successfully.")
        return redirect(url_for("admin_products"))
    return render_template(
        "admin/product_form.html", product=None, title="Add Product",
        categories=get_categories(),
    )
@app.route("/admin/edit_product/<int:product_id>", methods=["GET", "POST"])
def edit_product(product_id):
    if not admin_required():
        return redirect(url_for("login"))
    product = get_product_by_id(product_id)
    if not product:
        flash("Product not found.")
        return redirect(url_for("admin_products"))
    if request.method == "POST":
        save_product(product_id)
        flash("Product updated successfully.")
        return redirect(url_for("admin_products"))
    return render_template(
        "admin/product_form.html",
        product=product,
        title="Edit Product",
        existing_gallery=get_all_product_images(product),
        categories=get_categories(),
    )
@app.route("/admin/delete_product/<int:product_id>", methods=["POST"])
def delete_product(product_id):
    if not admin_required():
        return redirect(url_for("login"))
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM Reviews WHERE product_id = ?", product_id)
        cursor.execute("DELETE FROM Products WHERE id = ?", product_id)
        conn.commit()
    flash("Product deleted.")
    return redirect(url_for("admin_products"))
def save_product(product_id=None):
    """
    Save or update a product.
    Supports multiple local file uploads + multiple URL entries for gallery.
    Primary image: first uploaded file > image_url field first entry.
    Extra images stored in extra_images column (auto-migrated via ensure_database_schema).
    """
    name = request.form["name"].strip()
    category = request.form["category"].strip()
    price = request.form.get("price", type=float)
    description = request.form["description"].strip()
    brand = request.form["brand"].strip()
    rating = request.form.get("rating", type=float) or 4.0
    stock = request.form.get("stock", type=int) or 100
    # --- Handle URL fields ---
    # image_url: primary URL (first entry from the URL list)
    url_list_raw = request.form.get("image_urls_hidden", "").strip()
    url_entries = [u.strip() for u in url_list_raw.split(",") if u.strip()] if url_list_raw else []
    image_url = url_entries[0] if url_entries else request.form.get("image_url", "").strip()
    extra_url_images = ",".join(url_entries[1:]) if len(url_entries) > 1 else ""
    # --- Handle multiple file uploads ---
    uploaded_files = request.files.getlist("product_images")
    local_images_str = save_multiple_product_images(uploaded_files, name)
    # Merge: local uploads go in local_image (comma-sep), extra URLs in extra_images
    # extra_images = extra local uploads beyond the first + extra URL images
    local_parts = local_images_str.split(",") if local_images_str else []
    primary_local = local_parts[0] if local_parts else None
    extra_local = ",".join(local_parts[1:]) if len(local_parts) > 1 else ""
    extra_images_combined = ",".join(filter(None, [extra_local, extra_url_images]))
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if product_id:
            if primary_local:
                # New local uploads provided — update local_image and extras
                cursor.execute(
                    """
                    UPDATE Products
                    SET name = ?, category = ?, price = ?, description = ?,
                        image_url = ?, local_image = ?, extra_images = ?,
                        brand = ?, rating = ?, stock = ?
                    WHERE id = ?
                    """,
                    name, category, price, description, image_url,
                    primary_local, extra_images_combined,
                    brand, rating, stock, product_id,
                )
            else:
                # No new file upload — update URLs, preserve existing local_image
                cursor.execute(
                    """
                    UPDATE Products
                    SET name = ?, category = ?, price = ?, description = ?,
                        image_url = ?, extra_images = ?,
                        brand = ?, rating = ?, stock = ?
                    WHERE id = ?
                    """,
                    name, category, price, description, image_url,
                    extra_images_combined,
                    brand, rating, stock, product_id,
                )
        else:
            cursor.execute(
                """
                INSERT INTO Products (name, category, price, description, image_url, local_image, extra_images, brand, rating, stock)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                name, category, price, description, image_url,
                primary_local, extra_images_combined,
                brand, rating, stock,
            )
        conn.commit()
if __name__ == "__main__":
    debug_mode = os.getenv("FLASK_DEBUG", "1") == "1"
    app.run(debug=debug_mode)

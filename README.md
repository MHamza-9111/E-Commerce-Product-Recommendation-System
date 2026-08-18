# ZiloCart — E-Commerce Product Recommendation System

A Flask-based e-commerce project with personalized product recommendations, shopping cart, order management, and an admin dashboard.

---

## Features

- User registration, login, password reset, profile management
- Customer and admin roles
- Product catalog with search, category filters, sort, and price range
- Shopping cart with quantity management and live stock checks
- Order placement with stock decrement and delivery details
- Order history per user
- Product reviews (purchase-gated, one per user per product)
- Personalized recommendations (hybrid: content + collaborative KNN)
- Trending products from MongoDB activity logs
- Admin dashboard: orders, products, users, reviews, analytics
- Admin orders page with status filter (Placed / Processing / Shipped / etc.)

---

## Setup

### 1. Install dependencies (app only)

```bash
pip install -r requirements-app.txt
```

For running the Jupyter notebook (data pipeline) as well:

```bash
pip install -r requirements-notebook.txt
```

### 2. Configure environment variables

Copy `.env.example` to `.env` and fill in your values:

```env
SECRET_KEY=your-long-random-secret-key-here
SQLSERVER_CONNECTION_STRING=DRIVER={ODBC Driver 17 for SQL Server};SERVER=localhost;DATABASE=EcommerceDB;Trusted_Connection=yes;Encrypt=no;TrustServerCertificate=yes;
MONGODB_URI=mongodb://localhost:27017/
```

> **Important:** Always set a strong, unique `SECRET_KEY` — never use the default.

### 3. Set up the database

Open SQL Server Management Studio, connect to your server, and run:

```
ECommerceDB.sql
```

> Note: `ECommerceDB.sql` is encoded as UTF-16 LE. If your tooling shows garbled text, re-save it as UTF-8 in SSMS via **File → Save As → with Encoding → UTF-8**.

### 5. Start MongoDB (optional)

MongoDB is used for activity logging (trending, recommendations). The app works without it — trending products will fall back to highest-rated items.

```bash
mongod
```

### 6. Run the app

```bash
cd Source Code
python app.py
```

Open: [http://127.0.0.1:5000](http://127.0.0.1:5000)

---

## Demo Accounts

| Role      | Email                  | Password    |
|-----------|------------------------|-------------|
| Admin     | admin@smartshop.com    | admin123    |
| Customer1 | demo@test.com          | test123     |
| Customer2 | fatima@test.com        | test123     |
| Customer3 | usman@test.com         | test123     |
| Customer3 | kamran@test.com        | test123     |

---

## How Recommendations Work

**Trending** — MongoDB logs views, cart adds, and orders. Products with the most recent activity surface as trending.

**Content-based** — On the product detail page, a TF-IDF + KNN model finds products with similar descriptions, category, and brand.

**Collaborative** — For logged-in users, a user-item matrix KNN finds other users with similar purchase history and recommends what they bought.

**Hybrid** — Combines content (40%) and collaborative (60%) signals. Falls back to trending/rating-based recommendations for new users.

---

## Project Structure

```
app.py                    Main Flask application
ECommerceDB.sql           SQL Server schema + seed data
requirements-app.txt      Python packages for running the web app
requirements-notebook.txt Additional packages for the Jupyter notebook
Main_Data_Pipeline.ipynb  EDA + model training notebook
templates/
  base.html               Shared layout and navigation
  index.html              Homepage with carousel and recommendations
  products.html           Public product catalog with filters
  product_detail.html     Product page with reviews and similar items
  cart.html               Shopping cart
  checkout.html           Checkout with delivery form
  order_history.html      Customer order history
  login.html / register.html / profile.html / forgot_password.html
  admin/
    dashboard.html        Admin stats overview
    orders.html           Order management with status filter
    products.html         Product management (edit/delete)
    product_form.html     Add / edit product form
    users.html            User management (ban/unban/delete)
    reviews.html          Review moderation
    reports.html          Analytics charts
static/
  logo.png
  uploads/
    products/             Locally uploaded product images
    profile_pictures/     User profile photos
```

---

## Known Limitations / Future Improvements

- No CSRF protection — add Flask-WTF for production deployment
- No email sending for password reset in local dev — configure SMTP in `.env`
- `Main_Data_Pipeline.ipynb` uses a hardcoded server name (`SERVER=MHAMZA`) — update the connection string cell before running
- No pagination on admin orders/products lists — add for large datasets

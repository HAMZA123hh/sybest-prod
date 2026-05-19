import os
import requests
from datetime import datetime, timedelta
from flask import Flask, render_template, jsonify, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = 'my_super_secret_key_12345'
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///database.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# مفتاح الـ API الخاص بـ TMDB
API_KEY = "6077e25ec7e3d48f522d81ed13e9b938"

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# ---------- نماذج قاعدة البيانات المطورة ----------
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    subscription = db.Column(db.String(20), default='free') # free, pending, vip
    expire_date = db.Column(db.DateTime, nullable=True)
    is_admin = db.Column(db.Boolean, default=False)

class PaymentRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    method = db.Column(db.String(50), nullable=False)
    transaction_id = db.Column(db.String(100), unique=True, nullable=False)
    status = db.Column(db.String(20), default='pending') # pending, approved, rejected
    username = db.Column(db.String(150))
    date_created = db.Column(db.DateTime, default=datetime.utcnow)

class Feedback(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    username = db.Column(db.String(150))
    message_type = db.Column(db.String(50)) # "طلب محتوى" أو "اقتراح/مشكلة"
    content = db.Column(db.Text, nullable=False)
    date_created = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    user = User.query.get(int(user_id))
    if user and user.subscription == 'vip' and user.expire_date:
        if datetime.utcnow() > user.expire_date:
            user.subscription = 'free'
            user.expire_date = None
            db.session.commit()
    return user

# إنشاء قاعدة البيانات تلقائياً
with app.app_context():
    db.create_all()

# ---------- الراوتات الأساسية ----------

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/feedback', methods=['GET', 'POST'])
@login_required 
def feedback():
    if request.method == 'POST':
        message_type = request.form.get('message_type')
        content = request.form.get('content', '').strip()
        
        if not content:
            flash('الرجاء كتابة تفاصيل الطلب أو الرأي!', 'error')
            return redirect(url_for('feedback'))
            
        new_feedback = Feedback(
            user_id=current_user.id,
            username=current_user.username,
            message_type=message_type,
            content=content
        )
        db.session.add(new_feedback)
        db.session.commit()
        flash('تم إرسال طلبك بنجاح! شكراً لمساهمتك في تطوير Sy-Best.', 'success')
        return redirect(url_for('home'))
        
    return render_template('feedback.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        
        if User.query.filter_by(username=username).first() or User.query.filter_by(email=email).first():
            flash('اسم المستخدم أو البريد الإلكتروني مسجل بالفعل!', 'error')
            return redirect(url_for('register'))
            
        hashed_pw = generate_password_hash(password, method='pbkdf2:sha256')
        
        is_first = User.query.count() == 0
        new_user = User(username=username, email=email, password=hashed_pw, is_admin=is_first)
        
        db.session.add(new_user)
        db.session.commit()
        
        if is_first:
            flash('تم إنشاء الحساب الأول كمدير للموقع بنجاح! يرجى تسجيل الدخول.', 'success')
        else:
            flash('تم إنشاء حسابك بنجاح! يمكنك تسجيل الدخول الآن.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()
        
        if user and check_password_hash(user.password, password):
            login_user(user)
            if user.is_admin:
                return redirect(url_for('admin_panel'))
            return redirect(url_for('home'))
        else:
            flash('البريد الإلكتروني أو كلمة المرور غير صحيحة!', 'error')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))

@app.route('/pay', methods=['GET', 'POST'])
@login_required
def pay():
    has_pending = PaymentRequest.query.filter_by(user_id=current_user.id, status='pending').first()
    
    if request.method == 'POST':
        if has_pending:
            flash('لديك طلب سابق قيد المراجعة بالفعل، يرجى الانتظار!', 'error')
            return redirect(url_for('home'))
            
        method = request.form.get('method')
        transaction_id = request.form.get('transaction_id').strip()
        
        if not transaction_id:
            flash('يرجى إدخال رقم عملية صحيح!', 'error')
            return redirect(url_for('pay'))
            
        existing = PaymentRequest.query.filter_by(transaction_id=transaction_id).first()
        if existing:
            flash('رقم العملية هذا تم إرساله مسبقاً!', 'error')
            return redirect(url_for('pay'))
            
        new_payment = PaymentRequest(user_id=current_user.id, method=method, transaction_id=transaction_id, username=current_user.username)
        current_user.subscription = 'pending'
        db.session.add(new_payment)
        db.session.commit()
        flash('تم إرسال طلبك بنجاح! سيتم تفعيل حسابك بعد مراجعة الحوالة.', 'success')
        return redirect(url_for('home'))
        
    return render_template('pay.html', has_pending=has_pending)

# ---------- راوتات الـ API ----------

@app.route('/api/movies')
def get_movies():
    page = request.args.get('page', 1, type=int)
    genre = request.args.get('genre', '', type=str)
    url = f"https://api.themoviedb.org/3/discover/movie?api_key={API_KEY}&language=en-US&sort_by=popularity.desc&page={page}"
    if genre: url += f"&with_genres={genre}"
    try: return jsonify(requests.get(url, timeout=15).json())
    except: return jsonify({"results": []})

@app.route('/api/shows')
def get_shows():
    page = request.args.get('page', 1, type=int)
    genre = request.args.get('genre', '', type=str)
    url = f"https://api.themoviedb.org/3/discover/tv?api_key={API_KEY}&language=en-US&sort_by=popularity.desc&page={page}"
    if genre: url += f"&with_genres={genre}"
    try: return jsonify(requests.get(url, timeout=15).json())
    except: return jsonify({"results": []})

@app.route('/api/arabic-movies')
def get_arabic_movies():
    page = request.args.get('page', 1, type=int)
    url = f"https://api.themoviedb.org/3/discover/movie?api_key={API_KEY}&language=ar-SA&sort_by=popularity.desc&with_original_language=ar&page={page}"
    try: return jsonify(requests.get(url, timeout=15).json())
    except: return jsonify({"results": []})

@app.route('/api/arabic-shows')
def get_arabic_shows():
    page = request.args.get('page', 1, type=int)
    url = f"https://api.themoviedb.org/3/discover/tv?api_key={API_KEY}&language=ar-SA&sort_by=popularity.desc&with_original_language=ar&page={page}"
    try: return jsonify(requests.get(url, timeout=15).json())
    except: return jsonify({"results": []})

@app.route('/api/turkish-shows')
def get_turkish_shows():
    page = request.args.get('page', 1, type=int)
    url = f"https://api.themoviedb.org/3/discover/tv?api_key={API_KEY}&language=ar-SA&sort_by=popularity.desc&with_original_language=tr&page={page}"
    try: return jsonify(requests.get(url, timeout=15).json())
    except: return jsonify({"results": []})

@app.route('/api/search/<string:query>')
def search_media(query):
    url = f"https://api.themoviedb.org/3/search/multi?api_key={API_KEY}&query={query}&language=ar-SA"
    try: return jsonify(requests.get(url, timeout=5).json())
    except: return jsonify({"results": []})


# ---------- فحص المشغل وجدار الحماية المتكيف ----------

@app.route('/movie/<string:movie_id>')
def movie_detail(movie_id):
    if current_user.is_authenticated and current_user.subscription == 'vip' and current_user.expire_date:
        if datetime.utcnow() > current_user.expire_date:
            current_user.subscription = 'free'
            current_user.expire_date = None
            db.session.commit()
            
    url = f"https://api.themoviedb.org/3/movie/{movie_id}?api_key={API_KEY}&language=ar-SA"
    movie_info = requests.get(url, timeout=15).json() if requests.get(url).status_code == 200 else {}
    
    # تحويل ذكي ومتكيف بالكامل بحسب بيئة التشغيل
    if request.host.startswith('127.0.0.1') or request.host.startswith('localhost'):
        embed_url = "//vidsrc.pm/embed/movie/{movie_id}"  # سيرفر التطوير المحلي المفتوح
    else:
        embed_url = "//vidsrc.xyz/embed/movie?tmdb={movie_id}" # السيرفر الافتراضي المستقر جداً أونلاين
        
    return render_template('movie.html', embed_url=embed_url, is_tv=False, media=movie_info)


@app.route('/tv/<string:tv_id>')
@app.route('/tv/<string:tv_id>/<int:season>/<int:episode>')
def tv_detail(tv_id, season=1, episode=1):
    if current_user.is_authenticated and current_user.subscription == 'vip' and current_user.expire_date:
        if datetime.utcnow() > current_user.expire_date:
            current_user.subscription = 'free'
            current_user.expire_date = None
            db.session.commit()
            
    url = f"https://api.themoviedb.org/3/tv/{tv_id}?api_key={API_KEY}&language=ar-SA"
    tv_info = requests.get(url, timeout=15).json() if requests.get(url).status_code == 200 else {}
    total_seasons = tv_info.get('number_of_seasons', 1)
    
    season_url = f"https://api.themoviedb.org/3/tv/{tv_id}/season/{season}?api_key={API_KEY}&language=ar-SA"
    season_data = requests.get(season_url, timeout=15).json() if requests.get(season_url).status_code == 200 else {}
    episodes = season_data.get('episodes', [])
    total_episodes_in_season = len(episodes)
    
    if not episodes:
        episodes_list = list(range(1, 21))
    else:
        episodes_list = [ep.get('episode_number') for ep in episodes]

    next_season = season
    next_episode = episode + 1

    if next_episode > total_episodes_in_season:
        if season < total_seasons:
            next_season = season + 1
            next_episode = 1
        else:
            next_season = None
            next_episode = None

    # تحويل ذكي ومتكيف بالكامل بحسب بيئة التشغيل للمسلسلات
    if request.host.startswith('127.0.0.1') or request.host.startswith('localhost'):
        embed_url = "//vidsrc.pm/embed/tv/{tv_id}/{season}/{episode}"
    else:
        # هنا أيضاً استخدمنا // مع vidsrc.net لضمان العمل
        embed_url = "//vidsrc.net/embed/tv?tmdb={tv_id}&season={season}&episode={episode}"
    return render_template(
        'movie.html', 
        embed_url=embed_url, 
        is_tv=True, 
        tv_id=tv_id, 
        current_season=season, 
        current_episode=episode, 
        total_seasons=list(range(1, total_seasons + 1)), 
        episodes_list=episodes_list, 
        episodes_detailed=episodes, 
        media=tv_info,
        next_season=next_season,
        next_episode=next_episode
    )

# ---------- لوحة تحكم الإدارة ----------
@app.route('/admin', methods=['GET', 'POST'])
@login_required
def admin_panel():
    if not current_user.is_admin:
        return "<h1 style='color:red; text-align:center; margin-top:50px;'>🔒 خطأ 403: غير مسموح لك بدخول هذه الصفحة.</h1>", 403
        
    if request.method == 'POST':
        action = request.form.get('action')
        if action in ['approve', 'reject']:
            req_id = request.form.get('req_id')
            payment_req = PaymentRequest.query.get(req_id)
            if payment_req:
                user = User.query.get(payment_req.user_id)
                if action == 'approve':
                    payment_req.status = 'approved'
                    if user:
                        user.subscription = 'vip'
                        user.expire_date = datetime.utcnow() + timedelta(days=30)
                elif action == 'reject':
                    payment_req.status = 'rejected'
                    if user:
                        user.subscription = 'free'
                db.session.commit()
                
        elif action == 'delete_feedback':
            feed_id = request.form.get('feed_id')
            feed_item = Feedback.query.get(feed_id)
            if feed_item:
                db.session.delete(feed_item)
                db.session.commit()
                flash('تم مسح الرسالة بنجاح.', 'success')
            
    pending_payments = PaymentRequest.query.filter_by(status='pending').all()
    all_users = User.query.all()
    all_feedbacks = Feedback.query.order_by(Feedback.date_created.desc()).all()
    
    return render_template('admin.html', payments=pending_payments, users=all_users, feedbacks=all_feedbacks)

@app.route('/secret-reset/<string:username>/<string:new_password>')
@login_required
def secret_reset(username, new_password):
    if not current_user.is_admin:
        return "🔒 غير مسموح لك بالدخول!", 403
        
    user = User.query.filter_by(username=username).first()
    if user:
        user.password = generate_password_hash(new_password, method='pbkdf2:sha256')
        db.session.commit()
        return f"<h1>✅ تم تصفير حساب {username} بنجاح، الباسورد الجديد: {new_password}</h1>"
    
    return "<h1>❌ هذا المستخدم غير موجود!</h1>", 404

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)

import os
import requests
import mysql.connector
import stripe
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file, abort, jsonify


from minio import Minio
from werkzeug.utils import secure_filename
import io
import uuid

# Configuração do Stripe (Modo de Teste)
STRIPE_SECRET_KEY = os.getenv('STRIPE_SECRET_KEY')
if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

MINIO_HOST = os.getenv('MINIO_ENDPOINT', 'minio')
MINIO_PORT = os.getenv('MINIO_PORT', '9000')
if ':' in MINIO_HOST:
    MINIO_ENDPOINT = MINIO_HOST
else:
    MINIO_ENDPOINT = f"{MINIO_HOST}:{MINIO_PORT}"

MINIO_ACCESS_KEY = os.getenv('MINIO_ROOT_USER', os.getenv('MINIO_ACCESS_KEY', 'minioadmin'))
MINIO_SECRET_KEY = os.getenv('MINIO_ROOT_PASSWORD', os.getenv('MINIO_SECRET_KEY', 'minioadmin123'))
MINIO_PUBLIC_URL = os.getenv('MINIO_PUBLIC_URL', 'http://localhost:9010')
MINIO_BUCKET = os.getenv('MINIO_BUCKET', 'perfil-fotos')

try:
    minio_client = Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=False
    )
except Exception as e:
    print("MinIO Client Initialization Error:", e)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'default_secret')
AUTH_SERVICE_URL = os.getenv('AUTH_SERVICE_URL', 'http://auth-service:5000')
LOG_SERVICE_URL = os.getenv('LOG_SERVICE_URL', 'http://log-service:5000')

def send_audit_log(acao, user_id=None):
    try:
        uid = user_id or session.get('user_id', 'anonimo')
        requests.post(f"{LOG_SERVICE_URL}/api/log", json={
            'usuario_id': uid,
            'acao': acao,
            'ip_origem': request.remote_addr
        }, timeout=2)
    except Exception as e:
        print(f"Erro ao enviar log: {e}")

def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv('DB_HOST'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME')
    )

def ensure_db_schema():
    """Garante que as colunas do plano premium existam no banco relacional."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        for col_sql in [
            "ALTER TABLE usuarios ADD COLUMN is_premium BOOLEAN NOT NULL DEFAULT 0",
            "ALTER TABLE usuarios ADD COLUMN stripe_customer_id VARCHAR(255)",
            "ALTER TABLE usuarios ADD COLUMN stripe_subscription_id VARCHAR(255)"
        ]:
            try:
                cursor.execute(col_sql)
                conn.commit()
            except mysql.connector.Error:
                pass
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"[Catalog] Aviso ao verificar colunas no banco: {e}")

try:
    ensure_db_schema()
except Exception:
    pass

def get_user_premium_status(user_id):
    """Consulta o status premium do usuário diretamente no banco de dados."""
    if not user_id:
        return False
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT is_premium FROM usuarios WHERE id = %s", (user_id,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        return bool(row.get('is_premium', 0)) if row else False
    except Exception as e:
        print(f"Erro ao checar status premium: {e}")
        return False


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        nome = request.form['nome']
        email = request.form['email']
        senha = request.form['senha']
        
        try:
            res = requests.post(f"{AUTH_SERVICE_URL}/api/register", json={
                'nome': nome,
                'email': email,
                'senha': senha,
                'role': 'usuario'
            }, timeout=15)
            data = res.json()
            if res.status_code == 200 and data.get('success'):
                flash('Cadastro realizado com sucesso! Faça login.')
                return redirect(url_for('login'))
            else:
                flash(data.get('error', 'Erro ao realizar cadastro.'))
        except requests.RequestException as e:
            flash(f'Erro de conexão com o serviço de autenticação: {e}')
            
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        senha = request.form['senha']
        
        try:
            res = requests.post(f"{AUTH_SERVICE_URL}/api/login", json={
                'email': email,
                'senha': senha
            }, timeout=15)
            data = res.json()
            if res.status_code == 200 and data.get('success'):
                user = data.get('user', {})
                session['user_id'] = user.get('id')
                session['nome'] = user.get('nome')
                session['role'] = user.get('role', 'usuario')
                session['avatar_url'] = user.get('avatar_url')
                session['is_premium'] = bool(user.get('is_premium', False))
                return redirect(url_for('index'))
            else:
                flash(data.get('error', 'Credenciais inválidas.'))
        except requests.RequestException as e:
            flash(f'Erro de conexão com o serviço de autenticação: {e}')
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    send_audit_log('logout')
    session.clear()
    return redirect(url_for('login'))

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form['email']
        try:
            base_url = os.getenv('APP_URL') or request.host_url
            res = requests.post(f"{AUTH_SERVICE_URL}/api/forgot-password", json={
                'email': email,
                'base_url': base_url
            }, timeout=15)
            data = res.json()
            flash(data.get('message', 'Solicitação processada com sucesso.'))
        except requests.RequestException as e:
            flash(f'Erro ao se comunicar com o serviço de autenticação: {e}')
        return redirect(url_for('login'))
        
    return render_template('forgot_password.html')

@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    # Verifica validade do token primeiro
    try:
        res_verify = requests.post(f"{AUTH_SERVICE_URL}/api/verify-token", json={'token': token}, timeout=15)
        data_verify = res_verify.json()
        if not data_verify.get('valid'):
            return render_template('reset_password.html', error=data_verify.get('reason', 'Link inválido ou expirado.'))
    except requests.RequestException as e:
        return render_template('reset_password.html', error=f'Erro de conexão com o serviço de autenticação: {e}')

    if request.method == 'POST':
        nova_senha = request.form['nova_senha']
        try:
            res = requests.post(f"{AUTH_SERVICE_URL}/api/reset-password", json={
                'token': token,
                'nova_senha': nova_senha
            }, timeout=15)
            data = res.json()
            if res.status_code == 200 and data.get('success'):
                flash('Senha redefinida com sucesso! Faça login com a nova senha.')
                return redirect(url_for('login'))
            else:
                return render_template('reset_password.html', error=data.get('error', 'Erro ao redefinir senha.'))
        except requests.RequestException as e:
            return render_template('reset_password.html', error=f'Erro ao comunicar com o serviço de autenticação: {e}')

    return render_template('reset_password.html', error=None)

@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # Sincroniza status premium do usuário atual
    is_premium = get_user_premium_status(session['user_id'])
    session['is_premium'] = is_premium

    api_key = os.getenv('TMDB_API_KEY')
    url_busca = f"https://api.themoviedb.org/3/search/person?query=Tom+Hanks&api_key={api_key}"
    search_res = requests.get(url_busca).json()
    
    print("Retorno TMDB:", search_res) # Debug para ver o erro no terminal
    
    movies = []
    if 'results' in search_res and len(search_res['results']) > 0:
        person_id = search_res['results'][0]['id']
        movies_res = requests.get(f"https://api.themoviedb.org/3/person/{person_id}/movie_credits?api_key={api_key}").json()
        movies = movies_res.get('cast', [])
    else:
        flash('Erro de API: Filme não encontrado ou chave TMDB inválida. Verifique os logs.')

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("SELECT tmdb_movie_id FROM favoritos WHERE usuario_id = %s", (session['user_id'],))
    favoritos = {row['tmdb_movie_id'] for row in cursor.fetchall()}
    
    cursor.execute("""
        SELECT c.id, c.tmdb_movie_id, c.texto, c.usuario_id, u.nome
        FROM comentarios c
        JOIN usuarios u ON c.usuario_id = u.id
    """)
    comentarios = {}
    for row in cursor.fetchall():
        if row['tmdb_movie_id'] not in comentarios:
            comentarios[row['tmdb_movie_id']] = []
        comentarios[row['tmdb_movie_id']].append({
            'id': row['id'],
            'texto': row['texto'],
            'usuario_id': row['usuario_id'],
            'nome': row['nome']
        })
        
    cursor.close()
    conn.close()

    return render_template(
        'index.html', 
        movies=movies, 
        favoritos=favoritos, 
        comentarios=comentarios, 
        is_premium=is_premium,
        limite_favoritos=5
    )

@app.route('/favoritar', methods=['POST'])
def favoritar():
    if 'user_id' not in session: return redirect(url_for('login'))
    user_id = session['user_id']
    movie_id = request.form['movie_id']
    titulo = request.form['titulo']
    poster_path = request.form['poster_path']
    
    # 4. Benefício real do Plano Premium: limite de favoritos para plano gratuito
    is_premium = get_user_premium_status(user_id)
    session['is_premium'] = is_premium
    LIMITE_GRATUITO = 5

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Se for usuário comum, verifica se atingiu o limite de 5 favoritos
        if not is_premium:
            cursor.execute("SELECT COUNT(*) FROM favoritos WHERE usuario_id = %s", (user_id,))
            (total_atuais,) = cursor.fetchone()
            if total_atuais >= LIMITE_GRATUITO:
                send_audit_log('403_limite_favoritos_atingido', user_id)
                flash(f"⚠️ Limite atingido! O plano gratuito permite no máximo {LIMITE_GRATUITO} filmes favoritos. Assine o Plano Premium para ter favoritos ilimitados!")
                return redirect(url_for('index'))

        cursor.execute("INSERT INTO favoritos (usuario_id, tmdb_movie_id, titulo, poster_path) VALUES (%s, %s, %s, %s)", 
                       (user_id, movie_id, titulo, poster_path))
        conn.commit()
        send_audit_log(f'favoritar_filme_{movie_id}', user_id)
        flash(f'Filme "{titulo}" adicionado aos favoritos!')
    except mysql.connector.IntegrityError:
        flash(f'O filme "{titulo}" já está na sua lista de favoritos.')
    except Exception as e:
        flash(f'Erro ao favoritar: {e}')
    finally:
        cursor.close()
        conn.close()
    return redirect(url_for('index'))

@app.route('/desfavoritar', methods=['POST'])
def desfavoritar():
    if 'user_id' not in session: return redirect(url_for('login'))
    user_id = session['user_id']
    movie_id = request.form['movie_id']
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM favoritos WHERE usuario_id = %s AND tmdb_movie_id = %s", 
                       (user_id, movie_id))
        conn.commit()
        send_audit_log(f'desfavoritar_filme_{movie_id}', user_id)
        flash('Filme removido dos favoritos com sucesso.')
    except Exception as e:
        flash(f'Erro ao remover favorito: {e}')
    finally:
        cursor.close()
        conn.close()
    return redirect(request.referrer or url_for('index'))

# ==============================================================
# ATIVIDADE 7: STRIPE CHECKOUT E WEBHOOK (PLANO PREMIUM)
# ==============================================================

@app.route('/checkout', methods=['GET', 'POST'])
@app.route('/stripe/checkout', methods=['GET', 'POST'])
def checkout():
    """
    Cria a Checkout Session no Stripe (modo teste) e redireciona o usuário (Requisito 2).
    """
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    user_id = session['user_id']
    is_premium = get_user_premium_status(user_id)
    if is_premium:
        flash("⭐ Você já é um assinante Premium! Aproveite os favoritos ilimitados.")
        return redirect(url_for('perfil', user_id=user_id))
        
    stripe_key = os.getenv('STRIPE_SECRET_KEY')
    if not stripe_key:
        flash("Configuração Stripe ausente: defina STRIPE_SECRET_KEY no seu arquivo .env.")
        return redirect(url_for('perfil', user_id=user_id))
        
    stripe.api_key = stripe_key
    app_url = os.getenv('APP_URL') or request.host_url.rstrip('/')
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, email, nome FROM usuarios WHERE id = %s", (user_id,))
    usuario = cursor.fetchone()
    cursor.close()
    conn.close()
    
    price_id = os.getenv('STRIPE_PRICE_ID')
    
    try:
        # Se um STRIPE_PRICE_ID foi cadastrado no Stripe Dashboard, usa ele.
        # Caso contrário, utiliza produto mensal dinâmico de R$ 9,90/mês
        if price_id and price_id.strip():
            line_items = [{
                'price': price_id.strip(),
                'quantity': 1,
            }]
        else:
            line_items = [{
                'price_data': {
                    'currency': 'brl',
                    'product_data': {
                        'name': 'Catálogo Tom Hanks - Plano Premium',
                        'description': 'Favoritos ilimitados e selo VIP exclusivo no perfil'
                    },
                    'unit_amount': 990, # R$ 9,90 em centavos
                    'recurring': {
                        'interval': 'month'
                    }
                },
                'quantity': 1,
            }]

        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=line_items,
            mode='subscription',
            customer_email=usuario['email'] if usuario else None,
            client_reference_id=str(user_id),
            metadata={
                'user_id': str(user_id),
                'plano': 'premium'
            },
            success_url=f"{app_url}/checkout/sucesso?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{app_url}/checkout/cancelado",
        )
        send_audit_log('iniciar_checkout_stripe', user_id)
        # Redireciona o usuário para o formulário de pagamento hospedado pelo Stripe
        return redirect(checkout_session.url, code=303)
    except Exception as e:
        print(f"[Stripe Checkout Error] {e}")
        flash(f"Erro ao criar sessão de checkout no Stripe: {e}")
        return redirect(url_for('perfil', user_id=user_id))

@app.route('/checkout/sucesso')
def checkout_sucesso():
    """
    Retorno do usuário após conclusão bem-sucedida do checkout no Stripe.
    """
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    user_id = session['user_id']
    send_audit_log('retorno_checkout_sucesso', user_id)
    # Atualiza a sessão
    session['is_premium'] = get_user_premium_status(user_id)
    
    flash("🎉 Parabéns! Sua assinatura foi iniciada. O Stripe está confirmando seu pagamento e seus benefícios já estão liberados!")
    return redirect(url_for('perfil', user_id=user_id))

@app.route('/checkout/cancelado')
def checkout_cancelado():
    """
    Retorno do usuário se cancelar ou fechar o checkout.
    """
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    user_id = session['user_id']
    send_audit_log('cancelamento_checkout_stripe', user_id)
    flash("Assinatura cancelada. Nenhuma cobrança foi efetuada e você continua no plano gratuito.")
    return redirect(url_for('perfil', user_id=user_id))

@app.route('/webhook/stripe', methods=['POST'])
@app.route('/stripe/webhook', methods=['POST'])
@app.route('/api/stripe/webhook', methods=['POST'])
@app.route('/api/webhook/stripe', methods=['POST'])
def stripe_webhook():
    """
    Endpoint de Webhook que recebe a notificação assíncrona do Stripe (Requisito 3).
    Valida a assinatura criptográfica (Stripe-Signature).
    Atualiza o usuário no banco para is_premium = 1 sem nunca armazenar dados de cartão (Requisito 5).
    """
    payload = request.data
    sig_header = request.headers.get('Stripe-Signature')
    endpoint_secret = os.getenv('STRIPE_WEBHOOK_SECRET')
    stripe_key = os.getenv('STRIPE_SECRET_KEY')
    if stripe_key:
        stripe.api_key = stripe_key

    event = None

    if endpoint_secret:
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, endpoint_secret
            )
        except ValueError as e:
            print(f"[Webhook Error] Payload inválido: {e}")
            return jsonify({'error': 'Payload inválido'}), 400
        except stripe.error.SignatureVerificationError as e:
            print(f"[Webhook Error] Assinatura do Stripe inválida: {e}")
            return jsonify({'error': 'Assinatura inválida'}), 400
        except Exception as e:
            print(f"[Webhook Error] Erro ao validar assinatura: {e}")
            return jsonify({'error': str(e)}), 400
    else:
        # Fallback caso endpoint_secret não tenha sido preenchido em dev
        print("[Webhook Warning] STRIPE_WEBHOOK_SECRET não configurado. Parseando JSON diretamente.")
        try:
            import json
            event = json.loads(payload.decode('utf-8'))
        except Exception as e:
            return jsonify({'error': 'JSON inválido'}), 400

    if hasattr(event, 'to_dict'):
        event_dict = event.to_dict()
    elif isinstance(event, dict):
        event_dict = event
    else:
        event_dict = dict(event)

    event_type = event_dict.get('type')
    data_object = event_dict.get('data', {}).get('object', {})
    print(f"[Stripe Webhook] Evento recebido: {event_type}")

    # Pagamento de assinatura confirmado
    if event_type == 'checkout.session.completed':
        user_id = data_object.get('client_reference_id') or (data_object.get('metadata') or {}).get('user_id')
        customer_id = data_object.get('customer')
        subscription_id = data_object.get('subscription')

        if user_id:
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """UPDATE usuarios 
                       SET is_premium = 1, stripe_customer_id = %s, stripe_subscription_id = %s 
                       WHERE id = %s""",
                    (customer_id, subscription_id, user_id)
                )
                conn.commit()
                cursor.close()
                conn.close()
                print(f"[Stripe Webhook] Usuário {user_id} promovido a PREMIUM com sucesso!")
                send_audit_log(f'upgrade_premium_confirmado_{user_id}', user_id)
            except Exception as e:
                print(f"[Stripe Webhook] Erro ao persistir premium no banco: {e}")
                return jsonify({'error': 'Erro ao atualizar banco de dados'}), 500

    # Cancelamento de assinatura
    elif event_type in ['customer.subscription.deleted', 'customer.subscription.paused']:
        subscription_id = data_object.get('id')
        customer_id = data_object.get('customer')

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                """UPDATE usuarios 
                   SET is_premium = 0 
                   WHERE stripe_subscription_id = %s OR stripe_customer_id = %s""",
                (subscription_id, customer_id)
            )
            conn.commit()
            cursor.close()
            conn.close()
            print(f"[Stripe Webhook] Assinatura {subscription_id} cancelada. Usuário rebaixado para plano gratuito.")
            send_audit_log(f'cancelamento_premium_assinatura_{subscription_id}')
        except Exception as e:
            print(f"[Stripe Webhook] Erro ao desativar assinatura no banco: {e}")
            return jsonify({'error': 'Erro ao atualizar banco de dados'}), 500

    return jsonify({'received': True}), 200


@app.route('/comentar', methods=['POST'])
def comentar():
    if 'user_id' not in session: return redirect(url_for('login'))
    movie_id = request.form['movie_id']
    texto = request.form['texto']
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO comentarios (usuario_id, tmdb_movie_id, texto) VALUES (%s, %s, %s)", 
                   (session['user_id'], movie_id, texto))
    conn.commit()
    send_audit_log(f'comentar_filme_{movie_id}')
    cursor.close()
    conn.close()
    return redirect(url_for('index'))

@app.route('/apagar_comentario/<int:comment_id>', methods=['POST'])
def apagar_comentario(comment_id):
    if 'user_id' not in session: 
        return "Não autenticado", 401
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Descobrir dono do comentário
    cursor.execute("SELECT usuario_id FROM comentarios WHERE id = %s", (comment_id,))
    com = cursor.fetchone()
    
    if not com:
        cursor.close()
        conn.close()
        return "Comentário não encontrado", 404

    is_owner = (com['usuario_id'] == session['user_id'])
    
    # Checar papel do usuário no auth-service
    try:
        res = requests.get(f"{AUTH_SERVICE_URL}/api/check-role/{session['user_id']}", timeout=5)
        if res.status_code == 200:
            current_role = res.json().get('role', 'usuario')
        else:
            current_role = session.get('role', 'usuario')
    except:
        current_role = session.get('role', 'usuario')

    # RBAC: dono do comentário ou admin pode apagar
    if not is_owner and current_role != 'admin':
        send_audit_log(f'403_apagar_comentario_{comment_id}')
        cursor.close()
        conn.close()
        return "403 Forbidden - Você não tem permissão para apagar este comentário.", 403

    cursor.execute("DELETE FROM comentarios WHERE id = %s", (comment_id,))
    conn.commit()
    send_audit_log(f'apagar_comentario_{comment_id}')
    cursor.close()
    conn.close()
    
    flash('Comentário apagado com sucesso!')
    return redirect(url_for('index'))

@app.route('/admin/logs')
def admin_logs():
    if 'user_id' not in session: 
        return redirect(url_for('login'))
        
    try:
        res = requests.get(f"{AUTH_SERVICE_URL}/api/check-role/{session['user_id']}", timeout=5)
        current_role = res.json().get('role', 'usuario') if res.status_code == 200 else session.get('role')
    except:
        current_role = session.get('role', 'usuario')
        
    if current_role != 'admin':
        send_audit_log('403_acessar_logs')
        return "403 Forbidden - Apenas administradores podem ver os logs.", 403

    logs = []
    try:
        res = requests.get(f"{LOG_SERVICE_URL}/api/logs?limit=50", timeout=5)
        if res.status_code == 200:
            logs = res.json().get('logs', [])
    except Exception as e:
        flash(f"Erro ao buscar logs: {e}")
        
    return render_template('logs.html', logs=logs)



@app.route('/perfil/<int:user_id>', methods=['GET', 'POST'])
def perfil(user_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # 1. Recuperar dados do usuário (incluindo status premium)
    cursor.execute("SELECT id, nome, email, bio, avatar_url, is_premium FROM usuarios WHERE id = %s", (user_id,))
    usuario = cursor.fetchone()
    if not usuario:
        cursor.close()
        conn.close()
        return "Usuário não encontrado", 404

    # 2. Se for POST, editar perfil (Acesso apenas do dono)
    is_owner = (session['user_id'] == user_id)
    if is_owner:
        session['is_premium'] = bool(usuario.get('is_premium', 0))
    
    if request.method == 'POST':
        if not is_owner:
            send_audit_log(f'403_editar_perfil_{user_id}')
            return "403 Forbidden - Você não tem permissão para editar este perfil.", 403
            
        nome = request.form.get('nome') or usuario['nome']
        bio = request.form.get('bio')
        foto = request.files.get('foto')
        
        avatar_url = usuario['avatar_url']
        
        # Validar arquivo
        if foto and foto.filename:
            if not allowed_file(foto.filename):
                flash("Tipo de arquivo inválido. Apenas imagens (png, jpg, jpeg, gif, webp).")
                return redirect(url_for('perfil', user_id=user_id))
            
            # Limite de tamanho (2MB)
            file_data = foto.read()
            if len(file_data) > 2 * 1024 * 1024:
                flash("A imagem deve ter no máximo 2MB.")
                return redirect(url_for('perfil', user_id=user_id))
                
            # Preparar upload MinIO
            filename = secure_filename(foto.filename)
            ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
            object_name = f"avatar_{user_id}_{uuid.uuid4().hex}.{ext}"
            
            try:
                if not minio_client.bucket_exists(MINIO_BUCKET):
                    minio_client.make_bucket(MINIO_BUCKET)
                    import json
                    policy = {
                        "Version": "2012-10-17",
                        "Statement": [{
                            "Effect": "Allow",
                            "Principal": {"AWS": ["*"]},
                            "Action": ["s3:GetObject"],
                            "Resource": [f"arn:aws:s3:::{MINIO_BUCKET}/*"]
                        }]
                    }
                    minio_client.set_bucket_policy(MINIO_BUCKET, json.dumps(policy))

                minio_client.put_object(
                    MINIO_BUCKET,
                    object_name,
                    io.BytesIO(file_data),
                    len(file_data),
                    content_type=foto.content_type
                )
                # URL roteada pelo próprio Flask para contornar o firewall
                avatar_url = url_for('serve_avatar', filename=object_name)
            except Exception as e:
                flash(f"Erro ao salvar imagem no MinIO: {e}")
                return redirect(url_for('perfil', user_id=user_id))
                
        # Atualizar banco
        cursor.execute("UPDATE usuarios SET nome = %s, bio = %s, avatar_url = %s WHERE id = %s", (nome, bio, avatar_url, user_id))
        conn.commit()
        session['nome'] = nome
        session['avatar_url'] = avatar_url
        send_audit_log(f'editar_perfil_{user_id}')
        flash("Perfil atualizado com sucesso!")
        return redirect(url_for('perfil', user_id=user_id))
        
    # 3. Recuperar favoritos do usuário
    cursor.execute("SELECT tmdb_movie_id, titulo, poster_path FROM favoritos WHERE usuario_id = %s", (user_id,))
    favoritos_lista = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('perfil.html', usuario=usuario, favoritos=favoritos_lista, is_owner=is_owner)

@app.route('/avatar/<filename>')
def serve_avatar(filename):
    try:
        response = minio_client.get_object(MINIO_BUCKET, filename)
        file_data = response.read()
        response.close()
        response.release_conn()
        return send_file(io.BytesIO(file_data), mimetype='image/jpeg')
    except Exception as e:
        print(f"Erro ao buscar avatar no MinIO: {e}")
        abort(404)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)


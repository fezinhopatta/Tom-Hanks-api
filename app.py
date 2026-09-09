import os
import requests
import mysql.connector
from flask import Flask, render_template, request, redirect, url_for, session, flash

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

    return render_template('index.html', movies=movies, favoritos=favoritos, comentarios=comentarios)

@app.route('/favoritar', methods=['POST'])
def favoritar():
    if 'user_id' not in session: return redirect(url_for('login'))
    movie_id = request.form['movie_id']
    titulo = request.form['titulo']
    poster_path = request.form['poster_path']
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO favoritos (usuario_id, tmdb_movie_id, titulo, poster_path) VALUES (%s, %s, %s, %s)", 
                       (session['user_id'], movie_id, titulo, poster_path))
        conn.commit()
        send_audit_log(f'favoritar_filme_{movie_id}')
    except mysql.connector.IntegrityError:
        pass 
    finally:
        cursor.close()
        conn.close()
    return redirect(url_for('index'))

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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

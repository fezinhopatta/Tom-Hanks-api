import os
import uuid
import smtplib
import threading
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import mysql.connector
import requests
from flask import Flask, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'auth_default_secret')
LOG_SERVICE_URL = os.getenv('LOG_SERVICE_URL', 'http://log-service:5000')

def send_audit_log(usuario_id, acao):
    try:
        requests.post(f"{LOG_SERVICE_URL}/api/log", json={
            'usuario_id': usuario_id,
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

def init_db():
    """Garante que as tabelas usuarios e reset_tokens existam com o esquema correto."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Tabela usuarios
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id INT AUTO_INCREMENT PRIMARY KEY,
                nome VARCHAR(100) NOT NULL,
                email VARCHAR(100) NOT NULL UNIQUE,
                senha_hash VARCHAR(255) NOT NULL,
                role VARCHAR(20) NOT NULL DEFAULT 'usuario'
            ) ENGINE=InnoDB;
        """)
        
        # Adiciona a coluna 'role' caso a tabela já existia sem ela
        try:
            cursor.execute("ALTER TABLE usuarios ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'usuario'")
            conn.commit()
        except mysql.connector.Error:
            pass # Coluna já existe

        # Tabela reset_tokens
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reset_tokens (
                id INT AUTO_INCREMENT PRIMARY KEY,
                token VARCHAR(255) NOT NULL UNIQUE,
                usuario_id INT NOT NULL,
                criado_em DATETIME NOT NULL,
                expira_em DATETIME NOT NULL,
                usado BOOLEAN NOT NULL DEFAULT 0,
                FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
            ) ENGINE=InnoDB;
        """)
        conn.commit()
        cursor.close()
        conn.close()
        print("[Auth Service] Banco de dados inicializado com sucesso.")
    except Exception as e:
        print(f"[Auth Service] Erro ao inicializar banco de dados: {e}")

# Executa inicialização do banco ao carregar
init_db()

def send_reset_email(to_email, reset_url):
    """Envia o e-mail de redefinição de senha via Mailtrap/Brevo SMTP."""
    mail_server = os.getenv('MAIL_SERVER', 'sandbox.smtp.mailtrap.io')
    mail_port = int(os.getenv('MAIL_PORT', 2525))
    mail_user = os.getenv('MAIL_USERNAME', '')
    mail_pass = os.getenv('MAIL_PASSWORD', '')
    mail_from = os.getenv('MAIL_FROM', 'no-reply@tomhanks.local')

    print(f"[Auth Service] Enviando e-mail de redefinição para: {to_email}")
    print(f"[Auth Service] Link de redefinição: {reset_url}")

    if not mail_user or not mail_pass:
        print("[Auth Service] Credenciais SMTP não configuradas. Link apenas impresso nos logs.")
        return True

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = 'Redefinição de Senha - Catálogo Tom Hanks'
        msg['From'] = mail_from
        msg['To'] = to_email

        text_content = f"Olá!\n\nVocê solicitou a redefinição da sua senha.\nClique no link abaixo para criar uma nova senha (válido por 30 minutos):\n{reset_url}\n\nSe você não solicitou esta alteração, ignore este e-mail."
        html_content = f"""
        <html>
          <body>
            <h2>Redefinição de Senha</h2>
            <p>Você solicitou a redefinição de sua senha no sistema <strong>Catálogo Tom Hanks</strong>.</p>
            <p>Clique no botão abaixo para redefinir sua senha (válido por 30 minutos):</p>
            <p><a href="{reset_url}" style="padding: 10px 20px; background-color: #007bff; color: white; text-decoration: none; border-radius: 5px;">Redefinir Senha</a></p>
            <p>Ou copie e cole o seguinte link no seu navegador:</p>
            <p><a href="{reset_url}">{reset_url}</a></p>
            <br>
            <p><small>Se você não solicitou a alteração, ignore este e-mail.</small></p>
          </body>
        </html>
        """

        msg.attach(MIMEText(text_content, 'plain'))
        msg.attach(MIMEText(html_content, 'html'))

        with smtplib.SMTP(mail_server, mail_port) as server:
            server.starttls()
            server.login(mail_user, mail_pass)
            server.sendmail(mail_from, [to_email], msg.as_string())
            
        print("[Auth Service] E-mail enviado com sucesso via SMTP Mailtrap!")
        return True
    except Exception as e:
        print(f"[Auth Service] Erro ao enviar e-mail via SMTP: {e}")
        return False

@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json() or request.form
    nome = data.get('nome')
    email = data.get('email')
    senha = data.get('senha')
    role = data.get('role', 'usuario')

    if not nome or not email or not senha:
        return jsonify({'success': False, 'error': 'Preencha todos os campos.'}), 400

    senha_hash = generate_password_hash(senha)

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO usuarios (nome, email, senha_hash, role) VALUES (%s, %s, %s, %s)",
            (nome, email, senha_hash, role)
        )
        conn.commit()
        return jsonify({'success': True, 'message': 'Usuário cadastrado com sucesso.'})
    except mysql.connector.IntegrityError:
        return jsonify({'success': False, 'error': 'E-mail já cadastrado.'}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json() or request.form
    email = data.get('email')
    senha = data.get('senha')

    if not email or not senha:
        return jsonify({'success': False, 'error': 'Preencha e-mail e senha.'}), 400

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM usuarios WHERE email = %s", (email,))
        user = cursor.fetchone()
        
        if user and check_password_hash(user['senha_hash'], senha):
            send_audit_log(user['id'], 'login')
            return jsonify({
                'success': True,
                'user': {
                    'id': user['id'],
                    'nome': user['nome'],
                    'email': user['email'],
                    'role': user.get('role', 'usuario')
                }
            })
        send_audit_log(email, 'tentativa_login_falha')
        return jsonify({'success': False, 'error': 'Credenciais inválidas.'}), 401
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/forgot-password', methods=['POST'])
def forgot_password():
    data = request.get_json() or request.form
    email = data.get('email')
    base_url = data.get('base_url') or os.getenv('APP_URL', 'http://localhost:5000')

    if not email:
        return jsonify({'success': False, 'error': 'Informe o e-mail.'}), 400

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id FROM usuarios WHERE email = %s", (email,))
        user = cursor.fetchone()

        if user:
            token = uuid.uuid4().hex
            criado_em = datetime.now()
            expira_em = criado_em + timedelta(minutes=30)
            
            cursor.execute(
                """INSERT INTO reset_tokens (token, usuario_id, criado_em, expira_em, usado)
                   VALUES (%s, %s, %s, %s, 0)""",
                (token, user['id'], criado_em, expira_em)
            )
            conn.commit()

            reset_url = f"{base_url.rstrip('/')}/reset-password/{token}"
            threading.Thread(target=send_reset_email, args=(email, reset_url), daemon=True).start()

        return jsonify({
            'success': True,
            'message': 'Se o e-mail estiver cadastrado, você receberá o link para redefinir sua senha.'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/verify-token', methods=['POST'])
def verify_token():
    data = request.get_json() or request.form
    token = data.get('token')

    if not token:
        return jsonify({'valid': False, 'reason': 'Token não fornecido.'}), 400

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM reset_tokens WHERE token = %s", (token,))
        record = cursor.fetchone()

        if not record:
            return jsonify({'valid': False, 'reason': 'Token não encontrado.'})

        if record['usado']:
            return jsonify({'valid': False, 'reason': 'Este link de redefinição já foi utilizado.'})

        if record['expira_em'] < datetime.now():
            return jsonify({'valid': False, 'reason': 'Este link de redefinição expirou (válido por 30 minutos).'})

        return jsonify({'valid': True})
    except Exception as e:
        return jsonify({'valid': False, 'reason': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/reset-password', methods=['POST'])
def reset_password():
    data = request.get_json() or request.form
    token = data.get('token')
    nova_senha = data.get('nova_senha')

    if not token or not nova_senha:
        return jsonify({'success': False, 'error': 'Token e nova senha são obrigatórios.'}), 400

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM reset_tokens WHERE token = %s", (token,))
        record = cursor.fetchone()

        if not record:
            return jsonify({'success': False, 'error': 'Token inválido ou não encontrado.'}), 400

        if record['usado']:
            return jsonify({'success': False, 'error': 'Este link de redefinição já foi utilizado.'}), 400

        if record['expira_em'] < datetime.now():
            return jsonify({'success': False, 'error': 'Este link de redefinição expirou.'}), 400

        # Atualiza a senha do usuário
        nova_hash = generate_password_hash(nova_senha)
        cursor.execute("UPDATE usuarios SET senha_hash = %s WHERE id = %s", (nova_hash, record['usuario_id']))
        
        # Marca o token como usado
        cursor.execute("UPDATE reset_tokens SET usado = 1 WHERE id = %s", (record['id'],))
        conn.commit()

        return jsonify({'success': True, 'message': 'Senha redefinida com sucesso!'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/check-role/<int:user_id>', methods=['GET'])
def check_role(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT role FROM usuarios WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        if user:
            return jsonify({'role': user['role']})
        return jsonify({'role': 'usuario'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

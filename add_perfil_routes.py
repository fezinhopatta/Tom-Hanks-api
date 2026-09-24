import re

with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Adiciona import
import_minio = """
from minio import Minio
from werkzeug.utils import secure_filename
import io
import uuid

MINIO_ENDPOINT = os.getenv('MINIO_ENDPOINT', 'localhost:9000')
MINIO_ACCESS_KEY = os.getenv('MINIO_ACCESS_KEY', 'minioadmin')
MINIO_SECRET_KEY = os.getenv('MINIO_SECRET_KEY', 'minioadmin')
MINIO_BUCKET = 'perfil'

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

"""

content = content.replace("app = Flask(__name__)", import_minio + "app = Flask(__name__)")

routes_perfil = """
@app.route('/perfil/<int:user_id>', methods=['GET', 'POST'])
def perfil(user_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # 1. Recuperar dados do usuário
    cursor.execute("SELECT id, nome, email, bio, avatar_url FROM usuarios WHERE id = %s", (user_id,))
    usuario = cursor.fetchone()
    if not usuario:
        cursor.close()
        conn.close()
        return "Usuário não encontrado", 404

    # 2. Se for POST, editar perfil (Acesso apenas do dono)
    is_owner = (session['user_id'] == user_id)
    
    if request.method == 'POST':
        if not is_owner:
            send_audit_log(f'403_editar_perfil_{user_id}')
            return "403 Forbidden - Você não tem permissão para editar este perfil.", 403
            
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
                minio_client.put_object(
                    MINIO_BUCKET,
                    object_name,
                    io.BytesIO(file_data),
                    len(file_data),
                    content_type=foto.content_type
                )
                # URL pública direta via browser
                avatar_url = f"http://localhost:9000/{MINIO_BUCKET}/{object_name}"
            except Exception as e:
                flash(f"Erro ao salvar imagem no MinIO: {e}")
                return redirect(url_for('perfil', user_id=user_id))
                
        # Atualizar banco
        cursor.execute("UPDATE usuarios SET bio = %s, avatar_url = %s WHERE id = %s", (bio, avatar_url, user_id))
        conn.commit()
        send_audit_log(f'editar_perfil_{user_id}')
        flash("Perfil atualizado com sucesso!")
        return redirect(url_for('perfil', user_id=user_id))
        
    # 3. Recuperar favoritos do usuário
    cursor.execute("SELECT tmdb_movie_id, titulo, poster_path FROM favoritos WHERE usuario_id = %s", (user_id,))
    favoritos_lista = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('perfil.html', usuario=usuario, favoritos=favoritos_lista, is_owner=is_owner)
"""

if "def perfil(user_id):" not in content:
    content += "\n" + routes_perfil

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)

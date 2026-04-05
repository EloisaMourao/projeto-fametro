from flask import Flask, flash, redirect, render_template, request, session, url_for
from datetime import datetime
import os
import sqlite3
from uuid import uuid4
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "uma_chave_secreta_aqui")
app.config["UPLOAD_FOLDER"] = "static/images"
app.config["ALLOWED_EXTENSIONS"] = {"png", "jpg", "jpeg", "gif", "webp"}
app.config["ADMIN_USERNAME"] = os.environ.get("ADMIN_USERNAME", "admin")
app.config["ADMIN_PASSWORD"] = os.environ.get("ADMIN_PASSWORD", "admin123")

INSTANCE_FOLDER = "instance"
DB_PATH = os.path.join(INSTANCE_FOLDER, "noticias.db")

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
os.makedirs(INSTANCE_FOLDER, exist_ok=True)


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def criar_banco():
    conn = get_db_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS noticias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT NOT NULL,
            resumo TEXT,
            conteudo TEXT NOT NULL,
            categoria TEXT DEFAULT 'Geral',
            imagem TEXT,
            destaque INTEGER DEFAULT 0,
            likes INTEGER DEFAULT 0,
            data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    conn.close()



def migrar_banco():
    conn = get_db_connection()
    colunas = {
        coluna[1] for coluna in conn.execute("PRAGMA table_info(noticias)").fetchall()
    }

    if "resumo" not in colunas:
        conn.execute("ALTER TABLE noticias ADD COLUMN resumo TEXT")
    if "categoria" not in colunas:
        conn.execute("ALTER TABLE noticias ADD COLUMN categoria TEXT DEFAULT 'Geral'")
    if "destaque" not in colunas:
        conn.execute("ALTER TABLE noticias ADD COLUMN destaque INTEGER DEFAULT 0")
    if "likes" not in colunas:
        conn.execute("ALTER TABLE noticias ADD COLUMN likes INTEGER DEFAULT 0")

    conn.execute(
        """
        UPDATE noticias
        SET resumo = COALESCE(NULLIF(TRIM(resumo), ''), SUBSTR(conteudo, 1, 180)),
            categoria = COALESCE(NULLIF(TRIM(categoria), ''), 'Geral'),
            destaque = COALESCE(destaque, 0),
            likes = COALESCE(likes, 0)
        """
    )
    conn.commit()
    conn.close()


criar_banco()
migrar_banco()


CATEGORIAS = [
    "Geral",
    "Cidade",
    "Eventos",
    "Educação",
    "Tecnologia",
    "Esporte",
    "Cultura",
]

MESES_ABREVIADOS = {
    1: "jan",
    2: "fev",
    3: "mar",
    4: "abr",
    5: "mai",
    6: "jun",
    7: "jul",
    8: "ago",
    9: "set",
    10: "out",
    11: "nov",
    12: "dez",
}



def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in app.config["ALLOWED_EXTENSIONS"]



def salvar_imagem(imagem_file):
    if not imagem_file or imagem_file.filename == "":
        return None
    if not allowed_file(imagem_file.filename):
        return None

    nome_seguro = secure_filename(imagem_file.filename)
    nome_base, extensao = os.path.splitext(nome_seguro)
    nome_final = f"{nome_base}-{uuid4().hex[:8]}{extensao.lower()}"
    caminho = os.path.join(app.config["UPLOAD_FOLDER"], nome_final)
    imagem_file.save(caminho)
    return f"static/images/{nome_final}"



def obter_noticia(noticia_id):
    conn = get_db_connection()
    noticia = conn.execute("SELECT * FROM noticias WHERE id = ?", (noticia_id,)).fetchone()
    conn.close()
    return noticia



def montar_filtros():
    busca = request.args.get("q", "").strip()
    categoria = request.args.get("categoria", "")
    ordenacao = request.args.get("ordenar", "recentes")
    somente_com_imagem = request.args.get("imagem") == "1"

    filtros_sql = []
    valores = []

    if busca:
        filtros_sql.append("(titulo LIKE ? OR resumo LIKE ? OR conteudo LIKE ?)")
        termo = f"%{busca}%"
        valores.extend([termo, termo, termo])

    if categoria:
        filtros_sql.append("categoria = ?")
        valores.append(categoria)

    if somente_com_imagem:
        filtros_sql.append("imagem IS NOT NULL AND imagem != ''")

    where_clause = f"WHERE {' AND '.join(filtros_sql)}" if filtros_sql else ""

    order_map = {
        "recentes": "destaque DESC, data_criacao DESC",
        "antigos": "destaque DESC, data_criacao ASC",
        "populares": "destaque DESC, likes DESC, data_criacao DESC",
        "titulo": "destaque DESC, titulo COLLATE NOCASE ASC",
    }
    order_clause = order_map.get(ordenacao, order_map["recentes"])

    return {
        "busca": busca,
        "categoria": categoria,
        "ordenar": ordenacao,
        "somente_com_imagem": somente_com_imagem,
        "where_clause": where_clause,
        "valores": valores,
        "order_clause": order_clause,
    }


@app.template_filter("datetime_br")
def datetime_br(value):
    if not value:
        return ""

    if isinstance(value, datetime):
        data = value
    else:
        texto = str(value).strip()
        formatos = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M")
        data = None
        for formato in formatos:
            try:
                data = datetime.strptime(texto, formato)
                break
            except ValueError:
                continue
        if data is None:
            return texto

    return f"{data.day:02d} {MESES_ABREVIADOS[data.month]} {data.year} às {data.strftime('%H:%M')}"


@app.context_processor
def inject_global_data():
    return {
        "admin_logado": bool(session.get("admin")),
        "categorias_disponiveis": CATEGORIAS,
    }


@app.route("/")
def home():
    return redirect(url_for("noticias"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("admin"):
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        usuario = request.form.get("usuario", "").strip()
        senha = request.form.get("senha", "")

        if (
            usuario == app.config["ADMIN_USERNAME"]
            and senha == app.config["ADMIN_PASSWORD"]
        ):
            session["admin"] = True
            flash("Login de administrador realizado com sucesso.", "success")
            return redirect(url_for("dashboard"))

        flash("Usuário ou senha inválidos.", "error")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("admin", None)
    flash("Sessão administrativa encerrada.", "info")
    return redirect(url_for("noticias"))


@app.route("/dashboard")
def dashboard():
    if not session.get("admin"):
        return redirect(url_for("login"))

    conn = get_db_connection()
    noticias = conn.execute(
        "SELECT * FROM noticias ORDER BY data_criacao DESC"
    ).fetchall()
    totais = conn.execute(
        "SELECT COUNT(*) AS posts, COALESCE(SUM(likes), 0) AS likes FROM noticias"
    ).fetchone()
    conn.close()

    return render_template(
        "dashboard.html",
        noticias=noticias,
        total_posts=totais["posts"],
        total_likes=totais["likes"],
    )


@app.route("/criar", methods=["GET", "POST"])
def criar_noticia():
    if not session.get("admin"):
        return redirect(url_for("login"))

    if request.method == "POST":
        titulo = request.form.get("titulo", "").strip()
        resumo = request.form.get("resumo", "").strip()
        conteudo = request.form.get("conteudo", "").strip()
        categoria = request.form.get("categoria", "Geral").strip() or "Geral"
        destaque = 1 if request.form.get("destaque") == "1" else 0
        imagem = salvar_imagem(request.files.get("imagem"))

        if not titulo or not conteudo:
            flash("Preencha pelo menos título e conteúdo para publicar.", "error")
            return render_template(
                "form_noticia.html",
                noticia=request.form,
                modo="criar",
                categorias=CATEGORIAS,
            )

        resumo_final = resumo or conteudo[:180]
        categoria_final = categoria if categoria in CATEGORIAS else "Geral"

        conn = get_db_connection()
        conn.execute(
            """
            INSERT INTO noticias (titulo, resumo, conteudo, categoria, imagem, destaque)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (titulo, resumo_final, conteudo, categoria_final, imagem, destaque),
        )
        conn.commit()
        conn.close()

        flash("Post publicado no feed com sucesso.", "success")
        return redirect(url_for("dashboard"))

    return render_template(
        "form_noticia.html",
        noticia=None,
        modo="criar",
        categorias=CATEGORIAS,
    )


@app.route("/editar/<int:noticia_id>", methods=["GET", "POST"])
def editar_noticia(noticia_id):
    if not session.get("admin"):
        return redirect(url_for("login"))

    noticia = obter_noticia(noticia_id)
    if not noticia:
        flash("Post não encontrado.", "error")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        titulo = request.form.get("titulo", "").strip()
        resumo = request.form.get("resumo", "").strip()
        conteudo = request.form.get("conteudo", "").strip()
        categoria = request.form.get("categoria", "Geral").strip() or "Geral"
        destaque = 1 if request.form.get("destaque") == "1" else 0
        imagem_atual = request.form.get("imagem_atual") or noticia["imagem"]
        nova_imagem = salvar_imagem(request.files.get("imagem"))
        imagem_final = nova_imagem or imagem_atual

        if not titulo or not conteudo:
            flash("Preencha pelo menos título e conteúdo para salvar.", "error")
            noticia_form = {
                "id": noticia_id,
                "titulo": titulo,
                "resumo": resumo,
                "conteudo": conteudo,
                "categoria": categoria,
                "destaque": destaque,
                "imagem": imagem_final,
            }
            return render_template(
                "form_noticia.html",
                noticia=noticia_form,
                modo="editar",
                categorias=CATEGORIAS,
            )

        resumo_final = resumo or conteudo[:180]
        categoria_final = categoria if categoria in CATEGORIAS else "Geral"

        conn = get_db_connection()
        conn.execute(
            """
            UPDATE noticias
            SET titulo = ?, resumo = ?, conteudo = ?, categoria = ?, imagem = ?, destaque = ?
            WHERE id = ?
            """,
            (titulo, resumo_final, conteudo, categoria_final, imagem_final, destaque, noticia_id),
        )
        conn.commit()
        conn.close()

        flash("Post atualizado com sucesso.", "success")
        return redirect(url_for("dashboard"))

    return render_template(
        "form_noticia.html",
        noticia=noticia,
        modo="editar",
        categorias=CATEGORIAS,
    )


@app.route("/excluir/<int:noticia_id>", methods=["POST"])
def excluir_noticia(noticia_id):
    if not session.get("admin"):
        return redirect(url_for("login"))

    conn = get_db_connection()
    conn.execute("DELETE FROM noticias WHERE id = ?", (noticia_id,))
    conn.commit()
    conn.close()

    flash("Post removido do painel.", "info")
    return redirect(url_for("dashboard"))


@app.route("/curtir/<int:noticia_id>", methods=["POST"])
def curtir_noticia(noticia_id):
    noticia = obter_noticia(noticia_id)
    if not noticia:
        flash("Esse post não foi encontrado.", "error")
        return redirect(url_for("noticias"))

    liked_posts = session.get("liked_posts", [])
    if noticia_id in liked_posts:
        flash("Você já curtiu esse post.", "info")
        return redirect(url_for("noticias", **request.args))

    conn = get_db_connection()
    conn.execute("UPDATE noticias SET likes = likes + 1 WHERE id = ?", (noticia_id,))
    conn.commit()
    conn.close()

    liked_posts.append(noticia_id)
    session["liked_posts"] = liked_posts
    flash("Curtida enviada.", "success")
    return redirect(url_for("noticias", **request.args))


@app.route("/noticias")
def noticias():
    filtros = montar_filtros()
    conn = get_db_connection()
    noticias = conn.execute(
        f"""
        SELECT * FROM noticias
        {filtros['where_clause']}
        ORDER BY {filtros['order_clause']}
        """,
        filtros["valores"],
    ).fetchall()
    destaque = noticias[0] if noticias else None
    noticias_lista = noticias[1:] if len(noticias) > 1 else noticias
    categorias = conn.execute(
        "SELECT DISTINCT categoria FROM noticias WHERE categoria IS NOT NULL AND categoria != '' ORDER BY categoria"
    ).fetchall()
    conn.close()

    categorias_feed = [item[0] for item in categorias if item[0]]

    return render_template(
        "noticias.html",
        noticias=noticias_lista,
        destaque=destaque,
        filtros=filtros,
        categorias=categorias_feed or CATEGORIAS,
        liked_posts=session.get("liked_posts", []),
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
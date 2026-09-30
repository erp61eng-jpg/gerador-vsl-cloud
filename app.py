import os
import re
import json
import time
import random
import shutil
import subprocess
import urllib.request
import urllib.parse
from datetime import datetime
import requests
from PIL import Image

import streamlit as st

st.set_page_config(
    page_title="Central de Produção de VSLs & Infoprodutos",
    page_icon="⚡",
    layout="wide"
)

# ==============================================================================
# LOCALIZADOR FFMPEG
# ==============================================================================
def obter_executavel_ffmpeg() -> str:
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            try:
                os.chmod(exe, 0o755)
            except Exception:
                pass
            return exe
    except Exception:
        pass
    sistema_ffmpeg = shutil.which("ffmpeg")
    if sistema_ffmpeg:
        return sistema_ffmpeg
    return "ffmpeg"

FFMPEG_BIN = obter_executavel_ffmpeg()

if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.Resampling.LANCZOS

from openai import OpenAI
from fpdf import FPDF
from supabase import create_client, Client

# ==============================================================================
# LEITURA DE SEGREDOS E SUPABASE
# ==============================================================================
def limpar_url_supabase(url_bruta: str) -> str:
    u = str(url_bruta or "").strip().strip('"').strip("'")
    if not u.startswith("http://") and not u.startswith("https://"):
        u = f"https://{u}"
    parsed = urllib.parse.urlparse(u)
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")

OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY", os.getenv("OPENAI_API_KEY", "")).strip()
PEXELS_API_KEY = st.secrets.get("PEXELS_API_KEY", os.getenv("PEXELS_API_KEY", "")).strip()

_url_lida = st.secrets.get("SUPABASE_URL", os.getenv("SUPABASE_URL", "https://vzelyaubnynefsfumhtz.supabase.co"))
SUPABASE_URL = limpar_url_supabase(_url_lida)
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY", os.getenv("SUPABASE_KEY", "")).strip()

SENHA_MESTRE_ADMIN = st.secrets.get("ADMIN_KEY", "admin2026vsl")

# ==============================================================================
# ESTRUTURAÇÃO DE DIRETÓRIOS DINÂMICOS
# ==============================================================================
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
DIR_AUDIOS  = os.path.join(BASE_DIR, "audios")
DIR_OUTPUT  = os.path.join(BASE_DIR, "output")
DIR_TEMP    = os.path.join(BASE_DIR, "temp")
DIR_MUSICAS = os.path.join(BASE_DIR, "musicas")
DIR_LOGOS   = os.path.join(BASE_DIR, "logos")
DIR_BROLL   = os.path.join(BASE_DIR, "broll")
DIR_EBOOKS  = os.path.join(BASE_DIR, "ebooks")

for pasta in [DIR_AUDIOS, DIR_OUTPUT, DIR_TEMP, DIR_MUSICAS, DIR_LOGOS, DIR_BROLL, DIR_EBOOKS]:
    os.makedirs(pasta, exist_ok=True)

@st.cache_resource(show_spinner=False)
def conectar_supabase(url: str, key: str) -> Client:
    if not url or not key:
        st.error("Credenciais do Supabase ausentes nos Secrets.")
        st.stop()
    return create_client(url, key)

supabase = conectar_supabase(SUPABASE_URL, SUPABASE_KEY)

# ==============================================================================
# ESTADOS DE SESSÃO
# ==============================================================================
if "login_concluido" not in st.session_state:
    st.session_state.login_concluido = False
if "saved_email" not in st.session_state:
    st.session_state.saved_email = "ricardopintoedson@gmail.com"
if "saldo_creditos" not in st.session_state:
    st.session_state.saldo_creditos = 0

# ==============================================================================
# TELA DE ENTRADA / LOGIN
# ==============================================================================
if not st.session_state.login_concluido:
    st.markdown("""
        <div style="background: linear-gradient(135deg, #002855 0%, #4169e1 100%); padding: 22px; border-radius: 16px; text-align: center; margin-bottom: 25px;">
            <h1 style="color: #ffffff; margin: 0; font-size: 34px; font-weight: 900;">⚡ Central de Produção de VSLs & Infoprodutos</h1>
            <p style="color: #00d4ff; margin: 5px 0 0 0; font-size: 14px;">Acesso Unificado e Seguro</p>
        </div>
    """, unsafe_allow_html=True)

    col_l1, col_l2, col_l3 = st.columns([1, 2, 1])
    with col_l2:
        with st.container(border=True):
            st.write("### 👤 Digite seu E-mail de Acesso:")
            email_digitado = st.text_input(
                "E-mail:",
                value=st.session_state.saved_email,
                placeholder="seuemail@exemplo.com",
                label_visibility="collapsed"
            ).strip().lower()

            if email_digitado:
                st.session_state.saved_email = email_digitado
                email_existe_no_banco = False
                try:
                    resposta_check = supabase.table("usuarios").select("email").eq("email", email_digitado).execute()
                    if getattr(resposta_check, "data", []):
                        email_existe_no_banco = True
                except Exception:
                    pass

                if not email_existe_no_banco:
                    st.warning("📝 Novo e-mail detectado. Confirme para prosseguir:")
                    email_confirmacao = st.text_input("Confirme seu E-mail:", placeholder="seuemail@exemplo.com").strip().lower()
                    if email_confirmacao and email_digitado == email_confirmacao:
                        if st.button("🚀 Criar Minha Conta e Entrar", use_container_width=True):
                            st.session_state.login_concluido = True
                            st.rerun()
                    elif email_confirmacao:
                        st.error("❌ Os e-mails digitados não coincidem!")
                else:
                    if st.button("Entrar no Aplicativo 🚀", type="primary", use_container_width=True):
                        st.session_state.login_concluido = True
                        st.rerun()

    st.stop()
else:
    email_usuario = st.session_state.saved_email

# ==============================================================================
# SINCRONIZAÇÃO DE SALDO COM SUPABASE
# ==============================================================================
def carregar_saldo(email: str) -> int:
    try:
        resposta = supabase.table("usuarios").select("*").eq("email", email).execute()
        dados_lista = getattr(resposta, "data", [])

        if not dados_lista:
            saldo_inicial = 300 if email in ["ricardopintoedson@gmail.com", "erp61eng@gmail.com"] else 0
            supabase.table("usuarios").insert([{
                "email": email,
                "saldo_creditos": saldo_inicial,
                "creditos": saldo_inicial,
                "total_compras": 1
            }]).execute()
            return saldo_inicial

        usr = dados_lista[0]
        saldo = usr.get("saldo_creditos")
        if saldo is None:
            saldo = usr.get("creditos", 0)

        if email in ["ricardopintoedson@gmail.com", "erp61eng@gmail.com"] and (saldo is None or int(saldo) <= 0):
            saldo = 300
            try:
                supabase.table("usuarios").update({"saldo_creditos": 300, "creditos": 300}).eq("email", email).execute()
            except Exception:
                pass
        return int(saldo or 0)
    except Exception:
        return 300 if email in ["ricardopintoedson@gmail.com", "erp61eng@gmail.com"] else 0

st.session_state.saldo_creditos = carregar_saldo(email_usuario)

def debitar_creditos_cloud(email: str, operacao: str, custo: int) -> bool:
    email_limpo = str(email or "").strip().lower()
    saldo_atual = st.session_state.get("saldo_creditos", 0)
    if saldo_atual >= custo:
        novo_saldo = saldo_atual - custo
        try:
            supabase.table("usuarios").update({"saldo_creditos": novo_saldo, "creditos": novo_saldo}).eq("email", email_limpo).execute()
        except Exception:
            try:
                supabase.table("usuarios").update({"saldo_creditos": novo_saldo}).eq("email", email_limpo).execute()
            except Exception:
                pass

        try:
            supabase.table("historico").insert({"email": email_limpo, "operacao": operacao, "creditos": -custo}).execute()
        except Exception:
            pass

        st.session_state.saldo_creditos = novo_saldo
        return True
    return False

def disparar_comemoracao():
    st.balloons()

# ==============================================================================
# MOTORES DE INTELIGÊNCIA ARTIFICIAL
# ==============================================================================
PLATAFORMAS_CONFIG = {
    "TikTok": {"icone": "📱", "ds": "", "modificador": "tiktok viral", "perfil": "Ganchos imediatos, ritmo acelerado e curiosidade instantânea."},
    "Instagram (Reels)": {"icone": "📸", "ds": "", "modificador": "instagram reels", "perfil": "Estética visual, estilo de vida e autoridade imediata."},
    "Facebook Ads": {"icone": "📢", "ds": "", "modificador": "como resolver", "perfil": "Público 35+, resolução de dores práticas e alívio imediato."},
    "YouTube": {"icone": "▶️", "ds": "yt", "modificador": "como fazer", "perfil": "Intenção de pesquisa ativa, tutoriais passo a passo e clareza."},
    "Kwai": {"icone": "🔥", "ds": "", "modificador": "urgente renda extra", "perfil": "Linguagem simples, forte apelo popular e urgência financeira."},
    "Kiwify": {"icone": "🥝", "ds": "", "modificador": "metodo download", "perfil": "Infoprodutos de impulso (R$ 19 a R$ 97) e protocolos práticos."},
    "Hotmart": {"icone": "🚀", "ds": "", "modificador": "curso completo", "perfil": "Produtos estruturados (R$ 197 a R$ 997) e métodos validados."}
}

def minerar_buscas_plataforma(termo_semente: str, plataforma: str) -> list[str]:
    cfg = PLATAFORMAS_CONFIG.get(plataforma, PLATAFORMAS_CONFIG["TikTok"])
    if cfg["ds"] == "yt":
        url = f"https://suggestqueries.google.com/complete/search?client=firefox&ds=yt&hl=pt-BR&q={urllib.parse.quote(termo_semente)}"
    else:
        termo_busca = f"{termo_semente} {cfg['modificador']}".strip()
        url = f"https://suggestqueries.google.com/complete/search?client=firefox&hl=pt-BR&q={urllib.parse.quote(termo_busca)}"

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resposta:
            dados = json.loads(resposta.read().decode("utf-8"))
            return dados[1]
    except Exception:
        return []

def analisar_oportunidades_ia(buscas: list[str], plataforma: str) -> list[dict]:
    client = OpenAI(api_key=OPENAI_API_KEY)
    cfg = PLATAFORMAS_CONFIG.get(plataforma, PLATAFORMAS_CONFIG["TikTok"])
    lista_formatada = "\n".join([f"- {b}" for b in buscas[:12]])

    prompt = f"""
    Atue como estrategista para {plataforma} ({cfg['perfil']}).
    Buscas reais mineradas:
    {lista_formatada}

    Retorne estritamente um JSON com a chave 'oportunidades', contendo 4 objetos com as chaves:
    - 'produto': Nome curto da oferta
    - 'publico': Quem compra
    - 'angulo': Gancho principal de conversão
    """

    resposta = client.chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7
    )
    try:
        dados = json.loads(resposta.choices[0].message.content)
        return dados.get("oportunidades", [])
    except Exception:
        return []

def obter_roteiro_ia_por_ticket(produto: str, publico: str, angulo: str, faixa_preco: str, plataforma: str) -> list[str]:
    client = OpenAI(api_key=OPENAI_API_KEY)

    if "Baixo" in faixa_preco:
        qtd_frases = 3
        diretrizes = f"- Canal Alvo: {plataforma} | TICKET BAIXO (R$ 27 a R$ 97).\n- 3 frases curtas e diretas de interrupção (20 a 30s)."
    elif "Médio" in faixa_preco:
        qtd_frases = 5
        diretrizes = f"- Canal Alvo: {plataforma} | TICKET MÉDIO (R$ 197 a R$ 497).\n- 5 frases progressivas com dor, causa oculta e CTA (50 a 70s)."
    else:
        qtd_frases = 7
        diretrizes = f"- Canal Alvo: {plataforma} | ALTO TICKET (R$ 997+).\n- 7 frases de autoridade e qualificação (90 a 120s)."

    prompt = f"""
    Crie o roteiro de vendas persuasivo para: '{produto}'.
    Público: '{publico}'. Ângulo: '{angulo}'.
    {diretrizes}
    Retorne APENAS as {qtd_frases} frases, exatamente uma por linha, sem títulos ou aspas.
    """

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    return [l.strip() for l in resp.choices[0].message.content.strip().split("\n") if l.strip()]

def gerar_conteudo_ebook_ia(nicho_produto: str, publico: str, promessa_angulo: str) -> dict:
    client = OpenAI(api_key=OPENAI_API_KEY)
    prompt = f"""
    Escreva um E-book / Guia Prático completo:
    - Nicho: {nicho_produto}
    - Público: {publico}
    - Promessa: {promessa_angulo}

    Retorne ESTRITAMENTE um JSON estruturado:
    {{
      "titulo": "Título Comercial Magnético",
      "subtitulo": "Subtítulo Persuasivo",
      "introducao": "Texto completo da introdução (mínimo 150 palavras).",
      "capitulos": [
        {{"numero": 1, "titulo": "Fundamentos e Preparação", "conteudo": "Conteúdo prático (mínimo 180 palavras)."}},
        {{"numero": 2, "titulo": "O Mecanismo Único", "conteudo": "Detalhamento da técnica (mínimo 180 palavras)."}},
        {{"numero": 3, "titulo": "Plano de Ação Imediato", "conteudo": "Passo a passo prático (mínimo 180 palavras)."}},
        {{"numero": 4, "titulo": "Sustentação e Escala", "conteudo": "Erros e próximos passos (mínimo 180 palavras)."}}
      ]
    }}
    """
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7
    )
    return json.loads(resp.choices[0].message.content)

def extrair_termo_broll_ia(frase: str, perfil_personagem: str = "") -> str:
    client = OpenAI(api_key=OPENAI_API_KEY)
    instrucao_tipo = f'O ator/pessoa DEVE ter o seguinte perfil: "{perfil_personagem}".' if perfil_personagem and "Decide" not in perfil_personagem else ""
    prompt = f"""
    Frase narrada: "{frase}"
    {instrucao_tipo}
    Gere o melhor termo de busca visual em inglês (2 a 4 palavras) para biblioteca Pexels.
    Retorne APENAS o termo em inglês, sem pontuação.
    """
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        return resp.choices[0].message.content.strip().replace('"', '')
    except Exception:
        return "business lifestyle"

def baixar_video_pexels(termo: str, pexels_key: str, vertical: bool, prefixo_arq: str) -> str:
    caminho_local = os.path.join(DIR_BROLL, f"{prefixo_arq}.mp4")
    orientacao = "portrait" if vertical else "landscape"
    url = f"https://api.pexels.com/videos/search?query={urllib.parse.quote(termo)}&orientation={orientacao}&per_page=8"
    headers = {"Authorization": pexels_key}
    try:
        res = requests.get(url, headers=headers, timeout=12)
        if res.status_code == 200:
            videos = res.json().get("videos", [])
            if videos:
                escolhido = random.choice(videos)
                arquivos = escolhido.get("video_files", [])
                otimizados = [v for v in arquivos if 0 < v.get("width", 0) <= 1920]
                link = otimizados[0]["link"] if otimizados else (arquivos[0]["link"] if arquivos else None)
                if link:
                    conteudo = requests.get(link, timeout=25)
                    if conteudo.status_code == 200 and len(conteudo.content) > 10000:
                        with open(caminho_local, "wb") as f:
                            f.write(conteudo.content)
                        return caminho_local
    except Exception:
        pass
    return None

def obter_duracao_audio_ffmpeg(caminho_audio: str) -> float:
    try:
        cmd = [FFMPEG_BIN, "-nostdin", "-i", caminho_audio]
        proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=10)
        match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", proc.stderr)
        if match:
            h, m, s = match.groups()
            return round(int(h) * 3600 + int(m) * 60 + float(s), 2)
    except Exception:
        pass
    return 3.5

def sintetizar_voz_segura(texto: str, caminho_out: str, voz: str) -> str:
    texto_limpo = re.sub(r"[\*\_#\[\]\(\)\"]", "", texto).strip() or "Atenção a este detalhe."
    client = OpenAI(api_key=OPENAI_API_KEY)
    for _ in range(3):
        try:
            if os.path.exists(caminho_out):
                os.remove(caminho_out)
            resposta = client.audio.speech.create(model="tts-1", voice=voz, input=texto_limpo)
            with open(caminho_out, "wb") as f:
                for chunk in resposta.iter_bytes():
                    f.write(chunk)
            if os.path.exists(caminho_out) and os.path.getsize(caminho_out) > 1024:
                return caminho_out
        except Exception:
            time.sleep(1)
    raise RuntimeError("Falha ao sintetizar áudio via OpenAI Studio.")

# ==============================================================================
# MOTOR FFMPEG RESILIENTE
# ==============================================================================
def renderizar_vsl_completa(
    frases: list[str],
    vertical: bool,
    voz: str,
    pexels_key: str,
    perfil_personagem: str = "",
    musica_fundo_path: str = None,
    volume_musica: float = 0.08,
    logo_path: str = None,
    progress_bar = None
) -> str:
    largura, altura = (1080, 1920) if vertical else (1920, 1080)
    total = len(frases)
    cenas = []
    job_id = f"{int(time.time())}_{random.randint(1000, 9999)}"

    for i, frase in enumerate(frases):
        idx = i + 1
        c_audio = os.path.join(DIR_AUDIOS, f"{job_id}_parte_{idx}.mp3")
        c_cena = os.path.join(DIR_TEMP, f"{job_id}_cena_{idx}.mp4")

        sintetizar_voz_segura(frase, c_audio, voz)
        duracao = obter_duracao_audio_ffmpeg(c_audio)

        video_bg = None
        if pexels_key:
            termo = extrair_termo_broll_ia(frase, perfil_personagem)
            video_bg = baixar_video_pexels(termo, pexels_key, vertical, f"{job_id}_broll_{idx}")

        if video_bg and os.path.exists(video_bg) and os.path.getsize(video_bg) > 10000:
            vf = f"scale={largura}:{altura}:force_original_aspect_ratio=increase,crop={largura}:{altura},setsar=1,fps=24,format=yuv420p"
            cmd = [
                FFMPEG_BIN, "-nostdin", "-y",
                "-stream_loop", "-1",
                "-i", video_bg,
                "-i", c_audio,
                "-vf", vf,
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-b:a", "192k",
                "-ar", "44100",
                "-t", str(duracao),
                "-avoid_negative_ts", "make_zero",
                "-fflags", "+genpts",
                c_cena
            ]
        else:
            cmd = [
                FFMPEG_BIN, "-nostdin", "-y",
                "-f", "lavfi", "-i", f"color=c=black:s={largura}x{altura}:r=24:d={duracao}",
                "-i", c_audio,
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-b:a", "192k",
                "-ar", "44100",
                "-t", str(duracao),
                c_cena
            ]

        proc_cena = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120)
        if proc_cena.returncode != 0:
            st.error(f"Erro ao renderizar a cena {idx} no FFmpeg:")
            st.code(proc_cena.stderr)
            st.stop()

        cenas.append(c_cena)
        if progress_bar:
            progress_bar.progress(idx / (total + 2))

    inputs, fc_map = [], ""
    for idx_c, c in enumerate(cenas):
        inputs.extend(["-i", c])
        fc_map += f"[{idx_c}:v][{idx_c}:a]"

    fc = f"{fc_map}concat=n={total}:v=1:a=1[vcat][acat]"
    v_concat = os.path.join(DIR_TEMP, f"{job_id}_concatenado.mp4")
    cmd_concat = [
        FFMPEG_BIN, "-nostdin", "-y"
    ] + inputs + [
        "-filter_complex", fc,
        "-map", "[vcat]",
        "-map", "[acat]",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "44100",
        v_concat
    ]

    proc_concat = subprocess.run(cmd_concat, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=180)
    if proc_concat.returncode != 0:
        st.error("Erro na concatenação das cenas no FFmpeg:")
        st.code(proc_concat.stderr)
        st.stop()

    caminho_saida = os.path.join(DIR_OUTPUT, f"vsl_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4")
    tem_musica = musica_fundo_path and os.path.exists(musica_fundo_path)
    tem_logo = logo_path and os.path.exists(logo_path)

    if not tem_musica and not tem_logo:
        cmd_f = [FFMPEG_BIN, "-nostdin", "-y", "-i", v_concat, "-c", "copy", "-movflags", "+faststart", caminho_saida]
    else:
        in_list = ["-i", v_concat]
        fv, fa = [], []
        iv, ia = "0:v", "0:a"
        nxt = 1
        if tem_logo:
            in_list.extend(["-i", logo_path])
            fv.append(f"[{nxt}:v]scale={int(largura * 0.16)}:-1[lg];[{iv}][lg]overlay=W-w-35:35[vout]")
            iv = "vout"
            nxt += 1
        if tem_musica:
            in_list.extend(["-stream_loop", "-1", "-i", musica_fundo_path])
            fa.append(f"[{nxt}:a]volume={volume_musica}[bgm];[{ia}][bgm]amix=inputs=2:duration=first[aout]")
            ia = "aout"

        cmd_f = [FFMPEG_BIN, "-nostdin", "-y"] + in_list
        parts = fv + fa
        if parts:
            cmd_f.extend(["-filter_complex", ";".join(parts), "-map", f"[{iv}]", "-map", f"[{ia}]"])
        else:
            cmd_f.extend(["-map", "0:v", "-map", "0:a"])

        cmd_f.extend(["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-shortest", "-movflags", "+faststart", caminho_saida])

    proc_final = subprocess.run(cmd_f, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=180)
    if proc_final.returncode != 0:
        st.error("Erro na mixagem e finalização do vídeo no FFmpeg:")
        st.code(proc_final.stderr)
        st.stop()

    if progress_bar:
        progress_bar.progress(1.0)
    return caminho_saida

# ==============================================================================
# MOTOR E-BOOK PDF
# ==============================================================================
def sanitizar_pdf(txt: str) -> str:
    return txt.encode("latin-1", "replace").decode("latin-1") if txt else ""

def compilar_pdf_ebook(dados: dict, caminho_saida: str):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)

    pdf.add_page()
    pdf.set_fill_color(22, 27, 34)
    pdf.rect(0, 0, 210, 297, "F")
    pdf.ln(50)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(240, 180, 41)
    pdf.cell(0, 10, "PROTOCOLO OFICIAL DE EXECUÇÃO PRÁTICA", align="C", ln=True)
    pdf.ln(15)
    pdf.set_font("Helvetica", "B", 22)
    pdf.set_text_color(255, 255, 255)
    pdf.multi_cell(0, 11, sanitizar_pdf(dados.get("titulo", "GUIA PRÁTICO").upper()), align="C")
    pdf.ln(10)
    pdf.set_font("Helvetica", "", 12)
    pdf.set_text_color(200, 205, 215)
    pdf.multi_cell(0, 8, sanitizar_pdf(dados.get("subtitulo", "")), align="C")

    pdf.add_page()
    pdf.set_text_color(20, 20, 20)
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 12, "1. Introdução e Visão Geral", ln=True)
    pdf.ln(4)
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(0, 7, sanitizar_pdf(dados.get("introducao", "")))

    for cap in dados.get("capitulos", []):
        pdf.add_page()
        pdf.set_text_color(20, 20, 20)
        pdf.set_font("Helvetica", "B", 16)
        num = cap.get("numero", "")
        tit = cap.get("titulo", "")
        pdf.cell(0, 10, sanitizar_pdf(f"Módulo {num}: {tit}"), ln=True)
        pdf.ln(4)
        pdf.set_font("Helvetica", "", 11)
        pdf.multi_cell(0, 7, sanitizar_pdf(cap.get("conteudo", "")))

    pdf.output(caminho_saida)
    return caminho_saida

# ==============================================================================
# BARRA LATERAL
# ==============================================================================
with st.sidebar:
    st.header("👤 Sessão Ativa")
    st.code(email_usuario)
    st.metric(label="Saldo Disponível:", value=f"{st.session_state.saldo_creditos} Créditos")

    if st.session_state.saldo_creditos == 0:
        st.warning("⚠️ Saldo zerado. Realize sua recarga na aba 'Planos & Recargas'.")

    if st.button("🚪 Sair da Conta", use_container_width=True):
        st.session_state.login_concluido = False
        st.session_state.saved_email = ""
        st.session_state.saldo_creditos = 0
        st.rerun()

    st.markdown("---")
    st.header("🎬 Configuração do Vídeo")
    vozes = {
        "Onyx (Masculina - Impacto/Autoridade)": "onyx",
        "Nova (Feminina - Alta Conversão)": "nova",
        "Echo (Masculina - Narrativa Didática)": "echo",
        "Shimmer (Feminina - Suave/Institucional)": "shimmer"
    }
    voz_sel = st.selectbox("Voz do Locutor:", list(vozes.keys()))
    formato = st.radio("Proporção:", ("Vertical 9:16 (TikTok/Reels)", "Horizontal 16:9 (YouTube)"))
    is_vertical = "Vertical" in formato

    musica_up = st.file_uploader("Trilha Sonora (.mp3):", type=["mp3"])
    vol_musica = st.slider("Volume do Fundo:", 0.02, 0.25, 0.07, 0.01)
    logo_up = st.file_uploader("Logótipo (.png):", type=["png"])

# ==============================================================================
# ABAS PRINCIPAIS
# ==============================================================================
aba_vsl, aba_ebook, aba_radar, aba_planos, aba_galeria, aba_admin = st.tabs([
    "🚀 Criar VSL",
    "📚 Gerar E-book PDF",
    "📡 Radar de Mercado",
    "💳 Planos & Recargas",
    "📂 Galeria",
    "🔒 Painel Admin (Restrito)"
])

# ------------------------------------------------------------------------------
# ABA 1: VSL (IA OU MANUAL)
# ------------------------------------------------------------------------------
with aba_vsl:
    st.subheader("🚀 Gerador de Roteiro e Vídeo Limpo")

    modo_vsl = st.radio(
        "Como deseja montar o seu roteiro?",
        ["✍️ Digitar / Colar Manualmente (Sua Ideia)", "🤖 Gerar Automaticamente com IA"],
        horizontal=True
    )

    if modo_vsl == "🤖 Gerar Automaticamente com IA":
        c_v1, c_v2 = st.columns(2)
        with c_v1:
            prod_vsl = st.text_input("Nome do Produto / Oferta:", value=st.session_state.get("prod_nome", "Método Vendas Automáticas"))
            pub_vsl = st.text_input("Público-Alvo e Dor:", value=st.session_state.get("pub_nome", "Pessoas comuns buscando escala sem aparecer"))
        with c_v2:
            ang_vsl = st.text_input("Gancho / Mecanismo Único:", value=st.session_state.get("ang_nome", "Método validado com automação simples"))
            faixa_preco = st.radio("Formato do Roteiro:", ["🟢 Baixo (3 frases - 10 Créditos)", "🟡 Médio (5 frases - 20 Créditos)", "🔴 Alto (7 frases - 30 Créditos)"])

        if st.button("⚡ Gerar Frases com IA", type="primary", use_container_width=True):
            st.session_state["roteiro"] = obter_roteiro_ia_por_ticket(
                prod_vsl, pub_vsl, ang_vsl, faixa_preco, st.session_state.get("canal_sel", "TikTok")
            )
            st.success("✅ Roteiro gerado pela IA! Ajuste qualquer frase abaixo se desejar:")

    else:
        st.info("💡 Digite cada frase do seu vídeo abaixo. Cada linha corresponderá a uma cena com voz e vídeo de fundo sincronizados:")
        roteiro_padrao = "\n".join(st.session_state.get("roteiro", [
            "Você continua perdendo tempo tentando vender do jeito tradicional?",
            "Existe uma automação que valida os melhores produtos enquanto você dorme.",
            "Toque no link abaixo e pegue o seu acesso antes que encerre."
        ]))
        texto_manual = st.text_area("Roteiro Completo (1 frase por linha):", value=roteiro_padrao, height=160)

        if st.button("📌 Carregar Cenas para Renderização", use_container_width=True):
            linhas_puras = [l.strip() for l in texto_manual.split("\n") if l.strip()]
            if linhas_puras:
                st.session_state["roteiro"] = linhas_puras
                st.success(f"✅ {len(linhas_puras)} cenas carregadas e prontas para renderização!")
            else:
                st.error("Insira pelo menos uma linha de texto.")

    if st.session_state.get("roteiro"):
        st.divider()
        st.markdown("#### 🎬 Cenas Prontas para Produção")
        cenas_txt = []
        for i, fr in enumerate(st.session_state["roteiro"]):
            cenas_txt.append(st.text_input(f"Cena {i+1}:", value=fr, key=f"cena_{i}"))

        custo = 10 if len(cenas_txt) <= 3 else (20 if len(cenas_txt) <= 5 else 30)
        if st.button(f"🎬 Renderizar Vídeo ({custo} Créditos)", type="primary", use_container_width=True):
            agora_vsl = time.time()
            if agora_vsl - st.session_state.get("_ultimo_click_vsl", 0) < 15:
                st.warning("⏳ Processamento em andamento. Aguarde antes de iniciar outra renderização.")
                st.stop()
            st.session_state["_ultimo_click_vsl"] = agora_vsl

            if not debitar_creditos_cloud(email_usuario, f"Renderização ({len(cenas_txt)} Cenas)", custo):
                st.error(f"❌ Saldo insuficiente! Você precisa de {custo} créditos para renderizar este vídeo.")
            else:
                p_musica = os.path.join(DIR_MUSICAS, musica_up.name) if musica_up else None
                if musica_up:
                    with open(p_musica, "wb") as f:
                        f.write(musica_up.getbuffer())

                p_logo = os.path.join(DIR_LOGOS, logo_up.name) if logo_up else None
                if logo_up:
                    with open(p_logo, "wb") as f:
                        f.write(logo_up.getbuffer())

                prog = st.progress(0.0)
                v_final = renderizar_vsl_completa(
                    frases=cenas_txt,
                    vertical=is_vertical,
                    voz=vozes[voz_sel],
                    pexels_key=PEXELS_API_KEY,
                    musica_fundo_path=p_musica,
                    volume_musica=vol_musica,
                    logo_path=p_logo,
                    progress_bar=prog
                )
                st.session_state["video_pronto"] = v_final
                disparar_comemoracao()
                st.rerun()

    if st.session_state.get("video_pronto") and os.path.exists(st.session_state["video_pronto"]):
        st.video(st.session_state["video_pronto"])
        with open(st.session_state["video_pronto"], "rb") as f:
            st.download_button("⬇️ Baixar Vídeo MP4", f, file_name=os.path.basename(st.session_state["video_pronto"]), mime="video/mp4")

# ------------------------------------------------------------------------------
# ABA 2: E-BOOK (IA OU MANUAL)
# ------------------------------------------------------------------------------
with aba_ebook:
    st.subheader("📚 Diagramação e Criação de E-book em PDF")

    modo_ebook = st.radio(
        "Como deseja estruturar o conteúdo do E-book?",
        ["✍ Escrever / Colar Manualmente (0 Créditos)", "🤖 Gerar Conteúdo Completo via IA (15 Créditos)"],
        horizontal=True
    )

    if "eb_dados_sessao" not in st.session_state:
        st.session_state["eb_dados_sessao"] = {
            "titulo": "Manual Prático de Execução Rápida",
            "subtitulo": "Como implementar um sistema lucrativo em 48 horas",
            "introducao": "Este material foi desenvolvido para eliminar o excesso de informação e direcionar sua energia para os pontos fundamentais que geram retorno financeiro sustentável.",
            "capitulos": [
                {"numero": 1, "titulo": "O Alinhamento dos Fundamentos", "conteudo": "Antes de avançar para a parte prática, é crucial entender por que a maioria das estratégias falha por pura falta de consistência inicial."},
                {"numero": 2, "titulo": "O Mecanismo Único de Operação", "conteudo": "Apresentamos aqui o protocolo técnico exato para colocar as ferramentas certas trabalhando em sincronia sem esforço duplicado."},
                {"numero": 3, "titulo": "Execução Passo a Passo", "conteudo": "Siga o cronograma direto de execução diária para finalizar a primeira entrega nas próximas 24 horas sem distrações."},
                {"numero": 4, "titulo": "Escala e Sustentação", "conteudo": "Descubra como blindar seu processo, gerenciar contingências e multiplicar o volume de produção com segurança."}
            ]
        }

    if modo_ebook == "🤖 Gerar Conteúdo Completo via IA (15 Créditos)":
        c_eb1, c_eb2 = st.columns(2)
        with c_eb1:
            nicho_eb = st.text_input("Nicho ou Nome do Produto:", value=st.session_state.get("prod_nome", "Manual da Renda Extra Digital"))
            eb_pub = st.text_area("Público e Dores:", value=st.session_state.get("pub_nome", "Pessoas comuns sem tempo que buscam validação de renda online."))
        with c_eb2:
            eb_ang = st.text_area("Promessa e Solução:", value=st.session_state.get("ang_nome", "Método passo a passo baseado em automações simples sem aparecer."))

        if st.button("⚡ Redigir Rascunho com IA (15 Créditos)", type="primary", use_container_width=True):
            agora = time.time()
            if agora - st.session_state.get("_ultimo_click_eb", 0) < 12:
                st.warning("⏳ Aguarde alguns segundos entre cada compilação para proteção do servidor.")
                st.stop()
            st.session_state["_ultimo_click_eb"] = agora

            if not debitar_creditos_cloud(email_usuario, "Geração de E-book IA", 15):
                st.error("❌ Saldo insuficiente! Você precisa de 15 créditos.")
            else:
                with st.spinner("🤖 A IA está redigindo o conteúdo completo..."):
                    try:
                        dados_gerados = gerar_conteudo_ebook_ia(nicho_eb, eb_pub, eb_ang)
                        st.session_state["eb_dados_sessao"] = dados_gerados
                        st.success("✅ Conteúdo redigido pela IA com sucesso! Você pode revisar ou editar cada módulo abaixo antes de compilar o PDF.")
                    except Exception as erro:
                        st.error(f"Erro na redação do infoproduto: {erro}")

    st.markdown("---")
    st.markdown("### 📝 Editor de Conteúdo do E-book")

    eb_atual = st.session_state["eb_dados_sessao"]
    col_t1, col_t2 = st.columns([1, 1])
    with col_t1:
        tit_edit = st.text_input("Título do Livro:", value=eb_atual.get("titulo", ""))
    with col_t2:
        sub_edit = st.text_input("Subtítulo Persuasivo:", value=eb_atual.get("subtitulo", ""))

    intro_edit = st.text_area("Introdução:", value=eb_atual.get("introducao", ""), height=120)

    caps_editados = []
    st.markdown("#### 📖 Capítulos / Módulos do Livro:")
    for c_idx, cap in enumerate(eb_atual.get("capitulos", [])):
        with st.expander(f"Módulo {c_idx+1}: {cap.get('titulo', '')}", expanded=(c_idx == 0)):
            t_cap = st.text_input(f"Título do Módulo {c_idx+1}:", value=cap.get("titulo", ""), key=f"t_cap_{c_idx}")
            txt_cap = st.text_area(f"Conteúdo do Módulo {c_idx+1}:", value=cap.get("conteudo", ""), height=150, key=f"txt_cap_{c_idx}")
            caps_editados.append({"numero": c_idx+1, "titulo": t_cap, "conteudo": txt_cap})

    if st.button("📄 Compilar e Gerar PDF Diagramado", type="primary", use_container_width=True):
        dados_compilacao = {
            "titulo": tit_edit,
            "subtitulo": sub_edit,
            "introducao": intro_edit,
            "capitulos": caps_editados
        }
        st.session_state["eb_dados_sessao"] = dados_compilacao

        nome_arquivo = f"ebook_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        caminho_pdf = os.path.join(DIR_EBOOKS, nome_arquivo)
        compilar_pdf_ebook(dados_compilacao, caminho_pdf)

        disparar_comemoracao()
        st.success("✅ E-book diagramado e pronto para download!")

        with open(caminho_pdf, "rb") as f:
            st.download_button(
                label=f"⬇️ Baixar {tit_edit} (.pdf)",
                data=f,
                file_name=nome_arquivo,
                mime="application/pdf",
                type="primary",
                use_container_width=True
            )

# ------------------------------------------------------------------------------
# ABA 3: RADAR (IA OU MANUAL)
# ------------------------------------------------------------------------------
with aba_radar:
    st.subheader("🔍 Espião de Tendências & Cadastro de Oportunidades")

    modo_radar = st.radio(
        "Como deseja registrar a oportunidade de mercado?",
        ["✍️ Cadastrar Manualmente (Minha Própria Ideia)", "🤖 Minerar Buscas e Sugerir com IA (2 Créditos)"],
        horizontal=True
    )

    if modo_radar == "🤖 Minerar Buscas e Sugerir com IA (2 Créditos)":
        col_p1, col_p2, col_p3 = st.columns([2, 2, 1])
        with col_p1:
            plat_sel = st.selectbox("Plataforma:", list(PLATAFORMAS_CONFIG.keys()))
        with col_p2:
            angulo_pesq = st.selectbox("Ângulo:", ["como ganhar dinheiro com", "como acabar com", "metodo para", "como resolver"])
        with col_p3:
            st.write("")
            st.caption("Custo: 2 cr")
            btn_rastrear = st.button("📡 Rastrear", use_container_width=True)

        if btn_rastrear:
            if not debitar_creditos_cloud(email_usuario, f"Radar ({plat_sel})", 2):
                st.error("❌ Saldo insuficiente! Adquira créditos na aba de Planos.")
            else:
                with st.spinner("Minerando dados do canal..."):
                    buscas = minerar_buscas_plataforma(angulo_pesq, plat_sel)
                    if buscas:
                        st.session_state["radar_oportunidades"] = analisar_oportunidades_ia(buscas, plat_sel)
                        st.session_state["plat_ativa"] = plat_sel
                        st.rerun()

        if st.session_state.get("radar_oportunidades"):
            for idx, op in enumerate(st.session_state["radar_oportunidades"]):
                with st.container(border=True):
                    st.markdown(f"#### 🏷️ {op.get('produto', '')}")
                    st.write(f"**Público:** {op.get('publico', '')}")
                    st.write(f"**Gancho:** {op.get('angulo', '')}")
                    if st.button("✅ Usar Esta Ideia nos Geradores", key=f"sel_{idx}"):
                        st.session_state["prod_nome"] = op.get("produto", "")
                        st.session_state["pub_nome"] = op.get("publico", "")
                        st.session_state["ang_nome"] = op.get("angulo", "")
                        st.session_state["canal_sel"] = st.session_state.get("plat_ativa", "TikTok")
                        st.toast("Ideia carregada com sucesso!")

    else:
        st.info("💡 Insira diretamente a ideia validada por você para preencher automaticamente as abas de VSL e E-book:")
        col_m1, col_m2 = st.columns(2)
        with col_m1:
            nome_manual = st.text_input("Nome do Produto / Oferta:", placeholder="Ex: Protocolo Queima 21D")
            pub_manual = st.text_input("Público-Alvo e Dores:", placeholder="Ex: Mães após o parto sem tempo de ir à academia")
        with col_m2:
            ang_manual = st.text_input("Ângulo de Venda / Mecanismo:", placeholder="Ex: Treinos de 12 minutos em casa sem equipamentos")
            canal_manual = st.selectbox("Canal Principal de Tráfego:", list(PLATAFORMAS_CONFIG.keys()))

        if st.button("📌 Salvar e Carregar Ideia nos Geradores (0 Créditos)", type="primary", use_container_width=True):
            if nome_manual.strip():
                st.session_state["prod_nome"] = nome_manual.strip()
                st.session_state["pub_nome"] = pub_manual.strip()
                st.session_state["ang_nome"] = ang_manual.strip()
                st.session_state["canal_sel"] = canal_manual
                st.success("✅ Sua ideia foi definida como ativa! Ela já foi repassada para as abas '🚀 Criar VSL' e '📚 Gerar E-book PDF'.")
            else:
                st.error("Informe pelo menos o nome do produto.")

# ------------------------------------------------------------------------------
# ABA 4: PLANOS
# ------------------------------------------------------------------------------
with aba_planos:
    st.subheader("💎 Recargas Oficiais de Créditos")
    st.subheader("📦 Planos Regulares de Volume e Escala")
    c1, c2, c3 = st.columns(3)
    with c1:
        with st.container(border=True):
            st.markdown("### 🟢 Starter\n## R$ 57,00\n**(160 créditos)**")
            st.write("• 16 VSLs Curtas ou 8 Médias\n• 10 E-books diagramados\n• Suporte individual")
            st.link_button("💳 COMPRAR STARTER", url="https://pay.kiwify.com.br", use_container_width=True)
    with c2:
        with st.container(border=True):
            st.markdown("### 🟡 Pro\n## R$ 87,00\n**(300 créditos)**")
            st.write("• 30 VSLs Curtas ou 15 Médias\n• 20 E-books diagramados\n• Mineração em todos os canais")
            st.link_button("🚀 COMPRAR PRO", url="https://pay.kiwify.com.br", use_container_width=True, type="primary")
    with c3:
        with st.container(border=True):
            st.markdown("### 🔴 VIP Escala\n## R$ 117,00\n**(500 créditos)**")
            st.write("• 50 VSLs Curtas ou 25 Médias\n• 33 E-books diagramados\n• Processamento prioritário")
            st.link_button("👑 ASSINAR VIP", url="https://pay.kiwify.com.br", use_container_width=True)

# ------------------------------------------------------------------------------
# ABA 5: GALERIA
# ------------------------------------------------------------------------------
with aba_galeria:
    st.subheader("📂 Ficheiros Armazenados Localmente")
    tab_v, tab_e = st.tabs(["Vídeos (.mp4)", "E-books (.pdf)"])
    with tab_v:
        for v in sorted(os.listdir(DIR_OUTPUT), reverse=True):
            if v.endswith(".mp4"):
                st.write(f"🎬 `{v}`")
    with tab_e:
        for e in sorted(os.listdir(DIR_EBOOKS), reverse=True):
            if e.endswith(".pdf"):
                st.write(f"📚 `{e}`")

# ------------------------------------------------------------------------------
# ABA 6: PAINEL ADMIN
# ------------------------------------------------------------------------------
with aba_admin:
    st.subheader("🔒 Central de Gestão & Injeção de Créditos")
    senha_adm_digitada = st.text_input("Digite a Senha Mestra de Administrador:", type="password", key="in_senha_adm")

    if senha_adm_digitada == SENHA_MESTRE_ADMIN:
        st.success("✅ Acesso Administrativo Autorizado.")
        st.write("---")

        col_ad1, col_ad2 = st.columns([2, 1])
        with col_ad1:
            email_alvo = st.text_input("E-mail do Cliente:", placeholder="cliente@exemplo.com")
        with col_ad2:
            qtd_creditos_adm = st.number_input("Créditos a Injetar:", min_value=1, max_value=10000, value=300, step=50)

        if st.button("⚡ Injetar Créditos", type="primary"):
            if not email_alvo:
                st.error("Informe o e-mail do cliente.")
            else:
                try:
                    res_user = supabase.table("usuarios").select("*").eq("email", email_alvo.strip().lower()).execute()
                    if res_user.data:
                        val_atual = res_user.data[0].get("saldo_creditos", res_user.data[0].get("creditos", 0)) or 0
                        n_saldo = val_atual + qtd_creditos_adm
                        supabase.table("usuarios").update({"saldo_creditos": n_saldo, "creditos": n_saldo}).eq("email", email_alvo.strip().lower()).execute()
                    else:
                        supabase.table("usuarios").insert([{
                            "email": email_alvo.strip().lower(),
                            "saldo_creditos": qtd_creditos_adm,
                            "creditos": qtd_creditos_adm,
                            "total_compras": 1
                        }]).execute()
                        n_saldo = qtd_creditos_adm
                    st.success(f"✅ Injetados {qtd_creditos_adm} créditos para {email_alvo}. Novo saldo: {n_saldo}.")
                    st.rerun()
                except Exception as err:
                    st.error(f"Erro ao injetar créditos: {err}")
    elif senha_adm_digitada:
        st.error("Senha mestra incorreta.")

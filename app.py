import os
import re
import json
import time
import random
import hashlib
import subprocess
import urllib.request
import urllib.parse
from datetime import datetime
import requests
from PIL import Image

# ==============================================================================
# LOCALIZADOR DO EXECUTÁVEL FFMPEG
# ==============================================================================
try:
    import imageio_ffmpeg
    FFMPEG_BIN = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    FFMPEG_BIN = "ffmpeg"

if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.Resampling.LANCZOS

import streamlit as st
import streamlit.components.v1 as components
from openai import OpenAI
from fpdf import FPDF
from supabase import create_client, Client

# ==============================================================================
# LEITURA DE SEGREDOS E FILTRO RIGOROSO DO SUPABASE
# ==============================================================================
def limpar_url_supabase(url_bruta: str) -> str:
    """Extrai estritamente https://dominio.supabase.co descartando barras e /rest/v1/."""
    u = str(url_bruta or "").strip().strip('"').strip("'")
    if not u.startswith("http://") and not u.startswith("https://"):
        u = f"https://{u}"
    parsed = urllib.parse.urlparse(u)
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")

OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY", os.getenv("OPENAI_API_KEY", "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")).strip()
PEXELS_API_KEY = st.secrets.get("PEXELS_API_KEY", os.getenv("PEXELS_API_KEY", "Jodt5ylpnldkeKbU96DSj2aMYapUDlqqRUvBAKcmtmzaw3wof22fVDnn")).strip()

_url_lida = st.secrets.get("SUPABASE_URL", os.getenv("SUPABASE_URL", "https://vzelyaubnynefsfumhtz.supabase.co"))
SUPABASE_URL = limpar_url_supabase(_url_lida)
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY", os.getenv("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZ6ZWx5YXVibnluZWZzZnVtaHR6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTA0MzQ4NDMsImV4cCI6MjEwNjAxMDg0M30.D1wBNPKGJ0scNWNtsO47FZrRn82SAiKAnKLAJZ_gXu4")).strip()

SENHA_MESTRE_ADMIN = st.secrets.get("ADMIN_KEY", "admin2026vsl")

BASE_DIR    = r"C:\gerador_vsl"
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
        st.error("Credenciais do Supabase ausentes.")
        st.stop()
    return create_client(url, key)

supabase = conectar_supabase(SUPABASE_URL, SUPABASE_KEY)

# ==============================================================================
# SEGURANÇA CRIPTOGRÁFICA & GESTÃO CLOUD
# ==============================================================================
SALT_SECRETO = "vsl_engine_crypto_salt_2026"

def gerar_hash_senha(senha: str) -> str:
    dado = f"{senha}_{SALT_SECRETO}".encode("utf-8")
    return hashlib.sha256(dado).hexdigest()

def autenticar_usuario_cloud(email: str, senha: str) -> dict:
    email_limpo = email.strip().lower()
    hash_s = gerar_hash_senha(senha)
    try:
        rpc_res = supabase.rpc("autenticar_ou_registrar_usuario", {
            "p_email": email_limpo,
            "p_senha_hash": hash_s
        }).execute()
        return rpc_res.data
    except Exception as e:
        return {"sucesso": False, "mensagem": f"Erro de conexão com servidor: {e}"}

def obter_dados_usuario(email: str) -> dict:
    try:
        res = supabase.table("usuarios").select("saldo_creditos, total_compras").eq("email", email.strip().lower()).execute()
        if res.data and len(res.data) > 0:
            return {
                "saldo": res.data[0].get("saldo_creditos", 0),
                "compras": res.data[0].get("total_compras", 0)
            }
    except Exception:
        pass
    return {"saldo": 0, "compras": 0}

def debitar_creditos_cloud(email: str, operacao: str, custo: int) -> bool:
    try:
        rpc_res = supabase.rpc("debitar_creditos_atomico", {
            "p_email": email.strip().lower(),
            "p_operacao": operacao,
            "p_custo": custo
        }).execute()
        return bool(rpc_res.data)
    except Exception:
        return False

def registrar_aceite_termos(email: str):
    try:
        supabase.table("historico").insert({
            "email": email.strip().lower(),
            "operacao": "Termos de Uso e Isenção de Responsabilidade Aceitos Formalmente",
            "creditos": 0
        }).execute()
    except Exception:
        pass

def processar_recarga_com_dobro_cloud(email: str, creditos_base: int, origem: str) -> dict:
    """Executa a função SQL que detecta a 1ª compra e dobra automaticamente."""
    try:
        rpc_res = supabase.rpc("processar_recarga_automatica", {
            "p_email": email.strip().lower(),
            "p_creditos_comprados": creditos_base,
            "p_origem": origem
        }).execute()
        return rpc_res.data
    except Exception as e:
        return {"sucesso": False, "mensagem": f"Erro ao processar recarga: {e}"}

def tratar_para_texto(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, dict):
        return "\n".join([f"{k.capitalize()}: {tratar_para_texto(v)}" for k, v in valor.items()])
    if isinstance(valor, list):
        return "\n".join([f"- {tratar_para_texto(item)}" for item in valor])
    return str(valor).strip()

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
    Atue como estrategista especializado para: {plataforma}.
    Perfil do canal: {cfg['perfil']}.
    Buscas reais mineradas:
    {lista_formatada}

    Retorne estritamente um JSON com a chave 'oportunidades', contendo 4 objetos com as chaves:
    - 'produto': Nome curto e comercial da oferta
    - 'publico': Quem compra e a dor latente dessa rede
    - 'angulo': Gancho principal de conversão nativo
    """

    resposta = client.chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7
    )
    try:
        dados = json.loads(resposta.choices[0].message.content)
        return [
            {
                "produto": tratar_para_texto(item.get("produto")),
                "publico": tratar_para_texto(item.get("publico")),
                "angulo": tratar_para_texto(item.get("angulo"))
            }
            for item in dados.get("oportunidades", [])
        ]
    except Exception:
        return []

def otimizar_perguntas_por_nicho_ia(nicho_manual: str) -> dict:
    client = OpenAI(api_key=OPENAI_API_KEY)
    prompt = f"""
    Você é o estrategista-chefe de uma produtora digital de alta conversão.
    O nicho definido é: "{nicho_manual}".

    Crie o preenchimento estratégico completo:
    1. Nome do Produto / Protocolo: Nome de impacto com subtítulo persuasivo.
    2. Raio-X do Público e Dor Oculta: Perfil exato do comprador e dor latente.
    3. Promessa Irrecusável e Mecanismo Único: Promessa quantificável com prazo e mecanismo.

    Retorne estritamente um JSON com as chaves 'produto', 'publico' e 'angulo'.
    """
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7
    )
    try:
        dados = json.loads(resp.choices[0].message.content)
        return {
            "produto": tratar_para_texto(dados.get("produto", "")),
            "publico": tratar_para_texto(dados.get("publico", "")),
            "angulo": tratar_para_texto(dados.get("angulo", ""))
        }
    except Exception:
        return {}

def obter_roteiro_ia_por_ticket(produto: str, publico: str, angulo: str, faixa_preco: str, plataforma: str) -> list[str]:
    client = OpenAI(api_key=OPENAI_API_KEY)

    if "Baixo" in faixa_preco:
        qtd_frases = 3
        diretrizes = f"""
        - Canal Alvo: {plataforma} | TICKET BAIXO (R$ 27 a R$ 97).
        - Estrutura: Exatamente 3 frases curtas e diretas de interrupção (20 a 30s).
        - Frase 1: Gancho visceral nativo do {plataforma}.
        - Frase 2: Apresentação da solução simples e mecanismo único.
        - Frase 3: CTA imediato para o botão de compra.
        """
    elif "Médio" in faixa_preco:
        qtd_frases = 5
        diretrizes = f"""
        - Canal Alvo: {plataforma} | TICKET MÉDIO (R$ 197 a R$ 497).
        - Estrutura: Exatamente 5 frases progressivas (50 a 70s).
        - Frase 1: Identificação com a dor do comprador.
        - Frase 2: Revelação da causa oculta do problema.
        - Frase 3: Apresentação do Mecanismo Único.
        - Frase 4: Quebra de objeção chave.
        - Frase 5: CTA forte com valor promocional.
        """
    else:
        qtd_frases = 7
        diretrizes = f"""
        - Canal Alvo: {plataforma} | ALTO TICKET (R$ 997+ / Mentoria).
        - Estrutura: Exatamente 7 frases de autoridade e qualificação (90 a 120s).
        - Frase 1: Filtro exclusivo de público.
        - Frase 2: Custo financeiro de continuar insistindo no erro.
        - Frase 3: A grande mentira do mercado desmascarada.
        - Frase 4: O Mecanismo Único estruturado.
        - Frase 5: Prova de previsibilidade e transformação.
        - Frase 6: Filtro de compromisso.
        - Frase 7: Chamada de ação para aplicação/vagas.
        """

    prompt = f"""
    Crie o roteiro de vendas persuasivo para: '{produto}'.
    Público: '{publico}'. Ângulo: '{angulo}'.
    {diretrizes}
    Retorne APENAS as {qtd_frases} frases, exatamente uma por linha, sem títulos, números ou aspas.
    """

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    return [l.strip() for l in resp.choices[0].message.content.strip().split("\n") if l.strip()]

def gerar_conteudo_ebook_ia(nicho_produto: str, publico: str, promessa_angulo: str) -> dict:
    """Gera a estrutura completa de um infoproduto via GPT-4o-mini."""
    client = OpenAI(api_key=OPENAI_API_KEY)
    prompt = f"""
    Você é um autor best-seller e estrategista de infoprodutos digitais de alta conversão.
    Escreva um E-book / Guia Prático completo, aprofundado e altamente acionável.

    DADOS DO PRODUTO:
    - Nicho / Título Base: {nicho_produto}
    - Público-Alvo e Dores Reais: {publico}
    - Promessa Central e Mecanismo: {promessa_angulo}

    Retorne ESTRITAMENTE um JSON estruturado com as seguintes chaves:
    {{
      "titulo": "Título Comercial Magnético",
      "subtitulo": "Subtítulo Persuasivo e Específico",
      "introducao": "Texto completo da introdução contextualizando o problema, quebrando crenças limitantes e estabelecendo a lógica da solução (mínimo 150 palavras).",
      "capitulos": [
        {{
          "numero": 1,
          "titulo": "Nome do Capítulo 1",
          "conteudo": "Conteúdo prático ensinando os fundamentos e preparando o terreno para a aplicação (mínimo 180 palavras)."
        }},
        {{
          "numero": 2,
          "titulo": "Nome do Capítulo 2",
          "conteudo": "Apresentação e detalhamento técnico do Mecanismo Único de resolução da dor (mínimo 180 palavras)."
        }},
        {{
          "numero": 3,
          "titulo": "Nome do Capítulo 3",
          "conteudo": "Plano de ação passo a passo para execução imediata nas primeiras 24 a 48 horas (mínimo 180 palavras)."
        }},
        {{
          "numero": 4,
          "titulo": "Nome do Capítulo 4",
          "conteudo": "Protocolo de sustentação, erros comuns que travam os resultados e próximos passos para escala (mínimo 180 palavras)."
        }}
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
    instrucao_tipo = f'O ator/pessoa DEVE ter o seguinte perfil físico: "{perfil_personagem}".' if perfil_personagem and "Decide" not in perfil_personagem else ""
    prompt = f"""
    Você é diretor de fotografia de vídeos publicitários.
    Frase narrada: "{frase}"
    {instrucao_tipo}

    Gere o melhor termo de busca visual em inglês (2 a 4 palavras) para biblioteca Pexels.
    Retorne APENAS o termo em inglês, sem pontuação ou aspas.
    """
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        return resp.choices[0].message.content.strip().replace('"', '')
    except Exception:
        return "business professional lifestyle"

def baixar_video_pexels(termo: str, pexels_key: str, vertical: bool, indice: int) -> str:
    caminho_local = os.path.join(DIR_BROLL, f"broll_{indice}.mp4")
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
                if otimizados:
                    otimizados.sort(key=lambda x: x.get("width", 0), reverse=True)
                    link = otimizados[0]["link"]
                else:
                    arquivos.sort(key=lambda x: x.get("width", 0))
                    link = arquivos[0]["link"]

                conteudo = requests.get(link, timeout=20)
                with open(caminho_local, "wb") as f:
                    f.write(conteudo.content)
                return caminho_local
    except Exception:
        pass
    return None

def obter_duracao_audio_ffmpeg(caminho_audio: str) -> float:
    try:
        cmd = [FFMPEG_BIN, "-i", caminho_audio, "-f", "null", "-"]
        proc = subprocess.run(cmd, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True)
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
# MOTOR FFMPEG
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

    for i, frase in enumerate(frases):
        idx = i + 1
        c_audio = os.path.join(DIR_AUDIOS, f"parte_{idx}.mp3")
        c_cena = os.path.join(DIR_TEMP, f"cena_{idx}.mp4")

        sintetizar_voz_segura(frase, c_audio, voz)
        duracao = obter_duracao_audio_ffmpeg(c_audio)

        video_bg = None
        if pexels_key:
            termo = extrair_termo_broll_ia(frase, perfil_personagem)
            video_bg = baixar_video_pexels(termo, pexels_key, vertical, idx)

        audio_p = c_audio.replace("\\", "/")
        cena_p = c_cena.replace("\\", "/")

        if video_bg and os.path.exists(video_bg):
            bg_p = video_bg.replace("\\", "/")
            vf = f"scale={largura}:{altura}:force_original_aspect_ratio=increase,crop={largura}:{altura},setsar=1,fps=24,setpts=PTS-STARTPTS"
            cmd = [
                FFMPEG_BIN, "-y", "-stream_loop", "-1", "-i", bg_p, "-i", audio_p,
                "-vf", vf, "-map", "0:v", "-map", "1:a",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-r", "24", "-g", "48",
                "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-t", str(duracao), cena_p
            ]
        else:
            cmd = [
                FFMPEG_BIN, "-y", "-f", "lavfi", "-i", f"color=c=0x0F0F14:s={largura}x{altura}:d={duracao}:r=24",
                "-i", audio_p, "-map", "0:v", "-map", "1:a",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-r", "24", "-g", "48",
                "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-t", str(duracao), cena_p
            ]

        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        cenas.append(c_cena)
        if progress_bar:
            progress_bar.progress(idx / (total + 2))

    inputs, fc_map = [], ""
    for idx_c, c in enumerate(cenas):
        inputs.extend(["-i", c.replace("\\", "/")])
        fc_map += f"[{idx_c}:v][{idx_c}:a]"
    
    fc = f"{fc_map}concat=n={total}:v=1:a=1[vcat][acat]"
    v_concat = os.path.join(DIR_TEMP, "concatenado.mp4")
    cmd_concat = [
        FFMPEG_BIN, "-y"
    ] + inputs + [
        "-filter_complex", fc, "-map", "[vcat]", "-map", "[acat]",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-r", "24", "-g", "48",
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100", v_concat.replace("\\", "/")
    ]
    subprocess.run(cmd_concat, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    caminho_saida = os.path.join(DIR_OUTPUT, f"vsl_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4")
    tem_musica = musica_fundo_path and os.path.exists(musica_fundo_path)
    tem_logo = logo_path and os.path.exists(logo_path)

    if not tem_musica and not tem_logo:
        cmd_f = [FFMPEG_BIN, "-y", "-i", v_concat.replace("\\", "/"), "-c", "copy", "-movflags", "+faststart", caminho_saida.replace("\\", "/")]
    else:
        in_list = ["-i", v_concat.replace("\\", "/")]
        fv, fa = [], []
        iv, ia = "0:v", "0:a"
        nxt = 1
        if tem_logo:
            in_list.extend(["-i", logo_path.replace("\\", "/")])
            fv.append(f"[{nxt}:v]scale={int(largura * 0.16)}:-1[lg];[{iv}][lg]overlay=W-w-35:35[vout]")
            iv = "vout"
            nxt += 1
        if tem_musica:
            in_list.extend(["-stream_loop", "-1", "-i", musica_fundo_path.replace("\\", "/")])
            fa.append(f"[{nxt}:a]volume={volume_musica}[bgm];[{ia}][bgm]amix=inputs=2:duration=first[aout]")
            ia = "aout"

        cmd_f = [FFMPEG_BIN, "-y"] + in_list
        parts = fv + fa
        if parts:
            cmd_f.extend(["-filter_complex", ";".join(parts), "-map", f"[{iv}]", "-map", f"[{ia}]"])
        else:
            cmd_f.extend(["-map", "0:v", "-map", "0:a"])

        cmd_f.extend(["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-shortest", "-movflags", "+faststart", caminho_saida.replace("\\", "/")])

    subprocess.run(cmd_f, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
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
    
    # Capa
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

    # Introdução
    pdf.add_page()
    pdf.set_text_color(20, 20, 20)
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 12, "1. Introdução e Visão Geral", ln=True)
    pdf.ln(4)
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(0, 7, sanitizar_pdf(dados.get("introducao", "")))

    # Capítulos gerados pela IA
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
# INTERFACE PRINCIPAL & GATING DE LOGIN
# ==============================================================================
st.set_page_config(page_title="Central de Criativos & VSL Cloud", page_icon="⚡", layout="wide")

if "usuario_ativo" not in st.session_state:
    st.session_state["usuario_ativo"] = None

# TELA DE ENTRADA / LOGIN DO CLIENTE
if not st.session_state["usuario_ativo"]:
    st.title("⚡ Central de Produção de VSLs & Infoprodutos")
    st.caption("Acesso restrito e criptografado. Seus projetos, roteiros e créditos são protegidos na nuvem.")

    col_l1, col_l2, col_l3 = st.columns([1, 2, 1])
    with col_l2:
        with st.container(border=True):
            st.markdown("### 🔐 Acesso Seguro do Comprador")
            st.info("⚠️ **Primeiro Acesso:** Crie uma senha de acesso vinculada ao seu e-mail. Esta senha será exigida em todos os seus logins futuros para proteger seus créditos.")

            tab_log, tab_reg = st.tabs(["🔑 Já Possuo Conta / Login", "✨ Primeiro Acesso / Criar Senha"])

            with tab_log:
                email_login = st.text_input("Seu E-mail Cadastrado:", placeholder="seuemail@exemplo.com", key="in_email_login")
                senha_login = st.text_input("Sua Senha:", type="password", key="in_senha_login")
                btn_entrar_login = st.button("🚀 Entrar no Sistema", type="primary", use_container_width=True)

                if btn_entrar_login:
                    el = email_login.strip().lower()
                    if not el or not senha_login:
                        st.error("Preencha o e-mail e a senha.")
                    else:
                        resp_auth = autenticar_usuario_cloud(el, senha_login)
                        if resp_auth.get("sucesso"):
                            st.session_state["usuario_ativo"] = el
                            st.session_state["saldo_ativo"] = resp_auth.get("saldo", 0)
                            st.success(resp_auth.get("mensagem"))
                            st.rerun()
                        else:
                            st.error(resp_auth.get("mensagem", "Erro de autenticação."))

            with tab_reg:
                email_reg1 = st.text_input("1. Seu E-mail da Compra:", placeholder="seuemail@exemplo.com", key="in_email_reg1")
                email_reg2 = st.text_input("2. Confirme o E-mail:", placeholder="seuemail@exemplo.com", key="in_email_reg2")
                senha_reg1 = st.text_input("Crie uma Senha Segura (mínimo 6 dígitos):", type="password", key="in_senha_reg1")
                senha_reg2 = st.text_input("Confirme sua Senha:", type="password", key="in_senha_reg2")

                with st.expander("⚖️ Ler Termos de Uso, Isenção de Responsabilidade e Conformidade Legal", expanded=False):
                    st.markdown("""
                    **TERMOS DE USO E DECLARAÇÃO DE ISENÇÃO DE RESPONSABILIDADE**
                    
                    Ao utilizar esta plataforma, o USUÁRIO concorda expressa, irrevogável e integralmente com as seguintes condições:
                    
                    1. **Natureza da Ferramenta e Limitação de Resultados:** Esta plataforma é uma ferramenta tecnológica de produtividade e auxílio operacional baseada em Inteligência Artificial. **Não há garantia implícita ou explícita de faturamento, vendas, lucros, conversões ou sucesso comercial**. O desempenho de qualquer campanha publicitária, vídeo ou infoproduto depende exclusivamente das estratégias, orçamentos e do modelo de negócios do próprio USUÁRIO.
                    
                    2. **Responsabilidade Exclusiva pelo Conteúdo:** O USUÁRIO declara ser o único e exclusivo responsável pelo teor de todos os textos, áudios, roteiros, e-books e vídeos gerados, aprovados ou veiculados através do sistema. É de total encargo do USUÁRIO garantir a veracidade de alegações, cumprimento de normas sanitárias (ex: ANVISA), diretrizes de órgãos de defesa do consumidor (PROCON), autorregulamentação publicitária (CONAR) e políticas de anúncios de plataformas terceiras (Meta Ads, Google Ads, TikTok Ads, YouTube).
                    
                    3. **Isenção e Indenidade da Plataforma:** A plataforma, seus desenvolvedores, proprietários e operadores técnicos **isentam-se de toda e qualquer responsabilidade civil, criminal, administrativa ou consumerista** decorrente de:
                       * Bloqueios (*bans*), restrições ou desativações de contas em redes sociais ou gerenciadores de anúncios.
                       * Contestação, litígio ou processo movido por consumidores finais ou terceiros lesados por promessas veiculadas pelo USUÁRIO.
                       * Violação de marcas registradas, direitos autorais ou propriedade intelectual introduzidos pelo USUÁRIO.
                    
                    4. **Proibição de Ilícitos:** Fica terminantemente vedada a utilização desta tecnologia para a criação de materiais fraudulentos, golpes financeiros, pornografia, desinformação, produtos ilegais ou qualquer prática vedada pela legislação vigente.
                    """)

                check_termos = st.checkbox(
                    "Declaro que LI, COMPREENDI e CONCORDO com os Termos de Uso e com a Isenção Total de Responsabilidade da plataforma.",
                    key="check_termos_blindagem"
                )

                btn_criar_conta = st.button("🛡️ Criar Acesso Blindado", type="primary", use_container_width=True)

                if btn_criar_conta:
                    er1 = email_reg1.strip().lower()
                    er2 = email_reg2.strip().lower()

                    if not er1 or not er2 or not senha_reg1 or not senha_reg2:
                        st.error("Preencha todos os campos do formulário.")
                    elif er1 != er2:
                        st.error("Os e-mails informados não coincidem.")
                    elif senha_reg1 != senha_reg2:
                        st.error("As senhas informadas não coincidem.")
                    elif len(senha_reg1) < 6:
                        st.error("A senha deve possuir pelo menos 6 caracteres.")
                    elif not check_termos:
                        st.error("É obrigatório concordar com os Termos de Uso e a Isenção de Responsabilidade.")
                    else:
                        resp_auth = autenticar_usuario_cloud(er1, senha_reg1)
                        if resp_auth.get("sucesso"):
                            registrar_aceite_termos(er1)
                            st.session_state["usuario_ativo"] = er1
                            st.session_state["saldo_ativo"] = resp_auth.get("saldo", 0)
                            st.success(resp_auth.get("mensagem"))
                            st.rerun()
                        else:
                            st.error(resp_auth.get("mensagem", "Falha ao registrar."))

    st.stop()

# USUÁRIO AUTENTICADO
usuario_email = st.session_state["usuario_ativo"]
dados_user = obter_dados_usuario(usuario_email)
saldo_usuario = dados_user["saldo"]
total_compras_usuario = dados_user["compras"]

# BARRA LATERAL
with st.sidebar:
    st.header("👤 Sessão Segura")
    st.code(usuario_email)
    st.metric(label="Saldo Atual:", value=f"{saldo_usuario} Créditos")

    if total_compras_usuario == 0:
        st.success("🎁 **BÔNUS DISPONÍVEL!**\nSua próxima recarga será DOBRADA automaticamente pelo sistema.")
    else:
        st.caption(f"Status: Cliente Ativo ({total_compras_usuario} recargas realizadas)")

    if saldo_usuario == 0:
        st.warning("⚠️ Saldo zerado. Realize sua recarga na aba 'Planos & Recargas' para produzir seus criativos.")

    if st.button("🚪 Encerrar Sessão", use_container_width=True):
        st.session_state["usuario_ativo"] = None
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

# ABAS PRINCIPAIS
aba_planos, aba_radar, aba_ebook, aba_vsl, aba_galeria, aba_admin = st.tabs([
    "💳 Planos & Recargas",
    "📡 Radar de Mercado",
    "📚 Gerar E-book PDF via IA",
    "🚀 Criar VSL",
    "📂 Galeria",
    "🔒 Painel Admin (Restrito)"
])

# ABA 1: PLANOS COM DETECÇÃO AUTOMÁTICA DE DOBRO
with aba_planos:
    st.subheader("💎 Recargas Oficiais de Créditos")

    if total_compras_usuario == 0:
        with st.container(border=True):
            col_b1, col_b2 = st.columns([3, 1])
            with col_b1:
                st.markdown("### 🔥 OFERTA ESPECIAL DE BOAS-VINDAS: COMPRE 50 E LEVE 100")
                st.write("Identificamos que você ainda não realizou compras. O sistema está configurado para **DOBRAR os créditos automaticamente** na sua primeira recarga (Compre 50 e receba 100 créditos no total).")
            with col_b2:
                st.markdown("## **R$ 27,00**")
                st.caption("Pagamento Único via Kiwify")
                st.link_button(
                    "💳 COMPRAR 100 CRÉDITOS (R$ 27)",
                    url="https://pay.kiwify.com.br",
                    type="primary",
                    use_container_width=True
                )
    else:
        st.info("ℹ️ Você já aproveitou o bônus de primeira compra. Selecione abaixo seu pacote regular de recarga.")

    st.write("")
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

# ABA 2: RADAR
with aba_radar:
    st.subheader("🔍 Espião de Tendências")
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
        if not debitar_creditos_cloud(usuario_email, f"Radar ({plat_sel})", 2):
            st.error("❌ Saldo insuficiente! Adquira créditos na primeira aba.")
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
                st.markdown(f"#### 🏷️ {op['produto']}")
                st.write(f"**Público:** {op['publico']}")
                st.write(f"**Gancho:** {op['angulo']}")
                if st.button("✅ Usar Esta Ideia", key=f"sel_{idx}"):
                    st.session_state["prod_nome"] = op["produto"]
                    st.session_state["pub_nome"] = op["publico"]
                    st.session_state["ang_nome"] = op["angulo"]
                    st.session_state["canal_sel"] = st.session_state.get("plat_ativa", "TikTok")
                    st.toast("Ideia carregada para produção!")

# ABA 3: E-BOOK GERADO 100% POR IA COM RATE-LIMITING
with aba_ebook:
    st.subheader("📚 Criação do Infoproduto em PDF via IA")
    st.caption("O modelo GPT-4o-mini estrutura os títulos, redige a introdução e compõe 4 módulos aprofundados.")

    nicho_eb = st.text_input("Nicho ou Nome do Produto:", value=st.session_state.get("prod_nome", "Manual da Renda Extra Digital"))
    col_eb1, col_eb2 = st.columns(2)
    with col_eb1:
        eb_pub = st.text_area("Público e Dores:", value=st.session_state.get("pub_nome", "Pessoas comuns sem tempo que buscam validação de renda online."))
    with col_eb2:
        eb_ang = st.text_area("Promessa e Solução:", value=st.session_state.get("ang_nome", "Método passo a passo baseado em automações simples sem aparecer."))

    if st.button("⚡ Gerar E-book Completo por IA (15 Créditos)", type="primary", use_container_width=True):
        agora = time.time()
        if agora - st.session_state.get("_ultimo_click_eb", 0) < 12:
            st.warning("⏳ Aguarde alguns segundos entre cada compilação para proteção do servidor.")
            st.stop()
        st.session_state["_ultimo_click_eb"] = agora

        if not debitar_creditos_cloud(usuario_email, "Geração de E-book IA", 15):
            st.error("❌ Saldo insuficiente! Você precisa de 15 créditos.")
        else:
            with st.spinner("🤖 A IA está redigindo o conteúdo completo e formatando o PDF..."):
                try:
                    dados_eb = gerar_conteudo_ebook_ia(nicho_eb, eb_pub, eb_ang)
                    nome_arquivo = f"ebook_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
                    caminho_pdf = os.path.join(DIR_EBOOKS, nome_arquivo)
                    compilar_pdf_ebook(dados_eb, caminho_pdf)
                    
                    disparar_comemoracao()
                    st.success("✅ Livro digital redigido e formatado com sucesso!")
                    
                    with open(caminho_pdf, "rb") as f:
                        st.download_button(
                            label=f"⬇️ Baixar {dados_eb.get('titulo', 'E-book')} (.pdf)",
                            data=f,
                            file_name=nome_arquivo,
                            mime="application/pdf",
                            type="primary",
                            use_container_width=True
                        )
                except Exception as erro:
                    st.error(f"Erro na redação ou compilação do infoproduto: {erro}")

# ABA 4: VSL COM PROTEÇÃO CONTRA CLIQUE DUPLO
with aba_vsl:
    st.subheader("🚀 Gerador de Roteiro e Vídeo Limpo")
    prod_vsl = st.text_input("Produto:", value=st.session_state.get("prod_nome", "Método Rápido"))
    pub_vsl = st.text_input("Público:", value=st.session_state.get("pub_nome", "Pessoas buscando solução prática."))
    ang_vsl = st.text_input("Gancho:", value=st.session_state.get("ang_nome", "Mecanismo definitivo de escala."))
    faixa_preco = st.radio("Ticket:", ["🟢 Baixo (3 frases - 10 Créditos)", "🟡 Médio (5 frases - 20 Créditos)", "🔴 Alto (7 frases - 30 Créditos)"])

    if st.button("⚡ Criar Roteiro Estruturado", type="primary", use_container_width=True):
        st.session_state["roteiro"] = obter_roteiro_ia_por_ticket(prod_vsl, pub_vsl, ang_vsl, faixa_preco, st.session_state.get("canal_sel", "TikTok"))

    if st.session_state.get("roteiro"):
        st.divider()
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

            if not debitar_creditos_cloud(usuario_email, f"Renderização ({len(cenas_txt)} Cenas)", custo):
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

# ABA 5: GALERIA
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

# ABA 6: PAINEL ADMINISTRATIVO (MOTOR DE DOBRO AUTOMÁTICO INTEGRADO)
with aba_admin:
    st.subheader("🔒 Central de Gestão & Injeção Inteligente de Créditos")
    st.caption("Uso restrito do proprietário. O sistema calcula automaticamente se a recarga deve ser dobrada.")

    senha_adm_digitada = st.text_input("Digite a Senha Mestra de Administrador:", type="password", key="in_senha_adm")

    if senha_adm_digitada == SENHA_MESTRE_ADMIN:
        st.success("✅ Acesso Administrativo Autorizado.")
        st.write("---")

        col_ad1, col_ad2, col_ad3 = st.columns([2, 1, 2])
        with col_ad1:
            email_alvo = st.text_input("E-mail do Cliente:", placeholder="cliente@exemplo.com")
        with col_ad2:
            qtd_creditos_adm = st.number_input("Créditos Comprados:", min_value=1, max_value=10000, value=50, step=10)
        with col_ad3:
            origem_recarga = st.selectbox("Origem do Pagamento:", ["Kiwify (Venda Aprovada)", "PIX Manual", "Hotmart", "Suporte / Bonificação"])

        if st.button("⚡ Processar Recarga com Dobro Automático", type="primary"):
            if not email_alvo:
                st.error("Informe o e-mail do cliente.")
            else:
                resp_rec = processar_recarga_com_dobro_cloud(email_alvo, qtd_creditos_adm, origem_recarga)
                if resp_rec.get("sucesso"):
                    if resp_rec.get("primeira_compra"):
                        st.balloons()
                        st.success(f"🎉 **PRIMEIRA COMPRA DETECTADA!** O cliente comprou {qtd_creditos_adm} e recebeu o dobro: **{resp_rec.get('creditos_entregues')} créditos**. Novo saldo: {resp_rec.get('novo_saldo')}.")
                    else:
                        st.info(f"✅ Recarga convencional processada. Foram adicionados **{resp_rec.get('creditos_entregues')} créditos**. Novo saldo: {resp_rec.get('novo_saldo')}.")
                    st.rerun()
                else:
                    st.error(resp_rec.get("mensagem", "Falha ao processar."))
    elif senha_adm_digitada:
        st.error("Senha mestra incorreta.")
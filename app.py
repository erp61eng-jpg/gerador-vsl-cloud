import os
import re
import json
import time
import subprocess
import requests
from datetime import datetime
from typing import List, Dict, Tuple, Optional

import streamlit as st
from openai import OpenAI
from supabase import create_client, Client

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

# Tentativa de importação compatível do SDK do Google Gemini
try:
    from google import genai
    HAS_GENAI_NEW = True
except ImportError:
    HAS_GENAI_NEW = False
    try:
        import google.generativeai as legacy_genai
        HAS_GENAI_LEGACY = True
    except ImportError:
        HAS_GENAI_LEGACY = False

# ==============================================================================
# 1. CONFIGURAÇÕES INICIAIS, DIRETÓRIOS & CONSTANTES
# ==============================================================================
st.set_page_config(
    page_title="Central VSL & DubfyAi Global",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

DIR_BASE = os.path.dirname(os.path.abspath(__file__))
DIR_VSL = os.path.join(DIR_BASE, "temp_vsl")
DIR_EBOOKS = os.path.join(DIR_BASE, "temp_ebooks")
DIR_AUDIOS = os.path.join(DIR_BASE, "temp_audios")
DIR_PEXELS = os.path.join(DIR_BASE, "temp_pexels")
DIR_MUSICAS = os.path.join(DIR_BASE, "temp_musicas")
DIR_LOGOS = os.path.join(DIR_BASE, "temp_logos")

for d in [DIR_VSL, DIR_EBOOKS, DIR_AUDIOS, DIR_PEXELS, DIR_MUSICAS, DIR_LOGOS]:
    os.makedirs(d, exist_ok=True)

def obter_credencial(chave: str, padrao: str = "") -> str:
    try:
        return st.secrets.get(chave, os.getenv(chave, padrao))
    except Exception:
        return os.getenv(chave, padrao)

SUPABASE_URL = obter_credencial("SUPABASE_URL")
SUPABASE_KEY = obter_credencial("SUPABASE_KEY")
OPENAI_API_KEY = obter_credencial("OPENAI_API_KEY")
GEMINI_API_KEY = obter_credencial("GEMINI_API_KEY")
PEXELS_API_KEY = obter_credencial("PEXELS_API_KEY")

# Inicialização do Supabase
supabase_client: Optional[Client] = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        st.sidebar.error(f"Erro ao ligar ao Supabase: {e}")

# 36 Idiomas Oficiais do Sistema
IDIOMAS_SISTEMA_36 = {
    "🇺🇸 Inglês (EUA)": "English (US)",
    "🇬🇧 Inglês (Reino Unido)": "English (UK)",
    "🇪🇸 Espanhol": "Español",
    "🇫🇷 Francês": "Français",
    "🇩🇪 Alemão": "Deutsch",
    "🇮🇹 Italiano": "Italiano",
    "🇵🇹 Português (Portugal)": "Português (PT)",
    "🇳🇱 Holandês": "Nederlands",
    "🇵🇱 Polaco": "Polski",
    "🇷🇺 Russo": "Русский",
    "🇨🇳 Mandarim (Simplificado)": "Chinese (Simplified)",
    "🇯🇵 Japonês": "Japanese",
    "🇰🇷 Coreano": "Korean",
    "🇸🇦 Árabe": "Arabic",
    "🇮🇳 Hindi": "Hindi",
    "🇹🇷 Turco": "Türkçe",
    "🇸🇪 Sueco": "Svenska",
    "🇳🇴 Norueguês": "Norsk",
    "🇩🇰 Dinamarquês": "Dansk",
    "🇫🇮 Finlandês": "Suomi",
    "🇬🇷 Grego": "Greek",
    "🇨🇿 Checo": "Czech",
    "🇷🇴 Romeno": "Română",
    "🇭🇺 Húngaro": "Magyar",
    "🇮🇱 Hebraico": "Hebrew",
    "🇮🇩 Indonésio": "Bahasa Indonesia",
    "🇻🇳 Vietnamita": "Tiếng Việt",
    "🇹🇭 Tailandês": "Thai",
    "🇺🇦 Ucraniano": "Ukrainian",
    "🇲🇾 Malaio": "Bahasa Melayu",
    "🇵🇭 Filipino (Tagalog)": "Tagalog",
    "🇧🇩 Bengali": "Bengali",
    "🇭🇷 Croata": "Hrvatski",
    "🇸🇰 Eslovaco": "Slovenčina",
    "🇧🇬 Búlgaro": "Bulgarian",
    "🇿🇦 Africâner": "Afrikaans"
}

# ==============================================================================
# 2. MOTOR DE CRÉDITOS & SUPABASE
# ==============================================================================
def obter_dados_usuario(email: str) -> dict:
    if not supabase_client or not email:
        return {"saldo": 0, "total_compras": 0}
    try:
        res = supabase_client.from_("usuarios").select("*").eq("email", email.lower().strip()).execute()
        if res.data and len(res.data) > 0:
            user = res.data[0]
            saldo = user.get("saldo_creditos", user.get("creditos", 0))
            return {"saldo": saldo, "total_compras": user.get("total_compras", 0)}
        else:
            supabase_client.from_("usuarios").insert([{"email": email.lower().strip(), "saldo_creditos": 0, "creditos": 0, "total_compras": 0}]).execute()
            return {"saldo": 0, "total_compras": 0}
    except Exception:
        return {"saldo": 0, "total_compras": 0}

def debitar_creditos_cloud(email: str, operacao: str, quantidade: int) -> bool:
    if not supabase_client or not email:
        return True
    try:
        dados = obter_dados_usuario(email)
        saldo_atual = dados["saldo"]
        if saldo_atual < quantidade:
            return False
        novo_saldo = saldo_atual - quantidade
        supabase_client.from_("usuarios").update({"saldo_creditos": novo_saldo, "creditos": novo_saldo}).eq("email", email.lower().strip()).execute()
        supabase_client.from_("historico").insert([{"email": email.lower().strip(), "operacao": f"Uso: {operacao}", "creditos": -quantidade}]).execute()
        return True
    except Exception:
        return False

# ==============================================================================
# 3. MOTORES DE IA: GERAÇÃO, TRADUÇÃO & MINERAÇÃO
# ==============================================================================
def executar_prompt_ia(prompt: str, formato_json: bool = False, temperatura: float = 0.4) -> str:
    """Invoca o Gemini (com fallback para OpenAI) de forma resiliente."""
    if GEMINI_API_KEY:
        try:
            if HAS_GENAI_NEW:
                client = genai.Client(api_key=GEMINI_API_KEY)
                cfg = {"response_mime_type": "application/json"} if formato_json else {}
                res = client.models.generate_content(model="gemini-1.5-flash", contents=prompt, config=cfg)
                return res.text
            elif HAS_GENAI_LEGACY:
                legacy_genai.configure(api_key=GEMINI_API_KEY)
                model = legacy_genai.GenerativeModel("gemini-1.5-flash")
                res = model.generate_content(prompt)
                return res.text
        except Exception:
            pass

    if OPENAI_API_KEY:
        client = OpenAI(api_key=OPENAI_API_KEY)
        kwargs = {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": prompt}], "temperature": temperatura}
        if formato_json:
            kwargs["response_format"] = {"type": "json_object"}
        res = client.chat.completions.create(**kwargs)
        return res.choices[0].message.content

    raise ValueError("Nenhuma chave válida configurada para Gemini ou OpenAI.")

def traduzir_texto_ia(texto: str, idioma_destino: str) -> str:
    if not texto.strip():
        return ""
    prompt = f"""
    Atue como tradutor nativo e copywriter sênior no idioma '{idioma_destino}'.
    Traduza o texto abaixo mantendo o tom persuasivo, ritmo natural, métrica comercial e formatação original:
    
    "{texto}"
    
    Retorne estritamente o texto traduzido, sem aspas e sem explicações.
    """
    try:
        return executar_prompt_ia(prompt, formato_json=False, temperatura=0.3).strip()
    except Exception:
        return texto

def minerar_nicho_profundo_ia(nicho: str, profundidade: str) -> str:
    prompt = f"""
    Atue como Diretor de Aquisição e Especialista Sênior em Tráfego Pago, Copywriting e Validação de Produtos Digitais.
    Domínio absoluto de: Google Ads (Search, YouTube Ads, PMax), Meta Ads, Kiwify e plataformas internacionais.
    
    Analise a fundo o seguinte nicho:
    NICHO: "{nicho}"
    NÍVEL DE PROFUNDIDADE: {profundidade}
    
    Gere um dossiê executivo completo formatado em Markdown com as seguintes seções estruturadas:
    
    ### 1. 🎯 PÚBLICO-ALVO & NÍVEL DE CONSCIÊNCIA
    - Perfil do comprador real (faixa etária, motivação urgente de compra).
    - Nível de consciência e temperatura média de tráfego.
    
    ### 2. ⚡ AS 3 MAIORES DORES OCULTAS & AS 3 PRINCIPAIS OBJEÇÕES
    - Dores profundas que aceleram a decisão de compra.
    - Objeções reais e contra-argumentos de resposta imediata na copy.
    
    ### 3. 💎 ARQUITETURA DO PRODUTO & MECANISMO ÚNICO
    - **Nome Sugerido do E-book / Treinamento:** (Comercial, magnético e de alto valor percebido).
    - **A Grande Promessa (Big Idea):** (1 frase direta e de impacto visceral).
    - **Mecanismo Único:** Qual o método exclusivo por trás da solução?
    
    ### 4. 👑 O PATRÃO GOOGLE ADS (KIT COMPLETO DE CAMPANHA)
    #### A) Palavras-Chave de Fundo de Funil (Compradores Reais):
    - Liste 6 a 8 palavras-chave com alta intenção de compra formatadas em Correspondência de Frase `"termo"` e Correspondência Exata `[termo]`.
    
    #### B) Lista de Palavras-Chave Negativas (Blindagem de Verba):
    - Liste 10 termos obrigatórios para negativar de imediato (ex: grátis, pdf grátis, login, reclame aqui, torrent, baixar, etc.).
    
    #### C) Anúncio Responsivo de Pesquisa (RSA Pronto para Copiar e Colar):
    - **Títulos (máx. 30 caracteres cada):** Liste 5 títulos magnéticos diferentes.
    - **Descrições (máx. 90 caracteres cada):** Liste 3 descrições persuasivas com chamada para ação clara (CTA).
    
    #### D) Gancho para YouTube Ads (Vídeo In-Stream / Primeiros 5 Segundos):
    - A frase de abertura exata para usar na VSL no YouTube, retendo compradores e descartando curiosos antes do limite de cobrança.
    
    ### 5. 💰 ESTRATÉGIA DE MONETIZAÇÃO & ESCALA
    - **Preço Frontend (Brasil):** R$ (Ticket para escala no PIX/Cartão).
    - **Preço Internacional (EUA/Europa):** US$ / € (para venda com o material traduzido).
    - **Order Bump Perfeito:** Produto complementar irresistível para adicionar no checkout.
    
    Seja pragmático, analítico e 100% voltado para geração de faturamento real.
    """
    return executar_prompt_ia(prompt, formato_json=False, temperatura=0.35)

def gerar_roteiro_vsl_ia(nicho: str, promessa: str, publico: str, num_cenas: int = 5) -> List[str]:
    prompt = f"""
    Crie um roteiro persuasivo de alta conversão para VSL (Vídeo de Vendas) sobre:
    Nicho: {nicho}
    Promessa: {promessa}
    Público: {publico}
    
    Gere exatamente {num_cenas} frases de impacto direto (cada frase representará uma cena com corte visual dinâmico).
    Retorne estritamente um JSON no seguinte formato:
    {{
        "cenas": [
            "Frase da cena 1...",
            "Frase da cena 2..."
        ]
    }}
    """
    resp = executar_prompt_ia(prompt, formato_json=True, temperatura=0.5)
    dados = json.loads(resp)
    return dados.get("cenas", [])

def gerar_conteudo_ebook_ia(tema: str, publico: str) -> dict:
    prompt = f"""
    Atue como autor técnico e editor de manuais comerciais de alta escala.
    Crie o conteúdo completo e estruturado para um manual prático e comercial sobre:
    Tema: {tema}
    Público: {publico}
    
    Retorne estritamente um JSON estruturado com:
    {{
        "titulo": "Título Principal",
        "subtitulo": "Subtítulo Persuasivo",
        "termo_capa": "Termo em inglês para buscar foto no Pexels (ex: artisan sourdough bread)",
        "introducao": "Texto completo e formal de introdução...",
        "capitulos": [
            {{
                "numero": 1,
                "titulo": "Título do Módulo 1",
                "termo_busca_foto": "Termo em inglês para foto (ex: flour and water kneading)",
                "conteudo": "Texto completo, com passos, checklists e detalhes técnicos..."
            }},
            {{
                "numero": 2,
                "titulo": "Título do Módulo 2",
                "termo_busca_foto": "Termo em inglês para foto",
                "conteudo": "Texto completo..."
            }},
            {{
                "numero": 3,
                "titulo": "Título do Módulo 3",
                "termo_busca_foto": "Termo em inglês para foto",
                "conteudo": "Texto completo..."
            }},
            {{
                "numero": 4,
                "titulo": "Título do Módulo 4",
                "termo_busca_foto": "Termo em inglês para foto",
                "conteudo": "Texto completo..."
            }}
        ]
    }}
    """
    resp = executar_prompt_ia(prompt, formato_json=True, temperatura=0.4)
    return json.loads(resp)

def traduzir_ebook_completo_ia(dados_ebook: dict, idioma_destino: str, progress_bar=None) -> dict:
    total_etapas = 2 + len(dados_ebook.get("capitulos", []))
    etapa_atual = 0

    titulo_tr = traduzir_texto_ia(dados_ebook.get("titulo", ""), idioma_destino)
    subtitulo_tr = traduzir_texto_ia(dados_ebook.get("subtitulo", ""), idioma_destino)
    etapa_atual += 1
    if progress_bar:
        progress_bar.progress(etapa_atual / total_etapas)

    intro_tr = traduzir_texto_ia(dados_ebook.get("introducao", ""), idioma_destino)
    etapa_atual += 1
    if progress_bar:
        progress_bar.progress(etapa_atual / total_etapas)

    capitulos_tr = []
    for cap in dados_ebook.get("capitulos", []):
        t_cap_tr = traduzir_texto_ia(cap.get("titulo", ""), idioma_destino)
        c_cap_tr = traduzir_texto_ia(cap.get("conteudo", ""), idioma_destino)
        capitulos_tr.append({
            "numero": cap.get("numero", 1),
            "titulo": t_cap_tr,
            "termo_busca_foto": cap.get("termo_busca_foto", ""),
            "conteudo": c_cap_tr
        })
        etapa_atual += 1
        if progress_bar:
            progress_bar.progress(etapa_atual / total_etapas)

    return {
        "titulo": titulo_tr,
        "subtitulo": subtitulo_tr,
        "termo_capa": dados_ebook.get("termo_capa", ""),
        "introducao": intro_tr,
        "capitulos": capitulos_tr
    }

# ==============================================================================
# 4. PROCESSAMENTO GRÁFICO (PDF REPORTLAB COM FOTOS DO PEXELS)
# ==============================================================================
def buscar_foto_pexels(query: str, pexels_key: str, dest_path: str) -> bool:
    if not pexels_key or not query:
        return False
    try:
        url = f"https://api.pexels.com/v1/search?query={requests.utils.quote(query)}&per_page=1&orientation=landscape"
        headers = {"Authorization": pexels_key}
        res = requests.get(url, headers=headers, timeout=12)
        if res.status_code == 200:
            data = res.json()
            if data.get("photos"):
                img_url = data["photos"][0]["src"]["large"]
                img_data = requests.get(img_url, timeout=12).content
                with open(dest_path, "wb") as f:
                    f.write(img_data)
                return True
    except Exception:
        pass
    return False

def compilar_pdf_ebook_com_fotos(dados: dict, pexels_key: str, caminho_pdf: str) -> str:
    doc = SimpleDocTemplate(
        caminho_pdf,
        pagesize=letter,
        rightMargin=45,
        leftMargin=45,
        topMargin=45,
        bottomMargin=45
    )
    styles = getSampleStyleSheet()

    cor_primaria = colors.HexColor("#1A202C")
    cor_destaque = colors.HexColor("#2B6CB0")

    estilo_capa_tit = ParagraphStyle(
        'CapaTitulo',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=28,
        leading=34,
        textColor=cor_destaque,
        alignment=1,
        spaceAfter=15
    )
    estilo_capa_sub = ParagraphStyle(
        'CapaSub',
        parent=styles['Normal'],
        fontName='Helvetica-Oblique',
        fontSize=15,
        leading=20,
        textColor=cor_primaria,
        alignment=1,
        spaceAfter=25
    )
    estilo_h1 = ParagraphStyle(
        'TitCap',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=20,
        leading=26,
        textColor=cor_destaque,
        spaceBefore=15,
        spaceAfter=12
    )
    estilo_corpo = ParagraphStyle(
        'CorpoTexto',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=11,
        leading=17,
        textColor=cor_primaria,
        spaceAfter=10
    )

    flowables = []

    # CAPA
    flowables.append(Spacer(1, 40))
    flowables.append(Paragraph(dados.get("titulo", "Manual Técnico"), estilo_capa_tit))
    flowables.append(Paragraph(dados.get("subtitulo", "Guia de Implementação e Resultados"), estilo_capa_sub))

    termo_capa = dados.get("termo_capa", "business strategy")
    capa_img_path = os.path.join(DIR_PEXELS, f"capa_{int(time.time())}.jpg")
    if buscar_foto_pexels(termo_capa, pexels_key, capa_img_path):
        try:
            flowables.append(RLImage(capa_img_path, width=480, height=270))
        except Exception:
            pass

    flowables.append(PageBreak())

    # INTRODUÇÃO
    flowables.append(Paragraph("Introdução Estratégica", estilo_h1))
    flowables.append(Spacer(1, 10))
    for p in dados.get("introducao", "").split("\n"):
        if p.strip():
            flowables.append(Paragraph(p.strip(), estilo_corpo))

    flowables.append(PageBreak())

    # CAPÍTULOS
    for cap in dados.get("capitulos", []):
        flowables.append(Paragraph(f"Módulo {cap.get('numero')}: {cap.get('titulo')}", estilo_h1))
        flowables.append(Spacer(1, 8))

        termo_cap = cap.get("termo_busca_foto", "")
        if termo_cap:
            cap_img_path = os.path.join(DIR_PEXELS, f"cap_{cap.get('numero')}_{int(time.time())}.jpg")
            if buscar_foto_pexels(termo_cap, pexels_key, cap_img_path):
                try:
                    flowables.append(RLImage(cap_img_path, width=460, height=240))
                    flowables.append(Spacer(1, 12))
                except Exception:
                    pass

        for p_cap in cap.get("conteudo", "").split("\n"):
            if p_cap.strip():
                flowables.append(Paragraph(p_cap.strip(), estilo_corpo))

        flowables.append(PageBreak())

    doc.build(flowables)
    return caminho_pdf

# ==============================================================================
# 5. PROCESSAMENTO DE VÍDEO (TTS, PEXELS & FFMPEG)
# ==============================================================================
def sintetizar_audio_tts(texto: str, output_path: str, voz: str = "onyx") -> bool:
    if not OPENAI_API_KEY:
        return False
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        resp = client.audio.speech.create(model="tts-1", voice=voz, input=texto)
        resp.stream_to_file(output_path)
        return True
    except Exception:
        return False

def obter_duracao_audio(audio_path: str) -> float:
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", audio_path
    ]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return float(res.stdout.strip())
    except Exception:
        return 4.0

def buscar_video_pexels(query: str, pexels_key: str, dest_path: str, vertical: bool = False) -> bool:
    if not pexels_key or not query:
        return False
    orientacao = "portrait" if vertical else "landscape"
    url = f"https://api.pexels.com/videos/search?query={requests.utils.quote(query)}&per_page=1&orientation={orientacao}"
    headers = {"Authorization": pexels_key}
    try:
        res = requests.get(url, headers=headers, timeout=12)
        if res.status_code == 200:
            data = res.json()
            if data.get("videos"):
                video_files = data["videos"][0].get("video_files", [])
                target_files = [v for v in video_files if v.get("width") and v.get("height")]
                if target_files:
                    target_files.sort(key=lambda x: x["width"] * x["height"], reverse=True)
                    video_url = target_files[0]["link"]
                    v_bytes = requests.get(video_url, timeout=20).content
                    with open(dest_path, "wb") as f:
                        f.write(v_bytes)
                    return True
    except Exception:
        pass
    return False

def renderizar_vsl_completa(
    frases: List[str],
    vertical: bool,
    voz: str,
    pexels_key: str,
    musica_fundo_path: Optional[str] = None,
    volume_musica: float = 0.08,
    logo_path: Optional[str] = None,
    progress_bar = None
) -> str:
    res_w, res_h = (1080, 1920) if vertical else (1920, 1080)
    cenas_clipes = []
    total = len(frases)

    for idx, frase in enumerate(frases):
        prefixo = f"cena_{idx}_{int(time.time())}"
        a_path = os.path.join(DIR_AUDIOS, f"{prefixo}.mp3")
        sintetizar_audio_tts(frase, a_path, voz=voz)
        duracao = obter_duracao_audio(a_path)

        v_raw_path = os.path.join(DIR_PEXELS, f"{prefixo}_raw.mp4")
        tem_video = buscar_video_pexels(frase, pexels_key, v_raw_path, vertical=vertical)

        cena_out = os.path.join(DIR_VSL, f"{prefixo}_out.mp4")

        # Escapando o texto para o filtro drawtext do FFmpeg
        txt_escapado = frase.replace(":", "\\:").replace("'", "").replace('"', '').replace("%", "\\%")

        if tem_video and os.path.exists(v_raw_path):
            vf = (
                f"scale={res_w}:{res_h}:force_original_aspect_ratio=increase,"
                f"crop={res_w}:{res_h},"
                f"drawtext=text='{txt_escapado}':fontcolor=white:fontsize=48:box=1:boxcolor=black@0.65:"
                f"boxborderw=14:x=(w-text_w)/2:y=h-(h*0.22)"
            )
            cmd = [
                "ffmpeg", "-y", "-stream_loop", "-1", "-i", v_raw_path,
                "-i", a_path, "-t", str(duracao),
                "-vf", vf, "-c:v", "libx264", "-c:a", "aac", "-b:a", "192k",
                "-pix_fmt", "yuv420p", "-shortest", cena_out
            ]
        else:
            vf = (
                f"drawtext=text='{txt_escapado}':fontcolor=white:fontsize=52:box=1:boxcolor=blue@0.65:"
                f"boxborderw=18:x=(w-text_w)/2:y=(h-text_h)/2"
            )
            cmd = [
                "ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=0x1A202C:s={res_w}x{res_h}:d={duracao}",
                "-i", a_path, "-vf", vf, "-c:v", "libx264", "-c:a", "aac",
                "-b:a", "192k", "-pix_fmt", "yuv420p", "-shortest", cena_out
            ]

        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        cenas_clipes.append(cena_out)

        if progress_bar:
            progress_bar.progress((idx + 0.8) / total)

    # Concatenação das cenas
    concat_txt_path = os.path.join(DIR_VSL, f"concat_{int(time.time())}.txt")
    with open(concat_txt_path, "w", encoding="utf-8") as f:
        for c in cenas_clipes:
            f.write(f"file '{c.replace(os.sep, '/')}'\n")

    vsl_sem_trilha = os.path.join(DIR_VSL, f"vsl_base_{int(time.time())}.mp4")
    cmd_concat = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_txt_path,
        "-c", "copy", vsl_sem_trilha
    ]
    subprocess.run(cmd_concat, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    # Finalização: Trilha sonora e Logótipo
    vsl_final = os.path.join(DIR_VSL, f"vsl_final_{int(time.time())}.mp4")
    if musica_fundo_path and os.path.exists(musica_fundo_path):
        cmd_final = [
            "ffmpeg", "-y", "-i", vsl_sem_trilha, "-stream_loop", "-1", "-i", musica_fundo_path,
            "-filter_complex",
            f"[1:a]volume={volume_musica}[bg];[0:a][bg]amix=inputs=2:duration=first:dropout_transition=2[aout]",
            "-map", "0:v", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-shortest", vsl_final
        ]
        subprocess.run(cmd_final, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    else:
        vsl_final = vsl_sem_trilha

    return vsl_final

def dublar_roteiro_e_renderizar_vsl(
    frases_originais: List[str],
    idioma_alvo: str,
    vertical: bool,
    voz: str,
    pexels_key: str,
    musica_fundo_path: Optional[str] = None,
    volume_musica: float = 0.08,
    logo_path: Optional[str] = None,
    progress_bar = None
) -> Tuple[str, List[str]]:
    frases_traduzidas = []
    total_frases = len(frases_originais)

    for idx_f, frase in enumerate(frases_originais):
        prompt_tr_cena = f"""
        Atue como locutor publicitário e copywriter no idioma '{idioma_alvo}'.
        Traduza e adapte a seguinte frase de VSL para uma fala de alto impacto, natural e persuasiva:
        "{frase}"
        
        Retorne estritamente a frase traduzida, sem aspas ou explicações.
        """
        texto_tr = traduzir_texto_ia(frase, idioma_alvo)
        frases_traduzidas.append(texto_tr)
        if progress_bar:
            progress_bar.progress((idx_f + 1) / (total_frases * 2))

    video_dublado = renderizar_vsl_completa(
        frases=frases_traduzidas,
        vertical=vertical,
        voz=voz,
        pexels_key=pexels_key,
        musica_fundo_path=musica_fundo_path,
        volume_musica=volume_musica,
        logo_path=logo_path,
        progress_bar=progress_bar
    )
    return video_dublado, frases_traduzidas

# ==============================================================================
# 6. INTERFACE STREAMLIT (SISTEMA CENTRALIZADO)
# ==============================================================================

# BARRA LATERAL (AUTENTICAÇÃO & SALDO)
with st.sidebar:
    st.sidebar.markdown(
        """
        <div style="display: flex; align-items: center; gap: 14px; padding: 6px 0 22px 0;">
            <svg width="48" height="48" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
                <rect width="100" height="100" rx="22" fill="url(#bg_grad)" />
                <circle cx="50" cy="50" r="38" stroke="url(#ring_grad)" stroke-width="3" stroke-dasharray="8 6" opacity="0.8"/>
                <path d="M40 30L72 50L40 70V30Z" fill="#00F2FE"/>
                <path d="M52 24L64 48L48 50L58 76L38 52L52 50L50 24Z" fill="#38BDF8"/>
                <defs>
                    <linearGradient id="bg_grad" x1="0" y1="0" x2="100" y2="100" gradientUnits="userSpaceOnUse">
                        <stop stop-color="#0F172A" />
                        <stop offset="0.6" stop-color="#1E3A8A" />
                        <stop offset="1" stop-color="#0284C7" />
                    </linearGradient>
                    <linearGradient id="ring_grad" x1="0" y1="0" x2="100" y2="100" gradientUnits="userSpaceOnUse">
                        <stop stop-color="#00F2FE" />
                        <stop offset="1" stop-color="#2563EB" />
                    </linearGradient>
                </defs>
            </svg>
            <div style="line-height: 1.15;">
                <span style="font-size: 11px; font-weight: 800; color: #0284C7; letter-spacing: 2px; text-transform: uppercase;">CENTRAL</span><br>
                <span style="font-size: 21px; font-weight: 900; color: #1D4ED8; letter-spacing: -0.5px;">DUBFY<span style="color: #00B4D8;">AI</span></span>
                <span style="font-size: 13px; font-weight: 800; background: #2563EB; color: #FFFFFF; padding: 2px 7px; border-radius: 4px; margin-left: 4px; vertical-align: middle;">VSL</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    st.markdown("## ⚡ Central DubfyAi & VSL")
    st.caption("Automação de Produtos Digitais & Escala Internacional")
    st.markdown("---")

    email_usuario = st.text_input("Seu E-mail Cadastrado:", value="contato@meunegocio.com").lower().strip()
    dados_user = obter_dados_usuario(email_usuario)
    saldo_atual = dados_user["saldo"]

    col_s1, col_s2 = st.columns(2)
    with col_s1:
        st.metric("Créditos", f"{saldo_atual} cr")
    with col_s2:
        st.metric("Compras", dados_user["total_compras"])

    st.markdown("---")
    st.markdown("### 🛒 Recarga Automática Kiwify")
    st.markdown("""
    - **Starter VSL** (+160 cr / 320 novato)
    - **Pro VSL** (+300 cr / 600 novato)
    - **VIP Escala** (+500 cr / 1000 novato)
    """)
    st.info("💡 Pagamentos aprovados caem no seu saldo no mesmo segundo via Webhook.")

    st.markdown("---")
    st.caption("Status das APIs:")
    st.write("• Supabase:", "🟢 Ativo" if supabase_client else "🔴 Pendente")
    st.write("• OpenAI:", "🟢 Ativo" if OPENAI_API_KEY else "🔴 Ausente")
    st.write("• Gemini:", "🟢 Ativo" if GEMINI_API_KEY else "🔴 Ausente")
    st.write("• Pexels:", "🟢 Ativo" if PEXELS_API_KEY else "🔴 Ausente")

# ABAS PRINCIPAIS DO SISTEMA
tab_minerador, tab_vsl, tab_ebook, tab_master = st.tabs([
    "🔍 1. Minerador & Google Ads",
    "🚀 2. Criar VSL & Dublagem Global",
    "📚 3. Criar E-book & Tradução Global",
    "👑 4. Gestão Master"
])

# ------------------------------------------------------------------------------
# ABA 1: MINERADOR & GOOGLE ADS
# ------------------------------------------------------------------------------
with tab_minerador:
    st.markdown("## 🔍 Minerador & Validador de Nichos com Kit Google Ads")
    st.caption("Analise nichos comerciais, descubra dores ocultas e obtenha a campanha completa pronta para o Google Ads e YouTube Ads.")

    NICHOS_PREDEFINIDOS = [
        "🍞 Gastronomia & Pães Sem Glúten",
        "🎂 Confeitaria Lucrativa & Bolos Caseiros",
        "🐕 Adestramento Canino & Comportamento Pet",
        "💰 Renda Extra & Milhas Aéreas",
        "🌱 Jardinagem, Suculentas & Hortas em Apartamento",
        "🛠️ Manutenção Residencial & Marido de Aluguel",
        "💅 Estética, Cílios & Sobrancelhas",
        "🧘 Saúde Natural, Chás Medicinais & Sono",
        "✍️ Digitar Nicho Personalizado (Manual)..."
    ]

    col_m1, col_m2 = st.columns([2, 1])
    with col_m1:
        nicho_sel = st.selectbox("Selecione um Nicho ou Digite o Seu:", NICHOS_PREDEFINIDOS)
    with col_m2:
        profundidade = st.selectbox("Profundidade da Análise:", ["Dossiê Completo de Lançamento", "Raio-X Rápido de Dores & Promessas"])

    nicho_final = nicho_sel
    if "Manual" in nicho_sel:
        nicho_manual = st.text_input(
            "Digite o Nicho ou Micronicho que deseja pesquisar:",
            placeholder="Ex: Instalação e higienização de ar condicionado split",
            help="Pode ser qualquer tema técnico, comercial ou de hobby."
        )
        if nicho_manual.strip():
            nicho_final = nicho_manual.strip()

    st.info(f"🎯 **Nicho Selecionado para Mineração:** `{nicho_final}`")

    if st.button("🚀 Analisar Nicho & Gerar Kit Google Ads", type="primary"):
        if not nicho_final or "Manual" in nicho_final:
            st.warning("Por favor, informe um nicho válido.")
        else:
            with st.spinner("Analisando concorrência, intenção de busca e gerando campanhas do Google Ads..."):
                try:
                    resultado_dossie = minerar_nicho_profundo_ia(nicho_final, profundidade)
                    st.session_state["resultado_pesquisa_nicho"] = resultado_dossie
                    st.session_state["nicho_pesquisado_nome"] = nicho_final
                except Exception as err:
                    st.error(f"Erro na análise: {err}")

    if st.session_state.get("resultado_pesquisa_nicho"):
        st.markdown("---")
        st.markdown(f"### 📊 Dossiê Executivo: {st.session_state.get('nicho_pesquisado_nome')}")

        aba_d1, aba_d2 = st.tabs(["📑 Raio-X & Estrutura do Produto", "👑 Kit Pronto: O Patrão Google Ads"])
        with aba_d1:
            st.markdown(st.session_state["resultado_pesquisa_nicho"])
        with aba_d2:
            st.info("💡 **Campanha Pronta para Copiar e Colar:** Títulos, descrições RSA, negativas e gancho para YouTube Ads.")
            st.text_area(
                "📋 Conteúdo do Dossiê e Palavras-chave:",
                value=st.session_state["resultado_pesquisa_nicho"],
                height=350
            )
            nome_arq_txt = f"campanha_google_ads_{re.sub(r'[^a-zA-Z0-9]', '_', st.session_state.get('nicho_pesquisado_nome', 'nicho').lower())}.txt"
            st.download_button(
                "⬇️ Baixar Kit de Campanha (.txt)",
                data=st.session_state["resultado_pesquisa_nicho"],
                file_name=nome_arq_txt,
                mime="text/plain",
                use_container_width=True
            )

# ------------------------------------------------------------------------------
# ABA 2: CRIAR VSL & DUBLAGEM GLOBAL
# ------------------------------------------------------------------------------
with tab_vsl:
    st.markdown("## 🚀 Criador de Vídeo de Vendas (VSL) & Dublagem Global")
    st.caption("Gere roteiros persuasivos, renderize com cortes de B-roll e duble em 36 idiomas com sincronização completa.")

    col_v1, col_v2 = st.columns(2)
    with col_v1:
        tema_vsl = st.text_input("Tema / Produto da VSL:", "Pães Artesanais Sem Glúten")
        promessa_vsl = st.text_input("Grande Promessa:", "Faça pães perfeitos e fature R$ 3.000 da cozinha de casa")
    with col_v2:
        publico_vsl = st.text_input("Público-Alvo:", "Mulheres e mães que buscam renda extra")
        qtd_cenas = st.slider("Quantidade de Cenas (Cortes Dinâmicos):", 3, 10, 5)

    col_opt1, col_opt2, col_opt3 = st.columns(3)
    with col_opt1:
        formato_vertical = st.checkbox("Formato Vertical 9:16 (Reels/TikTok/Shorts)", value=False)
    with col_opt2:
        voz_sel = st.selectbox("Locução (OpenAI TTS):", ["onyx (Forte/Masculina)", "alloy (Neutra)", "nova (Energética/Feminina)", "echo (Suave)"])
        voz_codigo = voz_sel.split()[0]
    with col_opt3:
        musica_up = st.file_uploader("Trilha Sonora (.mp3 opcional):", type=["mp3"])

    if st.button("🎬 Gerar Roteiro e Renderizar VSL Original (20 cr)", type="primary"):
        if saldo_atual < 20:
            st.error("❌ Saldo insuficiente! Você precisa de 20 créditos.")
        else:
            barra_vsl = st.progress(0.0)
            with st.spinner("Gerando roteiro magnético e compilando cenas no FFmpeg..."):
                try:
                    roteiro_frases = gerar_roteiro_vsl_ia(tema_vsl, promessa_vsl, publico_vsl, qtd_cenas)
                    st.session_state["roteiro_vsl"] = roteiro_frases

                    p_musica = None
                    if musica_up:
                        p_musica = os.path.join(DIR_MUSICAS, musica_up.name)
                        with open(p_musica, "wb") as f_m:
                            f_m.write(musica_up.getbuffer())

                    video_pronto = renderizar_vsl_completa(
                        frases=roteiro_frases,
                        vertical=formato_vertical,
                        voz=voz_codigo,
                        pexels_key=PEXELS_API_KEY,
                        musica_fundo_path=p_musica,
                        progress_bar=barra_vsl
                    )

                    debitar_creditos_cloud(email_usuario, f"Criação VSL ({tema_vsl})", 20)
                    st.session_state["video_vsl_pronto"] = video_pronto
                    st.success("✅ VSL original renderizada com sucesso!")
                    st.rerun()
                except Exception as e_vsl:
                    st.error(f"Erro na renderização da VSL: {e_vsl}")

    # Exibição do Vídeo Original e Botão de Dublagem
    if st.session_state.get("video_vsl_pronto") and os.path.exists(st.session_state["video_vsl_pronto"]):
        st.markdown("---")
        st.markdown("### 🎬 Vídeo VSL Finalizado:")
        st.video(st.session_state["video_vsl_pronto"])

        with open(st.session_state["video_vsl_pronto"], "rb") as f_v:
            st.download_button(
                "⬇️ Baixar VSL Original (.mp4)",
                data=f_v,
                file_name=os.path.basename(st.session_state["video_vsl_pronto"]),
                mime="video/mp4",
                use_container_width=True
            )

        # MÓDULO DE DUBLAGEM GLOBAL PARA 36 IDIOMAS
        st.markdown("---")
        with st.container(border=True):
            st.markdown("### 🌐 Dublar VSL em 36 Idiomas (DubfyAi Global)")
            st.caption("Traduza a narração, gere novas vozes nativas e re-sincronize as durações dos cortes automaticamente.")

            col_d1, col_d2 = st.columns([2, 1])
            with col_d1:
                idioma_dub_sel = st.selectbox("Selecione o Idioma para Dublar:", list(IDIOMAS_SISTEMA_36.keys()))
            with col_d2:
                st.write("")
                st.caption("Custo: 20 Créditos")
                btn_dub = st.button("🎙️ Dublar Vídeo Agora (20 cr)", type="primary", use_container_width=True)

            if btn_dub:
                if saldo_atual < 20:
                    st.error("❌ Saldo insuficiente para dublagem internacional.")
                elif not st.session_state.get("roteiro_vsl"):
                    st.error("Roteiro original não encontrado na sessão.")
                else:
                    nome_lingua_dub = IDIOMAS_SISTEMA_36[idioma_dub_sel]
                    barra_dub = st.progress(0.0)
                    with st.spinner(f"Traduzindo roteiro e sintetizando dublagem nativa para {idioma_dub_sel}..."):
                        try:
                            p_musica = os.path.join(DIR_MUSICAS, musica_up.name) if musica_up else None
                            v_dublado, rot_tr = dublar_roteiro_e_renderizar_vsl(
                                frases_originais=st.session_state["roteiro_vsl"],
                                idioma_alvo=nome_lingua_dub,
                                vertical=formato_vertical,
                                voz=voz_codigo,
                                pexels_key=PEXELS_API_KEY,
                                musica_fundo_path=p_musica,
                                progress_bar=barra_dub
                            )
                            debitar_creditos_cloud(email_usuario, f"Dublagem VSL ({nome_lingua_dub})", 20)
                            st.session_state["video_dublado_pronto"] = v_dublado
                            st.session_state["video_dublado_idioma"] = idioma_dub_sel
                            st.session_state["video_dublado_roteiro"] = rot_tr
                            st.success(f"✅ VSL dublada com sucesso para {idioma_dub_sel}!")
                            st.rerun()
                        except Exception as e_dub:
                            st.error(f"Erro na dublagem da VSL: {e_dub}")

        if st.session_state.get("video_dublado_pronto") and os.path.exists(st.session_state["video_dublado_pronto"]):
            st.markdown(f"#### 🎬 Vídeo Dublado em {st.session_state.get('video_dublado_idioma')}:")
            st.video(st.session_state["video_dublado_pronto"])
            with open(st.session_state["video_dublado_pronto"], "rb") as f_vd:
                st.download_button(
                    f"⬇️ BAIXAR VSL DUBLADA EM {st.session_state.get('video_dublado_idioma').upper()} (.MP4)",
                    data=f_vd,
                    file_name=os.path.basename(st.session_state["video_dublado_pronto"]),
                    mime="video/mp4",
                    type="primary",
                    use_container_width=True
                )

# ------------------------------------------------------------------------------
# ABA 3: CRIAR E-BOOK & TRADUÇÃO GLOBAL
# ------------------------------------------------------------------------------
with tab_ebook:
    st.markdown("## 📚 Criador de E-book com Fotos Reais & Tradução Global")
    st.caption("Escreva manuais completos com fotos do Pexels e traduza o livro inteiro para 36 idiomas em 1 clique.")

    col_e1, col_e2 = st.columns(2)
    with col_e1:
        tema_ebook = st.text_input("Tema do E-book:", "Manual Definitivo dos Pães Sem Glúten")
    with col_e2:
        publico_ebook = st.text_input("Público-Alvo:", "Pessoas com restrição alimentar e empreendedoras")

    if st.button("📖 Gerar E-book Completo com Fotos (.PDF) (10 cr)", type="primary"):
        if saldo_atual < 10:
            st.error("❌ Saldo insuficiente! Você precisa de 10 créditos.")
        else:
            with st.spinner("Estruturando capítulos, baixando fotos em HD e gerando PDF..."):
                try:
                    dados_eb = gerar_conteudo_ebook_ia(tema_ebook, publico_ebook)
                    st.session_state["dados_ebook_sessao"] = dados_eb

                    nome_pdf = f"ebook_{int(time.time())}.pdf"
                    caminho_pdf = os.path.join(DIR_EBOOKS, nome_pdf)
                    compilar_pdf_ebook_com_fotos(dados_eb, PEXELS_API_KEY, caminho_pdf)

                    debitar_creditos_cloud(email_usuario, f"Criação E-book ({tema_ebook})", 10)
                    st.session_state["pdf_ebook_pronto"] = caminho_pdf
                    st.session_state["pdf_ebook_nome"] = nome_pdf
                    st.success("✅ E-book gerado e compilado com sucesso!")
                    st.rerun()
                except Exception as e_eb:
                    st.error(f"Erro na compilação do E-book: {e_eb}")

    # Exibição do E-book Pronto e Expansão Global
    if st.session_state.get("pdf_ebook_pronto") and os.path.exists(st.session_state["pdf_ebook_pronto"]):
        st.markdown("---")
        st.markdown("### 📥 Seu E-book Original em Português:")
        with open(st.session_state["pdf_ebook_pronto"], "rb") as f_eb:
            st.download_button(
                "⬇️️ Baixar E-book Original (.PDF)",
                data=f_eb,
                file_name=st.session_state.get("pdf_ebook_nome", "ebook.pdf"),
                mime="application/pdf",
                use_container_width=True
            )

        # TRADUÇÃO GLOBAL NAS 36 LÍNGUAS
        st.markdown("---")
        with st.container(border=True):
            st.markdown("### 🌐 Tradução Global do E-book (36 Idiomas)")
            st.caption("Internacionalize seu livro mantendo a estrutura de capítulos, imagens em alta resolução e paginação profissional.")

            col_tr1, col_tr2 = st.columns([2, 1])
            with col_tr1:
                idioma_eb_sel = st.selectbox("Selecione o Idioma de Destino:", list(IDIOMAS_SISTEMA_36.keys()))
            with col_tr2:
                st.write("")
                st.caption("Custo: 10 Créditos")
                btn_trad_eb = st.button("🌍 Traduzir E-book Completo (10 cr)", type="primary", use_container_width=True)

            if btn_trad_eb:
                if saldo_atual < 10:
                    st.error("❌ Saldo insuficiente para internacionalização.")
                elif not st.session_state.get("dados_ebook_sessao"):
                    st.error("Dados originais do e-book não encontrados.")
                else:
                    nome_lingua_eb = IDIOMAS_SISTEMA_36[idioma_eb_sel]
                    barra_eb_tr = st.progress(0.0)
                    with st.spinner(f"Traduzindo capa, introdução e todos os módulos para {idioma_eb_sel}..."):
                        try:
                            dados_tr = traduzir_ebook_completo_ia(
                                st.session_state["dados_ebook_sessao"],
                                nome_lingua_eb,
                                progress_bar=barra_eb_tr
                            )
                            cod_idioma = re.sub(r'[^a-zA-Z0-9]', '_', nome_lingua_eb.lower())
                            nome_pdf_tr = f"manual_{cod_idioma}_{int(time.time())}.pdf"
                            caminho_pdf_tr = os.path.join(DIR_EBOOKS, nome_pdf_tr)

                            compilar_pdf_ebook_com_fotos(dados_tr, PEXELS_API_KEY, caminho_pdf_tr)
                            debitar_creditos_cloud(email_usuario, f"Tradução E-book ({nome_lingua_eb})", 10)

                            st.session_state["pdf_global_pronto"] = caminho_pdf_tr
                            st.session_state["pdf_global_nome"] = nome_pdf_tr
                            st.session_state["pdf_global_lingua"] = idioma_eb_sel
                            st.success(f"✅ E-book traduzido com sucesso para {idioma_eb_sel}!")
                            st.rerun()
                        except Exception as e_tr:
                            st.error(f"Erro na tradução do e-book: {e_tr}")

        if st.session_state.get("pdf_global_pronto") and os.path.exists(st.session_state["pdf_global_pronto"]):
            st.success(f"✅ Arquivo internacionalizado pronto: **{st.session_state.get('pdf_global_lingua')}**")
            with open(st.session_state["pdf_global_pronto"], "rb") as f_tr_eb:
                st.download_button(
                    label=f"⬇️ BAIXAR E-BOOK EM {st.session_state.get('pdf_global_lingua').upper()} (.PDF)",
                    data=f_tr_eb,
                    file_name=st.session_state.get("pdf_global_nome", "ebook_global.pdf"),
                    mime="application/pdf",
                    type="primary",
                    use_container_width=True
                )

# ------------------------------------------------------------------------------
# ABA 4: GESTÃO MASTER
# ------------------------------------------------------------------------------
with tab_master:
    st.markdown("## 👑 Painel de Gestão Master")
    st.caption("Visão geral de faturamento, volume de usuários e integridade do sistema.")

    if not supabase_client:
        st.warning("Conexão com o Supabase inativa ou chaves não configuradas.")
    else:
        try:
            res_users = supabase_client.from_("usuarios").select("*").execute()
            usuarios_lista = res_users.data if res_users.data else []

            res_pedidos = supabase_client.from_("pedidos_kiwify").select("*").execute()
            pedidos_lista = res_pedidos.data if res_pedidos.data else []

            faturamento_total = sum(float(p.get("valor_pago", 0)) for p in pedidos_lista)
            total_clientes = len(usuarios_lista)
            saldo_circulante = sum(u.get("saldo_creditos", u.get("creditos", 0)) for u in usuarios_lista)

            cm1, cm2, cm3 = st.columns(3)
            with cm1:
                st.metric("Faturamento Kiwify", f"R$ {faturamento_total:,.2f}")
            with cm2:
                st.metric("Total de Clientes", total_clientes)
            with cm3:
                st.metric("Passivo de Créditos", f"{saldo_circulante} cr")

            st.markdown("---")
            st.markdown("### 📋 Últimos Pedidos Recebidos da Kiwify:")
            if pedidos_lista:
                st.dataframe(pedidos_lista, use_container_width=True)
            else:
                st.info("Nenhum pedido registrado até o momento.")

        except Exception as e_master:
            st.error(f"Erro ao carregar dados administrativos: {e_master}")

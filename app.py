import os
import re
import json
import time
import textwrap
import subprocess
import requests
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional, Any

import streamlit as st
from openai import OpenAI
from supabase import create_client, Client

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle, HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
from reportlab.pdfgen import canvas

# Compatibilidade com SDKs do Google Gemini
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
# FUNÇÃO AUXILIAR DE SANITIZAÇÃO DE TEXTO
# ==============================================================================
def sanitizar_texto(valor: Any) -> str:
    """Converte listas, dicionários ou nulos retornados pela IA em texto puro formatado."""
    if valor is None:
        return ""
    if isinstance(valor, str):
        return valor
    if isinstance(valor, list):
        itens = []
        for item in valor:
            if isinstance(item, (dict, list)):
                itens.append(sanitizar_texto(item))
            else:
                itens.append(str(item))
        return "\n".join(f"• {x}" if not str(x).startswith("•") else str(x) for x in itens)
    if isinstance(valor, dict):
        linhas = []
        for k, v in valor.items():
            k_formatado = str(k).replace("_", " ").capitalize()
            if isinstance(v, (list, dict)):
                linhas.append(f"{k_formatado}:\n{sanitizar_texto(v)}")
            else:
                linhas.append(f"{k_formatado}: {v}")
        return "\n".join(linhas)
    return str(valor)

# ==============================================================================
# 1. CONFIGURAÇÕES INICIAIS, DIRETÓRIOS & PRESETS
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
DIR_FUSAO = os.path.join(DIR_BASE, "temp_fusao")

for d in [DIR_VSL, DIR_EBOOKS, DIR_AUDIOS, DIR_PEXELS, DIR_MUSICAS, DIR_LOGOS, DIR_FUSAO]:
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
TIKTOK_ADVERTISER_ID = obter_credencial("TIKTOK_ADVERTISER_ID", "7693205737438314502")
TIKTOK_ACCESS_TOKEN = obter_credencial("TIKTOK_ACCESS_TOKEN", "")

supabase_client: Optional[Client] = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        st.sidebar.error(f"Erro ao conectar ao Supabase: {e}")

PRESETS_PLATAFORMAS = {
    "TikTok (Ads / Orgânico 9:16)": {
        "resolucao": (1080, 1920),
        "vertical": True,
        "largura_linha": 22,
        "fontsize": 40,
        "pos_y": "h-text_h-420",
        "pos_marca_y": 140,
        "cta_padrao": "Toque no botão vermelho abaixo para garantir agora!"
    },
    "Instagram Reels / Meta Ads (9:16)": {
        "resolucao": (1080, 1920),
        "vertical": True,
        "largura_linha": 22,
        "fontsize": 40,
        "pos_y": "h-text_h-420",
        "pos_marca_y": 120,
        "cta_padrao": "Toque em Saiba Mais ou no link da bio para começar!"
    },
    "YouTube Shorts (9:16)": {
        "resolucao": (1080, 1920),
        "vertical": True,
        "largura_linha": 22,
        "fontsize": 40,
        "pos_y": "h-text_h-380",
        "pos_marca_y": 120,
        "cta_padrao": "Acesse o primeiro link fixado nos comentários!"
    },
    "Página de Vendas / YouTube (16:9 Horizontal)": {
        "resolucao": (1920, 1080),
        "vertical": False,
        "largura_linha": 42,
        "fontsize": 44,
        "pos_y": "h-text_h-95",
        "pos_marca_y": 50,
        "cta_padrao": "Clique no botão oficial logo abaixo deste vídeo!"
    }
}

TRILHAS_PADRAO = {
    "comercial_animada.mp3": "https://raw.githubusercontent.com/effacestudios/Royalty-Free-Music-Pack/master/commercial.mp3",
    "planejamento_vendas.mp3": "https://raw.githubusercontent.com/effacestudios/Royalty-Free-Music-Pack/master/Planning.mp3",
    "suave_dinamica.mp3": "https://raw.githubusercontent.com/effacestudios/Royalty-Free-Music-Pack/master/Happy%20Life.mp3"
}

def garantir_trilhas_padrao():
    os.makedirs(DIR_MUSICAS, exist_ok=True)
    existentes = [f for f in os.listdir(DIR_MUSICAS) if f.lower().endswith(".mp3")]
    if not existentes:
        for nome_arq, url in TRILHAS_PADRAO.items():
            dest = os.path.join(DIR_MUSICAS, nome_arq)
            try:
                r = requests.get(url, timeout=12)
                if r.status_code == 200 and len(r.content) > 10000:
                    with open(dest, "wb") as f:
                        f.write(r.content)
            except Exception:
                pass

garantir_trilhas_padrao()

def listar_musicas_locais() -> Dict[str, Optional[str]]:
    os.makedirs(DIR_MUSICAS, exist_ok=True)
    arquivos = [f for f in os.listdir(DIR_MUSICAS) if f.lower().endswith(".mp3")]
    opcoes = {"Sem trilha sonora (Apenas voz)": None}
    for arq in sorted(arquivos):
        nome_formatado = arq.replace("_", " ").replace("-", " ").replace(".mp3", "").title()
        opcoes[f"🎵 {nome_formatado}"] = os.path.join(DIR_MUSICAS, arq)
    return opcoes

# ==============================================================================
# 2. SISTEMA DE COMPRESSÃO AUTOMÁTICA & UPLOAD COM LEITOR EM TEMPO REAL
# ==============================================================================
def obter_duracao_audio(audio_path: str) -> float:
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", audio_path]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return float(res.stdout.strip())
    except Exception:
        return 180.0

def garantir_video_abaixo_50mb(caminho_mp4: str, max_mb: float = 42.0, status_placeholder=None) -> str:
    """Comprime o vídeo automaticamente no FFmpeg caso ultrapasse o limite do Supabase."""
    if not os.path.exists(caminho_mp4):
        return caminho_mp4

    tam_mb = os.path.getsize(caminho_mp4) / (1024 * 1024)
    if tam_mb <= max_mb:
        return caminho_mp4

    if status_placeholder:
        status_placeholder.info(f"⚡ Vídeo com {tam_mb:.1f} MB. Comprimindo para ~30 MB...")

    dir_origem = os.path.dirname(caminho_mp4)
    saida_comprimida = os.path.join(dir_origem, f"vsl_otimizada_{int(time.time())}.mp4")

    duracao = obter_duracao_audio(caminho_mp4)
    bitrate_total_k = int((30 * 8192) / max(duracao, 1.0))
    bitrate_video_k = max(500, bitrate_total_k - 128)

    cmd = [
        "ffmpeg", "-y", "-threads", "2",
        "-i", caminho_mp4,
        "-c:v", "libx264", "-b:v", f"{bitrate_video_k}k",
        "-maxrate", f"{int(bitrate_video_k * 1.3)}k",
        "-bufsize", f"{bitrate_video_k * 2}k",
        "-preset", "faster", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
        "-movflags", "+faststart",
        saida_comprimida
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    return saida_comprimida

class LeitorComProgresso:
    """Lê o arquivo em blocos e atualiza a barra do Streamlit com contador de MB."""
    def __init__(self, caminho_arquivo: str, barra_progresso=None, texto_status=None):
        self.caminho = caminho_arquivo
        self.tamanho_total = os.path.getsize(caminho_arquivo)
        self.arquivo = open(caminho_arquivo, "rb")
        self.bytes_enviados = 0
        self.barra = barra_progresso
        self.status = texto_status

    def __len__(self):
        return self.tamanho_total

    def read(self, tamanho: int = 65536):
        bloco = self.arquivo.read(tamanho)
        if bloco:
            self.bytes_enviados += len(bloco)
            progresso = min(1.0, self.bytes_enviados / self.tamanho_total)
            if self.barra:
                self.barra.progress(progresso)
            if self.status:
                mb_atual = self.bytes_enviados / (1024 * 1024)
                mb_total = self.tamanho_total / (1024 * 1024)
                self.status.caption(f"⬆️ Enviando para a nuvem: **{mb_atual:.1f} MB** de **{mb_total:.1f} MB** ({int(progresso * 100)}%)")
        return bloco

    def close(self):
        self.arquivo.close()

def hospedar_video_supabase(caminho_local: str, barra_progresso=None, texto_status=None) -> Optional[str]:
    """Comprime o vídeo se necessário, testa os buckets VIDEOS e videos e realiza upload com x-upsert."""
    if not SUPABASE_URL or not SUPABASE_KEY or not os.path.exists(caminho_local):
        st.error("Credenciais do Supabase ausentes ou arquivo de vídeo não encontrado.")
        return None

    caminho_pronto = garantir_video_abaixo_50mb(caminho_local, max_mb=42.0, status_placeholder=texto_status)
    candidatos = ["VIDEOS", "videos"]
    nome_arquivo = f"vsl_master_{int(time.time())}.mp4"

    headers_base = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "x-upsert": "true",
        "Content-Type": "video/mp4"
    }

    for bucket in candidatos:
        url_upload = f"{SUPABASE_URL.rstrip('/')}/storage/v1/object/{bucket}/{nome_arquivo}"
        leitor = LeitorComProgresso(caminho_pronto, barra_progresso, texto_status)
        try:
            resp = requests.post(url_upload, headers=headers_base, data=leitor, timeout=300)
            leitor.close()
            if resp.status_code in [200, 201]:
                return f"{SUPABASE_URL.rstrip('/')}/storage/v1/object/public/{bucket}/{nome_arquivo}"
        except Exception:
            leitor.close()

    st.error("Falha no upload automático do Supabase. Verifique se o bucket VIDEOS ou videos está público.")
    return None

def obter_dados_usuario(email: str) -> dict:
    if not supabase_client or not email:
        return {"saldo": 100, "total_compras": 0}
    try:
        res = supabase_client.from_("usuarios").select("*").eq("email", email.lower().strip()).execute()
        if res.data and len(res.data) > 0:
            user = res.data[0]
            saldo = user.get("saldo_creditos", user.get("creditos", 0))
            return {"saldo": saldo, "total_compras": user.get("total_compras", 0)}
        else:
            supabase_client.from_("usuarios").insert([{"email": email.lower().strip(), "saldo_creditos": 100, "creditos": 100, "total_compras": 0}]).execute()
            return {"saldo": 100, "total_compras": 0}
    except Exception:
        return {"saldo": 100, "total_compras": 0}

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
        return True

# ==============================================================================
# 3. MOTORES DE IA & COPYWRITING
# ==============================================================================
def executar_prompt_ia(prompt: str, formato_json: bool = False, temperatura: float = 0.25) -> str:
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

    raise ValueError("Nenhuma chave configurada para Gemini ou OpenAI.")

def minerar_nicho_profundo_ia(nicho: str, profundidade: str) -> dict:
    prompt = f"""
    Atue como Diretor de Aquisição e Copywriter de Elite.
    Analise o seguinte nicho com rigor técnico e comercial:
    NICHO: "{nicho}"
    NÍVEL DE PROFUNDIDADE: {profundidade}

    REGRA MANDATÓRIA: Todo o conteúdo DEVE ser em Português do Brasil (PT-BR).

    Retorne ESTRITAMENTE um JSON com as chaves:
    {{
        "nome_produto": "Nome comercial do produto",
        "grande_promessa": "1 frase visceral de transformação com resultado prático",
        "publico_alvo": "Descrição detalhada do cliente ideal",
        "mecanismo_unico": "Nome e resumo curto do método exclusivo",
        "oferta_cta": "Condição de compra e chamada para ação",
        "dores_objecoes": "3 maiores dores e 3 principais objeções",
        "campanha_google_ads": "Palavras-chave, negativas, títulos e descrições",
        "dossie_markdown": "Dossiê executivo completo em Markdown"
    }}
    """
    resp = executar_prompt_ia(prompt, formato_json=True, temperatura=0.25)
    try:
        dados = json.loads(resp)
        if isinstance(dados, dict):
            return {k: sanitizar_texto(v) for k, v in dados.items()}
    except Exception:
        pass

    return {
        "nome_produto": f"Método Definitivo: {nicho}",
        "grande_promessa": f"Aprenda o método testado e lucre com {nicho}",
        "publico_alvo": "Iniciantes e profissionais que buscam renda extra",
        "mecanismo_unico": f"Protocolo Estruturado de Execução em {nicho}",
        "oferta_cta": "Apenas R$ 97,00 com acesso vitalício e 7 dias de garantia",
        "dores_objecoes": "Falta de direcionamento claro e medo de errar",
        "campanha_google_ads": f"Palavras-chave: curso {nicho}, aprender {nicho}",
        "dossie_markdown": sanitizar_texto(resp)
    }

def gerar_roteiro_vsl_ia(nicho: str, promessa: str, publico: str, num_cenas: int = 5) -> List[Dict[str, str]]:
    prompt = f"""
    Crie um roteiro persuasivo para VSL curta (27 segundos):
    - Nicho: {nicho} | Promessa: {promessa} | Público: {publico}
    REGRA: O texto da chave 'fala' DEVE ser em Português do Brasil (PT-BR).
    Gere exatamente {num_cenas} cenas cronológicas com fala e termo_video em inglês para o Pexels.
    Retorne ESTRITAMENTE o JSON:
    {{ "cenas": [{{"fala": "...", "termo_video": "..."}}] }}
    """
    resp = executar_prompt_ia(prompt, formato_json=True, temperatura=0.25)
    termo_generico = re.sub(r'[^a-zA-Z0-9\s]', '', nicho).strip()
    try:
        dados = json.loads(resp)
        cenas_raw = dados.get("cenas", [])
        return [{"fala": sanitizar_texto(c["fala"]).strip(), "termo_video": sanitizar_texto(c.get("termo_video", termo_generico)).strip()} for c in cenas_raw if c.get("fala")]
    except Exception:
        return [{"fala": promessa, "termo_video": termo_generico}]

def gerar_roteiro_apresentacao_3min_ia(nome_produto: str, nicho: str, promessa: str, publico: str, oferta_cta: str) -> List[Dict[str, str]]:
    prompt = f"""
    Crie o roteiro completo de apresentação de 3 minutos para:
    - Produto: {nome_produto} | Nicho: {nicho} | Promessa: {promessa} | CTA: {oferta_cta}
    REGRA: Todo o texto DEVE ser em Português do Brasil (PT-BR).
    Gere 13 cenas cronológicas (Gancho, História, Revelação do Produto, Prova, Garantia e Oferta).
    Retorne ESTRITAMENTE o JSON:
    {{ "cenas": [{{"fala": "...", "termo_video": "..."}}] }}
    """
    resp = executar_prompt_ia(prompt, formato_json=True, temperatura=0.25)
    termo_generico = re.sub(r'[^a-zA-Z0-9\s]', '', nicho).strip()
    try:
        dados = json.loads(resp)
        cenas_raw = dados.get("cenas", [])
        return [{"fala": sanitizar_texto(c["fala"]).strip(), "termo_video": sanitizar_texto(c.get("termo_video", termo_generico)).strip()} for c in cenas_raw if c.get("fala")]
    except Exception:
        return [{"fala": f"Descubra agora o {nome_produto}.", "termo_video": termo_generico}]

# ==============================================================================
# 4. RENDERIZAÇÃO E FUSÃO (ÁUDIO 44.1kHz ESTÉREO CORRIGIDO)
# ==============================================================================
def sintetizar_audio_tts(texto: str, output_path: str, voz: str = "onyx") -> bool:
    if not OPENAI_API_KEY: return False
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        resp = client.audio.speech.create(model="tts-1", voice=voz, input=sanitizar_texto(texto))
        resp.stream_to_file(output_path)
        return True
    except Exception:
        return False

def buscar_video_pexels(query: str, pexels_key: str, dest_path: str, vertical: bool = False) -> bool:
    if not pexels_key: return False
    orientacao = "portrait" if vertical else "landscape"
    headers = {"Authorization": pexels_key}
    termo_limpo = re.sub(r'[^a-zA-Z0-9\s]', '', str(query)).strip() or "business"
    try:
        url = f"https://api.pexels.com/videos/search?query={requests.utils.quote(termo_limpo)}&per_page=3&orientation={orientacao}"
        res = requests.get(url, headers=headers, timeout=12)
        if res.status_code == 200:
            videos = res.json().get("videos", [])
            if videos:
                vfiles = videos[0].get("video_files", [])
                if vfiles:
                    v_bytes = requests.get(vfiles[0]["link"], timeout=25).content
                    with open(dest_path, "wb") as f: f.write(v_bytes)
                    return True
    except Exception:
        pass
    return False

def renderizar_vsl_completa(
    cenas: List[Dict[str, str]], plataforma_nome: str, voz: str, pexels_key: str,
    musica_fundo_path: Optional[str] = None, volume_musica: float = 0.08, marca_dagua: Optional[str] = None, progress_bar = None
) -> str:
    config = PRESETS_PLATAFORMAS.get(plataforma_nome, PRESETS_PLATAFORMAS["TikTok (Ads / Orgânico 9:16)"])
    res_w, res_h = config["resolucao"]
    vertical = config["vertical"]
    pos_y_legenda = config["pos_y"]
    tam_fonte = config["fontsize"]
    largura_wrap = config["largura_linha"]

    cenas_clipes = []
    total = len(cenas)

    filtro_marca = ""
    if marca_dagua and str(marca_dagua).strip():
        marca_limpa = re.sub(r"[':\\]", "", str(marca_dagua).strip())
        tam_fonte_marca = 28 if vertical else 22
        pos_y_m = config.get("pos_marca_y", 140)
        filtro_marca = f",drawtext=text='{marca_limpa}':fontcolor=white@0.75:fontsize={tam_fonte_marca}:box=1:boxcolor=black@0.45:boxborderw=8:x=45:y={pos_y_m}"

    for idx, item in enumerate(cenas):
        frase = sanitizar_texto(item.get("fala", "") if isinstance(item, dict) else str(item))
        termo_video = sanitizar_texto(item.get("termo_video", "business") if isinstance(item, dict) else "business")

        prefixo = f"cena_{idx}_{int(time.time())}"
        a_path = os.path.join(DIR_AUDIOS, f"{prefixo}.mp3")
        sintetizar_audio_tts(frase, a_path, voz=voz)
        duracao = obter_duracao_audio(a_path)

        v_raw_path = os.path.join(DIR_PEXELS, f"{prefixo}_raw.mp4")
        tem_video = buscar_video_pexels(termo_video, pexels_key, v_raw_path, vertical=vertical)
        cena_out = os.path.join(DIR_VSL, f"{prefixo}_out.mp4")

        linhas = textwrap.wrap(frase.strip(), width=largura_wrap)
        texto_formatado = "\n".join(linhas)
        legenda_txt = os.path.join(DIR_VSL, f"{prefixo}_legenda.txt")
        with open(legenda_txt, "w", encoding="utf-8") as f_l: f_l.write(texto_formatado)
        legenda_path_escapado = legenda_txt.replace(os.sep, "/").replace(":", "\\:")

        if tem_video and os.path.exists(v_raw_path):
            vf = (
                f"scale={res_w}:{res_h}:force_original_aspect_ratio=increase,crop={res_w}:{res_h},setsar=1,fps=30,"
                f"drawtext=textfile='{legenda_path_escapado}':fontcolor=white:fontsize={tam_fonte}:"
                f"box=1:boxcolor=black@0.80:boxborderw=14:line_spacing=10:x=(w-text_w)/2:y={pos_y_legenda}"
                f"{filtro_marca}"
            )
            cmd = [
                "ffmpeg", "-y", "-threads", "2", "-stream_loop", "-1", "-i", v_raw_path, "-i", a_path,
                "-map", "0:v:0", "-map", "1:a:0", "-t", f"{duracao:.2f}", "-vf", vf,
                "-c:v", "libx264", "-preset", "faster", "-crf", "26",
                "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
                "-pix_fmt", "yuv420p", cena_out
            ]
        else:
            vf = (
                f"setsar=1,fps=30,drawtext=textfile='{legenda_path_escapado}':fontcolor=white:fontsize={tam_fonte+4}:"
                f"box=1:boxcolor=blue@0.65:boxborderw=18:line_spacing=12:x=(w-text_w)/2:y={pos_y_legenda}"
                f"{filtro_marca}"
            )
            cmd = [
                "ffmpeg", "-y", "-threads", "2", "-f", "lavfi", "-i", f"color=c=0x0F172A:s={res_w}x{res_h}:d={duracao:.2f}", "-i", a_path,
                "-map", "0:v:0", "-map", "1:a:0", "-t", f"{duracao:.2f}", "-vf", vf,
                "-c:v", "libx264", "-preset", "faster", "-crf", "26",
                "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
                "-pix_fmt", "yuv420p", cena_out
            ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        cenas_clipes.append(cena_out)
        if progress_bar: progress_bar.progress((idx + 0.8) / total)

    concat_txt_path = os.path.join(DIR_VSL, f"concat_{int(time.time())}.txt")
    with open(concat_txt_path, "w", encoding="utf-8") as f:
        for c in cenas_clipes: f.write(f"file '{c.replace(os.sep, '/')}'\n")

    vsl_sem_trilha = os.path.join(DIR_VSL, f"vsl_base_{int(time.time())}.mp4")
    cmd_concat = [
        "ffmpeg", "-y", "-threads", "2", "-f", "concat", "-safe", "0", "-i", concat_txt_path,
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
        vsl_sem_trilha
    ]
    subprocess.run(cmd_concat, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    vsl_final = os.path.join(DIR_VSL, f"vsl_final_{int(time.time())}.mp4")
    if musica_fundo_path and os.path.exists(musica_fundo_path):
        cmd_final = [
            "ffmpeg", "-y", "-threads", "2", "-i", vsl_sem_trilha, "-stream_loop", "-1", "-i", musica_fundo_path,
            "-filter_complex", (
                f"[1:a]volume={volume_musica},aformat=sample_rates=44100:channel_layouts=stereo[bg];"
                f"[0:a]aformat=sample_rates=44100:channel_layouts=stereo[vox];"
                f"[vox][bg]amix=inputs=2:duration=first:dropout_transition=2[aout]"
            ),
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
            "-movflags", "+faststart", "-shortest", vsl_final
        ]
        subprocess.run(cmd_final, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    else:
        cmd_fs = [
            "ffmpeg", "-y", "-threads", "2", "-i", vsl_sem_trilha,
            "-map", "0:v", "-map", "0:a",
            "-c:v", "copy", "-c:a", "copy",
            "-movflags", "+faststart", vsl_final
        ]
        subprocess.run(cmd_fs, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    return vsl_final

def fundir_videos_com_trilha(
    video1_path: str, video2_path: str, output_path: str,
    musica_path: Optional[str] = None, volume_musica: float = 0.08, plataforma: str = "TikTok (Ads / Orgânico 9:16)"
) -> str:
    """Funde os dois vídeos garantindo áudio padronizado em 44.1kHz e compressão CRF 27."""
    config = PRESETS_PLATAFORMAS.get(plataforma, PRESETS_PLATAFORMAS["TikTok (Ads / Orgânico 9:16)"])
    w, h = config["resolucao"]

    dur_v1 = obter_duracao_audio(video1_path)
    dur_v2 = obter_duracao_audio(video2_path)
    dur_total = max(10.0, dur_v1 + dur_v2)

    if musica_path and os.path.exists(musica_path):
        filter_complex = (
            f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,fps=30[v0];"
            f"[1:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,fps=30[v1];"
            f"[0:a]aformat=sample_rates=44100:channel_layouts=stereo[a0];"
            f"[1:a]aformat=sample_rates=44100:channel_layouts=stereo[a1];"
            f"[v0][a0][v1][a1]concat=n=2:v=1:a=1[vcat][acat];"
            f"[2:a]volume={volume_musica},aformat=sample_rates=44100:channel_layouts=stereo[bg];"
            f"[acat][bg]amix=inputs=2:duration=first:dropout_transition=2[aout]"
        )
        cmd = [
            "ffmpeg", "-y", "-threads", "2",
            "-i", video1_path, "-i", video2_path, "-stream_loop", "-1", "-i", musica_path,
            "-filter_complex", filter_complex,
            "-map", "[vcat]", "-map", "[aout]",
            "-t", f"{dur_total:.2f}",
            "-c:v", "libx264", "-preset", "faster", "-crf", "27", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
            "-movflags", "+faststart",
            output_path
        ]
    else:
        filter_complex = (
            f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,fps=30[v0];"
            f"[1:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,fps=30[v1];"
            f"[0:a]aformat=sample_rates=44100:channel_layouts=stereo[a0];"
            f"[1:a]aformat=sample_rates=44100:channel_layouts=stereo[a1];"
            f"[v0][a0][v1][a1]concat=n=2:v=1:a=1[vcat][aout]"
        )
        cmd = [
            "ffmpeg", "-y", "-threads", "2",
            "-i", video1_path, "-i", video2_path,
            "-filter_complex", filter_complex,
            "-map", "[vcat]", "-map", "[aout]",
            "-t", f"{dur_total:.2f}",
            "-c:v", "libx264", "-preset", "faster", "-crf", "27", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
            "-movflags", "+faststart",
            output_path
        ]

    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    return output_path

# ==============================================================================
# 5. GERADOR COMPLETO DE PDFS (MANUAL TÉCNICO & ORDER BUMP)
# ==============================================================================
class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_number(num_pages)
            super().showPage()
        super().save()

    def draw_page_number(self, page_count):
        if self._pageNumber > 1:
            self.setFont("Helvetica", 9)
            self.setFillColor(colors.HexColor("#64748B"))
            self.drawRightString(letter[0] - 54, 36, f"Página {self._pageNumber} de {page_count}")
            self.drawString(54, 36, "Manual Técnico Oficial • Todos os Direitos Reservados")
            self.setStrokeColor(colors.HexColor("#CBD5E1"))
            self.setLineWidth(0.5)
            self.line(54, 48, letter[0] - 54, 48)

def compilar_livro_tecnico_pdf(titulo: str, subtitulo: str, publico: str, caminho_pdf: str):
    doc = SimpleDocTemplate(
        caminho_pdf,
        pagesize=letter,
        leftMargin=54, rightMargin=54, topMargin=54, bottomMargin=54
    )
    estilos = getSampleStyleSheet()

    estilo_capa_tit = ParagraphStyle("CapaTit", parent=estilos["Title"], fontName="Helvetica-Bold", fontSize=26, leading=32, textColor=colors.HexColor("#0F172A"), alignment=TA_CENTER)
    estilo_capa_sub = ParagraphStyle("CapaSub", parent=estilos["Normal"], fontName="Helvetica", fontSize=14, leading=18, textColor=colors.HexColor("#334155"), alignment=TA_CENTER)
    estilo_h1 = ParagraphStyle("H1", parent=estilos["Heading1"], fontName="Helvetica-Bold", fontSize=18, leading=22, textColor=colors.HexColor("#1E3A8A"), spaceBefore=18, spaceAfter=8)
    estilo_corpo = ParagraphStyle("Corpo", parent=estilos["Normal"], fontName="Helvetica", fontSize=10.5, leading=15, textColor=colors.HexColor("#1E293B"), alignment=TA_JUSTIFY, spaceAfter=8)

    flowables = []

    flowables.append(Spacer(1, 80))
    flowables.append(Paragraph(titulo.upper(), estilo_capa_tit))
    flowables.append(Spacer(1, 15))
    flowables.append(HRFlowable(width="60%", thickness=3, color=colors.HexColor("#2563EB"), spaceAfter=20, spaceBefore=10))
    flowables.append(Paragraph(subtitulo, estilo_capa_sub))
    flowables.append(Spacer(1, 180))

    info_data = [
        [Paragraph(f"<b>Destinatário:</b> {publico}", estilo_corpo)],
        [Paragraph(f"<b>Edição:</b> Oficial ({datetime.now().strftime('%Y')})", estilo_corpo)],
        [Paragraph("<b>Status:</b> Material Protegido e Registrado", estilo_corpo)]
    ]
    tab_info = Table(info_data, colWidths=[400])
    tab_info.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#F8FAFC")),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor("#E2E8F0")),
        ('PADDING', (0,0), (-1,-1), 10),
    ]))
    flowables.append(tab_info)
    flowables.append(PageBreak())

    modulos = [
        ("1. Introdução & Fundamentos Operacionais", "Este manual técnico foi desenvolvido como um guia de execução imediata para garantir previsibilidade e domínio técnico."),
        ("2. O Mecanismo Único de Execução", "Compreenda a lógica estrutural que separa amadores de profissionais no setor e implemente com precisão."),
        ("3. Passo a Passo de Implementação", "A rotina exata a ser seguida desde o primeiro dia de trabalho até a escala dos seus resultados."),
        ("4. Resolução de Falhas Críticas", "Os maiores gargalos enfrentados na operação diária e como contornar cada um com agilidade."),
        ("5. Otimização e Escala Contínua", "Como padronizar seus processos para multiplicar resultados com consistência e segurança.")
    ]

    for tit_m, desc_m in modulos:
        flowables.append(Paragraph(tit_m, estilo_h1))
        flowables.append(Paragraph(desc_m, estilo_corpo))
        flowables.append(Paragraph(
            "Execute cada etapa conforme as orientações e valide os registros semanais de controle para garantir a máxima eficiência do método.",
            estilo_corpo
        ))
        flowables.append(Spacer(1, 10))

    doc.build(flowables, canvasmaker=NumberedCanvas)
    return caminho_pdf

def compilar_order_bump_pdf(titulo: str, caminho_pdf: str):
    doc = SimpleDocTemplate(
        caminho_pdf,
        pagesize=letter,
        leftMargin=54, rightMargin=54, topMargin=54, bottomMargin=54
    )
    estilos = getSampleStyleSheet()

    estilo_tit = ParagraphStyle("TitCheck", parent=estilos["Title"], fontName="Helvetica-Bold", fontSize=22, leading=26, textColor=colors.HexColor("#065F46"), alignment=TA_CENTER)
    estilo_sub = ParagraphStyle("SubCheck", parent=estilos["Normal"], fontName="Helvetica", fontSize=12, leading=16, textColor=colors.HexColor("#047857"), alignment=TA_CENTER)
    estilo_item = ParagraphStyle("Item", parent=estilos["Normal"], fontName="Helvetica", fontSize=10, leading=14, textColor=colors.HexColor("#1F2937"))

    flowables = []
    flowables.append(Spacer(1, 20))
    flowables.append(Paragraph("CHECKLIST OFICIAL & GUIA RÁPIDO", estilo_tit))
    flowables.append(Spacer(1, 8))
    flowables.append(Paragraph(f"Material Complementar: {titulo}", estilo_sub))
    flowables.append(Spacer(1, 15))
    flowables.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#10B981"), spaceAfter=20, spaceBefore=5))

    checklist_dados = [
        ["[  ]", Paragraph("<b>Fase 1: Preparação</b> - Revisão das ferramentas e validação dos requisitos iniciais.", estilo_item)],
        ["[  ]", Paragraph("<b>Fase 2: Configuração</b> - Implementação do método conforme o protocolo técnico.", estilo_item)],
        ["[  ]", Paragraph("<b>Fase 3: Teste de Consistência</b> - Verificação de falhas e ajuste fino dos parâmetros.", estilo_item)],
        ["[  ]", Paragraph("<b>Fase 4: Lançamento Operacional</b> - Ativação oficial e monitoramento em tempo real.", estilo_item)],
        ["[  ]", Paragraph("<b>Fase 5: Rotina de Manutenção</b> - Check diário de indicadores para garantir estabilidade.", estilo_item)]
    ]

    tab = Table(checklist_dados, colWidths=[35, 465])
    tab.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#ECFDF5")),
        ('GRID', (0,0), (-1,-1), 1, colors.HexColor("#A7F3D0")),
        ('PADDING', (0,0), (-1,-1), 12),
        ('ALIGN', (0,0), (0,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    flowables.append(tab)
    flowables.append(Spacer(1, 30))
    flowables.append(Paragraph("💡 <i>Dica: Imprima esta folha ou use no tablet para checar cada etapa concluída diariamente.</i>", estilo_item))

    doc.build(flowables)
    return caminho_pdf

# ==============================================================================
# 6. GERADOR DO HTML E INTEGRAÇÃO TIKTOK
# ==============================================================================
TIKTOK_API_BASE = "https://business-api.tiktok.com/open_api/v1.3"

def disparar_campanha_tiktok_completa(
    advertiser_id: str, access_token: str, video_path: str, campaign_name: str,
    copy_text: str, landing_page_url: str, orcamento_diario: float, identity_id: Optional[str] = None
) -> dict:
    headers = {"Access-Token": access_token}
    headers_json = {"Access-Token": access_token, "Content-Type": "application/json"}
    if not os.path.exists(video_path): raise FileNotFoundError(f"Arquivo não encontrado: {video_path}")

    url_upload = f"{TIKTOK_API_BASE}/file/video/ad/upload/"
    with open(video_path, "rb") as vf:
        res_upload = requests.post(url_upload, headers=headers, data={"advertiser_id": advertiser_id, "upload_type": "UPLOAD_BY_FILE"}, files={"video_file": vf}).json()
    if res_upload.get("code") != 0: raise Exception(f"Erro Upload TikTok: {res_upload.get('message')}")
    video_id = res_upload["data"]["video_id"]

    res_camp = requests.post(
        f"{TIKTOK_API_BASE}/campaign/create/", headers=headers_json,
        json={"advertiser_id": advertiser_id, "campaign_name": campaign_name, "objective_type": "WEB_CONVERSIONS", "budget_mode": "BUDGET_MODE_DYNAMIC"}
    ).json()
    if res_camp.get("code") != 0: raise Exception(f"Erro Campanha: {res_camp.get('message')}")
    campaign_id = res_camp["data"]["campaign_id"]

    data_formatada = (datetime.now(timezone.utc) + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
    payload_adgroup = {
        "advertiser_id": advertiser_id, "campaign_id": campaign_id, "adgroup_name": f"Grupo - {campaign_name}",
        "placement_type": "PLACEMENT_TYPE_NORMAL", "placements": ["PLACEMENT_TIKTOK"], "location_ids": ["6252001"],
        "budget_mode": "BUDGET_MODE_DAY", "budget": orcamento_diario, "schedule_type": "SCHEDULE_FROM_NOW",
        "schedule_start_time": data_formatada, "billing_event": "OCPM", "bid_type": "BID_TYPE_NO_BID", "optimization_goal": "CLICK"
    }
    res_adgroup = requests.post(f"{TIKTOK_API_BASE}/adgroup/create/", headers=headers_json, json=payload_adgroup).json()
    if res_adgroup.get("code") != 0: raise Exception(f"Erro AdGroup: {res_adgroup.get('message')}")
    adgroup_id = res_adgroup["data"]["adgroup_id"]

    separador = "&" if "?" in landing_page_url else "?"
    url_com_utms = (
        f"{landing_page_url}{separador}"
        f"utm_source=tiktok&utm_medium=cpc&utm_campaign=__CAMPAIGN_NAME__"
        f"&utm_term=__AID_NAME__&utm_content=__CID__&src=__CAMPAIGN_NAME__|__CID__"
    )

    criativo = {
        "ad_name": f"Criativo - {campaign_name}", "ad_format": "SINGLE_VIDEO", "video_id": video_id,
        "ad_text": copy_text[:100], "call_to_action": "LEARN_MORE", "landing_page_url": url_com_utms
    }
    if identity_id and identity_id.strip():
        criativo["identity_type"] = "CUSTOMIZED_USER"
        criativo["identity_id"] = identity_id.strip()

    res_ad = requests.post(f"{TIKTOK_API_BASE}/ad/create/", headers=headers_json, json={"advertiser_id": advertiser_id, "adgroup_id": adgroup_id, "creatives": [criativo]}).json()
    if res_ad.get("code") != 0: raise Exception(f"Erro Anúncio: {res_ad.get('message')}")

    return {"video_id": video_id, "campaign_id": campaign_id, "adgroup_id": adgroup_id, "ad_id": res_ad["data"]["ad_ids"][0]}

def gerar_html_landing_page(titulo: str, promessa: str, url_video_mp4: str, link_kiwify: str, delay_segundos: int = 147, pixel_id: str = "") -> str:
    script_pixel = f"""
    !function (w, d, t) {{
      w.TiktokAnalyticsObject=t;var tt=w[t]=w[t]||[];tt.methods=["page","track","identify","instances","debug","on","off","once","ready","alias","group","enableCookie","disableCookie"],tt.setAndDefer=function(t,e){{t[e]=function(){{t.push([e].concat(Array.prototype.slice.call(arguments,0)))}}}};for(var i=0;i<tt.methods.length;i++)tt.setAndDefer(tt,tt.methods[i]);tt.instance=function(t){{for(var e=tt._i[t]||[],n=0;n<tt.methods.length;n++)tt.setAndDefer(e,tt.methods[n]);return e}},tt.load=function(e,n){{var i="https://analytics.tiktok.com/i18n/pixel/events.js";tt._i=tt._i||{{}},tt._i[e]=[],tt._i[e]._u=i,tt._t=tt._t||{{}},tt._t[e]=+new Date,tt._o=tt._o||{{}},tt._o[e]=n||{{}};var o=document.createElement("script");o.type="text/javascript",o.async=!0,o.src=i+"?type=plugins&sdkid="+e;var a=document.getElementsByTagName("script")[0];a.parentNode.insertBefore(o,a)}};
      tt.load('{pixel_id}');
      tt.page();
    }}(window, document, 'ttq');
    """ if pixel_id else ""

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{titulo}</title>
  <script>{script_pixel}</script>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
    body {{ background-color: #0b0f19; color: #ffffff; text-align: center; padding: 20px 16px; }}
    .container {{ max-width: 580px; margin: 0 auto; }}
    .badge {{ display: inline-block; background: rgba(239, 68, 68, 0.2); color: #f87171; border: 1px solid #ef4444; padding: 5px 12px; border-radius: 999px; font-size: 12px; font-weight: bold; margin-bottom: 12px; }}
    h1 {{ font-size: 21px; line-height: 1.35; margin-bottom: 16px; font-weight: 800; }}
    .video-wrapper {{ position: relative; width: 100%; border-radius: 12px; overflow: hidden; background: #000; box-shadow: 0 10px 30px rgba(0,0,0,0.5); border: 1px solid #1f2937; }}
    video {{ width: 100%; display: block; }}
    .unmute-overlay {{ position: absolute; top: 0; left: 0; width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; background: rgba(0,0,0,0.45); cursor: pointer; z-index: 10; }}
    .unmute-btn {{ background: #ef4444; color: #fff; padding: 12px 24px; border-radius: 50px; font-weight: bold; font-size: 14px; box-shadow: 0 4px 15px rgba(239, 68, 68, 0.6); }}
    #oferta-container {{ display: none; margin-top: 24px; }}
    .btn-checkout {{ display: block; width: 100%; background: #22c55e; color: #000; font-size: 19px; font-weight: 900; text-decoration: none; padding: 18px; border-radius: 8px; text-transform: uppercase; box-shadow: 0 6px 20px rgba(34, 197, 94, 0.4); }}
    .garantia {{ font-size: 12px; color: #9ca3af; margin-top: 10px; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="badge">VÍDEO EXCLUSIVO</div>
    <h1>{promessa}</h1>
    <div class="video-wrapper">
      <div id="unmuteOverlay" class="unmute-overlay">
        <div class="unmute-btn">🔊 TOQUE PARA OUVIR O ÁUDIO</div>
      </div>
      <video id="vslVideo" playsinline autoplay muted preload="auto">
        <source src="{url_video_mp4}" type="video/mp4">
      </video>
    </div>
    <div id="oferta-container">
      <a href="{link_kiwify}" id="checkoutBtn" class="btn-checkout">GARANTIR MEU ACESSO AGORA</a>
      <div class="garantia">🔒 Compra 100% Segura • Acesso Imediato • 7 Dias de Garantia</div>
    </div>
  </div>
  <script>
    const video = document.getElementById('vslVideo');
    const overlay = document.getElementById('unmuteOverlay');
    const oferta = document.getElementById('oferta-container');
    const checkoutBtn = document.getElementById('checkoutBtn');

    overlay.addEventListener('click', () => {{
      video.muted = false;
      video.play();
      overlay.style.display = 'none';
    }});

    function liberar() {{
      oferta.style.display = 'block';
      localStorage.setItem('oferta_liberada_{abs(hash(titulo)) % 10000}', 'true');
    }}

    if (localStorage.getItem('oferta_liberada_{abs(hash(titulo)) % 10000}') === 'true') {{
      oferta.style.display = 'block';
    }}

    video.addEventListener('timeupdate', () => {{
      if (video.currentTime >= {delay_segundos}) {{
        liberar();
      }}
    }});

    window.addEventListener('DOMContentLoaded', () => {{
      const params = window.location.search;
      if (params && checkoutBtn) {{
        try {{
          const urlObj = new URL(checkoutBtn.href, window.location.origin);
          const currentParams = new URLSearchParams(params);
          currentParams.forEach((val, key) => {{
            urlObj.searchParams.set(key, val);
          }});
          checkoutBtn.href = urlObj.toString();
        }} catch(e) {{
          const sep = checkoutBtn.href.includes('?') ? '&' : '?';
          checkoutBtn.href += sep + params.replace('?', '');
        }}
      }}
    }});

    checkoutBtn.addEventListener('click', () => {{
      if (typeof ttq !== 'undefined') ttq.track('InitiateCheckout');
    }});
  </script>
</body>
</html>"""

# ==============================================================================
# ESTADOS GLOBAIS E SINCRONIZAÇÃO
# ==============================================================================
ESTADOS_INICIAIS = {
    "nicho_pesquisado_nome": "Confeitaria Lucrativa & Bolos Caseiros",
    "miner_nome_produto": "Método Confeitaria Lucrativa & Bolos Caseiros",
    "miner_promessa": "Domine as receitas mais pedidas e fature da cozinha da sua casa",
    "miner_publico": "Mulheres e empreendedoras que buscam renda extra com doces",
    "miner_mecanismo": "Protocolo de Produção Padronizada Sem Glúten",
    "miner_oferta": "Apenas R$ 97,00 com acesso vitalício, 3 bônus exclusivos e 7 dias de garantia",
    "miner_dores": "Falta de receitas testadas, desperdício de ingredientes e medo de não conseguir vender",
    "miner_gads": "Palavras-chave: curso de bolos caseiros, como fazer bolos para vender\nNegativas: gratis, download",
    "miner_dossie": "### Dossiê de Mercado\nO mercado de confeitaria artesanal cresce consistentemente no Brasil.",
    "vsl_input_tema": "Método Confeitaria Lucrativa & Bolos Caseiros",
    "vsl_input_promessa": "Domine as receitas mais pedidas e fature da cozinha da sua casa",
    "vsl_input_publico": "Mulheres e empreendedoras que buscam renda extra com doces",
    "vsl_marca_ativa": "",
    "ap_prod_nome": "Método Confeitaria Lucrativa & Bolos Caseiros",
    "ap_prod_nicho": "Confeitaria Lucrativa & Bolos Caseiros",
    "ap_prod_promessa": "Domine as receitas mais pedidas e fature da cozinha da sua casa",
    "ap_prod_publico": "Mulheres e empreendedoras que buscam renda extra com doces",
    "ap_prod_oferta": "Apenas R$ 97,00 com acesso vitalício, 3 bônus exclusivos e 7 dias de garantia",
    "ap_marca_dagua": "",
    "ebook_input_tema": "Manual Prático: Confeitaria Lucrativa & Bolos Caseiros",
    "ebook_input_publico": "Mulheres e empreendedoras que buscam renda extra com doces"
}

for k_init, v_init in ESTADOS_INICIAIS.items():
    if k_init not in st.session_state:
        st.session_state[k_init] = v_init

def sincronizar_campos_mineracao():
    prod = sanitizar_texto(st.session_state.get("miner_nome_produto", ""))
    prom = sanitizar_texto(st.session_state.get("miner_promessa", ""))
    pub = sanitizar_texto(st.session_state.get("miner_publico", ""))
    oft = sanitizar_texto(st.session_state.get("miner_oferta", ""))
    nic = sanitizar_texto(st.session_state.get("nicho_pesquisado_nome", ""))

    st.session_state["vsl_input_tema"] = prod
    st.session_state["vsl_input_promessa"] = prom
    st.session_state["vsl_input_publico"] = pub

    st.session_state["ap_prod_nome"] = prod
    st.session_state["ap_prod_nicho"] = nic
    st.session_state["ap_prod_promessa"] = prom
    st.session_state["ap_prod_publico"] = pub
    st.session_state["ap_prod_oferta"] = oft

    st.session_state["ebook_input_tema"] = f"Manual Prático: {prod}"
    st.session_state["ebook_input_publico"] = pub

# ==============================================================================
# SIDEBAR
# ==============================================================================
with st.sidebar:
    st.markdown("## ⚡ Central DubfyAi & VSL")
    st.caption("Automação de Produtos Digitais & Escala Internacional")
    st.markdown("---")

    if "email_usuario_ativo" not in st.session_state:
        st.session_state["email_usuario_ativo"] = "erp61eng@gmail.com"

    email_digitado = st.text_input("Seu E-mail Cadastrado:", value=st.session_state["email_usuario_ativo"]).lower().strip()
    if email_digitado:
        st.session_state["email_usuario_ativo"] = email_digitado

    email_usuario = st.session_state["email_usuario_ativo"]
    dados_user = obter_dados_usuario(email_usuario)
    saldo_atual = dados_user["saldo"]

    col_s1, col_s2 = st.columns(2)
    with col_s1: st.metric("Créditos", f"{saldo_atual} cr")
    with col_s2: st.metric("Compras", dados_user["total_compras"])

    st.markdown("---")
    st.caption("Status das Conexões:")
    st.write("• Supabase:", "🟢 Ativo" if SUPABASE_URL and SUPABASE_KEY else "🔴 Pendente")
    st.write("• OpenAI:", "🟢 Ativo" if OPENAI_API_KEY else "🔴 Ausente")
    st.write("• Pexels:", "🟢 Ativo" if PEXELS_API_KEY else "🔴 Ausente")
    st.write("• TikTok Ads:", "🟢 Ativo" if TIKTOK_ACCESS_TOKEN else "🟡 Aguardando Token")

# ==============================================================================
# ABAS DO SISTEMA
# ==============================================================================
tab_minerador, tab_vsl, tab_apresentacao, tab_fusao, tab_ebook, tab_ads, tab_master = st.tabs([
    "🔍 1. Minerador & Google Ads",
    "🚀 2. Criar VSL Curta (27s)",
    "🎥 3. Apresentação (3 Min)",
    "🎞️ 4. Junção Contínua & Trilha",
    "📚 5. Livro Técnico & Order Bump",
    "🎯 6. Central TikTok Ads & Funil",
    "👑 7. Gestão Master"
])

# ------------------------------------------------------------------------------
# ABA 1: MINERADOR & GOOGLE ADS
# ------------------------------------------------------------------------------
with tab_minerador:
    st.markdown("## 🔍 1. Minerador de Nicho Estratégico & Google Ads")
    col_m1, col_m2 = st.columns([2, 1])
    with col_m1:
        nicho_sel = st.selectbox("Selecione um Nicho ou Digite:", [
            "🎂 Confeitaria Lucrativa & Bolos Caseiros",
            "🐕 Adestramento Canino & Comportamento Pet",
            "🍞 Gastronomia & Pães Sem Glúten",
            "💰 Renda Extra & Milhas Aéreas",
            "✍️ Digitar Nicho Manual..."
        ])
    with col_m2:
        profundidade = st.selectbox("Profundidade:", ["Dossiê Completo", "Raio-X Rápido"])

    nicho_final = nicho_sel
    if "Manual" in nicho_sel:
        nicho_manual = st.text_input("Digite o Nicho:")
        if nicho_manual.strip(): nicho_final = nicho_manual.strip()

    col_btn_m1, col_btn_m2 = st.columns(2)
    with col_btn_m1:
        if st.button("🚀 Analisar Nicho & Gerar Campos Automáticos", type="primary", use_container_width=True):
            with st.spinner("Minerando mercado em Português..."):
                res_m = minerar_nicho_profundo_ia(nicho_final, profundidade)
                st.session_state["nicho_pesquisado_nome"] = nicho_final
                st.session_state["miner_nome_produto"] = res_m.get("nome_produto", nicho_final)
                st.session_state["miner_promessa"] = res_m.get("grande_promessa", "")
                st.session_state["miner_publico"] = res_m.get("publico_alvo", "")
                st.session_state["miner_mecanismo"] = res_m.get("mecanismo_unico", "")
                st.session_state["miner_oferta"] = res_m.get("oferta_cta", "")
                st.session_state["miner_dores"] = res_m.get("dores_objecoes", "")
                st.session_state["miner_gads"] = res_m.get("campanha_google_ads", "")
                st.session_state["miner_dossie"] = res_m.get("dossie_markdown", "")
                sincronizar_campos_mineracao()
                st.success("✅ Nicho minerado com sucesso!")
                st.rerun()

    with col_btn_m2:
        if st.button("🔄 Sincronizar Alterações com Todas as Abas", use_container_width=True):
            sincronizar_campos_mineracao()
            st.success("✅ Todas as abas sincronizadas com os dados atuais!")

    st.markdown("---")
    col_ed1, col_ed2 = st.columns(2)
    with col_ed1:
        st.text_input("🏷️ Nome do Produto:", key="miner_nome_produto", on_change=sincronizar_campos_mineracao)
        st.text_input("⚡ Grande Promessa:", key="miner_promessa", on_change=sincronizar_campos_mineracao)
        st.text_input("⚙️ Mecanismo Único:", key="miner_mecanismo")
    with col_ed2:
        st.text_input("🎯 Público-Alvo:", key="miner_publico", on_change=sincronizar_campos_mineracao)
        st.text_input("💰 Condição da Oferta:", key="miner_oferta", on_change=sincronizar_campos_mineracao)
        st.text_area("💥 Dores & Objeções Principais:", key="miner_dores", height=68)

    with st.expander("📊 Campanha Google Ads & Dossiê Completo", expanded=False):
        st.text_area("Estrutura Google Ads (Palavras-chave e Anúncios):", key="miner_gads", height=150)
        st.markdown(st.session_state.get("miner_dossie", ""))

# ------------------------------------------------------------------------------
# ABA 2: VSL CURTA (27S) COM DOWNLOAD DIRETO E ÁUDIO CORRIGIDO
# ------------------------------------------------------------------------------
with tab_vsl:
    st.markdown("## 🚀 2. Criador de VSL Curta (27s - Criativo de Anúncio)")
    col_v1, col_v2 = st.columns(2)
    with col_v1:
        tema_vsl = st.text_input("Tema / Produto:", key="vsl_input_tema")
        promessa_vsl = st.text_input("Promessa:", key="vsl_input_promessa")
        voz_vsl = st.selectbox("Locução do Criativo:", ["onyx", "alloy", "echo", "fable", "nova", "shimmer"])
    with col_v2:
        publico_vsl = st.text_input("Público-Alvo:", key="vsl_input_publico")
        marca_vsl = st.text_input("Marca d'água no Vídeo:", value=st.session_state.get("vsl_marca_ativa", ""))
        plat_vsl = st.selectbox("Formato do Criativo:", list(PRESETS_PLATAFORMAS.keys()), index=0)

    if st.button("🎬 Gerar e Renderizar VSL Curta (20 cr)", type="primary", use_container_width=True):
        if saldo_atual < 20:
            st.error("❌ Saldo insuficiente!")
        else:
            barra = st.progress(0.0)
            with st.spinner("Gerando roteiro e renderizando cenas com áudio estéreo..."):
                cenas = gerar_roteiro_vsl_ia(tema_vsl, promessa_vsl, publico_vsl, 5)
                v_pronto = renderizar_vsl_completa(cenas, plat_vsl, voz_vsl, PEXELS_API_KEY, marca_dagua=marca_vsl, progress_bar=barra)
                debitar_creditos_cloud(email_usuario, "VSL Curta", 20)
                st.session_state["video_vsl_pronto"] = v_pronto
                st.session_state["vsl_marca_ativa"] = marca_vsl
                st.success("✅ VSL Curta finalizada com áudio perfeito!")
                st.rerun()

    caminho_vsl_pronto = st.session_state.get("video_vsl_pronto")
    if caminho_vsl_pronto and os.path.exists(caminho_vsl_pronto):
        st.markdown("---")
        st.markdown("#### 🎬 Vídeo Pronto para Uso:")
        tam_mb = os.path.getsize(caminho_vsl_pronto) / (1024 * 1024)
        st.caption(f"📁 **Salvo no computador em:** `{caminho_vsl_pronto}` ({tam_mb:.1f} MB)")
        
        with open(caminho_vsl_pronto, "rb") as arq_vsl:
            bytes_vsl = arq_vsl.read()
            st.video(bytes_vsl, format="video/mp4")
            st.download_button(
                label="⬇️ Baixar Vídeo MP4 no Computador (27s)",
                data=bytes_vsl,
                file_name="vsl_curta_27s.mp4",
                mime="video/mp4",
                type="primary",
                use_container_width=True
            )

# ------------------------------------------------------------------------------
# ABA 3: APRESENTAÇÃO 3 MIN COM DOWNLOAD DIRETO E ÁUDIO CORRIGIDO
# ------------------------------------------------------------------------------
with tab_apresentacao:
    st.markdown("## 🎥 3. Apresentação Longa (Pitch de 3 Minutos)")
    col_ap1, col_ap2 = st.columns(2)
    with col_ap1:
        p_nome = st.text_input("Nome do Produto:", key="ap_prod_nome")
        p_nicho = st.text_input("Nicho:", key="ap_prod_nicho")
        p_prom = st.text_input("Promessa Central:", key="ap_prod_promessa")
        voz_ap = st.selectbox("Locução do Pitch:", ["onyx", "alloy", "echo", "fable", "nova", "shimmer"], key="voz_ap_sel")
    with col_ap2:
        p_pub = st.text_input("Público-Alvo:", key="ap_prod_publico")
        p_oft = st.text_input("Oferta / CTA:", key="ap_prod_oferta")
        m_ap = st.text_input("Marca d'água no Vídeo:", value=st.session_state.get("vsl_marca_ativa", ""), key="marca_ap_input")
        plat_ap = st.selectbox("Formato da Apresentação:", list(PRESETS_PLATAFORMAS.keys()), index=0, key="plat_ap_sel")

    if st.button("🎬 Gerar e Renderizar Apresentação de 3 Minutos (30 cr)", type="primary", use_container_width=True):
        if saldo_atual < 30:
            st.error("❌ Saldo insuficiente!")
        else:
            barra_ap = st.progress(0.0)
            with st.spinner("Gerando 13 cenas e sintetizando pitch de vendas..."):
                cenas_p = gerar_roteiro_apresentacao_3min_ia(p_nome, p_nicho, p_prom, p_pub, p_oft)
                v_pitch = renderizar_vsl_completa(cenas_p, plat_ap, voz_ap, PEXELS_API_KEY, marca_dagua=m_ap, progress_bar=barra_ap)
                debitar_creditos_cloud(email_usuario, "Apresentação Pitch", 30)
                st.session_state["video_pitch_pronto"] = v_pitch
                st.success("✅ Apresentação de 3 minutos pronta com áudio estéreo!")
                st.rerun()

    caminho_pitch_pronto = st.session_state.get("video_pitch_pronto")
    if caminho_pitch_pronto and os.path.exists(caminho_pitch_pronto):
        st.markdown("---")
        st.markdown("#### 🎬 Apresentação Pronta para Uso:")
        tam_mb_pitch = os.path.getsize(caminho_pitch_pronto) / (1024 * 1024)
        st.caption(f"📁 **Salvo no computador em:** `{caminho_pitch_pronto}` ({tam_mb_pitch:.1f} MB)")
        
        with open(caminho_pitch_pronto, "rb") as arq_pitch:
            bytes_pitch = arq_pitch.read()
            st.video(bytes_pitch, format="video/mp4")
            st.download_button(
                label="⬇️ Baixar Apresentação MP4 no Computador (3 Min)",
                data=bytes_pitch,
                file_name="apresentacao_3min.mp4",
                mime="video/mp4",
                type="primary",
                use_container_width=True
            )

# ------------------------------------------------------------------------------
# ABA 4: JUNÇÃO CONTÍNUA & TRILHA DE FUNDO COM DOWNLOAD
# ------------------------------------------------------------------------------
with tab_fusao:
    st.markdown("## 🎞️ 4. Junção Contínua dos Vídeos & Masterização")
    st.caption("Funde o gancho de 27s com a Apresentação, já otimizando o bitrate para carregar instantaneamente na Landing Page.")

    col_f1, col_f2 = st.columns(2)
    with col_f1:
        v1_sessao = st.session_state.get("video_vsl_pronto")
        v1_orig = st.radio("Origem do Vídeo 1 (27s):", ["Usar da Aba 2", "Upload MP4"], key="f_v1_sel")
        caminho_v1 = v1_sessao if v1_orig == "Usar da Aba 2" else None
        if v1_orig == "Upload MP4":
            u1 = st.file_uploader("Upload Vídeo 1:", type=["mp4"], key="u_v1")
            if u1:
                p1 = os.path.join(DIR_FUSAO, f"v1_{int(time.time())}.mp4")
                with open(p1, "wb") as f: f.write(u1.read())
                caminho_v1 = p1

    with col_f2:
        v2_sessao = st.session_state.get("video_pitch_pronto")
        v2_orig = st.radio("Origem do Vídeo 2 (3 Min):", ["Usar da Aba 3", "Upload MP4"], key="f_v2_sel")
        caminho_v2 = v2_sessao if v2_orig == "Usar da Aba 3" else None
        if v2_orig == "Upload MP4":
            u2 = st.file_uploader("Upload Vídeo 2:", type=["mp4"], key="u_v2")
            if u2:
                p2 = os.path.join(DIR_FUSAO, f"v2_{int(time.time())}.mp4")
                with open(p2, "wb") as f: f.write(u2.read())
                caminho_v2 = p2

    col_t1, col_t2 = st.columns(2)
    with col_t1:
        musicas = listar_musicas_locais()
        trilha_sel = st.selectbox("Trilha Sonora de Fundo:", list(musicas.keys()))
        caminho_m = musicas[trilha_sel]
    with col_t2:
        vol_m = st.slider("Volume da Trilha Sonora:", 0.02, 0.20, 0.08, 0.01)

    if st.button("⚡ Executar Fusão Contínua com Trilha Sonora", type="primary", use_container_width=True):
        if not caminho_v1 or not os.path.exists(caminho_v1):
            st.error("Selecione ou gere o Vídeo 1 (27s).")
        elif not caminho_v2 or not os.path.exists(caminho_v2):
            st.error("Selecione ou gere o Vídeo 2 (Apresentação).")
        else:
            with st.spinner("Concatenando e masterizando com áudio estéreo contínuo..."):
                try:
                    saida_fusao = os.path.join(DIR_FUSAO, f"vsl_master_fundida_{int(time.time())}.mp4")
                    fundir_videos_com_trilha(caminho_v1, caminho_v2, saida_fusao, caminho_m, vol_m)
                    st.session_state["video_master_fundido"] = saida_fusao
                    tam_mb = os.path.getsize(saida_fusao) / (1024 * 1024)
                    st.success(f"🎉 Vídeo Master gerado com sucesso! Tamanho: {tam_mb:.1f} MB.")
                    st.rerun()
                except Exception as e_f:
                    st.error(f"Erro na fusão dos vídeos: {e_f}")

    caminho_fusao_pronto = st.session_state.get("video_master_fundido")
    if caminho_fusao_pronto and os.path.exists(caminho_fusao_pronto):
        st.markdown("---")
        st.markdown("#### 🎬 Vídeo Master Fundido:")
        tam_mb_f = os.path.getsize(caminho_fusao_pronto) / (1024 * 1024)
        st.caption(f"📁 **Salvo no computador em:** `{caminho_fusao_pronto}` ({tam_mb_f:.1f} MB)")
        
        with open(caminho_fusao_pronto, "rb") as arq_fusao:
            bytes_fusao = arq_fusao.read()
            st.video(bytes_fusao, format="video/mp4")
            st.download_button(
                label="⬇️ Baixar Vídeo Master Fundido (.mp4)",
                data=bytes_fusao,
                file_name="vsl_master_fundido.mp4",
                mime="video/mp4",
                type="primary",
                use_container_width=True
            )

# ------------------------------------------------------------------------------
# ABA 5: LIVRO TÉCNICO & ORDER BUMP (REPORTLAB COMPLETO)
# ------------------------------------------------------------------------------
with tab_ebook:
    st.markdown("## 📚 5. Entrega Digital (.PDF) & Order Bump")
    st.caption("Gera o arquivo de entrega técnica e o checklist de order bump formatados para envio imediato na Kiwify.")

    col_eb1, col_eb2 = st.columns(2)
    with col_eb1:
        t_eb = st.text_input("Título do Manual Técnico:", key="ebook_input_tema")
        sub_eb = st.text_input("Subtítulo da Capa:", value="Guia Prático Operacional Passo a Passo")
    with col_eb2:
        p_eb = st.text_input("Público-Alvo:", key="ebook_input_publico")
        chk_bump = st.checkbox("Incluir Order Bump (Checklist de Implementação Rápida)", value=True)

    if st.button("📖 Compilar Kit Digital Completo (.PDF)", type="primary", use_container_width=True):
        with st.spinner("Diagramando manual técnico e gerando páginas..."):
            p_pdf_manual = os.path.join(DIR_EBOOKS, f"manual_tecnico_{int(time.time())}.pdf")
            compilar_livro_tecnico_pdf(t_eb, sub_eb, p_eb, p_pdf_manual)
            st.session_state["pdf_manual_gerado"] = p_pdf_manual

            if chk_bump:
                p_pdf_bump = os.path.join(DIR_EBOOKS, f"order_bump_{int(time.time())}.pdf")
                compilar_order_bump_pdf(t_eb, p_pdf_bump)
                st.session_state["pdf_bump_gerado"] = p_pdf_bump

            st.success("✅ Kit de entrega digital compilado com sucesso!")
            st.rerun()

    col_dw1, col_dw2 = st.columns(2)
    with col_dw1:
        if st.session_state.get("pdf_manual_gerado") and os.path.exists(st.session_state["pdf_manual_gerado"]):
            with open(st.session_state["pdf_manual_gerado"], "rb") as f_man:
                st.download_button(
                    "⬇️ Baixar Manual Técnico (.PDF)",
                    data=f_man.read(),
                    file_name="manual_tecnico.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )
    with col_dw2:
        if st.session_state.get("pdf_bump_gerado") and os.path.exists(st.session_state["pdf_bump_gerado"]):
            with open(st.session_state["pdf_bump_gerado"], "rb") as f_bmp:
                st.download_button(
                    "⬇️ Baixar Order Bump Checklist (.PDF)",
                    data=f_bmp.read(),
                    file_name="order_bump.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )

# ------------------------------------------------------------------------------
# ABA 6: CENTRAL DE LANÇAMENTO & LANDING PAGE (COM UPLOAD MANUAL DE CRIATIVO)
# ------------------------------------------------------------------------------
with tab_ads:
    st.markdown("## 🎯 6. Central de Lançamento & Funil de Vendas")
    st.caption("Gere a Landing Page, pegue seu criativo pronto e suba a campanha no TikTok Ads em minutos.")

    aba_tt_lp, aba_tt_manual, aba_tt_api = st.tabs([
        "🌐 1. Gerador da Landing Page (index.html)",
        "🚀 2. Subir Anúncio no TikTok Ads (Recomendado)",
        "⚙️ 3. Disparo Automático via API (Avançado)"
    ])

    # SUB-ABA 1: GERADOR LANDING PAGE
    with aba_tt_lp:
        st.markdown("### 📄 Hospedagem do Vídeo & Criação do index.html")

        col_h1, col_h2 = st.columns([1.4, 1])
        with col_h1:
            st.markdown("##### 1. Vídeo da Apresentação (Master Fundido)")
            v_master = st.session_state.get("video_master_fundido")
            caminho_para_enviar = None

            origem_lp = st.radio(
                "Fonte do Vídeo da Página:",
                ["Usar Vídeo Master Fundido (Aba 4)", "Enviar arquivo .MP4 do meu PC"],
                key="origem_lp_radio"
            )

            if origem_lp == "Usar Vídeo Master Fundido (Aba 4)":
                if v_master and os.path.exists(v_master):
                    mb_v = os.path.getsize(v_master) / (1024 * 1024)
                    st.success(f"✅ Vídeo Master Fundido detectado: `{os.path.basename(v_master)}` ({mb_v:.1f} MB)")
                    caminho_para_enviar = v_master
                else:
                    st.warning("⚠️ Gere a fusão na Aba 4 ou envie o arquivo MP4 diretamente.")
            else:
                up_mp4 = st.file_uploader("Selecione o arquivo .MP4 do seu computador:", type=["mp4"], key="up_mp4_direto")
                if up_mp4:
                    p_up = os.path.join(DIR_FUSAO, f"upload_lp_{int(time.time())}.mp4")
                    with open(p_up, "wb") as f_u: f_u.write(up_mp4.read())
                    caminho_para_enviar = p_up
                    st.success(f"✅ Arquivo carregado: `{up_mp4.name}`")

            if st.button("☁️ Hospedar Vídeo na Nuvem (Comprime & Gera URL)", type="primary", use_container_width=True):
                if not caminho_para_enviar or not os.path.exists(caminho_para_enviar):
                    st.error("Nenhum vídeo selecionado ou carregado.")
                else:
                    barra_up = st.progress(0.0)
                    texto_up = st.empty()

                    url_pronta = hospedar_video_supabase(
                        caminho_local=caminho_para_enviar,
                        barra_progresso=barra_up,
                        texto_status=texto_up
                    )
                    if url_pronta:
                        st.session_state["lp_video_url_ativa"] = url_pronta
                        texto_up.empty()
                        barra_up.progress(1.0)
                        st.success("🎉 Vídeo comprimido e hospedado com sucesso!")
                        st.rerun()

        with col_h2:
            st.markdown("##### 2. Status do Link Direto")
            url_atual = st.session_state.get("lp_video_url_ativa", "")
            lp_v_url = st.text_input("URL Direta do Vídeo (.mp4):", value=url_atual, placeholder="https://...supabase.co/.../vsl.mp4")
            if lp_v_url:
                st.caption("✅ Link do vídeo conectado ao reprodutor.")

        st.markdown("---")
        st.markdown("##### 3. Configurações da Página de Vendas")
        col_lp1, col_lp2 = st.columns(2)
        with col_lp1:
            lp_tit = st.text_input("Título da Página:", value="Apresentação Exclusiva")
            lp_prom = st.text_input("Headline do Topo:", value=st.session_state.get("miner_promessa", "Descubra o Método Exato em Menos de 3 Minutos"))
        with col_lp2:
            lp_chk = st.text_input("Link de Pagamento (Kiwify):", placeholder="https://pay.kiwify.com.br/...")
            lp_delay = st.number_input("Tempo para Revelar Botão (Segundos):", value=147)
            lp_px = st.text_input("ID do Pixel do TikTok (Opcional):", placeholder="Ex: C9ABC12345DEF678")

        if lp_v_url and lp_chk:
            html_final = gerar_html_landing_page(
                titulo=lp_tit, promessa=lp_prom, url_video_mp4=lp_v_url,
                link_kiwify=lp_chk, delay_segundos=int(lp_delay), pixel_id=lp_px
            )
            st.markdown("---")
            col_d1, col_d2 = st.columns([1, 1])
            with col_d1:
                st.download_button(
                    "⬇️ 1. Baixar index.html Pronto",
                    data=html_final,
                    file_name="index.html",
                    mime="text/html",
                    type="primary",
                    use_container_width=True
                )
            with col_d2:
                st.link_button("🌐 2. Abrir Netlify Drop (Publicar Site)", "https://app.netlify.com/drop", use_container_width=True)
        else:
            st.info("💡 Cole o link de checkout da Kiwify e a URL do vídeo para liberar o download do index.html.")

    # SUB-ABA 2: SUBIR NO TIKTOK ADS (COM UPLOAD MANUAL DIRETO)
    with aba_tt_manual:
        st.markdown("### 🚀 Subir Campanha no TikTok Ads (Sem API / Sem Token)")
        st.caption("Envie o criativo que você tem no PC ou use o gerado no app, pegue seu link rastreado e suba o anúncio.")

        col_an1, col_an2 = st.columns(2)
        with col_an1:
            st.markdown("##### 1. Criativo do Anúncio (Vídeo)")
            origem_ad = st.radio(
                "Origem do Vídeo do Anúncio:",
                ["Enviar arquivo MP4 do meu PC (Vídeo Pronto)", "Usar Vídeo da Aba 2 (27s)"],
                key="origem_ad_manual_sel"
            )

            video_para_ad = None
            if origem_ad == "Enviar arquivo MP4 do meu PC (Vídeo Pronto)":
                up_ad_manual = st.file_uploader("Selecione o arquivo do criativo (.mp4):", type=["mp4"], key="up_ad_manual_file")
                if up_ad_manual:
                    p_up_ad = os.path.join(DIR_VSL, f"ad_manual_{int(time.time())}.mp4")
                    with open(p_up_ad, "wb") as f_mad:
                        f_mad.write(up_ad_manual.read())
                    video_para_ad = p_up_ad
                    st.session_state["video_vsl_pronto"] = p_up_ad
                    st.success(f"✅ Criativo carregado: `{up_ad_manual.name}`")
            else:
                v_aba2 = st.session_state.get("video_vsl_pronto")
                if v_aba2 and os.path.exists(v_aba2):
                    video_para_ad = v_aba2
                else:
                    st.warning("⚠️ O vídeo da Aba 2 ainda não foi gerado.")

            if video_para_ad and os.path.exists(video_para_ad):
                with open(video_para_ad, "rb") as vf_ad:
                    b_ad = vf_ad.read()
                    st.video(b_ad, format="video/mp4")
                    st.download_button(
                        "⬇️ Baixar Criativo do Anúncio (.mp4)",
                        data=b_ad,
                        file_name="anuncio_tiktok.mp4",
                        mime="video/mp4",
                        type="primary",
                        use_container_width=True
                    )

        with col_an2:
            st.markdown("##### 2. Link Rastreado da Landing Page")
            url_site_netlify = st.text_input(
                "Cole o link do seu site no Netlify:",
                placeholder="https://sua-pagina.netlify.app"
            )

            nome_campanha_utm = st.text_input("Nome de Identificação da Campanha:", value="CONV_PROD01_V1")

            separador = "&" if "?" in url_site_netlify else "?"
            url_rastreada = f"{url_site_netlify}{separador}utm_source=tiktok&utm_medium=cpc&utm_campaign={nome_campanha_utm}&src={nome_campanha_utm}" if url_site_netlify else ""

            if url_rastreada:
                st.markdown("**Copie esta URL para colocar no anúncio:**")
                st.code(url_rastreada, language="text")

            st.markdown("##### 3. Legenda Sugerida para o Anúncio")
            copy_sugerida = st.text_area(
                "Texto do Anúncio:",
                value="Método revelado em menos de 3 minutos! Toque em Saiba Mais 👇",
                height=70
            )

        st.markdown("---")
        col_cta_tt1, col_cta_tt2 = st.columns([1, 2])
        with col_cta_tt1:
            st.link_button("🚀 Abrir TikTok Ads Manager", "https://ads.tiktok.com", type="primary", use_container_width=True)
        with col_cta_tt2:
            st.info("💡 **Publicação:** Abra o gerenciador, clique em **Criar** > Escolha **Tráfego** > Suba o vídeo de 27s > Cole a URL rastreada e publique.")

    # SUB-ABA 3: DISPARO VIA API (OPCIONAL/AVANÇADO)
    with aba_tt_api:
        st.markdown("### ⚙️ Disparo Automático via API (Para quem já tem App aprovado)")
        col_ad_api1, col_ad_api2 = st.columns(2)
        with col_ad_api1:
            nome_camp_api = st.text_input("Nome da Campanha (API):", value=f"CONV - {datetime.now().strftime('%d/%m')}")
            url_lp_api = st.text_input("URL da Landing Page (API):", placeholder="https://sua-pagina.netlify.app")
            orcamento_api = st.number_input("Orçamento Diário (R$):", min_value=30.0, value=60.0, step=10.0)
            copy_ad_api = st.text_area("Texto do Anúncio (API):", value="Método revelado em menos de 3 minutos! Toque em Saiba Mais 👇")
        with col_ad_api2:
            adv_id_api = st.text_input("Advertiser ID:", value=TIKTOK_ADVERTISER_ID)
            tok_ad_api = st.text_input("TikTok Access Token:", value=TIKTOK_ACCESS_TOKEN, type="password")

        if st.button("Disparar Campanha via API", use_container_width=True):
            video_para_ad_api = st.session_state.get("video_vsl_pronto")
            if not tok_ad_api or not url_lp_api or not video_para_ad_api:
                st.error("Preencha o Token, a URL da Landing Page e selecione ou envie o vídeo do anúncio.")
            else:
                with st.spinner("Publicando via API..."):
                    try:
                        res = disparar_campanha_tiktok_completa(
                            advertiser_id=adv_id_api, access_token=tok_ad_api, video_path=video_para_ad_api,
                            campaign_name=nome_camp_api, copy_text=copy_ad_api, landing_page_url=url_lp_api,
                            orcamento_diario=orcamento_api
                        )
                        st.success("Campanha publicada!")
                        st.json(res)
                    except Exception as e_ad:
                        st.error(f"Erro na API: {e_ad}")

# ------------------------------------------------------------------------------
# ABA 7: GESTÃO MASTER
# ------------------------------------------------------------------------------
with tab_master:
    st.markdown("## 👑 Gestão & Métricas Gerais")
    if supabase_client:
        try:
            res_u = supabase_client.from_("usuarios").select("*").execute()
            st.metric("Total de Clientes no Banco", len(res_u.data) if res_u.data else 0)
        except Exception:
            st.write("Sem registros adicionais no momento.")
    else:
        st.info("Conecte o Supabase para visualizar o painel executivo.")

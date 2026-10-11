import os
import re
import json
import time
import textwrap
import subprocess
import requests
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Tuple, Optional, Any

import streamlit as st
from openai import OpenAI
from supabase import create_client, Client
from PIL import Image as PILImage, ImageOps

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image as RLImage, PageBreak, Table, TableStyle, HRFlowable, KeepTogether
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas

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
ELEVENLABS_API_KEY = obter_credencial("ELEVENLABS_API_KEY")
TIKTOK_ADVERTISER_ID = obter_credencial("TIKTOK_ADVERTISER_ID", "7693205737438314502")
TIKTOK_ACCESS_TOKEN = obter_credencial("TIKTOK_ACCESS_TOKEN", "")

supabase_client: Optional[Client] = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        st.sidebar.error(f"Erro ao ligar ao Supabase: {e}")

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

PRESETS_PLATAFORMAS = {
    "TikTok (Ads / Orgânico 9:16)": {
        "resolucao": (1080, 1920),
        "vertical": True,
        "largura_linha": 20,
        "fontsize": 44,
        "pos_y": "(h-text_h)/2 + 100",
        "pos_marca_y": 140,
        "cta_padrao": "Toque no botão vermelho abaixo para garantir agora!"
    },
    "Instagram Reels / Meta Ads (9:16)": {
        "resolucao": (1080, 1920),
        "vertical": True,
        "largura_linha": 22,
        "fontsize": 44,
        "pos_y": "h-text_h-420",
        "pos_marca_y": 120,
        "cta_padrao": "Toque em Saiba Mais ou no link da bio para começar!"
    },
    "YouTube Shorts (9:16)": {
        "resolucao": (1080, 1920),
        "vertical": True,
        "largura_linha": 22,
        "fontsize": 44,
        "pos_y": "h-text_h-380",
        "pos_marca_y": 120,
        "cta_padrao": "Acesse o primeiro link fixado nos comentários!"
    },
    "Página de Vendas / YouTube (16:9 Horizontal)": {
        "resolucao": (1920, 1080),
        "vertical": False,
        "largura_linha": 42,
        "fontsize": 46,
        "pos_y": "h-text_h-85",
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
# 3. MOTORES DE IA: GERAÇÃO, TRANSCIAÇÃO & MINERAÇÃO
# ==============================================================================
def executar_prompt_ia(prompt: str, formato_json: bool = False, temperatura: float = 0.3) -> str:
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
    texto_limpo = sanitizar_texto(texto).strip()
    if not texto_limpo:
        return ""
    prompt = f"""
    Atue como tradutor nativo de elite e copywriter sênior no idioma '{idioma_destino}'.
    Traduza e faça a TRANSCIAÇÃO do texto abaixo, mantendo a métrica comercial, persuasão e rigor técnico.

    REGRA DE OURO - LOCALIZAÇÃO FINANCEIRA & MOEDA:
    1. NUNCA mantenha valores em 'Reais' ou 'R$' para outros idiomas.
    2. NUNCA faça conversão 1 para 1 cega.
    3. Adapte valores para paridade crível de mercado.
    4. Elimine gírias ou expressões locais brasileiras.

    Texto:
    "{texto_limpo}"

    Retorne estritamente o texto traduzido, sem aspas e sem explicações.
    """
    try:
        return executar_prompt_ia(prompt, formato_json=False, temperatura=0.25).strip()
    except Exception:
        return texto_limpo

def minerar_nicho_profundo_ia(nicho: str, profundidade: str) -> dict:
    prompt = f"""
    Atue como Diretor de Aquisição, Copywriter de Elite e Especialista em Engenharia de Produtos Digitais.
    Analise o seguinte nicho com rigor técnico e comercial:
    NICHO: "{nicho}"
    NÍVEL DE PROFUNDIDADE: {profundidade}

    Crie uma arquitetura comercial completa e extraia campos precisos de alta conversão.

    Retorne ESTRITAMENTE um JSON com as seguintes chaves (TODOS OS VALORES DEVEM SER STRINGS):
    {{
        "nome_produto": "Nome comercial de alto impacto para o produto em texto único",
        "grande_promessa": "1 frase visceral de transformação com resultado prático e tangível",
        "publico_alvo": "Descrição detalhada do cliente ideal em texto corrido",
        "mecanismo_unico": "Nome e resumo curto do método ou mecanismo exclusivo por trás da solução",
        "oferta_cta": "Condição irresistível de compra e chamada para ação em texto",
        "dores_objecoes": "Texto descritivo em parágrafo com as 3 maiores dores ocultas e as 3 principais objeções",
        "campanha_google_ads": "Texto corrido formatado com palavras-chave, negativas, títulos e descrições",
        "dossie_markdown": "Dossiê executivo e mercadológico completo em Markdown estruturado"
    }}
    """
    resp = executar_prompt_ia(prompt, formato_json=True, temperatura=0.35)
    try:
        dados = json.loads(resp)
        if isinstance(dados, dict):
            return {k: sanitizar_texto(v) for k, v in dados.items()}
    except Exception:
        pass

    return {
        "nome_produto": f"Método Definitivo: {nicho}",
        "grande_promessa": f"Aprenda o método testado e lucre com {nicho}",
        "publico_alvo": "Iniciantes e profissionais que buscam renda extra e independência financeira",
        "mecanismo_unico": f"Protocolo Estruturado de Execução em {nicho}",
        "oferta_cta": "Apenas R$ 97,00 com acesso vitalício e 7 dias de garantia incondicional",
        "dores_objecoes": "Falta de direcionamento claro, medo de errar e desperdício de tempo e dinheiro",
        "campanha_google_ads": f"Palavras-chave: curso {nicho}, aprender {nicho}, como fazer {nicho}",
        "dossie_markdown": sanitizar_texto(resp)
    }

def gerar_roteiro_vsl_ia(nicho: str, promessa: str, publico: str, num_cenas: int = 5) -> List[Dict[str, str]]:
    prompt = f"""
    Atue como Diretor de Criação de VSL de alta conversão especializado no nicho: '{nicho}'.
    Crie um roteiro persuasivo e magnético sobre:
    - Nicho: {nicho}
    - Promessa Principal: {promessa}
    - Público-Alvo: {publico}
    
    Gere exatamente {num_cenas} cenas cronológicas.
    Para cada cena:
    1. "fala": Frase falada em português (curta, de 10 a 16 palavras, impactante).
    2. "termo_video": Termo em INGLÊS de 2 a 4 palavras para buscar vídeos em HD no Pexels que retratem exatamente o nicho '{nicho}'.
    
    Retorne estritamente um JSON:
    {{
        "cenas": [
            {{"fala": "...", "termo_video": "..."}}
        ]
    }}
    """
    resp = executar_prompt_ia(prompt, formato_json=True, temperatura=0.4)
    termo_generico = re.sub(r'[^a-zA-Z0-9\s]', '', nicho).strip()
    try:
        dados = json.loads(resp)
        cenas_raw = dados.get("cenas", [])
        cenas_limpas = []
        for c in cenas_raw:
            if isinstance(c, dict):
                fala = sanitizar_texto(c.get("fala", "")).strip()
                termo = sanitizar_texto(c.get("termo_video", termo_generico)).strip()
                if fala:
                    cenas_limpas.append({"fala": fala, "termo_video": termo})
        return cenas_limpas if cenas_limpas else [{"fala": promessa, "termo_video": termo_generico}]
    except Exception:
        return [
            {"fala": f"Descubra o método definitivo sobre {nicho}.", "termo_video": termo_generico},
            {"fala": promessa, "termo_video": f"{termo_generico} professional"},
            {"fala": "Aprenda o passo a passo testado para ter resultados reais.", "termo_video": f"{termo_generico} lifestyle"}
        ]

def gerar_roteiro_apresentacao_3min_ia(
    nome_produto: str,
    nicho: str,
    promessa: str,
    publico: str,
    oferta_cta: str
) -> List[Dict[str, str]]:
    prompt = f"""
    Atue como Especialista em Lançamentos Digitais e Diretor de Vídeo de Vendas (Pitch de 3 Minutos).
    Crie o roteiro completo de apresentação e venda do produto:
    - Nome do Produto: {nome_produto}
    - Nicho: {nicho}
    - Grande Promessa: {promessa}
    - Público-Alvo: {publico}
    - Oferta e Condição Especial (CTA Final): {oferta_cta}

    ESTRUTURA OBRIGATÓRIA DOS 3 MINUTOS (13 Cenas cronológicas):
    - Cenas 1 e 2 (0 a 30s) [GANCHO & DOR]: O erro fatal e a dor comum de quem tenta sozinho sem o método certo.
    - Cenas 3 e 4 (30s a 60s) [HISTÓRIA & MECANISMO]: A virada de chave e a descoberta do método validado.
    - Cenas 5, 6 e 7 (60s a 105s) [REVELAÇÃO DO PRODUTO]: Apresentação oficial do {nome_produto}, estrutura interna e ferramentas práticas.
    - Cenas 8 e 9 (105s a 135s) [TRANSFORMAÇÃO REAL]: Os ganhos de velocidade, segurança e lucro que o cliente terá.
    - Cenas 10 e 11 (135s a 160s) [GARANTIA & RISCO ZERO]: Quebra total de risco, suporte e acesso imediato.
    - Cenas 12 e 13 (160s a 180s) [OFERTA & CHAMADA PARA COMPRA]: Condição especial, bônus, aviso de urgência e comando de clique no botão.

    REGRAS TÉCNICAS:
    1. Cada "fala" deve conter entre 28 e 35 palavras em português, com dicção natural, persuasiva e direta (totalizando ~420 palavras).
    2. Cada "termo_video" deve ser um termo de 2 a 3 palavras em INGLÊS para busca precisa no acervo em HD do Pexels.

    Retorne ESTRITAMENTE o JSON:
    {{
        "cenas": [
            {{"fala": "...", "termo_video": "..."}}
        ]
    }}
    """
    resp = executar_prompt_ia(prompt, formato_json=True, temperatura=0.35)
    termo_generico = re.sub(r'[^a-zA-Z0-9\s]', '', nicho).strip()
    try:
        dados = json.loads(resp)
        cenas_raw = dados.get("cenas", [])
        cenas_limpas = []
        for c in cenas_raw:
            if isinstance(c, dict) and c.get("fala"):
                cenas_limpas.append({
                    "fala": sanitizar_texto(c["fala"]).strip(),
                    "termo_video": sanitizar_texto(c.get("termo_video", termo_generico)).strip()
                })
        return cenas_limpas if len(cenas_limpas) >= 8 else cenas_raw
    except Exception:
        return [
            {"fala": f"Se você busca uma transformação real em {nicho}, preste muita atenção nos próximos três minutos.", "termo_video": f"{termo_generico} focus"},
            {"fala": f"Apresentamos oficialmente o {nome_produto}, desenvolvido para entregar resultados rápidos e previsíveis.", "termo_video": f"{termo_generico} success"},
            {"fala": f"Clique no botão oficial abaixo, aproveite esta condição especial e garanta seu acesso imediato hoje mesmo.", "termo_video": "click button buy now"}
        ]

# ==============================================================================
# 4. ENGENHARIA DE GERAÇÃO DO LIVRO TÉCNICO & ORDER BUMP (REPORTLAB)
# ==============================================================================
def gerar_blueprint_ebook_ia(tema: str, publico: str) -> dict:
    prompt = f"""
    Atue como Autoridade Máxima e Escritor de Livros Técnicos e Comerciais no tema: '{tema}'.
    Público: {publico}

    Planeje a ARQUITETURA MESTRA de um MANUAL TÉCNICO E COMERCIAL AVANÇADO.
    O livro terá exatamente 5 Módulos Temáticos de alta densidade técnica.
    
    Retorne ESTRITAMENTE o JSON:
    {{
        "titulo": "Título de autoridade sobre {tema}",
        "subtitulo": "Subtítulo com promessa e método prático",
        "termo_capa": "termo em inglês para capa no Pexels",
        "modulos": [
            {{"numero": 1, "titulo": "Fundamentos Estruturais & Preparação Inicial", "objetivo": "...", "topicos": ["...", "...", "..."]}},
            {{"numero": 2, "titulo": "Metodologia Operacional Passo a Passo", "objetivo": "...", "topicos": ["...", "...", "..."]}},
            {{"numero": 3, "titulo": "Parâmetros Críticos, Calibração & Eficiência", "objetivo": "...", "topicos": ["...", "...", "..."]}},
            {{"numero": 4, "titulo": "Inspeção de Qualidade, Tolerâncias & Padrão de Entrega", "objetivo": "...", "topicos": ["...", "...", "..."]}},
            {{"numero": 5, "titulo": "Escala de Produção, Custos & Maximização de Margem", "objetivo": "...", "topicos": ["...", "...", "..."]}}
        ]
    }}
    """
    resp = executar_prompt_ia(prompt, formato_json=True, temperatura=0.3)
    return json.loads(resp)

def gerar_introducao_profunda_ia(tema: str, publico: str, blueprint: dict) -> str:
    prompt = f"""
    Escreva a INTRODUÇÃO TÉCNICA E EXECUTIVA do manual: '{blueprint.get('titulo')}'.
    TEMA: {tema}
    PÚBLICO: {publico}
    EXIGÊNCIAS: Texto denso, analítico e sem clichês (entre 400 e 600 palavras).
    Retorne APENAS o texto em parágrafos.
    """
    return executar_prompt_ia(prompt, formato_json=False, temperatura=0.3)

def gerar_capitulo_individual_ia(tema: str, publico: str, modulo_info: dict) -> dict:
    prompt = f"""
    Atue como Consultor de Elite no tema '{tema}'.
    Escreva o CONTEÚDO TÉCNICO EXAUSTIVO DO MÓDULO {modulo_info.get('numero')}: '{modulo_info.get('titulo')}'.
    Tópicos: {', '.join(modulo_info.get('topicos', []))}. Público: {publico}
    Retorne ESTRITAMENTE o JSON:
    {{
        "numero": {modulo_info.get('numero')},
        "titulo": "{modulo_info.get('titulo')}",
        "alerta_tecnico": "Texto cirúrgico do alerta crítico...",
        "subsecoes": [
            {{"subtitulo": "...", "conteudo": "Parágrafo técnico denso..."}},
            {{"subtitulo": "...", "conteudo": "Parágrafo técnico denso..."}},
            {{"subtitulo": "...", "conteudo": "Parágrafo técnico denso..."}}
        ],
        "nome_tabela": "Matriz Técnica de Especificações e Parâmetros",
        "tabela_parametros": [
            {{"item": "...", "parametro": "...", "funcao": "..."}},
            {{"item": "...", "parametro": "...", "funcao": "..."}},
            {{"item": "...", "parametro": "...", "funcao": "..."}},
            {{"item": "...", "parametro": "...", "funcao": "..."}}
        ],
        "passos_operacionais": ["Passo 1 detalhado...", "Passo 2 detalhado...", "Passo 3 detalhado...", "Passo 4 detalhado...", "Passo 5 detalhado..."],
        "termo_busca_foto_processo": "termo em inglês",
        "termo_busca_foto_resultado": "termo em inglês",
        "legenda_resultado": "Legenda analítica do resultado visual..."
    }}
    """
    resp = executar_prompt_ia(prompt, formato_json=True, temperatura=0.3)
    return json.loads(resp)

def gerar_apendice_economico_ia(tema: str, publico: str) -> dict:
    prompt = f"""
    Escreva a seção final de 'DOSSIÊ CLÍNICO DE FALHAS & ENGENHARIA DE PRECIFICAÇÃO' para: '{tema}'.
    Retorne ESTRITAMENTE o JSON:
    {{
        "titulo": "Dossiê Clínico de Resolução de Falhas & Engenharia de Lucro",
        "falhas": [
            {{"defeito": "...", "causa_raiz": "...", "correcao": "..."}},
            {{"defeito": "...", "causa_raiz": "...", "correcao": "..."}},
            {{"defeito": "...", "causa_raiz": "...", "correcao": "..."}}
        ],
        "custos_matriz": [
            {{"componente": "Insumos Base", "valor_estimado": "Valor realista", "detalhe": "Composição básica"}},
            {{"componente": "Custos Operacionais", "valor_estimado": "Valor realista", "detalhe": "Rateio técnico"}},
            {{"componente": "Preço de Venda Sugerido", "valor_estimado": "Margem 100% a 180%", "detalhe": "Posicionamento premium"}}
        ],
        "conclusao_executiva": "Texto técnico e motivador de encerramento."
    }}
    """
    resp = executar_prompt_ia(prompt, formato_json=True, temperatura=0.3)
    return json.loads(resp)

def gerar_order_bump_ia(tema: str, publico: str, titulo_principal: str) -> dict:
    prompt = f"""
    Crie o PRODUTO COMPLEMENTAR (ORDER BUMP / ACELERADOR PRÁTICO) para acompanhar: '{titulo_principal}'.
    Retorne ESTRITAMENTE o JSON:
    {{
        "titulo_bump": "Checklist de Campo",
        "subtitulo_bump": "Protocolo Rápido de Execução e Auditoria",
        "copy_oferta_kiwify": "Adicione o checklist prático por apenas R$ 19,90 e garanta execução sem erros.",
        "termo_capa": "practical checklist tool",
        "checklist_rotina": [
            {{"fase": "Pré-Execução", "item": "Auditoria de insumos e setup inicial", "criterio_aprovacao": "100% conforme"}},
            {{"fase": "Durante Operação", "item": "Monitoramento de temperatura e tempo", "criterio_aprovacao": "Dentro da tolerância"}},
            {{"fase": "Inspeção Final", "item": "Conferência visual de acabamento", "criterio_aprovacao": "Padrão comercial"}}
        ],
        "tabela_emergencia": [
            {{"anomalia": "Desvio de consistência", "risco_imediato": "Perda de lote", "comando_correcao": "Ajustar proporção imediata"}}
        ]
    }}
    """
    resp = executar_prompt_ia(prompt, formato_json=True, temperatura=0.3)
    return json.loads(resp)

def pipeline_geracao_livro_completo(tema: str, publico: str, gerar_bump: bool = True, status_placeholder=None, progress_bar=None) -> dict:
    if status_placeholder: status_placeholder.write("📐 [1/6] Projetando arquitetura técnica...")
    if progress_bar: progress_bar.progress(0.10)
    blueprint = gerar_blueprint_ebook_ia(tema, publico)

    if status_placeholder: status_placeholder.write("✍ [2/6] Escrevendo introdução técnica...")
    if progress_bar: progress_bar.progress(0.20)
    introducao = gerar_introducao_profunda_ia(tema, publico, blueprint)

    modulos_completos = []
    total_mod = len(blueprint.get("modulos", []))
    for idx_m, mod in enumerate(blueprint.get("modulos", [])):
        if status_placeholder: status_placeholder.write(f"🔬 [3/6] Redigindo Módulo {mod.get('numero')}...")
        cap_dados = gerar_capitulo_individual_ia(tema, publico, mod)
        modulos_completos.append(cap_dados)
        if progress_bar: progress_bar.progress(0.20 + ((idx_m + 1) / total_mod) * 0.45)

    if status_placeholder: status_placeholder.write("📊 [4/6] Compilando Troubleshooting...")
    if progress_bar: progress_bar.progress(0.75)
    apendice = gerar_apendice_economico_ia(tema, publico)

    dados_bump = None
    if gerar_bump:
        if status_placeholder: status_placeholder.write("🎁 [5/6] Construindo Order Bump...")
        dados_bump = gerar_order_bump_ia(tema, publico, blueprint.get("titulo"))
        if progress_bar: progress_bar.progress(0.90)

    return {
        "titulo": blueprint.get("titulo"),
        "subtitulo": blueprint.get("subtitulo"),
        "termo_capa": blueprint.get("termo_capa"),
        "introducao": introducao,
        "modulos": modulos_completos,
        "apendice": apendice,
        "order_bump": dados_bump
    }

def traduzir_livro_completo_ia(dados_livro: dict, idioma_destino: str, progress_bar=None) -> dict:
    total_etapas = 2 + len(dados_livro.get("modulos", [])) + 1
    if dados_livro.get("order_bump"): total_etapas += 1
    etapa = 0

    titulo_tr = traduzir_texto_ia(dados_livro.get("titulo", ""), idioma_destino)
    subtitulo_tr = traduzir_texto_ia(dados_livro.get("subtitulo", ""), idioma_destino)
    etapa += 1
    if progress_bar: progress_bar.progress(etapa / total_etapas)

    intro_tr = traduzir_texto_ia(dados_livro.get("introducao", ""), idioma_destino)
    etapa += 1
    if progress_bar: progress_bar.progress(etapa / total_etapas)

    modulos_tr = []
    for mod in dados_livro.get("modulos", []):
        t_mod = traduzir_texto_ia(mod.get("titulo", ""), idioma_destino)
        alerta_tr = traduzir_texto_ia(mod.get("alerta_tecnico", ""), idioma_destino)
        legenda_tr = traduzir_texto_ia(mod.get("legenda_resultado", ""), idioma_destino)

        subsecoes_tr = []
        for sub in mod.get("subsecoes", []):
            subsecoes_tr.append({
                "subtitulo": traduzir_texto_ia(sub.get("subtitulo", ""), idioma_destino),
                "conteudo": traduzir_texto_ia(sub.get("conteudo", ""), idioma_destino)
            })

        tabela_tr = []
        for item in mod.get("tabela_parametros", []):
            tabela_tr.append({
                "item": traduzir_texto_ia(item.get("item", ""), idioma_destino),
                "parametro": traduzir_texto_ia(item.get("parametro", ""), idioma_destino),
                "funcao": traduzir_texto_ia(item.get("funcao", ""), idioma_destino)
            })

        passos_tr = [traduzir_texto_ia(p, idioma_destino) for p in mod.get("passos_operacionais", [])]
        modulos_tr.append({
            "numero": mod.get("numero"),
            "titulo": t_mod,
            "alerta_tecnico": alerta_tr,
            "subsecoes": subsecoes_tr,
            "nome_tabela": traduzir_texto_ia(mod.get("nome_tabela", "Tabela Técnica"), idioma_destino),
            "tabela_parametros": tabela_tr,
            "passos_operacionais": passos_tr,
            "termo_busca_foto_processo": mod.get("termo_busca_foto_processo", ""),
            "termo_busca_foto_resultado": mod.get("termo_busca_foto_resultado", ""),
            "legenda_resultado": legenda_tr
        })
        etapa += 1
        if progress_bar: progress_bar.progress(etapa / total_etapas)

    ap_raw = dados_livro.get("apendice", {})
    falhas_tr = [{"defeito": traduzir_texto_ia(f.get("defeito", ""), idioma_destino),
                  "causa_raiz": traduzir_texto_ia(f.get("causa_raiz", ""), idioma_destino),
                  "correcao": traduzir_texto_ia(f.get("correcao", ""), idioma_destino)} for f in ap_raw.get("falhas", [])]
    custos_tr = [{"componente": traduzir_texto_ia(c.get("componente", ""), idioma_destino),
                  "valor_estimado": c.get("valor_estimado", ""),
                  "detalhe": traduzir_texto_ia(c.get("detalhe", ""), idioma_destino)} for c in ap_raw.get("custos_matriz", [])]

    apendice_tr = {
        "titulo": traduzir_texto_ia(ap_raw.get("titulo", "Dossiê Clínico de Falhas"), idioma_destino),
        "falhas": falhas_tr,
        "custos_matriz": custos_tr,
        "conclusao_executiva": traduzir_texto_ia(ap_raw.get("conclusao_executiva", ""), idioma_destino)
    }
    etapa += 1

    bump_tr = None
    if dados_livro.get("order_bump"):
        b_raw = dados_livro["order_bump"]
        chk_tr = [{"fase": traduzir_texto_ia(chk.get("fase", ""), idioma_destino),
                   "item": traduzir_texto_ia(chk.get("item", ""), idioma_destino),
                   "criterio_aprovacao": traduzir_texto_ia(chk.get("criterio_aprovacao", ""), idioma_destino)} for chk in b_raw.get("checklist_rotina", [])]
        tab_em_tr = [{"anomalia": traduzir_texto_ia(em.get("anomalia", ""), idioma_destino),
                      "risco_imediato": traduzir_texto_ia(em.get("risco_imediato", ""), idioma_destino),
                      "comando_correcao": traduzir_texto_ia(em.get("comando_correcao", ""), idioma_destino)} for em in b_raw.get("tabela_emergencia", [])]
        bump_tr = {
            "titulo_bump": traduzir_texto_ia(b_raw.get("titulo_bump", ""), idioma_destino),
            "subtitulo_bump": traduzir_texto_ia(b_raw.get("subtitulo_bump", ""), idioma_destino),
            "copy_oferta_kiwify": traduzir_texto_ia(b_raw.get("copy_oferta_kiwify", ""), idioma_destino),
            "termo_capa": b_raw.get("termo_capa", ""),
            "checklist_rotina": chk_tr,
            "tabela_emergencia": tab_em_tr
        }
        etapa += 1

    if progress_bar: progress_bar.progress(1.0)
    return {
        "titulo": titulo_tr, "subtitulo": subtitulo_tr, "termo_capa": dados_livro.get("termo_capa", ""),
        "introducao": intro_tr, "modulos": modulos_tr, "apendice": apendice_tr, "order_bump": bump_tr
    }

class NumeradorPaginas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pages = []
    def showPage(self):
        self.pages.append(dict(self.__dict__))
        self._startPage()
    def save(self):
        num_paginas = len(self.pages)
        for page in self.pages:
            self.__dict__.update(page)
            self.draw_footer(num_paginas)
            super().showPage()
        super().save()
    def draw_footer(self, page_count):
        if self._pageNumber > 1:
            self.saveState()
            self.setFont("Helvetica-Bold", 8.5)
            self.setFillColor(colors.HexColor("#64748B"))
            self.drawString(36, 18, "MANUAL DE ENGENHARIA & PROCEDIMENTOS | EDIÇÃO PROFISSIONAL")
            texto_pag = f"Página {self._pageNumber} de {page_count}"
            self.drawRightString(576, 18, texto_pag)
            self.setStrokeColor(colors.HexColor("#CBD5E1"))
            self.setLineWidth(0.6)
            self.line(36, 26, 576, 26)
            self.restoreState()

class NumeradorPaginasBump(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pages = []
    def showPage(self):
        self.pages.append(dict(self.__dict__))
        self._startPage()
    def save(self):
        num_paginas = len(self.pages)
        for page in self.pages:
            self.__dict__.update(page)
            self.draw_footer(num_paginas)
            super().showPage()
        super().save()
    def draw_footer(self, page_count):
        self.saveState()
        self.setFont("Helvetica-Bold", 8.5)
        self.setFillColor(colors.HexColor("#64748B"))
        self.drawString(36, 16, "CADERNO DE EXECUÇÃO & CHECKLIST OPERACIONAL | USO PRÁTICO")
        texto_pag = f"Pág. {self._pageNumber} de {page_count}"
        self.drawRightString(576, 16, texto_pag)
        self.setStrokeColor(colors.HexColor("#CBD5E1"))
        self.setLineWidth(0.6)
        self.line(36, 24, 576, 24)
        self.restoreState()

def buscar_foto_pexels(query: str, pexels_key: str, dest_path: str) -> bool:
    if not pexels_key or not query: return False
    try:
        url = f"https://api.pexels.com/v1/search?query={requests.utils.quote(query)}&per_page=1&orientation=landscape"
        headers = {"Authorization": pexels_key}
        res = requests.get(url, headers=headers, timeout=12)
        if res.status_code == 200:
            data = res.json()
            if data.get("photos"):
                img_url = data["photos"][0]["src"]["large"]
                img_data = requests.get(img_url, timeout=12).content
                with open(dest_path, "wb") as f: f.write(img_data)
                return True
    except Exception:
        pass
    return False

def recortar_foto_proporcional(orig_path: str, dest_path: str, target_w: int, target_h: int) -> bool:
    if not os.path.exists(orig_path): return False
    try:
        with PILImage.open(orig_path) as img:
            img_rgb = img.convert("RGB")
            img_cortada = ImageOps.fit(img_rgb, (target_w, target_h), method=PILImage.Resampling.LANCZOS)
            img_cortada.save(dest_path, "JPEG", quality=92)
        return True
    except Exception:
        return False

def compilar_pdf_livro_tecnico(dados_livro: dict, pexels_key: str, caminho_pdf: str) -> str:
    doc = SimpleDocTemplate(caminho_pdf, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=38, bottomMargin=36)
    styles = getSampleStyleSheet()
    cor_azul = colors.HexColor("#1D4ED8")
    cor_primaria = colors.HexColor("#0F172A")

    estilo_capa_tit = ParagraphStyle('CapaTitulo', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=26, leading=32, textColor=cor_azul, alignment=1, spaceAfter=10)
    estilo_capa_sub = ParagraphStyle('CapaSub', parent=styles['Normal'], fontName='Helvetica', fontSize=13, leading=17, textColor=cor_primaria, alignment=1, spaceAfter=18)
    estilo_h1 = ParagraphStyle('TitCap', parent=styles['Heading1'], fontName='Helvetica-Bold', fontSize=18, leading=22, textColor=cor_azul, spaceBefore=14, spaceAfter=6, keepWithNext=True)
    estilo_h2 = ParagraphStyle('TitSec', parent=styles['Heading2'], fontName='Helvetica-Bold', fontSize=13, leading=17, textColor=cor_primaria, spaceBefore=10, spaceAfter=4, keepWithNext=True)
    estilo_corpo = ParagraphStyle('CorpoTexto', parent=styles['Normal'], fontName='Helvetica', fontSize=11, leading=15, textColor=colors.HexColor("#1E293B"), spaceAfter=6, alignment=4)
    estilo_celula = ParagraphStyle('Cel', parent=styles['Normal'], fontName='Helvetica', fontSize=9.5, leading=13, textColor=cor_primaria)
    estilo_celula_h = ParagraphStyle('CelH', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, leading=13.5, textColor=colors.white)

    flowables = [
        Spacer(1, 20),
        Paragraph(dados_livro.get("titulo", "Manual Técnico"), estilo_capa_tit),
        Paragraph(dados_livro.get("subtitulo", "Guia Operacional"), estilo_capa_sub)
    ]
    flowables.append(Spacer(1, 15))
    flowables.append(PageBreak())

    flowables.append(Paragraph("Sumário Executivo", estilo_h1))
    flowables.append(HRFlowable(width="100%", thickness=1, color=cor_azul, spaceAfter=10))
    sumario_data = [[Paragraph("<b>Seção</b>", estilo_celula_h), Paragraph("<b>Módulo</b>", estilo_celula_h)]]
    for mod in dados_livro.get("modulos", []):
        sumario_data.append([Paragraph(f"Módulo {mod.get('numero')}", estilo_celula), Paragraph(mod.get("titulo", ""), estilo_celula)])
    tab_s = Table(sumario_data, colWidths=[110, 430])
    tab_s.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), cor_azul), ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1"))]))
    flowables.append(tab_s)
    flowables.append(PageBreak())

    flowables.append(Paragraph("Introdução Geral", estilo_h1))
    for p in dados_livro.get("introducao", "").split("\n"):
        if p.strip(): flowables.append(Paragraph(p.strip(), estilo_corpo))

    for mod in dados_livro.get("modulos", []):
        flowables.append(Spacer(1, 10))
        flowables.append(Paragraph(f"Módulo {mod.get('numero')}: {mod.get('titulo')}", estilo_h1))
        for sub in mod.get("subsecoes", []):
            flowables.append(Paragraph(sub.get("subtitulo", ""), estilo_h2))
            for p_sub in sub.get("conteudo", "").split("\n"):
                if p_sub.strip(): flowables.append(Paragraph(p_sub.strip(), estilo_corpo))

    doc.build(flowables, canvasmaker=NumeradorPaginas)
    return caminho_pdf

def compilar_pdf_order_bump(dados_bump: dict, pexels_key: str, caminho_pdf: str) -> str:
    doc = SimpleDocTemplate(caminho_pdf, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=32, bottomMargin=30)
    styles = getSampleStyleSheet()
    cor_verde = colors.HexColor("#059669")
    estilo_tit = ParagraphStyle('TitBump', parent=styles['Heading1'], fontName='Helvetica-Bold', fontSize=18, leading=22, textColor=cor_verde, alignment=1)
    estilo_corpo = ParagraphStyle('CorpoBump', parent=styles['Normal'], fontName='Helvetica', fontSize=10, leading=14)

    flowables = [
        Paragraph(f"📋 {dados_bump.get('titulo_bump', 'Checklist Operacional')}", estilo_tit),
        Spacer(1, 10)
    ]
    for chk in dados_bump.get("checklist_rotina", []):
        flowables.append(Paragraph(f"• <b>[{chk.get('fase')}]</b> {chk.get('item')} ({chk.get('criterio_aprovacao')})", estilo_corpo))
    doc.build(flowables, canvasmaker=NumeradorPaginasBump)
    return caminho_pdf

# ==============================================================================
# 5. PROCESSAMENTO DE VÍDEO (TTS, PEXELS, CONCAT E FUSÃO MASTER)
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

def obter_duracao_audio(audio_path: str) -> float:
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", audio_path]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return float(res.stdout.strip())
    except Exception:
        return 4.0

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
                f"drawtext=textfile='{legenda_path_escapado}':fontcolor=white:fontsize={tam_fonte}:box=1:boxcolor=black@0.80:boxborderw=16:line_spacing=12:x=(w-text_w)/2:y={pos_y_legenda}"
            )
            cmd = [
                "ffmpeg", "-y", "-stream_loop", "-1", "-i", v_raw_path, "-i", a_path,
                "-map", "0:v:0", "-map", "1:a:0", "-t", f"{duracao:.2f}", "-vf", vf,
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "22", "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2", "-pix_fmt", "yuv420p", cena_out
            ]
        else:
            vf = (
                f"setsar=1,fps=30,drawtext=textfile='{legenda_path_escapado}':fontcolor=white:fontsize={tam_fonte+4}:box=1:boxcolor=blue@0.65:boxborderw=20:line_spacing=14:x=(w-text_w)/2:y=(h-text_h)/2"
            )
            cmd = [
                "ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=0x0F172A:s={res_w}x{res_h}:d={duracao:.2f}", "-i", a_path,
                "-map", "0:v:0", "-map", "1:a:0", "-t", f"{duracao:.2f}", "-vf", vf,
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "22", "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2", "-pix_fmt", "yuv420p", cena_out
            ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        cenas_clipes.append(cena_out)
        if progress_bar: progress_bar.progress((idx + 0.8) / total)

    concat_txt_path = os.path.join(DIR_VSL, f"concat_{int(time.time())}.txt")
    with open(concat_txt_path, "w", encoding="utf-8") as f:
        for c in cenas_clipes: f.write(f"file '{c.replace(os.sep, '/')}'\n")

    vsl_sem_trilha = os.path.join(DIR_VSL, f"vsl_base_{int(time.time())}.mp4")
    cmd_concat = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_txt_path, "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2", vsl_sem_trilha]
    subprocess.run(cmd_concat, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    vsl_final = os.path.join(DIR_VSL, f"vsl_final_{int(time.time())}.mp4")
    if musica_fundo_path and os.path.exists(musica_fundo_path):
        cmd_final = [
            "ffmpeg", "-y", "-i", vsl_sem_trilha, "-stream_loop", "-1", "-i", musica_fundo_path,
            "-filter_complex", f"[1:a]volume={volume_musica}[bg];[0:a][bg]amix=inputs=2:duration=first:dropout_transition=2[aout]",
            "-map", "0:v", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", vsl_final
        ]
        subprocess.run(cmd_final, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    else:
        vsl_final = vsl_sem_trilha
    return vsl_final

def dublar_roteiro_e_renderizar_vsl(
    cenas_originais: List[Dict[str, str]], idioma_alvo: str, plataforma_nome: str, voz: str, pexels_key: str,
    musica_fundo_path: Optional[str] = None, volume_musica: float = 0.08, marca_dagua: Optional[str] = None, progress_bar = None
) -> Tuple[str, List[Dict[str, str]]]:
    cenas_traduzidas = []
    total = len(cenas_originais)
    for idx, c in enumerate(cenas_originais):
        fala = traduzir_texto_ia(c.get("fala", ""), idioma_alvo)
        cenas_traduzidas.append({"fala": fala, "termo_video": c.get("termo_video", "business")})
        if progress_bar: progress_bar.progress((idx + 1) / (total * 2))

    vid = renderizar_vsl_completa(cenas_traduzidas, plataforma_nome, voz, pexels_key, musica_fundo_path, volume_musica, marca_dagua, progress_bar)
    return vid, cenas_traduzidas

# ==============================================================================
# MOTOR DE FUSÃO DE VÍDEOS (27S + 2-3MIN COM TRILHA EM LOOP SEGURO)
# ==============================================================================
def fundir_videos_com_trilha(
    video1_path: str,
    video2_path: str,
    output_path: str,
    musica_path: Optional[str] = None,
    volume_musica: float = 0.08,
    plataforma: str = "TikTok (Ads / Orgânico 9:16)"
) -> str:
    config = PRESETS_PLATAFORMAS.get(plataforma, PRESETS_PLATAFORMAS["TikTok (Ads / Orgânico 9:16)"])
    w, h = config["resolucao"]

    dur_v1 = obter_duracao_audio(video1_path)
    dur_v2 = obter_duracao_audio(video2_path)
    dur_total = dur_v1 + dur_v2

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
            "ffmpeg", "-y",
            "-i", video1_path,
            "-i", video2_path,
            "-stream_loop", "-1", "-i", musica_path,
            "-filter_complex", filter_complex,
            "-map", "[vcat]", "-map", "[aout]",
            "-t", f"{dur_total:.2f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", output_path
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
            "ffmpeg", "-y",
            "-i", video1_path,
            "-i", video2_path,
            "-filter_complex", filter_complex,
            "-map", "[vcat]", "-map", "[aout]",
            "-t", f"{dur_total:.2f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", output_path
        ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    return output_path

# ==============================================================================
# MOTOR TIKTOK MARKETING API COM MACROS DINÂMICAS & LANDING PAGE COM REPASSE
# ==============================================================================
TIKTOK_API_BASE = "https://business-api.tiktok.com/open_api/v1.3"

def disparar_campanha_tiktok_completa(
    advertiser_id: str, access_token: str, video_path: str, campaign_name: str,
    copy_text: str, landing_page_url: str, orcamento_diario: float, identity_id: Optional[str] = None
) -> dict:
    headers = {"Access-Token": access_token}
    headers_json = {"Access-Token": access_token, "Content-Type": "application/json"}
    if not os.path.exists(video_path): raise FileNotFoundError(f"Arquivo de vídeo não encontrado em: {video_path}")

    # 1. Upload do Vídeo
    url_upload = f"{TIKTOK_API_BASE}/file/video/ad/upload/"
    with open(video_path, "rb") as vf:
        res_upload = requests.post(url_upload, headers=headers, data={"advertiser_id": advertiser_id, "upload_type": "UPLOAD_BY_FILE"}, files={"video_file": vf}).json()
    if res_upload.get("code") != 0: raise Exception(f"Erro no Upload do Vídeo: {res_upload.get('message')}")
    video_id = res_upload["data"]["video_id"]

    # 2. Criar Campanha
    res_camp = requests.post(
        f"{TIKTOK_API_BASE}/campaign/create/", headers=headers_json,
        json={"advertiser_id": advertiser_id, "campaign_name": campaign_name, "objective_type": "WEB_CONVERSIONS", "budget_mode": "BUDGET_MODE_DYNAMIC"}
    ).json()
    if res_camp.get("code") != 0: raise Exception(f"Erro ao criar Campanha: {res_camp.get('message')}")
    campaign_id = res_camp["data"]["campaign_id"]

    # 3. Criar Ad Group
    data_formatada = (datetime.now(timezone.utc) + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
    payload_adgroup = {
        "advertiser_id": advertiser_id, "campaign_id": campaign_id, "adgroup_name": f"Grupo - {campaign_name}",
        "placement_type": "PLACEMENT_TYPE_NORMAL", "placements": ["PLACEMENT_TIKTOK"], "location_ids": ["6252001"],
        "budget_mode": "BUDGET_MODE_DAY", "budget": orcamento_diario, "schedule_type": "SCHEDULE_FROM_NOW",
        "schedule_start_time": data_formatada, "billing_event": "OCPM", "bid_type": "BID_TYPE_NO_BID", "optimization_goal": "CLICK"
    }
    res_adgroup = requests.post(f"{TIKTOK_API_BASE}/adgroup/create/", headers=headers_json, json=payload_adgroup).json()
    if res_adgroup.get("code") != 0: raise Exception(f"Erro ao criar AdGroup: {res_adgroup.get('message')}")
    adgroup_id = res_adgroup["data"]["adgroup_id"]

    # 4. Criar Anúncio com INJEÇÃO AUTOMÁTICA DE UTMS DINÂMICAS DO TIKTOK E SRC KIWIFY
    separador = "&" if "?" in landing_page_url else "?"
    url_com_utms = (
        f"{landing_page_url}{separador}"
        f"utm_source=tiktok"
        f"&utm_medium=cpc"
        f"&utm_campaign=__CAMPAIGN_NAME__"
        f"&utm_term=__AID_NAME__"
        f"&utm_content=__CID__"
        f"&src=__CAMPAIGN_NAME__|__CID__"
    )

    criativo = {
        "ad_name": f"Criativo - {campaign_name}",
        "ad_format": "SINGLE_VIDEO",
        "video_id": video_id,
        "ad_text": copy_text[:100],
        "call_to_action": "LEARN_MORE",
        "landing_page_url": url_com_utms
    }
    if identity_id and identity_id.strip():
        criativo["identity_type"] = "CUSTOMIZED_USER"
        criativo["identity_id"] = identity_id.strip()

    res_ad = requests.post(f"{TIKTOK_API_BASE}/ad/create/", headers=headers_json, json={"advertiser_id": advertiser_id, "adgroup_id": adgroup_id, "creatives": [criativo]}).json()
    if res_ad.get("code") != 0: raise Exception(f"Erro ao publicar Anúncio: {res_ad.get('message')}")

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

    // Desbloqueio de áudio com clique
    overlay.addEventListener('click', () => {{
      video.muted = false;
      video.play();
      overlay.style.display = 'none';
    }});

    // Persistência de estado da oferta
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

    // REPASSE AUTOMÁTICO DE UTMS DO TIKTOK PARA O CHECKOUT DA KIWIFY
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
    "miner_dores": "Medo de perder matéria-prima, insegurança na precificação e dificuldade em atrair clientes",
    "miner_google_ads": "",
    "miner_dossie": "",
    "vsl_input_tema": "Método Confeitaria Lucrativa & Bolos Caseiros",
    "vsl_input_promessa": "Domine as receitas mais pedidas e fature da cozinha da sua casa",
    "vsl_input_publico": "Mulheres e empreendedoras que buscam renda extra com doces",
    "vsl_plataforma_ativa": "TikTok (Ads / Orgânico 9:16)",
    "vsl_musica_ativa": None,
    "vsl_marca_ativa": "",
    "ap_prod_nome": "Método Confeitaria Lucrativa & Bolos Caseiros",
    "ap_prod_nicho": "Confeitaria Lucrativa & Bolos Caseiros",
    "ap_prod_promessa": "Domine as receitas mais pedidas e fature da cozinha da sua casa",
    "ap_prod_publico": "Mulheres e empreendedoras que buscam renda extra com doces",
    "ap_prod_oferta": "Apenas R$ 97,00 com acesso vitalício, 3 bônus exclusivos e 7 dias de garantia",
    "ap_plataforma_ativa": "TikTok (Ads / Orgânico 9:16)",
    "ap_marca_dagua": "",
    "ebook_input_tema": "Manual Prático: Confeitaria Lucrativa & Bolos Caseiros",
    "ebook_input_publico": "Mulheres e empreendedoras que buscam renda extra com doces"
}

for chave_k, valor_v in ESTADOS_INICIAIS.items():
    if chave_k not in st.session_state:
        st.session_state[chave_k] = valor_v
    elif isinstance(valor_v, str) and not isinstance(st.session_state[chave_k], str):
        st.session_state[chave_k] = sanitizar_texto(st.session_state[chave_k])

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

    email_digitado = st.text_input("Seu E-mail Cadastrado:", value=st.session_state["email_usuario_ativo"], key="sidebar_email_input").lower().strip()
    if email_digitado and email_digitado != st.session_state["email_usuario_ativo"]:
        st.session_state["email_usuario_ativo"] = email_digitado

    email_usuario = st.session_state["email_usuario_ativo"]
    dados_user = obter_dados_usuario(email_usuario)
    saldo_atual = dados_user["saldo"]

    col_s1, col_s2 = st.columns(2)
    with col_s1: st.metric("Créditos", f"{saldo_atual} cr")
    with col_s2: st.metric("Compras", dados_user["total_compras"])

    st.markdown("---")
    st.caption("Status das APIs:")
    st.write("• Supabase:", "🟢 Ativo" if supabase_client else "🔴 Pendente")
    st.write("• OpenAI:", "🟢 Ativo" if OPENAI_API_KEY else "🔴 Ausente")
    st.write("• Gemini:", "🟢 Ativo" if GEMINI_API_KEY else "🔴 Ausente")
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
    st.markdown("## 🔍 1. Minerador de Nicho com Campos Automáticos & Editáveis")
    st.caption("A IA gera a estratégia completa e preenche os campos abaixo.")

    NICHOS_PREDEFINIDOS = [
        "🎂 Confeitaria Lucrativa & Bolos Caseiros",
        "🐕 Adestramento Canino & Comportamento Pet",
        "🍞 Gastronomia & Pães Sem Glúten",
        "💰 Renda Extra & Milhas Aéreas",
        "🌱 Jardinagem, Suculentas & Hortas em Apartamento",
        "✍️ Digitar Nicho Personalizado (Manual)..."
    ]
    col_m1, col_m2 = st.columns([2, 1])
    with col_m1:
        nicho_sel = st.selectbox("Selecione um Nicho ou Digite o Seu:", NICHOS_PREDEFINIDOS, key="miner_nicho_sel")
    with col_m2:
        profundidade = st.selectbox("Profundidade:", ["Dossiê Completo de Lançamento", "Raio-X Rápido de Dores & Promessas"], key="miner_profundidade")

    nicho_final = nicho_sel
    if "Manual" in nicho_sel:
        nicho_manual = st.text_input("Digite o Nicho:", placeholder="Ex: Fabricação de trufas gourmet", key="miner_nicho_manual")
        if nicho_manual.strip(): nicho_final = nicho_manual.strip()

    st.info(f"🎯 **Nicho Selecionado:** `{nicho_final}`")

    if st.button("🚀 Analisar Nicho & Gerar Campos Automáticos", type="primary", key="btn_minerar_nicho"):
        with st.spinner("Minerando dados e estruturando mecanismo..."):
            try:
                for k in ["video_vsl_pronto", "roteiro_vsl", "video_pitch_pronto", "roteiro_pitch_3min", "video_master_fundido"]:
                    st.session_state.pop(k, None)
                resultado_miner = minerar_nicho_profundo_ia(nicho_final, profundidade)

                st.session_state["nicho_pesquisado_nome"] = sanitizar_texto(nicho_final)
                st.session_state["miner_nome_produto"] = sanitizar_texto(resultado_miner.get("nome_produto", nicho_final))
                st.session_state["miner_promessa"] = sanitizar_texto(resultado_miner.get("grande_promessa", f"Domine {nicho_final}"))
                st.session_state["miner_publico"] = sanitizar_texto(resultado_miner.get("publico_alvo", "Iniciantes..."))
                st.session_state["miner_mecanismo"] = sanitizar_texto(resultado_miner.get("mecanismo_unico", "Método Passo a Passo"))
                st.session_state["miner_oferta"] = sanitizar_texto(resultado_miner.get("oferta_cta", "Apenas R$ 97,00 com garantia"))
                st.session_state["miner_dores"] = sanitizar_texto(resultado_miner.get("dores_objecoes", ""))
                st.session_state["miner_google_ads"] = sanitizar_texto(resultado_miner.get("campanha_google_ads", ""))
                st.session_state["miner_dossie"] = sanitizar_texto(resultado_miner.get("dossie_markdown", ""))
                sincronizar_campos_mineracao()
                st.success("✅ Nicho minerado com sucesso!")
                st.rerun()
            except Exception as err:
                st.error(f"Erro na análise: {err}")

    st.markdown("---")
    st.markdown("### ✏️ Arquitetura do Produto:")
    col_ed1, col_ed2 = st.columns(2)
    with col_ed1:
        st.text_input("🏷️ Nome do Produto:", key="miner_nome_produto", on_change=sincronizar_campos_mineracao)
        st.text_input("⚡ Grande Promessa:", key="miner_promessa", on_change=sincronizar_campos_mineracao)
        st.text_input("🔑 Mecanismo Único:", key="miner_mecanismo", on_change=sincronizar_campos_mineracao)
    with col_ed2:
        st.text_input("🎯 Público-Alvo:", key="miner_publico", on_change=sincronizar_campos_mineracao)
        st.text_input("💰 Condição da Oferta:", key="miner_oferta", on_change=sincronizar_campos_mineracao)

    st.session_state["miner_dores"] = sanitizar_texto(st.session_state.get("miner_dores", ""))
    st.text_area("⚡ Dores & Objeções:", key="miner_dores", height=85)

    if st.button("🔄 Sincronizar Alterações com Todas as Abas", key="btn_sync_manual"):
        sincronizar_campos_mineracao()
        st.toast("Campos sincronizados com sucesso!", icon="✅")

    if st.session_state.get("miner_dossie"):
        st.markdown("---")
        aba_d1, aba_d2 = st.tabs(["📑 Dossiê Executivo Completo", "👑 Kit Pronto: Google Ads & YouTube"])
        with aba_d1:
            st.markdown(sanitizar_texto(st.session_state["miner_dossie"]))
        with aba_d2:
            conteudo_ads = sanitizar_texto(st.session_state.get("miner_google_ads", ""))
            st.text_area("📋 Conteúdo da Campanha:", value=conteudo_ads, height=280, key="txt_kit_ads")
            st.download_button(
                "⬇️ Baixar Kit de Campanha (.txt)",
                data=conteudo_ads,
                file_name=f"campanha_google_ads_{int(time.time())}.txt",
                mime="text/plain",
                use_container_width=True,
                key="btn_down_kit_ads"
            )

# ------------------------------------------------------------------------------
# ABA 2: CRIAR VSL CURTA (27S) & DUBLAGEM
# ------------------------------------------------------------------------------
with tab_vsl:
    st.markdown("## 🚀 2. Criador de VSL Curta (27s - Gancho de Tráfego)")
    st.caption("Cria o criativo de impacto vertical para veicular nos anúncios do TikTok Ads.")

    col_plat_vsl1, col_plat_vsl2 = st.columns([2, 1])
    with col_plat_vsl1:
        plataforma_vsl_sel = st.selectbox("🎯 Formato da VSL:", list(PRESETS_PLATAFORMAS.keys()), index=0, key="vsl_plataforma_sel")
    with col_plat_vsl2:
        st.info(f"📐 Resolução: `{PRESETS_PLATAFORMAS[plataforma_vsl_sel]['resolucao'][0]}x{PRESETS_PLATAFORMAS[plataforma_vsl_sel]['resolucao'][1]}`")

    col_v1, col_v2 = st.columns(2)
    with col_v1:
        tema_vsl = st.text_input("Tema / Produto:", key="vsl_input_tema")
        promessa_vsl = st.text_input("Promessa da VSL:", key="vsl_input_promessa")
    with col_v2:
        publico_vsl = st.text_input("Público-Alvo:", key="vsl_input_publico")
        qtd_cenas = st.slider("Quantidade de Cenas:", 3, 10, 5, key="vsl_slider_cenas")

    col_opt1, col_opt2 = st.columns(2)
    with col_opt1:
        marca_dagua_input = st.text_input("🔒 Marca d'água:", value=st.session_state.get("vsl_marca_ativa", ""), key="vsl_input_marca_dagua")
    with col_opt2:
        voz_sel = st.selectbox("Locução:", ["onyx (Forte/Masculina)", "alloy (Neutra)", "nova (Energética/Feminina)"], key="vsl_select_voz")
        voz_codigo = voz_sel.split()[0]

    if st.button("🎬 Gerar e Renderizar VSL Curta (20 cr)", type="primary", key="btn_render_vsl"):
        if saldo_atual < 20:
            st.error("❌ Saldo insuficiente!")
        else:
            barra_vsl = st.progress(0.0)
            with st.spinner("Renderizando cenas da VSL curta..."):
                try:
                    cenas_estruturadas = gerar_roteiro_vsl_ia(tema_vsl, promessa_vsl, publico_vsl, qtd_cenas)
                    st.session_state["roteiro_vsl"] = cenas_estruturadas
                    st.session_state["vsl_marca_ativa"] = marca_dagua_input
                    st.session_state["vsl_plataforma_ativa"] = plataforma_vsl_sel

                    video_pronto = renderizar_vsl_completa(
                        cenas=cenas_estruturadas, plataforma_nome=plataforma_vsl_sel, voz=voz_codigo,
                        pexels_key=PEXELS_API_KEY, musica_fundo_path=None, volume_musica=0.0,
                        marca_dagua=marca_dagua_input, progress_bar=barra_vsl
                    )
                    debitar_creditos_cloud(email_usuario, f"VSL Curta ({tema_vsl})", 20)
                    st.session_state["video_vsl_pronto"] = video_pronto
                    st.success("✅ VSL Curta finalizada com sucesso!")
                    st.rerun()
                except Exception as e_vsl:
                    st.error(f"Erro na renderização: {e_vsl}")

    if st.session_state.get("video_vsl_pronto") and os.path.exists(st.session_state["video_vsl_pronto"]):
        st.markdown("---")
        st.markdown("### 🎬 VSL Curta Original (27s):")
        st.video(st.session_state["video_vsl_pronto"])

        with open(st.session_state["video_vsl_pronto"], "rb") as f_v:
            st.download_button("⬇️ Baixar VSL Curta (.mp4)", data=f_v, file_name="vsl_curta_27s.mp4", mime="video/mp4", use_container_width=True)

        st.markdown("---")
        with st.container(border=True):
            st.markdown("### 🌐 Dublar VSL Curta em 36 Idiomas (DubfyAi Global)")
            col_d1, col_d2 = st.columns([2, 1])
            with col_d1:
                idioma_dub_sel = st.selectbox("Selecione o Idioma:", list(IDIOMAS_SISTEMA_36.keys()), key="vsl_dub_sel")
            with col_d2:
                st.write("")
                st.caption("Custo: 20 Créditos")
                btn_dub = st.button("🎙 Dublar Vídeo Curto (20 cr)", type="primary", use_container_width=True, key="btn_exec_dub_vsl")

            if btn_dub:
                if saldo_atual < 20:
                    st.error("❌ Saldo insuficiente!")
                else:
                    barra_d = st.progress(0.0)
                    with st.spinner("Dublando vídeo curto..."):
                        try:
                            nome_ling = IDIOMAS_SISTEMA_36[idioma_dub_sel]
                            v_dub, _ = dublar_roteiro_e_renderizar_vsl(
                                cenas_originais=st.session_state["roteiro_vsl"], idioma_alvo=nome_ling,
                                plataforma_nome=st.session_state.get("vsl_plataforma_ativa", plataforma_vsl_sel),
                                voz=voz_codigo, pexels_key=PEXELS_API_KEY, musica_fundo_path=None,
                                volume_musica=0.0, marca_dagua=st.session_state.get("vsl_marca_ativa", ""), progress_bar=barra_d
                            )
                            debitar_creditos_cloud(email_usuario, f"Dublagem VSL ({nome_ling})", 20)
                            st.session_state["video_dublado_pronto"] = v_dub
                            st.session_state["video_dublado_idioma"] = idioma_dub_sel
                            st.success(f"✅ Vídeo curto dublado em {idioma_dub_sel}!")
                            st.rerun()
                        except Exception as e_d:
                            st.error(f"Erro na dublagem: {e_d}")

            if st.session_state.get("video_dublado_pronto") and os.path.exists(st.session_state["video_dublado_pronto"]):
                st.markdown(f"#### 🎬 Vídeo Curto Dublado ({st.session_state.get('video_dublado_idioma')}):")
                st.video(st.session_state["video_dublado_pronto"])

# ------------------------------------------------------------------------------
# ABA 3: APRESENTAÇÃO DO PRODUTO (3 MIN) & DUBLAGEM
# ------------------------------------------------------------------------------
with tab_apresentacao:
    st.markdown("## 🎥 3. Apresentação do Produto (Pitch Longo de 2 a 3 Min)")
    st.caption("Gera o vídeo longo que educa o lead e apresenta a oferta.")

    col_plat1, col_plat2 = st.columns([2, 1])
    with col_plat1:
        plataforma_ap_sel = st.selectbox("🎯 Formato:", list(PRESETS_PLATAFORMAS.keys()), index=0, key="ap_plataforma_sel")
    with col_plat2:
        st.info(f"📐 Resolução: `{PRESETS_PLATAFORMAS[plataforma_ap_sel]['resolucao'][0]}x{PRESETS_PLATAFORMAS[plataforma_ap_sel]['resolucao'][1]}`")

    col_ap1, col_ap2 = st.columns(2)
    with col_ap1:
        prod_nome = st.text_input("Nome do Produto:", key="ap_prod_nome")
        prod_nicho = st.text_input("Nicho:", key="ap_prod_nicho")
        prod_promessa = st.text_input("Promessa Central:", key="ap_prod_promessa")
    with col_ap2:
        prod_publico = st.text_input("Público-Alvo:", key="ap_prod_publico")
        prod_oferta = st.text_input("Oferta / CTA:", key="ap_prod_oferta")
        marca_ap = st.text_input("Marca d'água:", value=st.session_state.get("vsl_marca_ativa", ""), key="ap_marca_dagua")

    voz_ap_sel = st.selectbox("Locução do Pitch:", ["onyx (Forte/Masculina)", "alloy (Neutra)", "nova (Energética/Feminina)"], key="ap_voz_sel")
    voz_ap_cod = voz_ap_sel.split()[0]

    if st.button("🎬 Gerar e Renderizar Apresentação de 3 Minutos (30 cr)", type="primary", key="btn_render_apresentacao"):
        if saldo_atual < 30:
            st.error("❌ Saldo insuficiente!")
        else:
            barra_ap = st.progress(0.0)
            status_ap = st.empty()
            try:
                status_ap.write("✍️ Estruturando 13 cenas com técnica de retenção...")
                roteiro_pitch = gerar_roteiro_apresentacao_3min_ia(prod_nome, prod_nicho, prod_promessa, prod_publico, prod_oferta)
                st.session_state["roteiro_pitch_3min"] = roteiro_pitch
                st.session_state["ap_plataforma_ativa"] = plataforma_ap_sel

                status_ap.write("🎥 Renderizando cortes e legendas...")
                video_pitch = renderizar_vsl_completa(
                    cenas=roteiro_pitch, plataforma_nome=plataforma_ap_sel, voz=voz_ap_cod,
                    pexels_key=PEXELS_API_KEY, musica_fundo_path=None, volume_musica=0.0,
                    marca_dagua=marca_ap, progress_bar=barra_ap
                )
                debitar_creditos_cloud(email_usuario, f"Apresentação ({prod_nome})", 30)
                st.session_state["video_pitch_pronto"] = video_pitch
                status_ap.empty()
                st.success("✅ Vídeo de Apresentação concluído!")
                st.rerun()
            except Exception as e_pitch:
                st.error(f"Erro: {e_pitch}")

    if st.session_state.get("video_pitch_pronto") and os.path.exists(st.session_state["video_pitch_pronto"]):
        st.markdown("---")
        st.markdown("### 🎬 Apresentação Original (Pitch Longo):")
        st.video(st.session_state["video_pitch_pronto"])

        with open(st.session_state["video_pitch_pronto"], "rb") as f_ap:
            st.download_button("⬇️ Baixar Apresentação (.mp4)", data=f_ap, file_name="apresentacao_pitch.mp4", mime="video/mp4", use_container_width=True)

        st.markdown("---")
        with st.container(border=True):
            st.markdown("### 🌐 Dublar Vídeo de Apresentação em 36 Idiomas (DubfyAi Global)")
            col_ap_d1, col_ap_d2 = st.columns([2, 1])
            with col_ap_d1:
                idioma_pitch_sel = st.selectbox("Selecione o Idioma para Dublar:", list(IDIOMAS_SISTEMA_36.keys()), key="ap_dub_sel")
            with col_ap_d2:
                st.write("")
                st.caption("Custo: 30 Créditos")
                btn_dub_pitch = st.button("🎙 Dublar Apresentação (30 cr)", type="primary", use_container_width=True, key="btn_exec_dub_ap")

            if btn_dub_pitch:
                if saldo_atual < 30:
                    st.error("❌ Saldo insuficiente!")
                else:
                    barra_ap_d = st.progress(0.0)
                    with st.spinner("Dublando apresentação de 3 minutos..."):
                        try:
                            nome_ling_ap = IDIOMAS_SISTEMA_36[idioma_pitch_sel]
                            v_pitch_dub, _ = dublar_roteiro_e_renderizar_vsl(
                                cenas_originais=st.session_state["roteiro_pitch_3min"], idioma_alvo=nome_ling_ap,
                                plataforma_nome=st.session_state.get("ap_plataforma_ativa", plataforma_ap_sel),
                                voz=voz_ap_cod, pexels_key=PEXELS_API_KEY, musica_fundo_path=None,
                                volume_musica=0.0, marca_dagua=st.session_state.get("ap_marca_dagua", ""), progress_bar=barra_ap_d
                            )
                            debitar_creditos_cloud(email_usuario, f"Dublagem Apresentação ({nome_ling_ap})", 30)
                            st.session_state["video_pitch_dublado_pronto"] = v_pitch_dub
                            st.session_state["video_pitch_dublado_idioma"] = idioma_pitch_sel
                            st.success(f"✅ Apresentação dublada com sucesso para {idioma_pitch_sel}!")
                            st.rerun()
                        except Exception as e_d_ap:
                            st.error(f"Erro na dublagem da apresentação: {e_d_ap}")

            if st.session_state.get("video_pitch_dublado_pronto") and os.path.exists(st.session_state["video_pitch_dublado_pronto"]):
                st.markdown(f"#### 🎬 Apresentação Dublada ({st.session_state.get('video_pitch_dublado_idioma')}):")
                st.video(st.session_state["video_pitch_dublado_pronto"])

# ------------------------------------------------------------------------------
# ABA 4: JUNÇÃO CONTÍNUA DOS VÍDEOS & TRILHA DE FUNDO
# ------------------------------------------------------------------------------
with tab_fusao:
    st.markdown("## 🎞️ 4. Junção Contínua dos Vídeos & Masterização de Áudio")
    st.caption("Emende o vídeo de 27s com a Apresentação gerando um arquivo contínuo com trilha sonora profissional em loop.")

    col_f1, col_f2 = st.columns(2)
    with col_f1:
        st.markdown("### 🎬 Vídeo 1 (Gancho de 27s)")
        v1_sessao = st.session_state.get("video_vsl_pronto")
        v1_escolha = st.radio("Origem do Vídeo 1:", ["Usar Vídeo da Aba 2 (27s)", "Fazer Upload MP4"], key="fusao_v1_orig")
        caminho_v1 = None
        if v1_escolha == "Usar Vídeo da Aba 2 (27s)":
            if v1_sessao and os.path.exists(v1_sessao):
                st.success("✅ Vídeo da Aba 2 carregado!")
                st.video(v1_sessao)
                caminho_v1 = v1_sessao
            else:
                st.warning("Gere o vídeo na Aba 2 primeiro.")
        else:
            up1 = st.file_uploader("Upload Vídeo 1:", type=["mp4"], key="fusao_up_v1")
            if up1:
                p_tmp1 = os.path.join(DIR_FUSAO, f"v1_up_{int(time.time())}.mp4")
                with open(p_tmp1, "wb") as f: f.write(up1.read())
                caminho_v1 = p_tmp1
                st.video(caminho_v1)

    with col_f2:
        st.markdown("### 🎬 Vídeo 2 (Apresentação 2-3 Min)")
        v2_sessao = st.session_state.get("video_pitch_pronto")
        v2_escolha = st.radio("Origem do Vídeo 2:", ["Usar Vídeo da Aba 3 (Apresentação)", "Fazer Upload MP4"], key="fusao_v2_orig")
        caminho_v2 = None
        if v2_escolha == "Usar Vídeo da Aba 3 (Apresentação)":
            if v2_sessao and os.path.exists(v2_sessao):
                st.success("✅ Apresentação da Aba 3 carregada!")
                st.video(v2_sessao)
                caminho_v2 = v2_sessao
            else:
                st.warning("Gere o vídeo na Aba 3 primeiro.")
        else:
            up2 = st.file_uploader("Upload Vídeo 2:", type=["mp4"], key="fusao_up_v2")
            if up2:
                p_tmp2 = os.path.join(DIR_FUSAO, f"v2_up_{int(time.time())}.mp4")
                with open(p_tmp2, "wb") as f: f.write(up2.read())
                caminho_v2 = p_tmp2
                st.video(caminho_v2)

    st.markdown("---")
    st.markdown("### 🎵 Configuração da Trilha de Fundo & Geometria")
    col_t1, col_t2, col_t3 = st.columns(3)
    with col_t1:
        opcoes_m = listar_musicas_locais()
        trilha_escolhida = st.selectbox("Trilha Sonora:", list(opcoes_m.keys()), key="fusao_trilha_m")
        caminho_trilha = opcoes_m[trilha_escolhida]
    with col_t2:
        vol_trilha = st.slider("Volume da Trilha de Fundo:", 0.02, 0.20, 0.08, 0.01)
    with col_t3:
        formato_fusao = st.selectbox("Formato de Exportação:", list(PRESETS_PLATAFORMAS.keys()), index=0, key="fusao_preset_fmt")

    if st.button("⚡ Executar Fusão Contínua com Trilha Sonora", type="primary", use_container_width=True):
        if not caminho_v1 or not os.path.exists(caminho_v1):
            st.error("Selecione ou envie o Vídeo 1 (27s).")
        elif not caminho_v2 or not os.path.exists(caminho_v2):
            st.error("Selecione ou envie o Vídeo 2 (Apresentação).")
        else:
            with st.spinner("Concatenando vídeos e aplicando trilha sonora calibrada..."):
                try:
                    nome_saida = f"vsl_master_fundida_{int(time.time())}.mp4"
                    destino_final = os.path.join(DIR_FUSAO, nome_saida)
                    vid_fundido = fundir_videos_com_trilha(
                        video1_path=caminho_v1, video2_path=caminho_v2, output_path=destino_final,
                        musica_path=caminho_trilha, volume_musica=vol_trilha, plataforma=formato_fusao
                    )
                    st.session_state["video_master_fundido"] = vid_fundido
                    st.success("🎉 Fusão concluída com sucesso! Áudio e cortes perfeitamente ajustados.")
                    st.rerun()
                except Exception as err_f:
                    st.error(f"Erro na fusão: {err_f}")

    if st.session_state.get("video_master_fundido") and os.path.exists(st.session_state["video_master_fundido"]):
        st.markdown("---")
        st.markdown("### 🎬 Vídeo Master Unificado:")
        st.video(st.session_state["video_master_fundido"])
        with open(st.session_state["video_master_fundido"], "rb") as f_mf:
            st.download_button(
                "⬇️ Baixar Vídeo Master Fundido (.mp4)", data=f_mf,
                file_name=os.path.basename(st.session_state["video_master_fundido"]),
                mime="video/mp4", type="primary", use_container_width=True
            )

# ------------------------------------------------------------------------------
# ABA 5: LIVRO TÉCNICO & ORDER BUMP COM TRADUÇÃO GLOBAL
# ------------------------------------------------------------------------------
with tab_ebook:
    st.markdown("## 📚 5. Gerador de Livro Técnico & Order Bump")
    col_e1, col_e2 = st.columns(2)
    with col_e1: tema_ebook = st.text_input("Tema Central:", key="ebook_input_tema")
    with col_e2: publico_ebook = st.text_input("Público-Alvo:", key="ebook_input_publico")
    gerar_bump_opt = st.checkbox("🎁 Gerar também Order Bump (Checklist Operacional)", value=True, key="chk_gerar_bump")

    if st.button("📖 Compilar Kit Digital Completo (.PDF) (10 cr)", type="primary", key="btn_render_ebook"):
        if saldo_atual < 10:
            st.error("❌ Saldo insuficiente!")
        else:
            prog_bar = st.progress(0.0)
            status_box = st.empty()
            try:
                dados_livro = pipeline_geracao_livro_completo(tema_ebook, publico_ebook, gerar_bump_opt, status_box, prog_bar)
                st.session_state["dados_livro_sessao"] = dados_livro

                nome_pdf = f"manual_tecnico_{int(time.time())}.pdf"
                caminho_pdf = os.path.join(DIR_EBOOKS, nome_pdf)
                compilar_pdf_livro_tecnico(dados_livro, PEXELS_API_KEY, caminho_pdf)
                st.session_state["pdf_ebook_pronto"] = caminho_pdf
                st.session_state["pdf_ebook_nome"] = nome_pdf

                if gerar_bump_opt and dados_livro.get("order_bump"):
                    nome_bump = f"order_bump_{int(time.time())}.pdf"
                    caminho_bump = os.path.join(DIR_EBOOKS, nome_bump)
                    compilar_pdf_order_bump(dados_livro["order_bump"], PEXELS_API_KEY, caminho_bump)
                    st.session_state["pdf_bump_pronto"] = caminho_bump
                    st.session_state["pdf_bump_nome"] = nome_bump

                debitar_creditos_cloud(email_usuario, f"Kit Digital ({tema_ebook})", 10)
                status_box.empty()
                st.success("✅ Kit Digital Compilado com Sucesso!")
                st.rerun()
            except Exception as e_eb:
                st.error(f"Erro: {e_eb}")

    if st.session_state.get("pdf_ebook_pronto") and os.path.exists(st.session_state["pdf_ebook_pronto"]):
        col_dw1, col_dw2 = st.columns(2)
        with col_dw1:
            with open(st.session_state["pdf_ebook_pronto"], "rb") as f_eb:
                st.download_button("⬇️ Baixar Manual (.PDF)", data=f_eb, file_name="manual_tecnico.pdf", mime="application/pdf", use_container_width=True)
        with col_dw2:
            if st.session_state.get("pdf_bump_pronto") and os.path.exists(st.session_state["pdf_bump_pronto"]):
                with open(st.session_state["pdf_bump_pronto"], "rb") as f_bp:
                    st.download_button("⬇️ Baixar Order Bump (.PDF)", data=f_bp, file_name="order_bump.pdf", mime="application/pdf", type="primary", use_container_width=True)

        st.markdown("---")
        with st.container(border=True):
            st.markdown("### 🌐 Tradução Global do Kit (36 Idiomas)")
            col_tr1, col_tr2 = st.columns([2, 1])
            with col_tr1:
                idioma_eb_sel = st.selectbox("Selecione o Idioma de Destino:", list(IDIOMAS_SISTEMA_36.keys()), key="eb_trad_sel")
            with col_tr2:
                st.write("")
                st.caption("Custo: 10 Créditos")
                btn_trad_eb = st.button("🌍 Traduzir Kit (10 cr)", type="primary", use_container_width=True, key="btn_exec_trad_ebook")

            if btn_trad_eb:
                if saldo_atual < 10:
                    st.error("❌ Saldo insuficiente!")
                else:
                    barra_eb_tr = st.progress(0.0)
                    with st.spinner("Traduzindo e diagramando PDFs em idioma estrangeiro..."):
                        try:
                            nome_ling_eb = IDIOMAS_SISTEMA_36[idioma_eb_sel]
                            dados_tr = traduzir_livro_completo_ia(st.session_state["dados_livro_sessao"], nome_ling_eb, progress_bar=barra_eb_tr)
                            caminho_tr = os.path.join(DIR_EBOOKS, f"manual_{int(time.time())}.pdf")
                            compilar_pdf_livro_tecnico(dados_tr, PEXELS_API_KEY, caminho_tr)
                            st.session_state["pdf_global_pronto"] = caminho_tr
                            st.session_state["pdf_global_lingua"] = idioma_eb_sel
                            debitar_creditos_cloud(email_usuario, f"Tradução Kit ({nome_ling_eb})", 10)
                            st.success(f"✅ Kit traduzido com sucesso para {idioma_eb_sel}!")
                            st.rerun()
                        except Exception as e_tr_eb:
                            st.error(f"Erro na tradução: {e_tr_eb}")

            if st.session_state.get("pdf_global_pronto") and os.path.exists(st.session_state["pdf_global_pronto"]):
                st.success(f"✅ Kit traduzido para: {st.session_state.get('pdf_global_lingua')}")
                with open(st.session_state["pdf_global_pronto"], "rb") as f_gtr:
                    st.download_button(f"⬇️ Baixar Manual em {st.session_state.get('pdf_global_lingua')} (.PDF)", data=f_gtr, file_name="manual_traduzido.pdf", mime="application/pdf", use_container_width=True)

# ------------------------------------------------------------------------------
# ABA 6: CENTRAL TIKTOK ADS & LANDING PAGE (COM UTMS AUTOMÁTICAS)
# ------------------------------------------------------------------------------
with tab_ads:
    st.markdown("## 🎯 6. Central TikTok Ads & Funil de Conversão")
    st.caption("Gere a Landing Page oficial com delay e faça o upload direto do vídeo na API com injeção automática de UTMs dinâmicas.")

    video_final_anuncio = (
        st.session_state.get("video_master_fundido") or
        st.session_state.get("video_vsl_pronto")
    )

    aba_tt_disp, aba_tt_lp = st.tabs(["🚀 Disparo no TikTok Ads", "🌐 Gerador da Landing Page (index.html)"])

    with aba_tt_disp:
        col_ad1, col_ad2 = st.columns([1.2, 1])
        with col_ad1:
            nome_camp = st.text_input("Nome da Campanha:", value=f"Campanha Conversão - {datetime.now().strftime('%d/%m')}")
            url_lp = st.text_input("URL da Landing Page de Destino:", placeholder="https://meusite.com/vsl")
            st.info("ℹ️ **Rastreamento Dinâmico:** As macros oficiais (`__CAMPAIGN_NAME__`, `__AID_NAME__`, `__CID__` e `src=...`) são injetadas automaticamente na URL ao publicar.")
            orcamento = st.number_input("Orçamento Diário (R$):", min_value=30.0, value=60.0, step=10.0)
            copy_ad = st.text_area("Texto do Anúncio:", value="Método revelado em menos de 3 minutos! Toque em Saiba Mais.")
            adv_id = st.text_input("Advertiser ID:", value=TIKTOK_ADVERTISER_ID)
            tok_ad = st.text_input("TikTok Access Token:", value=TIKTOK_ACCESS_TOKEN, type="password")
            identity_ad = st.text_input("Identity ID (Opcional):", placeholder="Ex: 7123456789012345678")

        with col_ad2:
            st.markdown("##### Vídeo Selecionado para a Campanha:")
            if video_final_anuncio and os.path.exists(video_final_anuncio):
                st.video(video_final_anuncio)
                dur = obter_duracao_audio(video_final_anuncio)
                st.info(f"⏱️ Duração do arquivo: **{dur:.1f} segundos**")
            else:
                st.warning("Nenhum vídeo fundido encontrado. Gere o vídeo na Aba 4.")

        if st.button("🚀 Publicar Campanha Completa no TikTok Ads", type="primary", use_container_width=True):
            if not tok_ad: st.error("Informe o Access Token do TikTok.")
            elif not url_lp: st.error("Informe a URL da Landing Page.")
            elif not video_final_anuncio or not os.path.exists(video_final_anuncio): st.error("Nenhum vídeo disponível.")
            else:
                with st.spinner("Publicando anúncio via TikTok Marketing API com UTMs dinâmicas..."):
                    try:
                        res = disparar_campanha_tiktok_completa(
                            advertiser_id=adv_id, access_token=tok_ad, video_path=video_final_anuncio,
                            campaign_name=nome_camp, copy_text=copy_ad, landing_page_url=url_lp,
                            orcamento_diario=orcamento, identity_id=identity_ad
                        )
                        st.success("🎉 Campanha criada e enviada com sucesso ao TikTok Ads!")
                        st.json(res)
                    except Exception as err:
                        st.error(f"Erro ao publicar: {err}")

    with aba_tt_lp:
        st.markdown("### 📄 Gerador da Landing Page Oficial do Funil")
        st.caption("A página já inclui o repasse automático de todos os parâmetros UTM e SRC da URL diretamente para o botão de compra.")
        col_lp1, col_lp2 = st.columns(2)
        with col_lp1:
            lp_tit = st.text_input("Título da Página:", value="Apresentação Exclusiva")
            lp_prom = st.text_input("Headline do Topo:", value=st.session_state.get("miner_promessa", "Descubra o Método Exato"))
            lp_v_url = st.text_input("URL Direta do Vídeo Hospedado (.mp4):", placeholder="https://meustorage.com/vsl_master.mp4")
        with col_lp2:
            lp_chk = st.text_input("Link de Pagamento (Kiwify):", placeholder="https://pay.kiwify.com.br/...")
            lp_delay = st.number_input("Tempo para Revelar Botão (Segundos):", value=147)
            lp_px = st.text_input("ID do Pixel do TikTok (Opcional):", placeholder="Ex: C9ABC12345DEF678")

        if lp_v_url and lp_chk:
            html_p = gerar_html_landing_page(
                titulo=lp_tit, promessa=lp_prom, url_video_mp4=lp_v_url,
                link_kiwify=lp_chk, delay_segundos=int(lp_delay), pixel_id=lp_px
            )
            st.download_button(
                "⬇️ Baixar index.html Pronto para Hospedagem", data=html_p,
                file_name="index.html", mime="text/html", type="primary", use_container_width=True
            )

# ------------------------------------------------------------------------------
# ABA 7: GESTÃO MASTER
# ------------------------------------------------------------------------------
with tab_master:
    st.markdown("## 👑 Painel de Gestão Master")
    if not supabase_client:
        st.warning("Conexão com o Supabase inativa ou pendente de chaves.")
    else:
        try:
            res_u = supabase_client.from_("usuarios").select("*").execute()
            usuarios_lista = res_u.data if res_u.data else []
            res_p = supabase_client.from("pedidos_kiwify").select("*").execute()
            pedidos_lista = res_p.data if res_p.data else []

            fat_total = sum(float(p.get("valor_pago", 0)) for p in pedidos_lista)
            cm1, cm2, cm3 = st.columns(3)
            with cm1: st.metric("Faturamento Kiwify", f"R$ {fat_total:,.2f}")
            with cm2: st.metric("Total de Clientes", len(usuarios_lista))
            with cm3: st.metric("Créditos Circulantes", sum(u.get("saldo_creditos", 0) for u in usuarios_lista))

            if pedidos_lista:
                st.dataframe(pedidos_lista, use_container_width=True)
        except Exception as e_m:
            st.error(f"Erro ao carregar dados: {e_m}")

import os
import re
import json
import time
import textwrap
import subprocess
import requests
from datetime import datetime
from typing import List, Dict, Tuple, Optional

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
ELEVENLABS_API_KEY = obter_credencial("ELEVENLABS_API_KEY")

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
    if not texto.strip():
        return ""
    prompt = f"""
    Atue como tradutor nativo de elite e copywriter sênior no idioma '{idioma_destino}'.
    Traduza e faça a TRANSCIAÇÃO do texto abaixo, mantendo a métrica comercial, persuasão e rigor técnico.

    REGRA DE OURO - LOCALIZAÇÃO FINANCEIRA & MOEDA:
    1. NUNCA mantenha valores em 'Reais' ou 'R$' para outros idiomas.
    2. NUNCA faça conversão 1 para 1 cega.
    3. Adapte valores para paridade crível de mercado (ex: US$ ou Euros para tickets médios realistas).
    4. Elimine gírias ou expressões locais brasileiras.

    Texto:
    "{texto}"

    Retorne estritamente o texto traduzido, sem aspas e sem explicações.
    """
    try:
        return executar_prompt_ia(prompt, formato_json=False, temperatura=0.25).strip()
    except Exception:
        return texto

def minerar_nicho_profundo_ia(nicho: str, profundidade: str) -> str:
    prompt = f"""
    Atue como Diretor de Aquisição e Especialista Sênior em Tráfego Pago, Copywriting e Engenharia de Produtos Digitais.
    Domínio absoluto de: Google Ads, Meta Ads, Kiwify e plataformas internacionais.
    
    Analise o seguinte nicho com rigor técnico:
    NICHO: "{nicho}"
    NÍVEL DE PROFUNDIDADE: {profundidade}
    
    Gere um dossiê executivo completo formatado em Markdown com as seguintes seções estruturadas:
    
    ### 1. 🎯 PÚBLICO-ALVO & NÍVEL DE CONSCIÊNCIA
    ### 2. ⚡ AS 3 MAIORES DORES OCULTAS & AS 3 PRINCIPAIS OBJEÇÕES
    ### 3. 💎 ARQUITETURA DO PRODUTO & MECANISMO ÚNICO
    - **Nome Sugerido do Produto:** (Nome comercial de alto impacto).
    - **A Grande Promessa:** (1 frase visceral de transformação).
    - **Mecanismo Único:** O método por trás da solução.
    ### 4. 👑 O PATRÃO GOOGLE ADS (KIT COMPLETO DE CAMPANHA)
    #### A) Palavras-Chave de Fundo de Funil (Correspondência de Frase e Exata)
    #### B) Lista de 10 Palavras-Chave Negativas Obrigatórias
    #### C) Anúncio Responsivo de Pesquisa (5 Títulos e 3 Descrições)
    #### D) Gancho para YouTube Ads (Primeiros 5 Segundos)
    ### 5. 💰 ESTRATÉGIA DE MONETIZAÇÃO & ESCALA (Preço Brasil, Exterior e Order Bump)
    """
    return executar_prompt_ia(prompt, formato_json=False, temperatura=0.35)

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
                fala = c.get("fala", "").strip()
                termo = c.get("termo_video", termo_generico).strip()
                if fala:
                    cenas_limpas.append({"fala": fala, "termo_video": termo})
        return cenas_limpas if cenas_limpas else [{"fala": promessa, "termo_video": termo_generico}]
    except Exception:
        return [
            {"fala": f"Descubra o método definitivo sobre {nicho}.", "termo_video": termo_generico},
            {"fala": promessa, "termo_video": f"{termo_generico} professional"},
            {"fala": "Aprenda o passo a passo testado para ter resultados reais.", "termo_video": f"{termo_generico} lifestyle"}
        ]

# ==============================================================================
# 4. ENGENHARIA DE GERAÇÃO MODULAR DE E-BOOK (DEEP CHAPTER PIPELINE)
# ==============================================================================
def gerar_blueprint_ebook_ia(tema: str, publico: str) -> dict:
    prompt = f"""
    Atue como Autoridade Máxima, Consultor Técnico Sênior e Escritor de Livros Técnicos e Comerciais no tema: '{tema}'.
    Público-alvo: {publico}

    Planeje a ARQUITETURA MESTRA (Blueprint) de um MANUAL TÉCNICO E COMERCIAL AVANÇADO com rigor profissional.
    O livro terá exatamente 5 Módulos Temáticos de alta densidade técnica.
    
    Defina:
    1. Título e subtítulo magnéticos com forte autoridade.
    2. Termo de busca em inglês para a foto da capa no Pexels.
    3. Para cada um dos 5 Módulos:
       - Número (1 a 5)
       - Título Técnico do Módulo
       - Objetivo Prático do Módulo
       - 3 Tópicos Obrigatórios a serem dissecados em profundidade

    Retorne ESTRITAMENTE o JSON:
    {{
        "titulo": "...",
        "subtitulo": "...",
        "termo_capa": "...",
        "modulos": [
            {{
                "numero": 1,
                "titulo": "...",
                "objetivo": "...",
                "topicos": ["...", "...", "..."]
            }},
            {{
                "numero": 2,
                "titulo": "...",
                "objetivo": "...",
                "topicos": ["...", "...", "..."]
            }},
            {{
                "numero": 3,
                "titulo": "...",
                "objetivo": "...",
                "topicos": ["...", "...", "..."]
            }},
            {{
                "numero": 4,
                "titulo": "...",
                "objetivo": "...",
                "topicos": ["...", "...", "..."]
            }},
            {{
                "numero": 5,
                "titulo": "...",
                "objetivo": "...",
                "topicos": ["...", "...", "..."]
            }}
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

    EXIGÊNCIAS:
    1. Texto denso, analítico e sem clichês (entre 400 e 600 palavras).
    2. Apresente os fundamentos científicos/lógicos do método.
    3. Demonstre por que a maioria falha ao tentar aplicar métodos amadores.
    4. Explique como a abordagem deste manual resolve a raiz do problema com previsibilidade.

    Retorne APENAS o texto puro em parágrafos separados por duas quebras de linha.
    """
    return executar_prompt_ia(prompt, formato_json=False, temperatura=0.3)

def gerar_capitulo_individual_ia(tema: str, publico: str, modulo_info: dict) -> dict:
    prompt = f"""
    Atue como Especialista de Campo e Consultor de Elite no tema '{tema}'.
    Escreva o CONTEÚDO TÉCNICO EXAUSTIVO DO MÓDULO {modulo_info.get('numero')}: '{modulo_info.get('titulo')}'.
    Tópicos a cobrir com rigor: {', '.join(modulo_info.get('topicos', []))}.
    Público: {publico}

    DIRETRIZES DE EXTREMA DENSIDADE:
    1. PROIBIDO RESUMOS OU GENERALIDADES. Escreva com vocabulário de quem domina as variáveis reais do processo.
    2. Desenvolva 3 subseções ricas em detalhes técnicos explicativos.
    3. Crie uma TABELA DE PARÂMETROS / MATRIZ OPERACIONAL contendo 4 a 6 linhas técnicas com parâmetros mensuráveis (pesos, tolerâncias, tempos, ferramentas ou métricas exatas) e o impacto mecânico/prático de cada item.
    4. Crie um Procedimento Operacional Padrão (POP) passo a passo (mínimo 5 passos detalhados).
    5. Destaque um ALERTA TÉCNICO CRÍTICO sobre a falha mais grave cometida nesta etapa e como blindar a operação.
    6. Forneça 2 termos em inglês para o Pexels:
       - "termo_busca_foto_processo": Ação/execução precisa deste módulo.
       - "termo_busca_foto_resultado": Produto/resultado final impecável deste módulo.
       - "legenda_resultado": Comentário técnico sobre os indicadores visuais de sucesso.

    Retorne ESTRITAMENTE o JSON:
    {{
        "numero": {modulo_info.get('numero')},
        "titulo": "{modulo_info.get('titulo')}",
        "alerta_tecnico": "Texto cirúrgico do alerta crítico...",
        "subsecoes": [
            {{"subtitulo": "...", "conteudo": "Parágrafo técnico extenso e analítico com mínimo de 140 palavras..."}},
            {{"subtitulo": "...", "conteudo": "Parágrafo técnico extenso e analítico com mínimo de 140 palavras..."}},
            {{"subtitulo": "...", "conteudo": "Parágrafo técnico extenso e analítico com mínimo de 140 palavras..."}}
        ],
        "nome_tabela": "Matriz Técnica de Especificações e Parâmetros",
        "tabela_parametros": [
            {{"item": "...", "parametro": "...", "funcao": "..."}},
            {{"item": "...", "parametro": "...", "funcao": "..."}},
            {{"item": "...", "parametro": "...", "funcao": "..."}},
            {{"item": "...", "parametro": "...", "funcao": "..."}}
        ],
        "passos_operacionais": [
            "Passo 1 detalhado...",
            "Passo 2 detalhado...",
            "Passo 3 detalhado...",
            "Passo 4 detalhado...",
            "Passo 5 detalhado..."
        ],
        "termo_busca_foto_processo": "termo em inglês de 2 a 3 palavras",
        "termo_busca_foto_resultado": "termo em inglês de 2 a 3 palavras",
        "legenda_resultado": "Legenda analítica do resultado visual..."
    }}
    """
    resp = executar_prompt_ia(prompt, formato_json=True, temperatura=0.3)
    return json.loads(resp)

def gerar_apendice_economico_ia(tema: str, publico: str) -> dict:
    prompt = f"""
    Escreva a seção final de 'DOSSIÊ CLÍNICO DE FALHAS & ENGENHARIA DE PRECIFICAÇÃO' para: '{tema}'.
    Público: {publico}

    Exigências:
    1. Troubleshooting de 3 falhas graves frequentes com Diagnóstico de Causa Raiz e Ação Corretiva Imediata.
    2. Matriz Financeira de Custos, Precificação sugerida e Margem Líquida Real.

    Retorne ESTRITAMENTE o JSON:
    {{
        "titulo": "Dossiê Clínico de Resolução de Falhas & Engenharia de Lucro",
        "falhas": [
            {{"defeito": "...", "causa_raiz": "...", "correcao": "..."}},
            {{"defeito": "...", "causa_raiz": "...", "correcao": "..."}},
            {{"defeito": "...", "causa_raiz": "...", "correcao": "..."}}
        ],
        "custos_matriz": [
            {{"componente": "Insumos Base / Custos Diretos", "valor_estimado": "Valor médio realista", "detalhe": "Composição básica"}},
            {{"componente": "Custos Operacionais e Energia/Tempo", "valor_estimado": "Valor médio realista", "detalhe": "Rateio técnico"}},
            {{"componente": "Preço de Comercialização Sugerido", "valor_estimado": "Margem de 100% a 180%", "detalhe": "Posicionamento premium"}}
        ],
        "conclusao_executiva": "Texto técnico e motivador de encerramento com foco em consistência operacional."
    }}
    """
    resp = executar_prompt_ia(prompt, formato_json=True, temperatura=0.3)
    return json.loads(resp)

def pipeline_geracao_livro_completo(tema: str, publico: str, status_placeholder=None, progress_bar=None) -> dict:
    """Pipeline orquestrado em cadeia com múltiplas chamadas atômicas de tokens."""
    if status_placeholder:
        status_placeholder.write("📐 [1/5] Projetando arquitetura técnica e ementa do livro...")
    if progress_bar:
        progress_bar.progress(0.10)
    
    blueprint = gerar_blueprint_ebook_ia(tema, publico)
    
    if status_placeholder:
        status_placeholder.write("✍️ [2/5] Escrevendo introdução técnica aprofundada...")
    if progress_bar:
        progress_bar.progress(0.20)
    
    introducao = gerar_introducao_profunda_ia(tema, publico, blueprint)
    
    modulos_completos = []
    total_mod = len(blueprint.get("modulos", []))
    for idx_m, mod in enumerate(blueprint.get("modulos", [])):
        if status_placeholder:
            status_placeholder.write(f"🔬 [3/5] Redigindo Módulo {mod.get('numero')} ({mod.get('titulo')}) com matriz e POP...")
        cap_dados = gerar_capitulo_individual_ia(tema, publico, mod)
        modulos_completos.append(cap_dados)
        if progress_bar:
            prog = 0.20 + ((idx_m + 1) / total_mod) * 0.55
            progress_bar.progress(prog)

    if status_placeholder:
        status_placeholder.write("📊 [4/5] Compilando matriz de Troubleshooting e Engenharia Financeira...")
    if progress_bar:
        progress_bar.progress(0.85)

    apendice = gerar_apendice_economico_ia(tema, publico)

    if progress_bar:
        progress_bar.progress(0.95)

    return {
        "titulo": blueprint.get("titulo"),
        "subtitulo": blueprint.get("subtitulo"),
        "termo_capa": blueprint.get("termo_capa"),
        "introducao": introducao,
        "modulos": modulos_completos,
        "apendice": apendice
    }

def traduzir_livro_completo_ia(dados_livro: dict, idioma_destino: str, progress_bar=None) -> dict:
    total_etapas = 2 + len(dados_livro.get("modulos", [])) + 1
    etapa = 0

    titulo_tr = traduzir_texto_ia(dados_livro.get("titulo", ""), idioma_destino)
    subtitulo_tr = traduzir_texto_ia(dados_livro.get("subtitulo", ""), idioma_destino)
    etapa += 1
    if progress_bar:
        progress_bar.progress(etapa / total_etapas)

    intro_tr = traduzir_texto_ia(dados_livro.get("introducao", ""), idioma_destino)
    etapa += 1
    if progress_bar:
        progress_bar.progress(etapa / total_etapas)

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
        if progress_bar:
            progress_bar.progress(etapa / total_etapas)

    ap_raw = dados_livro.get("apendice", {})
    falhas_tr = []
    for f in ap_raw.get("falhas", []):
        falhas_tr.append({
            "defeito": traduzir_texto_ia(f.get("defeito", ""), idioma_destino),
            "causa_raiz": traduzir_texto_ia(f.get("causa_raiz", ""), idioma_destino),
            "correcao": traduzir_texto_ia(f.get("correcao", ""), idioma_destino)
        })

    custos_tr = []
    for c in ap_raw.get("custos_matriz", []):
        custos_tr.append({
            "componente": traduzir_texto_ia(c.get("componente", ""), idioma_destino),
            "valor_estimado": c.get("valor_estimado", ""),
            "detalhe": traduzir_texto_ia(c.get("detalhe", ""), idioma_destino)
        })

    conclusao_tr = traduzir_texto_ia(ap_raw.get("conclusao_executiva", ""), idioma_destino)

    apendice_tr = {
        "titulo": traduzir_texto_ia(ap_raw.get("titulo", "Dossiê Clínico de Falhas"), idioma_destino),
        "falhas": falhas_tr,
        "custos_matriz": custos_tr,
        "conclusao_executiva": conclusao_tr
    }

    return {
        "titulo": titulo_tr,
        "subtitulo": subtitulo_tr,
        "termo_capa": dados_livro.get("termo_capa", ""),
        "introducao": intro_tr,
        "modulos": modulos_tr,
        "apendice": apendice_tr
    }

# ==============================================================================
# 5. DIAGRAMAÇÃO EDITORIAL DO LIVRO TÉCNICO (REPORTLAB)
# ==============================================================================
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
            # Rodapé
            self.setFont("Helvetica-Bold", 8)
            self.setFillColor(colors.HexColor("#64748B"))
            self.drawString(36, 20, "MANUAL DE ENGENHARIA & PROCEDIMENTOS | EDIÇÃO PROFISSIONAL")
            texto_pag = f"Página {self._pageNumber} de {page_count}"
            self.drawRightString(576, 20, texto_pag)
            self.setStrokeColor(colors.HexColor("#CBD5E1"))
            self.setLineWidth(0.6)
            self.line(36, 30, 576, 30)

            # Cabeçalho Superior Suave
            self.setFont("Helvetica", 7.5)
            self.setFillColor(colors.HexColor("#94A3B8"))
            self.drawString(36, 762, "PROTOCOLO TÉCNICO PADRONIZADO")
            self.line(36, 756, 576, 756)
            self.restoreState()

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

def recortar_foto_proporcional(orig_path: str, dest_path: str, target_w: int, target_h: int) -> bool:
    if not os.path.exists(orig_path):
        return False
    try:
        with PILImage.open(orig_path) as img:
            img_rgb = img.convert("RGB")
            img_cortada = ImageOps.fit(img_rgb, (target_w, target_h), method=PILImage.Resampling.LANCZOS)
            img_cortada.save(dest_path, "JPEG", quality=92)
        return True
    except Exception:
        return False

def compilar_pdf_livro_tecnico(dados_livro: dict, pexels_key: str, caminho_pdf: str) -> str:
    doc = SimpleDocTemplate(
        caminho_pdf,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=46,
        bottomMargin=42
    )
    styles = getSampleStyleSheet()

    cor_primaria = colors.HexColor("#0F172A")
    cor_azul = colors.HexColor("#1D4ED8")
    cor_azul_claro = colors.HexColor("#F0F7FF")
    cor_alerta_bg = colors.HexColor("#FEF2F2")
    cor_alerta_border = colors.HexColor("#FCA5A5")
    cor_alerta_text = colors.HexColor("#991B1B")

    estilo_capa_tit = ParagraphStyle(
        'CapaTitulo',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=26,
        leading=32,
        textColor=cor_azul,
        alignment=1,
        spaceAfter=12
    )
    estilo_capa_sub = ParagraphStyle(
        'CapaSub',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=13,
        leading=17,
        textColor=cor_primaria,
        alignment=1,
        spaceAfter=22
    )
    estilo_h1 = ParagraphStyle(
        'TitCap',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=16,
        leading=20,
        textColor=cor_azul,
        spaceBefore=8,
        spaceAfter=6,
        keepWithNext=True
    )
    estilo_h2 = ParagraphStyle(
        'TitSec',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=11,
        leading=15,
        textColor=cor_primaria,
        spaceBefore=8,
        spaceAfter=4,
        keepWithNext=True
    )
    estilo_corpo = ParagraphStyle(
        'CorpoTexto',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=14,
        textColor=colors.HexColor("#1E293B"),
        spaceAfter=6,
        alignment=4  # Justificado
    )
    estilo_item = ParagraphStyle(
        'ItemPasso',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=12.5,
        textColor=cor_primaria,
        spaceAfter=3
    )
    estilo_alerta = ParagraphStyle(
        'BoxAlerta',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=12.5,
        textColor=cor_alerta_text
    )
    estilo_legenda_foto = ParagraphStyle(
        'LegendaFoto',
        parent=styles['Normal'],
        fontName='Helvetica-Oblique',
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor("#64748B"),
        alignment=1,
        spaceBefore=3,
        spaceAfter=6
    )
    estilo_celula = ParagraphStyle(
        'CelulaTab',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        leading=11,
        textColor=cor_primaria
    )
    estilo_celula_header = ParagraphStyle(
        'CelulaHeader',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=11,
        textColor=colors.white
    )

    flowables = []

    # ==================== CAPA ====================
    flowables.append(Spacer(1, 40))
    flowables.append(Paragraph(dados_livro.get("titulo", "Manual Técnico Profissional"), estilo_capa_tit))
    flowables.append(Paragraph(dados_livro.get("subtitulo", "Guia Técnico Avançado"), estilo_capa_sub))

    termo_capa = dados_livro.get("termo_capa", "engineering business")
    capa_raw = os.path.join(DIR_PEXELS, f"livro_capa_raw_{int(time.time())}.jpg")
    capa_fit = os.path.join(DIR_PEXELS, f"livro_capa_fit_{int(time.time())}.jpg")
    if buscar_foto_pexels(termo_capa, pexels_key, capa_raw):
        if recortar_foto_proporcional(capa_raw, capa_fit, 1080, 560):
            try:
                flowables.append(RLImage(capa_fit, width=540, height=280))
            except Exception:
                pass

    flowables.append(Spacer(1, 30))
    flowables.append(Paragraph("<b>AUTORIA:</b> DEPARTAMENTO DE ENGENHARIA DE PROCESSOS & DESENVOLVIMENTO", estilo_legenda_foto))
    flowables.append(PageBreak())

    # ==================== SUMÁRIO EXECUTIVO ====================
    flowables.append(Paragraph("Sumário Executivo", estilo_h1))
    flowables.append(HRFlowable(width="100%", thickness=1, color=cor_azul, spaceAfter=14))

    sumario_data = [
        [Paragraph("<b>Seção</b>", estilo_celula_header), Paragraph("<b>Título do Módulo Técnico</b>", estilo_celula_header)]
    ]
    sumario_data.append([Paragraph("<b>Introdução</b>", estilo_celula), Paragraph("Fundamentos Científicos & Visão Sistêmica", estilo_celula)])
    for mod in dados_livro.get("modulos", []):
        sumario_data.append([
            Paragraph(f"<b>Módulo {mod.get('numero')}</b>", estilo_celula),
            Paragraph(mod.get("titulo", ""), estilo_celula)
        ])
    sumario_data.append([Paragraph("<b>Apêndice</b>", estilo_celula), Paragraph("Dossiê de Falhas & Engenharia de Custos", estilo_celula)])

    tab_sumario = Table(sumario_data, colWidths=[90, 450])
    tab_sumario.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), cor_azul),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ('PADDING', (0, 0), (-1, -1), 6),
    ]))
    flowables.append(tab_sumario)
    flowables.append(PageBreak())

    # ==================== INTRODUÇÃO ====================
    flowables.append(Paragraph("Introdução Geral & Fundamentos Sistêmicos", estilo_h1))
    flowables.append(HRFlowable(width="100%", thickness=0.8, color=colors.HexColor("#CBD5E1"), spaceAfter=10))

    for p_intro in dados_livro.get("introducao", "").split("\n"):
        if p_intro.strip():
            flowables.append(Paragraph(p_intro.strip(), estilo_corpo))

    flowables.append(PageBreak())

    # ==================== MÓDULOS TÉCNICOS INDIVIDUAIS ====================
    for mod in dados_livro.get("modulos", []):
        flowables.append(Paragraph(f"Módulo {mod.get('numero')}: {mod.get('titulo')}", estilo_h1))
        flowables.append(HRFlowable(width="100%", thickness=0.8, color=cor_azul, spaceAfter=8))

        # Banner de Ação (Foto de Processo)
        termo_proc = mod.get("termo_busca_foto_processo")
        if termo_proc:
            p_raw = os.path.join(DIR_PEXELS, f"mod_proc_raw_{mod.get('numero')}_{int(time.time())}.jpg")
            p_fit = os.path.join(DIR_PEXELS, f"mod_proc_fit_{mod.get('numero')}_{int(time.time())}.jpg")
            if buscar_foto_pexels(termo_proc, pexels_key, p_raw):
                if recortar_foto_proporcional(p_raw, p_fit, 1080, 260):
                    try:
                        flowables.append(RLImage(p_fit, width=540, height=130))
                        flowables.append(Spacer(1, 6))
                    except Exception:
                        pass

        # Caixa de Alerta Técnico
        alerta = mod.get("alerta_tecnico")
        if alerta:
            tabela_alerta = Table(
                [[Paragraph(f"<b>⚠️ PONTO CRÍTICO DE CONTROLE (ALERTA):</b> {alerta}", estilo_alerta)]],
                colWidths=[540]
            )
            tabela_alerta.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), cor_alerta_bg),
                ('BOX', (0, 0), (-1, -1), 1, cor_alerta_border),
                ('PADDING', (0, 0), (-1, -1), 6),
            ]))
            flowables.append(tabela_alerta)
            flowables.append(Spacer(1, 8))

        # Subseções Técnicas Densas
        for sub in mod.get("subsecoes", []):
            flowables.append(Paragraph(sub.get("subtitulo", ""), estilo_h2))
            for p_sub in sub.get("conteudo", "").split("\n"):
                if p_sub.strip():
                    flowables.append(Paragraph(p_sub.strip(), estilo_corpo))

        flowables.append(Spacer(1, 6))

        # Matriz Técnica de Parâmetros
        itens_tab = mod.get("tabela_parametros", [])
        if itens_tab:
            flowables.append(Paragraph(f"📋 {mod.get('nome_tabela', 'Matriz Técnica')}", estilo_h2))
            dados_t = [
                [
                    Paragraph("<b>Componente / Parâmetro</b>", estilo_celula_header),
                    Paragraph("<b>Especificação / Tolerância</b>", estilo_celula_header),
                    Paragraph("<b>Função Mecânica & Impacto Prático</b>", estilo_celula_header)
                ]
            ]
            for item in itens_tab:
                dados_t.append([
                    Paragraph(item.get("item", ""), estilo_celula),
                    Paragraph(item.get("parametro", ""), estilo_celula),
                    Paragraph(item.get("funcao", ""), estilo_celula)
                ])

            tab_param = Table(dados_t, colWidths=[180, 110, 250])
            tab_param.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), cor_azul),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
                ('PADDING', (0, 0), (-1, -1), 4),
            ]))
            flowables.append(tab_param)
            flowables.append(Spacer(1, 8))

        # Procedimento Operacional Padrão (Passo a Passo)
        passos = mod.get("passos_operacionais", [])
        if passos:
            flowables.append(Paragraph("<b>Procedimento Operacional Padrão (POP):</b>", estilo_h2))
            for idx_p, passo in enumerate(passos, 1):
                flowables.append(Paragraph(f"<b>Passo {idx_p}:</b> {passo}", estilo_item))

        # Foto de Resultado de Excelência
        termo_res = mod.get("termo_busca_foto_resultado")
        if termo_res:
            r_raw = os.path.join(DIR_PEXELS, f"mod_res_raw_{mod.get('numero')}_{int(time.time())}.jpg")
            r_fit = os.path.join(DIR_PEXELS, f"mod_res_fit_{mod.get('numero')}_{int(time.time())}.jpg")
            if buscar_foto_pexels(termo_res, pexels_key, r_raw):
                if recortar_foto_proporcional(r_raw, r_fit, 1080, 240):
                    try:
                        flowables.append(Spacer(1, 6))
                        flowables.append(RLImage(r_fit, width=540, height=120))
                        leg = mod.get("legenda_resultado", "Indicador visual de conformidade do resultado.")
                        flowables.append(Paragraph(f"📷 <b>Controle Visual:</b> {leg}", estilo_legenda_foto))
                    except Exception:
                        pass

        flowables.append(PageBreak())

    # ==================== APÊNDICE: FALHAS & ENGENHARIA ECONÔMICA ====================
    ap = dados_livro.get("apendice", {})
    flowables.append(Paragraph(ap.get("titulo", "Dossiê Clínico de Falhas & Engenharia de Lucro"), estilo_h1))
    flowables.append(HRFlowable(width="100%", thickness=1, color=cor_azul, spaceAfter=10))

    # Tabela de Resolução de Falhas
    falhas = ap.get("falhas", [])
    if falhas:
        flowables.append(Paragraph("Matriz de Resolução de Anomalias (Troubleshooting)", estilo_h2))
        dados_falhas = [
            [
                Paragraph("<b>Defeito / Sintoma</b>", estilo_celula_header),
                Paragraph("<b>Causa Raiz</b>", estilo_celula_header),
                Paragraph("<b>Ação Corretiva Imediata</b>", estilo_celula_header)
            ]
        ]
        for f in falhas:
            dados_falhas.append([
                Paragraph(f.get("defeito", ""), estilo_celula),
                Paragraph(f.get("causa_raiz", ""), estilo_celula),
                Paragraph(f.get("correcao", ""), estilo_celula)
            ])
        tab_f = Table(dados_falhas, colWidths=[150, 180, 210])
        tab_f.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#334155")),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
            ('PADDING', (0, 0), (-1, -1), 4),
        ]))
        flowables.append(tab_f)
        flowables.append(Spacer(1, 10))

    # Matriz Econômica
    custos = ap.get("custos_matriz", [])
    if custos:
        flowables.append(Paragraph("Engenharia de Custos, Precificação & Margem", estilo_h2))
        dados_c = [
            [
                Paragraph("<b>Centro de Custo / Componente</b>", estilo_celula_header),
                Paragraph("<b>Estimativa / Valor</b>", estilo_celula_header),
                Paragraph("<b>Diretriz de Posicionamento</b>", estilo_celula_header)
            ]
        ]
        for c in custos:
            dados_c.append([
                Paragraph(c.get("componente", ""), estilo_celula),
                Paragraph(c.get("valor_estimado", ""), estilo_celula),
                Paragraph(c.get("detalhe", ""), estilo_celula)
            ])
        tab_c = Table(dados_c, colWidths=[180, 130, 230])
        tab_c.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), cor_azul),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
            ('PADDING', (0, 0), (-1, -1), 4),
        ]))
        flowables.append(tab_c)
        flowables.append(Spacer(1, 10))

    conclusao = ap.get("conclusao_executiva", "")
    if conclusao:
        flowables.append(Paragraph("Conclusão Executiva", estilo_h2))
        flowables.append(Paragraph(conclusao, estilo_corpo))

    doc.build(flowables, canvasmaker=NumeradorPaginas)
    return caminho_pdf

# ==============================================================================
# 6. PROCESSAMENTO DE VÍDEO (TTS, PEXELS & FFMPEG)
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
    if not pexels_key:
        return False

    orientacao = "portrait" if vertical else "landscape"
    headers = {"Authorization": pexels_key}

    termos_tentativa = [
        query,
        f"{query} tutorial",
        f"{query} close up",
        "professional hands at work",
        "business modern lifestyle"
    ]

    for termo in termos_tentativa:
        termo_limpo = re.sub(r'[^a-zA-Z0-9\s]', '', str(termo)).strip()
        if not termo_limpo:
            continue
        try:
            url = f"https://api.pexels.com/videos/search?query={requests.utils.quote(termo_limpo)}&per_page=4&orientation={orientacao}"
            res = requests.get(url, headers=headers, timeout=12)
            if res.status_code == 200:
                data = res.json()
                videos = data.get("videos", [])
                if videos:
                    for vid in videos:
                        vfiles = vid.get("video_files", [])
                        validos = [v for v in vfiles if v.get("width") and v.get("height") and v.get("link")]
                        if validos:
                            validos.sort(key=lambda x: x["width"] * x["height"], reverse=True)
                            escolhido = validos[0]
                            for v in validos:
                                if v.get("height") in [720, 1080] or v.get("width") in [720, 1080]:
                                    escolhido = v
                                    break
                            v_bytes = requests.get(escolhido["link"], timeout=25).content
                            if len(v_bytes) > 60000:
                                with open(dest_path, "wb") as f:
                                    f.write(v_bytes)
                                return True
        except Exception:
            continue
    return False

def criar_arquivo_legenda(texto: str, output_path: str, vertical: bool = False) -> str:
    largura = 24 if vertical else 40
    linhas = textwrap.wrap(texto.strip(), width=largura)
    texto_formatado = "\n".join(linhas)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(texto_formatado)
    return output_path

def renderizar_vsl_completa(
    cenas: List[Dict[str, str]],
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
    total = len(cenas)

    for idx, item in enumerate(cenas):
        frase = item.get("fala", "") if isinstance(item, dict) else str(item)
        termo_video = item.get("termo_video", "business tutorial") if isinstance(item, dict) else "business tutorial"

        prefixo = f"cena_{idx}_{int(time.time())}"
        a_path = os.path.join(DIR_AUDIOS, f"{prefixo}.mp3")
        sintetizar_audio_tts(frase, a_path, voz=voz)
        duracao = obter_duracao_audio(a_path)

        v_raw_path = os.path.join(DIR_PEXELS, f"{prefixo}_raw.mp4")
        tem_video = buscar_video_pexels(termo_video, pexels_key, v_raw_path, vertical=vertical)

        cena_out = os.path.join(DIR_VSL, f"{prefixo}_out.mp4")

        legenda_txt = os.path.join(DIR_VSL, f"{prefixo}_legenda.txt")
        criar_arquivo_legenda(frase, legenda_txt, vertical=vertical)
        legenda_path_escapado = legenda_txt.replace(os.sep, "/").replace(":", "\\:")

        fontsize = 44 if not vertical else 48

        if tem_video and os.path.exists(v_raw_path):
            vf = (
                f"scale={res_w}:{res_h}:force_original_aspect_ratio=increase,"
                f"crop={res_w}:{res_h},"
                f"setsar=1,"
                f"fps=30,"
                f"drawtext=textfile='{legenda_path_escapado}':fontcolor=white:fontsize={fontsize}:"
                f"box=1:boxcolor=black@0.75:boxborderw=16:line_spacing=12:"
                f"x=(w-text_w)/2:y=h-text_h-90"
            )
            cmd = [
                "ffmpeg", "-y",
                "-stream_loop", "-1", "-i", v_raw_path,
                "-i", a_path,
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-t", f"{duracao:.2f}",
                "-vf", vf,
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "22",
                "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
                "-pix_fmt", "yuv420p",
                cena_out
            ]
        else:
            vf = (
                f"setsar=1,fps=30,"
                f"drawtext=textfile='{legenda_path_escapado}':fontcolor=white:fontsize={fontsize+4}:"
                f"box=1:boxcolor=blue@0.65:boxborderw=20:line_spacing=14:"
                f"x=(w-text_w)/2:y=(h-text_h)/2"
            )
            cmd = [
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", f"color=c=0x0F172A:s={res_w}x{res_h}:d={duracao:.2f}",
                "-i", a_path,
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-t", f"{duracao:.2f}",
                "-vf", vf,
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "22",
                "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
                "-pix_fmt", "yuv420p",
                cena_out
            ]

        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        cenas_clipes.append(cena_out)

        if progress_bar:
            progress_bar.progress((idx + 0.8) / total)

    concat_txt_path = os.path.join(DIR_VSL, f"concat_{int(time.time())}.txt")
    with open(concat_txt_path, "w", encoding="utf-8") as f:
        for c in cenas_clipes:
            f.write(f"file '{c.replace(os.sep, '/')}'\n")

    vsl_sem_trilha = os.path.join(DIR_VSL, f"vsl_base_{int(time.time())}.mp4")
    cmd_concat = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_txt_path,
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
        vsl_sem_trilha
    ]
    subprocess.run(cmd_concat, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

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
    cenas_originais: List[Dict[str, str]],
    idioma_alvo: str,
    vertical: bool,
    voz: str,
    pexels_key: str,
    musica_fundo_path: Optional[str] = None,
    volume_musica: float = 0.08,
    logo_path: Optional[str] = None,
    progress_bar = None
) -> Tuple[str, List[Dict[str, str]]]:
    cenas_traduzidas = []
    total_frases = len(cenas_originais)

    for idx_f, cena in enumerate(cenas_originais):
        fala_orig = cena.get("fala", "") if isinstance(cena, dict) else str(cena)
        termo_orig = cena.get("termo_video", "business tutorial") if isinstance(cena, dict) else "business tutorial"

        texto_tr = traduzir_texto_ia(fala_orig, idioma_alvo)
        cenas_traduzidas.append({"fala": texto_tr, "termo_video": termo_orig})
        if progress_bar:
            progress_bar.progress((idx_f + 1) / (total_frases * 2))

    video_dublado = renderizar_vsl_completa(
        cenas=cenas_traduzidas,
        vertical=vertical,
        voz=voz,
        pexels_key=pexels_key,
        musica_fundo_path=musica_fundo_path,
        volume_musica=volume_musica,
        logo_path=logo_path,
        progress_bar=progress_bar
    )
    return video_dublado, cenas_traduzidas

# ==============================================================================
# 7. INICIALIZAÇÃO DE ESTADOS GLOBAIS
# ==============================================================================
if "vsl_input_tema" not in st.session_state:
    st.session_state["vsl_input_tema"] = "Confeitaria Lucrativa & Bolos Caseiros"
if "vsl_input_promessa" not in st.session_state:
    st.session_state["vsl_input_promessa"] = "Domine as receitas mais pedidas e fature da sua cozinha"
if "vsl_input_publico" not in st.session_state:
    st.session_state["vsl_input_publico"] = "Mulheres e empreendedoras que buscam renda extra com doces"

if "ebook_input_tema" not in st.session_state:
    st.session_state["ebook_input_tema"] = "Manual Definitivo da Confeitaria Lucrativa"
if "ebook_input_publico" not in st.session_state:
    st.session_state["ebook_input_publico"] = "Mulheres e empreendedoras que buscam renda extra com doces"

# BARRA LATERAL
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

    if "email_usuario_ativo" not in st.session_state:
        st.session_state["email_usuario_ativo"] = "erp61eng@gmail.com"

    email_digitado = st.text_input(
        "Seu E-mail Cadastrado:",
        value=st.session_state["email_usuario_ativo"],
        key="sidebar_email_input"
    ).lower().strip()

    if email_digitado and email_digitado != st.session_state["email_usuario_ativo"]:
        st.session_state["email_usuario_ativo"] = email_digitado

    email_usuario = st.session_state["email_usuario_ativo"]

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
    st.write("• ElevenLabs:", "🟢 Ativo" if ELEVENLABS_API_KEY else "🔴 Ausente")
    st.write("• Pexels:", "🟢 Ativo" if PEXELS_API_KEY else "🔴 Ausente")

# ABAS PRINCIPAIS
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
    st.caption("Analise nichos comerciais, descubra dores ocultas e sincronize os dados limpos nas abas seguintes.")

    NICHOS_PREDEFINIDOS = [
        "🎂 Confeitaria Lucrativa & Bolos Caseiros",
        "🐕 Adestramento Canino & Comportamento Pet",
        "🍞 Gastronomia & Pães Sem Glúten",
        "💰 Renda Extra & Milhas Aéreas",
        "🌱 Jardinagem, Suculentas & Hortas em Apartamento",
        "🛠️ Manutenção Residencial & Marido de Aluguel",
        "💅 Estética, Cílios & Sobrancelhas",
        "🧘 Saúde Natural, Chás Medicinais & Sono",
        "✍️ Digitar Nicho Personalizado (Manual)..."
    ]

    col_m1, col_m2 = st.columns([2, 1])
    with col_m1:
        nicho_sel = st.selectbox("Selecione um Nicho ou Digite o Seu:", NICHOS_PREDEFINIDOS, key="miner_nicho_sel")
    with col_m2:
        profundidade = st.selectbox("Profundidade da Análise:", ["Dossiê Completo de Lançamento", "Raio-X Rápido de Dores & Promessas"], key="miner_profundidade")

    nicho_final = nicho_sel
    if "Manual" in nicho_sel:
        nicho_manual = st.text_input(
            "Digite o Nicho ou Micronicho que deseja pesquisar:",
            placeholder="Ex: Fabricação de trufas e bombons gourmet",
            key="miner_nicho_manual"
        )
        if nicho_manual.strip():
            nicho_final = nicho_manual.strip()

    st.info(f"🎯 **Nicho Selecionado para Mineração:** `{nicho_final}`")

    if st.button("🚀 Analisar Nicho & Gerar Kit Google Ads", type="primary", key="btn_minerar_nicho"):
        if not nicho_final or "Manual" in nicho_final:
            st.warning("Por favor, informe um nicho válido.")
        else:
            with st.spinner("Limpando dados anteriores, minerando público e preparando campanhas..."):
                try:
                    chaves_para_limpar = [
                        "video_vsl_pronto", "roteiro_vsl", "video_dublado_pronto",
                        "video_dublado_idioma", "video_dublado_roteiro",
                        "pdf_ebook_pronto", "pdf_ebook_nome", "pdf_global_pronto",
                        "pdf_global_nome", "pdf_global_lingua", "dados_livro_sessao"
                    ]
                    for k in chaves_para_limpar:
                        st.session_state.pop(k, None)

                    resultado_dossie = minerar_nicho_profundo_ia(nicho_final, profundidade)
                    st.session_state["resultado_pesquisa_nicho"] = resultado_dossie
                    st.session_state["nicho_pesquisado_nome"] = nicho_final

                    st.session_state["vsl_input_tema"] = nicho_final
                    st.session_state["vsl_input_promessa"] = f"Aprenda o método definitivo e lucre com {nicho_final}"
                    st.session_state["vsl_input_publico"] = "Iniciantes e profissionais que buscam renda extra e independência financeira"

                    st.session_state["ebook_input_tema"] = f"Manual Prático e Definitivo: {nicho_final}"
                    st.session_state["ebook_input_publico"] = "Iniciantes e profissionais que buscam renda extra e independência financeira"

                    st.rerun()

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
                height=350,
                key="dossie_txt_area"
            )
            nome_arq_txt = f"campanha_google_ads_{re.sub(r'[^a-zA-Z0-9]', '_', st.session_state.get('nicho_pesquisado_nome', 'nicho').lower())}.txt"
            st.download_button(
                "⬇️ Baixar Kit de Campanha (.txt)",
                data=st.session_state["resultado_pesquisa_nicho"],
                file_name=nome_arq_txt,
                mime="text/plain",
                use_container_width=True,
                key="btn_download_campanha"
            )

# ------------------------------------------------------------------------------
# ABA 2: CRIAR VSL & DUBLAGEM GLOBAL
# ------------------------------------------------------------------------------
with tab_vsl:
    st.markdown("## 🚀 Criador de Vídeo de Vendas (VSL) & Dublagem Global")
    
    nicho_integrado = st.session_state.get("nicho_pesquisado_nome")
    if nicho_integrado:
        st.success(f"🎯 **Nicho Conectado da Mineração:** `{nicho_integrado}`")

    col_v1, col_v2 = st.columns(2)
    with col_v1:
        tema_vsl = st.text_input("Tema / Produto da VSL:", key="vsl_input_tema")
        promessa_vsl = st.text_input("Grande Promessa:", key="vsl_input_promessa")
    with col_v2:
        publico_vsl = st.text_input("Público-Alvo da VSL:", key="vsl_input_publico")
        qtd_cenas = st.slider("Quantidade de Cenas (Cortes Dinâmicos):", 3, 10, 5, key="vsl_slider_cenas")

    col_opt1, col_opt2, col_opt3 = st.columns(3)
    with col_opt1:
        formato_vertical = st.checkbox("Formato Vertical 9:16 (Reels/TikTok/Shorts)", value=False, key="vsl_check_vertical")
    with col_opt2:
        voz_sel = st.selectbox("Locução (OpenAI TTS):", ["onyx (Forte/Masculina)", "alloy (Neutra)", "nova (Energética/Feminina)", "echo (Suave)"], key="vsl_select_voz")
        voz_codigo = voz_sel.split()[0]
    with col_opt3:
        musica_up = st.file_uploader("Trilha Sonora (.mp3 opcional):", type=["mp3"], key="vsl_uploader_musica")

    if st.button("🎬 Gerar Roteiro e Renderizar VSL Original (20 cr)", type="primary", key="btn_render_vsl"):
        if saldo_atual < 20:
            st.error("❌ Saldo insuficiente! Você precisa de 20 créditos.")
        else:
            barra_vsl = st.progress(0.0)
            with st.spinner(f"Criando cenas visuais de '{tema_vsl}' no Pexels, áudio sincronizado e cortes dinâmicos..."):
                try:
                    cenas_estruturadas = gerar_roteiro_vsl_ia(tema_vsl, promessa_vsl, publico_vsl, qtd_cenas)
                    st.session_state["roteiro_vsl"] = cenas_estruturadas

                    p_musica = None
                    if musica_up:
                        p_musica = os.path.join(DIR_MUSICAS, musica_up.name)
                        with open(p_musica, "wb") as f_m:
                            f_m.write(musica_up.getbuffer())

                    video_pronto = renderizar_vsl_completa(
                        cenas=cenas_estruturadas,
                        vertical=formato_vertical,
                        voz=voz_codigo,
                        pexels_key=PEXELS_API_KEY,
                        musica_fundo_path=p_musica,
                        progress_bar=barra_vsl
                    )

                    debitar_creditos_cloud(email_usuario, f"Criação VSL ({tema_vsl})", 20)
                    st.session_state["video_vsl_pronto"] = video_pronto
                    st.success(f"✅ VSL de '{tema_vsl}' renderizada com sucesso!")
                    st.rerun()
                except Exception as e_vsl:
                    st.error(f"Erro na renderização da VSL: {e_vsl}")

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
                use_container_width=True,
                key="btn_down_vsl_orig"
            )

        st.markdown("---")
        with st.container(border=True):
            st.markdown("### 🌐 Dublar VSL em 36 Idiomas (DubfyAi Global)")
            st.caption("Traduza a narração, adapte valores para moedas locais e re-sincronize cortes.")

            col_d1, col_d2 = st.columns([2, 1])
            with col_d1:
                idioma_dub_sel = st.selectbox("Selecione o Idioma para Dublar:", list(IDIOMAS_SISTEMA_36.keys()), key="vsl_select_idioma_dub")
            with col_d2:
                st.write("")
                st.caption("Custo: 20 Créditos")
                btn_dub = st.button("🎙️ Dublar Vídeo Agora (20 cr)", type="primary", use_container_width=True, key="btn_exec_dub")

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
                                cenas_originais=st.session_state["roteiro_vsl"],
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
                    use_container_width=True,
                    key="btn_down_vsl_dub"
                )

# ------------------------------------------------------------------------------
# ABA 3: CRIAR LIVRO/E-BOOK TÉCNICO & TRADUÇÃO GLOBAL (PIPELINE MULTI-STAGE)
# ------------------------------------------------------------------------------
with tab_ebook:
    st.markdown("## 📚 Gerador de Livro Técnico & Manual de Engenharia Operacional")
    st.caption("Arquitetura em cadeia modular: gera capítulo por capítulo, garantindo 15 a 25 páginas reais com tabelas, POPs e análise de falhas.")

    col_e1, col_e2 = st.columns(2)
    with col_e1:
        tema_ebook = st.text_input("Tema Central do Manual:", key="ebook_input_tema")
    with col_e2:
        publico_ebook = st.text_input("Público-Alvo / Perfil Técnico:", key="ebook_input_publico")

    if st.button("📖 Compilar Livro Técnico Completo (.PDF) (10 cr)", type="primary", key="btn_render_ebook"):
        if saldo_atual < 10:
            st.error("❌ Saldo insuficiente! Você precisa de 10 créditos.")
        else:
            prog_bar = st.progress(0.0)
            status_box = st.empty()
            try:
                # Disparo do Pipeline em Série
                dados_livro = pipeline_geracao_livro_completo(
                    tema=tema_ebook,
                    publico=publico_ebook,
                    status_placeholder=status_box,
                    progress_bar=prog_bar
                )
                st.session_state["dados_livro_sessao"] = dados_livro

                status_box.write("📑 [5/5] Diagramando páginas editoriais com ReportLab e recortando imagens...")
                nome_pdf = f"manual_tecnico_{re.sub(r'[^a-zA-Z0-9]', '_', tema_ebook.lower())[:22]}_{int(time.time())}.pdf"
                caminho_pdf = os.path.join(DIR_EBOOKS, nome_pdf)

                compilar_pdf_livro_tecnico(dados_livro, PEXELS_API_KEY, caminho_pdf)

                debitar_creditos_cloud(email_usuario, f"Criação Livro Técnico ({tema_ebook})", 10)
                st.session_state["pdf_ebook_pronto"] = caminho_pdf
                st.session_state["pdf_ebook_nome"] = nome_pdf
                
                status_box.empty()
                prog_bar.progress(1.0)
                st.success("✅ Livro Técnico Profissional compilado com sucesso! Arquitetura completa, sumário e páginas densas.")
                st.rerun()
            except Exception as e_eb:
                st.error(f"Erro na compilação do Livro Técnico: {e_eb}")

    if st.session_state.get("pdf_ebook_pronto") and os.path.exists(st.session_state["pdf_ebook_pronto"]):
        st.markdown("---")
        st.markdown("### 📥 Seu Livro Técnico Original em Português:")
        with open(st.session_state["pdf_ebook_pronto"], "rb") as f_eb:
            st.download_button(
                "⬇️ Baixar Manual Técnico Completo (.PDF)",
                data=f_eb,
                file_name=st.session_state.get("pdf_ebook_nome", "manual_tecnico.pdf"),
                mime="application/pdf",
                use_container_width=True,
                key="btn_down_eb_orig"
            )

        st.markdown("---")
        with st.container(border=True):
            st.markdown("### 🌐 Tradução Global do Livro (36 Idiomas)")
            st.caption("Internacionalize preservando a diagramação editorial, matrizes técnicas e sumário.")

            col_tr1, col_tr2 = st.columns([2, 1])
            with col_tr1:
                idioma_eb_sel = st.selectbox("Selecione o Idioma de Destino:", list(IDIOMAS_SISTEMA_36.keys()), key="ebook_select_idioma_tr")
            with col_tr2:
                st.write("")
                st.caption("Custo: 10 Créditos")
                btn_trad_eb = st.button("🌍 Traduzir Livro Técnico (10 cr)", type="primary", use_container_width=True, key="btn_exec_trad_eb")

            if btn_trad_eb:
                if saldo_atual < 10:
                    st.error("❌ Saldo insuficiente para internacionalização.")
                elif not st.session_state.get("dados_livro_sessao"):
                    st.error("Dados da sessão não encontrados.")
                else:
                    nome_lingua_eb = IDIOMAS_SISTEMA_36[idioma_eb_sel]
                    barra_eb_tr = st.progress(0.0)
                    with st.spinner(f"Traduzindo módulos técnicos, procedimentos e matriz financeira para {idioma_eb_sel}..."):
                        try:
                            dados_tr = traduzir_livro_completo_ia(
                                st.session_state["dados_livro_sessao"],
                                nome_lingua_eb,
                                progress_bar=barra_eb_tr
                            )
                            cod_idioma = re.sub(r'[^a-zA-Z0-9]', '_', nome_lingua_eb.lower())
                            nome_pdf_tr = f"manual_{cod_idioma}_{int(time.time())}.pdf"
                            caminho_pdf_tr = os.path.join(DIR_EBOOKS, nome_pdf_tr)

                            compilar_pdf_livro_tecnico(dados_tr, PEXELS_API_KEY, caminho_pdf_tr)
                            debitar_creditos_cloud(email_usuario, f"Tradução Livro ({nome_lingua_eb})", 10)

                            st.session_state["pdf_global_pronto"] = caminho_pdf_tr
                            st.session_state["pdf_global_nome"] = nome_pdf_tr
                            st.session_state["pdf_global_lingua"] = idioma_eb_sel
                            st.success(f"✅ Livro Técnico traduzido com sucesso para {idioma_eb_sel}!")
                            st.rerun()
                        except Exception as e_tr:
                            st.error(f"Erro na tradução do livro: {e_tr}")

        if st.session_state.get("pdf_global_pronto") and os.path.exists(st.session_state["pdf_global_pronto"]):
            st.success(f"✅ Arquivo internacionalizado pronto: **{st.session_state.get('pdf_global_lingua')}**")
            with open(st.session_state["pdf_global_pronto"], "rb") as f_tr_eb:
                st.download_button(
                    label=f"⬇️ BAIXAR LIVRO TÉCNICO EM {st.session_state.get('pdf_global_lingua').upper()} (.PDF)",
                    data=f_tr_eb,
                    file_name=st.session_state.get("pdf_global_nome", "manual_global.pdf"),
                    mime="application/pdf",
                    type="primary",
                    use_container_width=True,
                    key="btn_down_eb_glob"
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

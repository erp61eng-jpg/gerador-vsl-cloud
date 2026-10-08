import os
import re
import json
import time
import textwrap
import subprocess
import requests
from datetime import datetime, timezone, timedelta
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

# ==============================================================================
# GESTOR DE TRILHAS SONORAS (DOWNLOAD AUTOMÁTICO SE ESTIVER VAZIO)
# ==============================================================================
TRILHAS_PADRAO = {
    "comercial_animada.mp3": "https://raw.githubusercontent.com/effacestudios/Royalty-Free-Music-Pack/master/commercial.mp3",
    "planejamento_vendas.mp3": "https://raw.githubusercontent.com/effacestudios/Royalty-Free-Music-Pack/master/Planning.mp3",
    "suave_dinamica.mp3": "https://raw.githubusercontent.com/effacestudios/Royalty-Free-Music-Pack/master/Happy%20Life.mp3"
}

def garantir_trilhas_padrao():
    """Baixa faixas instrumentais gratuitas se a pasta temp_musicas estiver vazia."""
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
    """Varre a pasta temp_musicas e retorna opções formatadas para seleção."""
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
    if not texto.strip():
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
# 4. ENGENHARIA DE GERAÇÃO DO LIVRO TÉCNICO (PIPELINE MULTI-STAGE)
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
            {{
                "numero": 1,
                "titulo": "Fundamentos Estruturais & Preparação Inicial",
                "objetivo": "...",
                "topicos": ["...", "...", "..."]
            }},
            {{
                "numero": 2,
                "titulo": "Metodologia Operacional Passo a Passo",
                "objetivo": "...",
                "topicos": ["...", "...", "..."]
            }},
            {{
                "numero": 3,
                "titulo": "Parâmetros Críticos, Calibração & Eficiência",
                "objetivo": "...",
                "topicos": ["...", "...", "..."]
            }},
            {{
                "numero": 4,
                "titulo": "Inspeção de Qualidade, Tolerâncias & Padrão de Entrega",
                "objetivo": "...",
                "topicos": ["...", "...", "..."]
            }},
            {{
                "numero": 5,
                "titulo": "Escala de Produção, Custos & Maximização de Margem",
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
    2. Apresente os fundamentos do método e por que amadores falham.
    3. Explique a previsibilidade e consistência da abordagem técnica deste livro.

    Retorne APENAS o texto em parágrafos.
    """
    return executar_prompt_ia(prompt, formato_json=False, temperatura=0.3)

def gerar_capitulo_individual_ia(tema: str, publico: str, modulo_info: dict) -> dict:
    prompt = f"""
    Atue como Consultor de Elite no tema '{tema}'.
    Escreva o CONTEÚDO TÉCNICO EXAUSTIVO DO MÓDULO {modulo_info.get('numero')}: '{modulo_info.get('titulo')}'.
    Tópicos a cobrir: {', '.join(modulo_info.get('topicos', []))}.
    Público: {publico}

    DIRETRIZES:
    1. Desenvolva 3 subseções ricas em detalhes explicativos (mínimo 130 palavras cada).
    2. Crie uma TABELA DE PARÂMETROS contendo 4 a 6 linhas técnicas com especificações mensuráveis e o impacto de cada uma.
    3. Crie um Procedimento Operacional Padrão (POP) passo a passo (mínimo 5 passos detalhados).
    4. Destaque um ALERTA TÉCNICO CRÍTICO sobre o erro mais fatal desta etapa.
    5. Forneça 2 termos em inglês para o Pexels:
       - "termo_busca_foto_processo": Ação/execução precisa deste módulo.
       - "termo_busca_foto_resultado": Produto/resultado final impecável deste módulo.
       - "legenda_resultado": Comentário técnico sobre conformidade visual.

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

# ==============================================================================
# 5. ENGENHARIA DO PRODUTO COMPLEMENTAR (ORDER BUMP)
# ==============================================================================
def gerar_order_bump_ia(tema: str, publico: str, titulo_principal: str) -> dict:
    prompt = f"""
    Atue como Especialista em Otimização de Conversão e Ferramentas Práticas de Campo.
    Crie o PRODUTO COMPLEMENTAR (ORDER BUMP / ACELERADOR PRÁTICO) para acompanhar o produto principal: '{titulo_principal}'.
    TEMA: {tema}
    PÚBLICO: {publico}

    O Order Bump deve ser um material de consulta rápida e execução imediata:
    1. "titulo_bump": Nome magnético.
    2. "subtitulo_bump": Subtítulo curto de transformação instantânea.
    3. "copy_oferta_kiwify": Texto curto de persuasão (3 linhas) para a caixinha de Order Bump da Kiwify.
    4. "checklist_rotina": 10 itens objetivos de verificação pré-execução / auditoria.
    5. "tabela_emergencia": 4 situações críticas de erro comum e o comando de ação em menos de 5 minutos.
    6. "termo_capa": Termo em inglês para imagem de capa (2 a 3 palavras).

    Retorne ESTRITAMENTE o JSON:
    {{
        "titulo_bump": "...",
        "subtitulo_bump": "...",
        "copy_oferta_kiwify": "...",
        "termo_capa": "...",
        "checklist_rotina": [
            {{"fase": "Pré-Execução", "item": "...", "criterio_aprovacao": "..."}},
            {{"fase": "Pré-Execução", "item": "...", "criterio_aprovacao": "..."}},
            {{"fase": "Durante Operação", "item": "...", "criterio_aprovacao": "..."}},
            {{"fase": "Durante Operação", "item": "...", "criterio_aprovacao": "..."}},
            {{"fase": "Durante Operação", "item": "...", "criterio_aprovacao": "..."}},
            {{"fase": "Inspeção Final", "item": "...", "criterio_aprovacao": "..."}},
            {{"fase": "Inspeção Final", "item": "...", "criterio_aprovacao": "..."}},
            {{"fase": "Auditoria de Saída", "item": "...", "criterio_aprovacao": "..."}}
        ],
        "tabela_emergencia": [
            {{"anomalia": "...", "risco_imediato": "...", "comando_correcao": "..."}},
            {{"anomalia": "...", "risco_imediato": "...", "comando_correcao": "..."}},
            {{"anomalia": "...", "risco_imediato": "...", "comando_correcao": "..."}},
            {{"anomalia": "...", "risco_imediato": "...", "comando_correcao": "..."}}
        ]
    }}
    """
    resp = executar_prompt_ia(prompt, formato_json=True, temperatura=0.3)
    return json.loads(resp)

def pipeline_geracao_livro_completo(tema: str, publico: str, gerar_bump: bool = True, status_placeholder=None, progress_bar=None) -> dict:
    if status_placeholder:
        status_placeholder.write("📐 [1/6] Projetando arquitetura técnica e ementa do livro...")
    if progress_bar:
        progress_bar.progress(0.10)
    
    blueprint = gerar_blueprint_ebook_ia(tema, publico)
    
    if status_placeholder:
        status_placeholder.write("✍ [2/6] Escrevendo introdução técnica aprofundada...")
    if progress_bar:
        progress_bar.progress(0.20)
    
    introducao = gerar_introducao_profunda_ia(tema, publico, blueprint)
    
    modulos_completos = []
    total_mod = len(blueprint.get("modulos", []))
    for idx_m, mod in enumerate(blueprint.get("modulos", [])):
        if status_placeholder:
            status_placeholder.write(f"🔬 [3/6] Redigindo Módulo {mod.get('numero')} ({mod.get('titulo')}) com matriz e POP...")
        cap_dados = gerar_capitulo_individual_ia(tema, publico, mod)
        modulos_completos.append(cap_dados)
        if progress_bar:
            prog = 0.20 + ((idx_m + 1) / total_mod) * 0.45
            progress_bar.progress(prog)

    if status_placeholder:
        status_placeholder.write("📊 [4/6] Compilando matriz de Troubleshooting e Engenharia Financeira...")
    if progress_bar:
        progress_bar.progress(0.75)

    apendice = gerar_apendice_economico_ia(tema, publico)

    dados_bump = None
    if gerar_bump:
        if status_placeholder:
            status_placeholder.write("🎁 [5/6] Construindo Produto Complementar de Order Bump...")
        dados_bump = gerar_order_bump_ia(tema, publico, blueprint.get("titulo"))
        if progress_bar:
            progress_bar.progress(0.90)

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
    if dados_livro.get("order_bump"):
        total_etapas += 1
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
    etapa += 1

    bump_tr = None
    if dados_livro.get("order_bump"):
        b_raw = dados_livro["order_bump"]
        chk_tr = []
        for chk in b_raw.get("checklist_rotina", []):
            chk_tr.append({
                "fase": traduzir_texto_ia(chk.get("fase", ""), idioma_destino),
                "item": traduzir_texto_ia(chk.get("item", ""), idioma_destino),
                "criterio_aprovacao": traduzir_texto_ia(chk.get("criterio_aprovacao", ""), idioma_destino)
            })

        tab_em_tr = []
        for em in b_raw.get("tabela_emergencia", []):
            tab_em_tr.append({
                "anomalia": traduzir_texto_ia(em.get("anomalia", ""), idioma_destino),
                "risco_imediato": traduzir_texto_ia(em.get("risco_imediato", ""), idioma_destino),
                "comando_correcao": traduzir_texto_ia(em.get("comando_correcao", ""), idioma_destino)
            })

        bump_tr = {
            "titulo_bump": traduzir_texto_ia(b_raw.get("titulo_bump", ""), idioma_destino),
            "subtitulo_bump": traduzir_texto_ia(b_raw.get("subtitulo_bump", ""), idioma_destino),
            "copy_oferta_kiwify": traduzir_texto_ia(b_raw.get("copy_oferta_kiwify", ""), idioma_destino),
            "termo_capa": b_raw.get("termo_capa", ""),
            "checklist_rotina": chk_tr,
            "tabela_emergencia": tab_em_tr
        }
        etapa += 1

    if progress_bar:
        progress_bar.progress(1.0)

    return {
        "titulo": titulo_tr,
        "subtitulo": subtitulo_tr,
        "termo_capa": dados_livro.get("termo_capa", ""),
        "introducao": intro_tr,
        "modulos": modulos_tr,
        "apendice": apendice_tr,
        "order_bump": bump_tr
    }

# ==============================================================================
# 6. DIAGRAMAÇÃO EDITORIAL COM FLUXO OTIMIZADO
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
            self.setFont("Helvetica-Bold", 8.5)
            self.setFillColor(colors.HexColor("#64748B"))
            self.drawString(36, 18, "MANUAL DE ENGENHARIA & PROCEDIMENTOS | EDIÇÃO PROFISSIONAL")
            texto_pag = f"Página {self._pageNumber} de {page_count}"
            self.drawRightString(576, 18, texto_pag)
            self.setStrokeColor(colors.HexColor("#CBD5E1"))
            self.setLineWidth(0.6)
            self.line(36, 26, 576, 26)

            self.setFont("Helvetica", 8)
            self.setFillColor(colors.HexColor("#94A3B8"))
            self.drawString(36, 764, "PROTOCOLO TÉCNICO PADRONIZADO")
            self.line(36, 758, 576, 758)
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
        topMargin=38,
        bottomMargin=36
    )
    styles = getSampleStyleSheet()

    cor_primaria = colors.HexColor("#0F172A")
    cor_azul = colors.HexColor("#1D4ED8")
    cor_alerta_bg = colors.HexColor("#FEF2F2")
    cor_alerta_border = colors.HexColor("#FCA5A5")
    cor_alerta_text = colors.HexColor("#991B1B")

    estilo_capa_tit = ParagraphStyle(
        'CapaTitulo',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=28,
        leading=34,
        textColor=cor_azul,
        alignment=1,
        spaceAfter=10
    )
    estilo_capa_sub = ParagraphStyle(
        'CapaSub',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=13.5,
        leading=18,
        textColor=cor_primaria,
        alignment=1,
        spaceAfter=18
    )
    estilo_h1 = ParagraphStyle(
        'TitCap',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=18,
        leading=23,
        textColor=cor_azul,
        spaceBefore=14,
        spaceAfter=6,
        keepWithNext=True
    )
    estilo_h2 = ParagraphStyle(
        'TitSec',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=13.5,
        leading=17.5,
        textColor=cor_primaria,
        spaceBefore=10,
        spaceAfter=4,
        keepWithNext=True
    )
    estilo_corpo = ParagraphStyle(
        'CorpoTexto',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=12,
        leading=16.5,
        textColor=colors.HexColor("#1E293B"),
        spaceAfter=6,
        alignment=4
    )
    estilo_item = ParagraphStyle(
        'ItemPasso',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=11.5,
        leading=15.5,
        textColor=cor_primaria,
        spaceAfter=3
    )
    estilo_alerta = ParagraphStyle(
        'BoxAlerta',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=11,
        leading=14.5,
        textColor=cor_alerta_text
    )
    estilo_legenda_foto = ParagraphStyle(
        'LegendaFoto',
        parent=styles['Normal'],
        fontName='Helvetica-Oblique',
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#64748B"),
        alignment=1,
        spaceBefore=3,
        spaceAfter=5
    )
    estilo_celula = ParagraphStyle(
        'CelulaTab',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=13.5,
        textColor=cor_primaria
    )
    estilo_celula_header = ParagraphStyle(
        'CelulaHeader',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=10.5,
        leading=14,
        textColor=colors.white
    )

    flowables = []

    # CAPA
    flowables.append(Spacer(1, 20))
    flowables.append(Paragraph(dados_livro.get("titulo", "Manual Técnico Profissional"), estilo_capa_tit))
    flowables.append(Paragraph(dados_livro.get("subtitulo", "Guia Técnico Avançado"), estilo_capa_sub))

    termo_capa = dados_livro.get("termo_capa", "engineering business")
    capa_raw = os.path.join(DIR_PEXELS, f"livro_capa_raw_{int(time.time())}.jpg")
    capa_fit = os.path.join(DIR_PEXELS, f"livro_capa_fit_{int(time.time())}.jpg")
    if buscar_foto_pexels(termo_capa, pexels_key, capa_raw):
        if recortar_foto_proporcional(capa_raw, capa_fit, 1080, 520):
            try:
                flowables.append(RLImage(capa_fit, width=540, height=260))
            except Exception:
                pass

    flowables.append(Spacer(1, 15))
    flowables.append(Paragraph("<b>AUTORIA:</b> DEPARTAMENTO DE ENGENHARIA DE PROCESSOS & DESENVOLVIMENTO", estilo_legenda_foto))
    flowables.append(PageBreak())

    # SUMÁRIO
    flowables.append(Paragraph("Sumário Executivo", estilo_h1))
    flowables.append(HRFlowable(width="100%", thickness=1, color=cor_azul, spaceAfter=10))

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

    tab_sumario = Table(sumario_data, colWidths=[110, 430])
    tab_sumario.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), cor_azul),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ('PADDING', (0, 0), (-1, -1), 5),
    ]))
    flowables.append(tab_sumario)
    flowables.append(PageBreak())

    # INTRODUÇÃO
    flowables.append(Paragraph("Introdução Geral & Fundamentos Sistêmicos", estilo_h1))
    flowables.append(HRFlowable(width="100%", thickness=0.8, color=colors.HexColor("#CBD5E1"), spaceAfter=8))

    for p_intro in dados_livro.get("introducao", "").split("\n"):
        if p_intro.strip():
            flowables.append(Paragraph(p_intro.strip(), estilo_corpo))

    flowables.append(Spacer(1, 10))
    flowables.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#E2E8F0"), spaceAfter=14))

    # MÓDULOS
    for mod in dados_livro.get("modulos", []):
        flowables.append(Paragraph(f"Módulo {mod.get('numero')}: {mod.get('titulo')}", estilo_h1))
        flowables.append(HRFlowable(width="100%", thickness=0.8, color=cor_azul, spaceAfter=6))

        termo_proc = mod.get("termo_busca_foto_processo")
        if termo_proc:
            p_raw = os.path.join(DIR_PEXELS, f"mod_proc_raw_{mod.get('numero')}_{int(time.time())}.jpg")
            p_fit = os.path.join(DIR_PEXELS, f"mod_proc_fit_{mod.get('numero')}_{int(time.time())}.jpg")
            if buscar_foto_pexels(termo_proc, pexels_key, p_raw):
                if recortar_foto_proporcional(p_raw, p_fit, 1080, 220):
                    try:
                        flowables.append(RLImage(p_fit, width=540, height=110))
                        flowables.append(Spacer(1, 4))
                    except Exception:
                        pass

        alerta = mod.get("alerta_tecnico")
        if alerta:
            tabela_alerta = Table(
                [[Paragraph(f"<b>⚠️ PONTO CRÍTICO DE CONTROLE (ALERTA):</b> {alerta}", estilo_alerta)]],
                colWidths=[540]
            )
            tabela_alerta.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), cor_alerta_bg),
                ('BOX', (0, 0), (-1, -1), 1, cor_alerta_border),
                ('PADDING', (0, 0), (-1, -1), 5),
            ]))
            flowables.append(tabela_alerta)
            flowables.append(Spacer(1, 6))

        for sub in mod.get("subsecoes", []):
            flowables.append(Paragraph(sub.get("subtitulo", ""), estilo_h2))
            for p_sub in sub.get("conteudo", "").split("\n"):
                if p_sub.strip():
                    flowables.append(Paragraph(p_sub.strip(), estilo_corpo))

        flowables.append(Spacer(1, 4))

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

            tab_param = Table(dados_t, colWidths=[170, 110, 260])
            tab_param.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), cor_azul),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
                ('PADDING', (0, 0), (-1, -1), 4),
            ]))
            flowables.append(tab_param)
            flowables.append(Spacer(1, 6))

        passos = mod.get("passos_operacionais", [])
        if passos:
            flowables.append(Paragraph("<b>Procedimento Operacional Padrão (POP):</b>", estilo_h2))
            for idx_p, passo in enumerate(passos, 1):
                flowables.append(Paragraph(f"<b>Passo {idx_p}:</b> {passo}", estilo_item))

        termo_res = mod.get("termo_busca_foto_resultado")
        if termo_res:
            r_raw = os.path.join(DIR_PEXELS, f"mod_res_raw_{mod.get('numero')}_{int(time.time())}.jpg")
            r_fit = os.path.join(DIR_PEXELS, f"mod_res_fit_{mod.get('numero')}_{int(time.time())}.jpg")
            if buscar_foto_pexels(termo_res, pexels_key, r_raw):
                if recortar_foto_proporcional(r_raw, r_fit, 1080, 200):
                    try:
                        flowables.append(Spacer(1, 4))
                        flowables.append(RLImage(r_fit, width=540, height=100))
                        leg = mod.get("legenda_resultado", "Indicador visual de conformidade do resultado.")
                        flowables.append(Paragraph(f"📷 <b>Controle Visual:</b> {leg}", estilo_legenda_foto))
                    except Exception:
                        pass

        flowables.append(Spacer(1, 10))
        flowables.append(HRFlowable(width="100%", thickness=0.8, color=colors.HexColor("#CBD5E1"), spaceAfter=14))

    # APÊNDICE
    ap = dados_livro.get("apendice", {})
    flowables.append(Paragraph(ap.get("titulo", "Dossiê Clínico de Falhas & Engenharia de Lucro"), estilo_h1))
    flowables.append(HRFlowable(width="100%", thickness=1, color=cor_azul, spaceAfter=8))

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
        flowables.append(Spacer(1, 8))

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
        tab_c = Table(dados_c, colWidths=[170, 130, 240])
        tab_c.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), cor_azul),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
            ('PADDING', (0, 0), (-1, -1), 4),
        ]))
        flowables.append(tab_c)
        flowables.append(Spacer(1, 8))

    conclusao = ap.get("conclusao_executiva", "")
    if conclusao:
        flowables.append(Paragraph("Conclusão Executiva", estilo_h2))
        flowables.append(Paragraph(conclusao, estilo_corpo))

    doc.build(flowables, canvasmaker=NumeradorPaginas)
    return caminho_pdf

def compilar_pdf_order_bump(dados_bump: dict, pexels_key: str, caminho_pdf: str) -> str:
    doc = SimpleDocTemplate(
        caminho_pdf,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=32,
        bottomMargin=30
    )
    styles = getSampleStyleSheet()

    cor_primaria = colors.HexColor("#0F172A")
    cor_verde = colors.HexColor("#059669")
    cor_vermelho = colors.HexColor("#DC2626")

    estilo_tit = ParagraphStyle(
        'TitBump',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=20,
        leading=24,
        textColor=cor_verde,
        alignment=1,
        spaceAfter=4
    )
    estilo_sub = ParagraphStyle(
        'SubBump',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=12,
        leading=16,
        textColor=cor_primaria,
        alignment=1,
        spaceAfter=10
    )
    estilo_sec = ParagraphStyle(
        'SecBump',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=13,
        leading=17,
        textColor=cor_primaria,
        spaceBefore=8,
        spaceAfter=4,
        keepWithNext=True
    )
    estilo_celula = ParagraphStyle(
        'CelBump',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9.5,
        leading=13,
        textColor=cor_primaria
    )
    estilo_celula_h = ParagraphStyle(
        'CelHBump',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=10,
        leading=13.5,
        textColor=colors.white
    )

    flowables = []

    flowables.append(Paragraph(f"📋 {dados_bump.get('titulo_bump', 'Checklist Operacional de Campo')}", estilo_tit))
    flowables.append(Paragraph(dados_bump.get('subtitulo_bump', 'Protocolo Rápido de Execução e Auditoria'), estilo_sub))

    termo_capa = dados_bump.get("termo_capa", "practical checklist tool")
    capa_raw = os.path.join(DIR_PEXELS, f"bump_capa_raw_{int(time.time())}.jpg")
    capa_fit = os.path.join(DIR_PEXELS, f"bump_capa_fit_{int(time.time())}.jpg")
    if buscar_foto_pexels(termo_capa, pexels_key, capa_raw):
        if recortar_foto_proporcional(capa_raw, capa_fit, 1080, 260):
            try:
                flowables.append(RLImage(capa_fit, width=540, height=130))
                flowables.append(Spacer(1, 6))
            except Exception:
                pass

    flowables.append(Paragraph("Checklist de Conformidade Operacional (Auditoria Passo a Passo)", estilo_sec))
    chks = dados_bump.get("checklist_rotina", [])
    if chks:
        dados_t_chk = [
            [
                Paragraph("<b>Fase / Etapa</b>", estilo_celula_h),
                Paragraph("<b>Ponto Crítico de Checagem</b>", estilo_celula_h),
                Paragraph("<b>Critério de Aprovação / Status</b>", estilo_celula_h)
            ]
        ]
        for c in chks:
            dados_t_chk.append([
                Paragraph(f"<b>{c.get('fase', '')}</b>", estilo_celula),
                Paragraph(c.get("item", ""), estilo_celula),
                Paragraph(f"[  ] {c.get('criterio_aprovacao', '')}", estilo_celula)
            ])

        tab_chk = Table(dados_t_chk, colWidths=[110, 250, 180])
        tab_chk.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), cor_verde),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
            ('PADDING', (0, 0), (-1, -1), 4),
        ]))
        flowables.append(tab_chk)
        flowables.append(Spacer(1, 8))

    flowables.append(Paragraph("Protocolo Rápido de Emergência (Resolução em 5 Minutos)", estilo_sec))
    em_list = dados_bump.get("tabela_emergencia", [])
    if em_list:
        dados_t_em = [
            [
                Paragraph("<b>Anomalia / Desvio Crítico</b>", estilo_celula_h),
                Paragraph("<b>Risco Imediato</b>", estilo_celula_h),
                Paragraph("<b>Ação Corretiva em 5 Minutos</b>", estilo_celula_h)
            ]
        ]
        for em in em_list:
            dados_t_em.append([
                Paragraph(f"⚠ {em.get('anomalia', '')}", estilo_celula),
                Paragraph(em.get("risco_imediato", ""), estilo_celula),
                Paragraph(em.get("comando_correcao", ""), estilo_celula)
            ])

        tab_em = Table(dados_t_em, colWidths=[140, 170, 230])
        tab_em.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), cor_vermelho),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
            ('PADDING', (0, 0), (-1, -1), 4),
        ]))
        flowables.append(tab_em)

    doc.build(flowables, canvasmaker=NumeradorPaginasBump)
    return caminho_pdf

# ==============================================================================
# 7. PROCESSAMENTO DE VÍDEO (TTS, PEXELS, WATERMARK & FFMPEG)
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
    marca_dagua: Optional[str] = None,
    progress_bar = None
) -> str:
    res_w, res_h = (1080, 1920) if vertical else (1920, 1080)
    cenas_clipes = []
    total = len(cenas)

    filtro_marca = ""
    if marca_dagua and marca_dagua.strip():
        marca_limpa = re.sub(r"[':\\]", "", marca_dagua.strip())
        tam_fonte_marca = 32 if vertical else 26
        pos_y_marca = 80 if vertical else 50
        filtro_marca = (
            f",drawtext=text='{marca_limpa}':fontcolor=white@0.65:"
            f"fontsize={tam_fonte_marca}:box=1:boxcolor=black@0.35:boxborderw=8:"
            f"x=45:y={pos_y_marca}"
        )

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
                f"{filtro_marca}"
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
                f"{filtro_marca}"
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
    marca_dagua: Optional[str] = None,
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
        marca_dagua=marca_dagua,
        progress_bar=progress_bar
    )
    return video_dublado, cenas_traduzidas

# ==============================================================================
# 8. MOTOR DE INTEGRAÇÃO TIKTOK MARKETING API
# ==============================================================================
TIKTOK_API_BASE = "https://business-api.tiktok.com/open_api/v1.3"

def disparar_campanha_tiktok_completa(
    advertiser_id: str,
    access_token: str,
    video_path: str,
    campaign_name: str,
    copy_text: str,
    landing_page_url: str,
    orcamento_diario: float
) -> dict:
    headers = {"Access-Token": access_token}
    headers_json = {"Access-Token": access_token, "Content-Type": "application/json"}

    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Vídeo não encontrado em: {video_path}")

    url_upload = f"{TIKTOK_API_BASE}/file/video/ad/upload/"
    with open(video_path, "rb") as vf:
        files = {"video_file": vf}
        data = {"advertiser_id": advertiser_id, "upload_type": "UPLOAD_BY_FILE"}
        res_upload = requests.post(url_upload, headers=headers, data=data, files=files).json()

    if res_upload.get("code") != 0:
        raise Exception(f"Erro no Upload do Vídeo: {res_upload.get('message')}")
    
    video_id = res_upload["data"]["video_id"]

    url_campaign = f"{TIKTOK_API_BASE}/campaign/create/"
    payload_campaign = {
        "advertiser_id": advertiser_id,
        "campaign_name": campaign_name,
        "objective_type": "WEB_CONVERSIONS",
        "budget_mode": "BUDGET_MODE_DYNAMIC"
    }
    res_camp = requests.post(url_campaign, headers=headers_json, json=payload_campaign).json()
    if res_camp.get("code") != 0:
        raise Exception(f"Erro ao criar Campanha: {res_camp.get('message')}")
    
    campaign_id = res_camp["data"]["campaign_id"]

    url_adgroup = f"{TIKTOK_API_BASE}/adgroup/create/"
    data_inicio = datetime.now(timezone.utc) + timedelta(minutes=10)
    data_formatada = data_inicio.strftime("%Y-%m-%d %H:%M:%S")

    payload_adgroup = {
        "advertiser_id": advertiser_id,
        "campaign_id": campaign_id,
        "adgroup_name": f"Grupo - {campaign_name}",
        "placement_type": "PLACEMENT_TYPE_NORMAL",
        "placements": ["PLACEMENT_TIKTOK"],
        "location_ids": ["6252001"],
        "budget_mode": "BUDGET_MODE_DAY",
        "budget": orcamento_diario,
        "schedule_type": "SCHEDULE_FROM_NOW",
        "schedule_start_time": data_formatada,
        "billing_event": "OCPM",
        "bid_type": "BID_TYPE_NO_BID",
        "optimization_goal": "CLICK"
    }
    res_adgroup = requests.post(url_adgroup, headers=headers_json, json=payload_adgroup).json()
    if res_adgroup.get("code") != 0:
        raise Exception(f"Erro ao criar Grupo de Anúncios: {res_adgroup.get('message')}")
    
    adgroup_id = res_adgroup["data"]["adgroup_id"]

    url_ad = f"{TIKTOK_API_BASE}/ad/create/"
    payload_ad = {
        "advertiser_id": advertiser_id,
        "adgroup_id": adgroup_id,
        "creatives": [{
            "ad_name": f"Criativo - {campaign_name}",
            "ad_format": "SINGLE_VIDEO",
            "video_id": video_id,
            "ad_text": copy_text[:100],
            "call_to_action": "LEARN_MORE",
            "landing_page_url": landing_page_url
        }]
    }
    res_ad = requests.post(url_ad, headers=headers_json, json=payload_ad).json()
    if res_ad.get("code") != 0:
        raise Exception(f"Erro ao publicar Anúncio: {res_ad.get('message')}")

    return {
        "video_id": video_id,
        "campaign_id": campaign_id,
        "adgroup_id": adgroup_id,
        "ad_id": res_ad["data"]["ad_ids"][0]
    }

# ==============================================================================
# 9. INICIALIZAÇÃO DE ESTADOS GLOBAIS
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

if "vsl_musica_ativa" not in st.session_state:
    st.session_state["vsl_musica_ativa"] = None
if "vsl_marca_ativa" not in st.session_state:
    st.session_state["vsl_marca_ativa"] = ""

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
    st.write("• TikTok Ads:", "🟢 Token Configurado" if TIKTOK_ACCESS_TOKEN else "🟡 Aguardando Token")

# ==============================================================================
# 10. ABAS PRINCIPAIS DO SISTEMA
# ==============================================================================
tab_minerador, tab_vsl, tab_ebook, tab_ads, tab_master = st.tabs([
    "🔍 1. Minerador & Google Ads",
    "🚀 2. Criar VSL & Dublagem Global",
    "📚 3. Criar Livro Técnico & Order Bump",
    "🎯 4. Central de Publicidade",
    "👑 5. Gestão Master"
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
                        "pdf_global_nome", "pdf_global_lingua", "dados_livro_sessao",
                        "pdf_bump_pronto", "pdf_bump_nome", "pdf_bump_global_pronto"
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
        formato_vertical = st.checkbox("Formato Vertical 9:16 (Reels/TikTok/Shorts)", value=True, key="vsl_check_vertical")
        marca_dagua_input = st.text_input(
            "🔒 Marca d'água (Anti-Cópia):",
            value=st.session_state.get("vsl_marca_ativa", ""),
            placeholder="Ex: @receitas.semgluten ou Manual Prático",
            help="Texto semi-transparente fixo no topo esquerdo do vídeo que impede plágio do seu anúncio.",
            key="vsl_input_marca_dagua"
        )
    with col_opt2:
        voz_sel = st.selectbox("Locução (OpenAI TTS):", ["onyx (Forte/Masculina)", "alloy (Neutra)", "nova (Energética/Feminina)", "echo (Suave)"], key="vsl_select_voz")
        voz_codigo = voz_sel.split()[0]
    with col_opt3:
        musica_up = st.file_uploader("Adicionar novo .mp3 (Salva no acervo):", type=["mp3"], key="vsl_uploader_musica")
        if musica_up:
            p_salvar = os.path.join(DIR_MUSICAS, musica_up.name)
            if not os.path.exists(p_salvar):
                with open(p_salvar, "wb") as f_m:
                    f_m.write(musica_up.getbuffer())
                st.toast(f"Música '{musica_up.name}' adicionada ao acervo!", icon="🎵")

        opcoes_musica = listar_musicas_locais()
        trilha_escolhida_nome = st.selectbox(
            "Trilha Sonora de Fundo (8% vol):",
            options=list(opcoes_musica.keys()),
            key="vsl_select_trilha"
        )
        caminho_musica_ativa = opcoes_musica[trilha_escolhida_nome]
        st.session_state["vsl_musica_ativa"] = caminho_musica_ativa

    if st.button("🎬 Gerar Roteiro e Renderizar VSL Original (20 cr)", type="primary", key="btn_render_vsl"):
        if saldo_atual < 20:
            st.error("❌ Saldo insuficiente! Você precisa de 20 créditos.")
        else:
            barra_vsl = st.progress(0.0)
            with st.spinner(f"Criando cenas visuais de '{tema_vsl}' no Pexels, áudio sincronizado e cortes dinâmicos..."):
                try:
                    cenas_estruturadas = gerar_roteiro_vsl_ia(tema_vsl, promessa_vsl, publico_vsl, qtd_cenas)
                    st.session_state["roteiro_vsl"] = cenas_estruturadas
                    st.session_state["vsl_marca_ativa"] = marca_dagua_input

                    p_musica = st.session_state.get("vsl_musica_ativa")

                    video_pronto = renderizar_vsl_completa(
                        cenas=cenas_estruturadas,
                        vertical=formato_vertical,
                        voz=voz_codigo,
                        pexels_key=PEXELS_API_KEY,
                        musica_fundo_path=p_musica,
                        volume_musica=0.08,
                        marca_dagua=marca_dagua_input,
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
                btn_dub = st.button("🎙 Dublar Vídeo Agora (20 cr)", type="primary", use_container_width=True, key="btn_exec_dub")

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
                            p_musica = st.session_state.get("vsl_musica_ativa")
                            marca_ativa = st.session_state.get("vsl_marca_ativa", marca_dagua_input)
                            v_dublado, rot_tr = dublar_roteiro_e_renderizar_vsl(
                                cenas_originais=st.session_state["roteiro_vsl"],
                                idioma_alvo=nome_lingua_dub,
                                vertical=formato_vertical,
                                voz=voz_codigo,
                                pexels_key=PEXELS_API_KEY,
                                musica_fundo_path=p_musica,
                                volume_musica=0.08,
                                marca_dagua=marca_ativa,
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
# ABA 3: CRIAR LIVRO TÉCNICO & ORDER BUMP / BÔNUS COMPLEMENTAR
# ------------------------------------------------------------------------------
with tab_ebook:
    st.markdown("## 📚 Gerador de Livro Técnico & Produto Complementar (Order Bump)")
    st.caption("Crie o manual técnico principal de alta densidade e, opcionalmente, o produto de Order Bump para dobrar seu ticket médio.")

    col_e1, col_e2 = st.columns(2)
    with col_e1:
        tema_ebook = st.text_input("Tema Central do Manual:", key="ebook_input_tema")
    with col_e2:
        publico_ebook = st.text_input("Público-Alvo / Perfil Técnico:", key="ebook_input_publico")

    gerar_bump_opt = st.checkbox(
        "🎁 Gerar também o Produto Complementar (Order Bump / Checklist Operacional de Alta Conversão)",
        value=True,
        key="chk_gerar_order_bump"
    )

    if st.button("📖 Compilar Kit Digital Completo (.PDF) (10 cr)", type="primary", key="btn_render_ebook"):
        if saldo_atual < 10:
            st.error("❌ Saldo insuficiente! Você precisa de 10 créditos.")
        else:
            prog_bar = st.progress(0.0)
            status_box = st.empty()
            try:
                dados_livro = pipeline_geracao_livro_completo(
                    tema=tema_ebook,
                    publico=publico_ebook,
                    gerar_bump=gerar_bump_opt,
                    status_placeholder=status_box,
                    progress_bar=prog_bar
                )
                st.session_state["dados_livro_sessao"] = dados_livro

                status_box.write("📑 Diagramando Manual Técnico Principal com ReportLab...")
                nome_pdf = f"manual_tecnico_{re.sub(r'[^a-zA-Z0-9]', '_', tema_ebook.lower())[:22]}_{int(time.time())}.pdf"
                caminho_pdf = os.path.join(DIR_EBOOKS, nome_pdf)
                compilar_pdf_livro_tecnico(dados_livro, PEXELS_API_KEY, caminho_pdf)

                st.session_state["pdf_ebook_pronto"] = caminho_pdf
                st.session_state["pdf_ebook_nome"] = nome_pdf

                if gerar_bump_opt and dados_livro.get("order_bump"):
                    status_box.write("🎁 Diagramando Caderno de Campo / Order Bump...")
                    nome_bump_pdf = f"order_bump_{re.sub(r'[^a-zA-Z0-9]', '_', tema_ebook.lower())[:20]}_{int(time.time())}.pdf"
                    caminho_bump_pdf = os.path.join(DIR_EBOOKS, nome_bump_pdf)
                    compilar_pdf_order_bump(dados_livro["order_bump"], PEXELS_API_KEY, caminho_bump_pdf)

                    st.session_state["pdf_bump_pronto"] = caminho_bump_pdf
                    st.session_state["pdf_bump_nome"] = nome_bump_pdf
                else:
                    st.session_state.pop("pdf_bump_pronto", None)

                debitar_creditos_cloud(email_usuario, f"Criação Kit Digital ({tema_ebook})", 10)

                status_box.empty()
                prog_bar.progress(1.0)
                st.success("✅ Kit Digital Compilado com Sucesso! Manual denso e acelerador de vendas prontos.")
                st.rerun()
            except Exception as e_eb:
                st.error(f"Erro na compilação do Kit: {e_eb}")

    if st.session_state.get("pdf_ebook_pronto") and os.path.exists(st.session_state["pdf_ebook_pronto"]):
        st.markdown("---")
        st.markdown("### 📦 Seus Produtos Digitais Prontos para Venda:")

        col_down1, col_down2 = st.columns(2)
        with col_down1:
            with st.container(border=True):
                st.markdown("#### 📘 1. Manual Técnico Principal")
                st.caption("Livro completo com fundamentos, ementa, procedimentos e análise de falhas.")
                with open(st.session_state["pdf_ebook_pronto"], "rb") as f_eb:
                    st.download_button(
                        "⬇️ Baixar Manual Técnico (.PDF)",
                        data=f_eb,
                        file_name=st.session_state.get("pdf_ebook_nome", "manual_tecnico.pdf"),
                        mime="application/pdf",
                        use_container_width=True,
                        key="btn_down_eb_orig"
                    )

        with col_down2:
            if st.session_state.get("pdf_bump_pronto") and os.path.exists(st.session_state["pdf_bump_pronto"]):
                with st.container(border=True):
                    st.markdown("#### 🎁 2. Produto Complementar (Order Bump)")
                    st.caption("Checklist operacional de campo e protocolos rápidos de emergência.")
                    with open(st.session_state["pdf_bump_pronto"], "rb") as f_bump:
                        st.download_button(
                            "⬇️ Baixar Order Bump / Checklist (.PDF)",
                            data=f_bump,
                            file_name=st.session_state.get("pdf_bump_nome", "checklist_order_bump.pdf"),
                            mime="application/pdf",
                            type="primary",
                            use_container_width=True,
                            key="btn_down_bump_orig"
                        )
            else:
                st.info("💡 A opção de produto complementar não foi selecionada nesta compilação.")

        if st.session_state.get("dados_livro_sessao", {}).get("order_bump"):
            b_info = st.session_state["dados_livro_sessao"]["order_bump"]
            with st.expander("📋 Ver Copy Pronta para a caixinha de Order Bump na Kiwify / Checkout"):
                st.markdown(f"**Título da Oferta:** `{b_info.get('titulo_bump')}`")
                st.markdown(f"**Preço Recomendado:** `R$ 19,90 ou R$ 24,90`")
                st.text_area("Texto de Chamada do Checkout:", value=b_info.get("copy_oferta_kiwify", ""), height=100)

        st.markdown("---")
        with st.container(border=True):
            st.markdown("### 🌐 Tradução Global do Kit (36 Idiomas)")
            st.caption("Internacionalize o manual e o order bump preservando diagramação e matrizes.")

            col_tr1, col_tr2 = st.columns([2, 1])
            with col_tr1:
                idioma_eb_sel = st.selectbox("Selecione o Idioma de Destino:", list(IDIOMAS_SISTEMA_36.keys()), key="ebook_select_idioma_tr")
            with col_tr2:
                st.write("")
                st.caption("Custo: 10 Créditos")
                btn_trad_eb = st.button("🌍 Traduzir Kit Completo (10 cr)", type="primary", use_container_width=True, key="btn_exec_trad_eb")

            if btn_trad_eb:
                if saldo_atual < 10:
                    st.error("❌ Saldo insuficiente para internacionalização.")
                elif not st.session_state.get("dados_livro_sessao"):
                    st.error("Dados da sessão não encontrados.")
                else:
                    nome_lingua_eb = IDIOMAS_SISTEMA_36[idioma_eb_sel]
                    barra_eb_tr = st.progress(0.0)
                    with st.spinner(f"Traduzindo Kit Técnico Completo para {idioma_eb_sel}..."):
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

                            st.session_state["pdf_global_pronto"] = caminho_pdf_tr
                            st.session_state["pdf_global_nome"] = nome_pdf_tr
                            st.session_state["pdf_global_lingua"] = idioma_eb_sel

                            if dados_tr.get("order_bump"):
                                nome_bump_tr = f"order_bump_{cod_idioma}_{int(time.time())}.pdf"
                                caminho_bump_tr = os.path.join(DIR_EBOOKS, nome_bump_tr)
                                compilar_pdf_order_bump(dados_tr["order_bump"], PEXELS_API_KEY, caminho_bump_tr)
                                st.session_state["pdf_bump_global_pronto"] = caminho_bump_tr
                                st.session_state["pdf_bump_global_nome"] = nome_bump_tr

                            debitar_creditos_cloud(email_usuario, f"Tradução Kit ({nome_lingua_eb})", 10)
                            st.success(f"✅ Kit traduzido com sucesso para {idioma_eb_sel}!")
                            st.rerun()
                        except Exception as e_tr:
                            st.error(f"Erro na tradução: {e_tr}")

        if st.session_state.get("pdf_global_pronto") and os.path.exists(st.session_state["pdf_global_pronto"]):
            st.success(f"✅ Kit internacionalizado pronto em: **{st.session_state.get('pdf_global_lingua')}**")
            col_tr_d1, col_tr_d2 = st.columns(2)
            with col_tr_d1:
                with open(st.session_state["pdf_global_pronto"], "rb") as f_tr_eb:
                    st.download_button(
                        label=f"⬇️ BAIXAR MANUAL EM {st.session_state.get('pdf_global_lingua').upper()} (.PDF)",
                        data=f_tr_eb,
                        file_name=st.session_state.get("pdf_global_nome", "manual_global.pdf"),
                        mime="application/pdf",
                        use_container_width=True,
                        key="btn_down_eb_glob"
                    )
            with col_tr_d2:
                if st.session_state.get("pdf_bump_global_pronto") and os.path.exists(st.session_state["pdf_bump_global_pronto"]):
                    with open(st.session_state["pdf_bump_global_pronto"], "rb") as f_tr_bump:
                        st.download_button(
                            label=f"⬇️ BAIXAR ORDER BUMP EM {st.session_state.get('pdf_global_lingua').upper()} (.PDF)",
                            data=f_tr_bump,
                            file_name=st.session_state.get("pdf_bump_global_nome", "order_bump_global.pdf"),
                            mime="application/pdf",
                            type="primary",
                            use_container_width=True,
                            key="btn_down_bump_glob"
                        )

# ------------------------------------------------------------------------------
# ABA 4: CENTRAL DE PUBLICIDADE MULTIPLATAFORMA
# ------------------------------------------------------------------------------
with tab_ads:
    st.markdown("## 🎯 Central de Tráfego & Publicidade Automática")
    st.caption("Dispare campanhas em redes de tráfego pago utilizando os criativos já renderizados nas etapas anteriores.")

    if "plataforma_ativa" not in st.session_state:
        st.session_state["plataforma_ativa"] = "TikTok"

    col_icon_tt, col_icon_meta, col_icon_goog = st.columns(3)
    with col_icon_tt:
        if st.button("🎵 **TikTok Ads**\n\n*(Vídeos Verticais 9:16)*", use_container_width=True):
            st.session_state["plataforma_ativa"] = "TikTok"
    with col_icon_meta:
        if st.button("🔵 **Meta Ads**\n\n*(Instagram Reels & Stories)*", use_container_width=True):
            st.session_state["plataforma_ativa"] = "Meta"
    with col_icon_goog:
        if st.button("🔴 **Google & YouTube**\n\n*(YouTube Shorts & Search)*", use_container_width=True):
            st.session_state["plataforma_ativa"] = "Google"

    st.markdown("---")

    # PAINEL TIKTOK ADS
    if st.session_state["plataforma_ativa"] == "TikTok":
        st.subheader("🎵 Disparo de Anúncios no TikTok Ads")

        video_atual = st.session_state.get("video_vsl_pronto")

        col_cfg1, col_cfg2 = st.columns([1.2, 1])

        with col_cfg1:
            st.markdown("##### 1. Configuração da Campanha")
            nome_sugerido = f"Campanha VSL - {st.session_state.get('nicho_pesquisado_nome', 'Conversão')}"
            nome_camp = st.text_input("Nome da Campanha:", value=nome_sugerido)
            link_checkout = st.text_input(
                "Link de Checkout da Kiwify / Página de Vendas:",
                placeholder="https://pay.kiwify.com.br/...",
                help="Insira a URL que receberá o tráfego do anúncio."
            )
            
            c_orc, c_moeda = st.columns([2, 1])
            with c_orc:
                orcamento = st.number_input("Orçamento Diário:", min_value=30.0, value=60.0, step=10.0)
            with c_moeda:
                st.selectbox("Moeda:", ["BRL (R$)"], disabled=True)

            copy_anuncio = st.text_area(
                "Texto do Anúncio (Legenda):",
                value=f"Descubra o passo a passo completo sobre {st.session_state.get('nicho_pesquisado_nome', 'este método')}! Toque em 'Saiba Mais'.",
                height=90
            )

        with col_cfg2:
            st.markdown("##### 2. Criativo em Vídeo (9:16)")
            if video_atual and os.path.exists(video_atual):
                st.video(video_atual)
                st.success("✅ Vídeo da VSL pronto e carregado na memória!")
            else:
                st.info("Nenhum vídeo renderizado na aba 2. Você pode subir um arquivo local:")
                video_manual = st.file_uploader("Carregar arquivo .MP4 do seu computador:", type=["mp4"])
                if video_manual:
                    caminho_ad = os.path.join(DIR_VSL, f"upload_manual_{int(time.time())}.mp4")
                    with open(caminho_ad, "wb") as f_up:
                        f_up.write(video_manual.read())
                    st.session_state["video_vsl_pronto"] = caminho_ad
                    st.video(caminho_ad)

        st.markdown("---")
        st.markdown("##### 3. Autenticação e Disparo")

        adv_padrao = TIKTOK_ADVERTISER_ID
        tok_padrao = TIKTOK_ACCESS_TOKEN

        col_c1, col_c2 = st.columns(2)
        with col_c1:
            adv_id_input = st.text_input("Advertiser ID (Conta Central VSL):", value=adv_padrao)
        with col_c2:
            token_input = st.text_input(
                "TikTok Access Token:",
                value=tok_padrao,
                type="password",
                help="Token gerado no portal TikTok for Business Developers"
            )

        aba_disparo, aba_manual_tt = st.tabs(["⚡ Disparo Automático (1 Clique)", "📥 Download & Atalho Manual"])

        with aba_disparo:
            if st.button("🚀 Publicar Campanha Completa no TikTok Ads", type="primary", use_container_width=True):
                vid_path = st.session_state.get("video_vsl_pronto")
                if not token_input:
                    st.error("⚠️ Insira o Access Token do TikTok para autenticar a API.")
                elif not link_checkout:
                    st.error("⚠️ Preencha o link de checkout da Kiwify.")
                elif not vid_path or not os.path.exists(vid_path):
                    st.error("⚠️ Nenhum arquivo de vídeo carregado na memória.")
                else:
                    with st.spinner("⏳ Criando campanha, enviando vídeo e ativando anúncio no TikTok..."):
                        try:
                            res_publicacao = disparar_campanha_tiktok_completa(
                                advertiser_id=adv_id_input,
                                access_token=token_input,
                                video_path=vid_path,
                                campaign_name=nome_camp,
                                copy_text=copy_anuncio,
                                landing_page_url=link_checkout,
                                orcamento_diario=orcamento
                            )
                            st.success("🎉 Campanha criada e enviada com sucesso ao TikTok Ads!")
                            st.json(res_publicacao)
                        except Exception as e_pub:
                            st.error(f"Erro na publicação: {e_pub}")

        with aba_manual_tt:
            st.caption("Caso ainda não tenha o Access Token gerado, baixe o vídeo e abra o gerenciador:")
            col_m_btn1, col_m_btn2 = st.columns(2)
            with col_m_btn1:
                if video_atual and os.path.exists(video_atual):
                    with open(video_atual, "rb") as f_v_ad:
                        st.download_button(
                            "📥 Baixar Vídeo Renderizado (.mp4)",
                            data=f_v_ad,
                            file_name="anuncio_tiktok_vsl.mp4",
                            use_container_width=True
                        )
            with col_m_btn2:
                st.link_button(
                    "🌐 Abrir TikTok Ads Manager",
                    "https://ads.tiktok.com/i18n/dashboard",
                    use_container_width=True
                )

    # PAINEL META ADS
    elif st.session_state["plataforma_ativa"] == "Meta":
        st.subheader("🔵 Meta Ads (Instagram Reels & Stories)")
        st.info("Módulo estruturado para integração via Graph API do Facebook. Utilizará o mesmo vídeo 9:16 gerado pela VSL.")

    # PAINEL GOOGLE ADS
    elif st.session_state["plataforma_ativa"] == "Google":
        st.subheader("🔴 Google Ads & YouTube Shorts")
        st.info("Módulo estruturado para disparo de YouTube Shorts e campanhas de Display/Search.")

# ------------------------------------------------------------------------------
# ABA 5: GESTÃO MASTER
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

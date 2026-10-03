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

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image as RLImage, PageBreak, Table, TableStyle, HRFlowable
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
    2. NUNCA faça conversão 1 para 1 cega (ex: NÃO transforme R$ 3.000 em 3.000 Euros ou Dólares).
    3. Adapte valores para paridade crível de mercado:
       - Espanhol/Europeu: R$ 3.000 vira "entre 600€ e 1.000€ mensais de renda extra".
       - Inglês/Dólar: R$ 3.000 vira "$600 a $1.200 USD de renda extra".
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
    Atue como Diretor de Aquisição e Especialista Sênior em Tráfego Pago, Copywriting e Validação de Produtos Digitais.
    Domínio absoluto de: Google Ads, Meta Ads, Kiwify e plataformas internacionais.
    
    Analise o seguinte nicho:
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
    
    Gere exatamente {num_cenas} cenas cronológicas (atenção, dor, virada, benefício, CTA).
    Para cada cena:
    1. "fala": Frase falada em português (curta, de 10 a 16 palavras, impactante).
    2. "termo_video": Termo em INGLÊS de 2 a 4 palavras para buscar vídeos em HD no Pexels que retratem exatamente o nicho '{nicho}' (Ex: se for cachorro: "dog training park", "obedient dog trainer"; se for ar condicionado: "air conditioner technician repair"; se for confeitaria: "decorating cake pastry chef"). NUNCA use termos de outros nichos.
    
    Retorne estritamente um JSON:
    {{
        "cenas": [
            {{"fala": "...", "termo_video": "..."}}
        ]
    }}
    """
    resp = executar_prompt_ia(prompt, formato_json=True, temperatura=0.4)
    termo_generico_nicho = re.sub(r'[^a-zA-Z0-9\s]', '', nicho).strip()
    try:
        dados = json.loads(resp)
        cenas_raw = dados.get("cenas", [])
        cenas_limpas = []
        for c in cenas_raw:
            if isinstance(c, dict):
                fala = c.get("fala", "").strip()
                termo = c.get("termo_video", termo_generico_nicho).strip()
                if fala:
                    cenas_limpas.append({"fala": fala, "termo_video": termo})
        return cenas_limpas if cenas_limpas else [{"fala": promessa, "termo_video": termo_generico_nicho}]
    except Exception:
        return [
            {"fala": f"Descubra o método definitivo sobre {nicho}.", "termo_video": termo_generico_nicho},
            {"fala": promessa, "termo_video": f"{termo_generico_nicho} professional"},
            {"fala": "Aprenda o passo a passo testado para ter resultados reais.", "termo_video": f"{termo_generico_nicho} lifestyle"}
        ]

def gerar_conteudo_ebook_ia(tema: str, publico: str) -> dict:
    prompt = f"""
    Atue como Especialista de Elite, Autoridade Sênior e Consultor Master no tema: '{tema}'.
    Escreva um MANUAL TÉCNICO E PRÁTICO AVANÇADO, DENSO E COM DUPLA ILUSTRAÇÃO sobre:
    - TEMA: {tema}
    - PÚBLICO: {publico}

    DIRETRIZES DE EXTREMO RIGOR:
    1. PROIBIDO TEXTO SUPERFICIAL OU RESUMINHOS. Seja um manual comercial de alto valor.
    2. O conteúdo deve ser 100% PERSONALIZADO para '{tema}'.
       - Se for Pet/Cães: foco em comportamento canino, reforço positivo, comandos e resolução de desobediência.
       - Se for Técnico/Serviços: ferramentas, procedimentos passo a passo, diagnósticos de defeito e segurança.
       - Se for Culinária: insumos exatos em gramas, reações físico-químicas, temperaturas e ponto de textura.
       - Se for Negócios: estratégias, métricas, planilhas e plano de ação.
    3. Para CADA capítulo, forneça DOIS termos de busca em inglês para o Pexels FOCADOS EXCLUSIVAMENTE em '{tema}':
       - "termo_busca_foto_processo": Ação/preparo/treinamento/trabalho no nicho '{tema}'.
       - "termo_busca_foto_resultado": O resultado final de sucesso no nicho '{tema}'.
       - "legenda_resultado": Frase técnica sobre o resultado visual esperado.
    4. Crie uma TABELA TÉCNICA ESTRUTURADA por capítulo com parâmetros objetivos (ex: Insumos/Ferramentas/Comandos, Medidas/Doses/Tempos, e Impacto Prático).
    5. No Módulo 4, inclua Diagnóstico de Erros Comuns e Precificação/Monetização no mercado de '{tema}'.

    Retorne ESTRITAMENTE um JSON estruturado com o seguinte esquema:
    {{
        "titulo": "Título Comercial Magnético para {tema}",
        "subtitulo": "Subtítulo de Transformação e Método Prático",
        "termo_capa": "Termo em inglês de 2 a 4 palavras para foto de capa no Pexels sobre {tema}",
        "introducao": "Texto denso e detalhado de introdução explicando as bases sólidas e o método prático...",
        "capitulos": [
            {{
                "numero": 1,
                "titulo": "Fundamentos Estratégicos & Pilares Iniciais",
                "termo_busca_foto_processo": "termo em inglês de ação sobre {tema}",
                "termo_busca_foto_resultado": "termo em inglês de resultado sobre {tema}",
                "legenda_resultado": "Resultado visual da primeira etapa bem executada.",
                "alerta_tecnico": "O erro mais comum cometido por iniciantes neste tema e como evitar.",
                "conteudo": "Explicação técnica densa e aprofundada dos fundamentos...",
                "receita_nome": "Ficha Técnica / Protocolo Operacional Padrão",
                "tabela_ingredientes": [
                    {{"ingrediente": "Item / Ferramenta / Insumo 1", "quantidade": "Dose / Medida / Tempo", "funcao": "Função prática e impacto no resultado"}},
                    {{"ingrediente": "Item / Ferramenta / Insumo 2", "quantidade": "Dose / Medida / Tempo", "funcao": "Função prática e impacto no resultado"}},
                    {{"ingrediente": "Item / Ferramenta / Insumo 3", "quantidade": "Dose / Medida / Tempo", "funcao": "Função prática e impacto no resultado"}},
                    {{"ingrediente": "Item / Ferramenta / Insumo 4", "quantidade": "Dose / Medida / Tempo", "funcao": "Função prática e impacto no resultado"}}
                ],
                "passos_preparo": [
                    "Passo 1 detalhado com técnica e cuidado.",
                    "Passo 2 com tempo e parâmetro exato.",
                    "Passo 3 de finalização e conferência."
                ]
            }},
            {{
                "numero": 2,
                "titulo": "Aplicação Prática Avançada & Execução do Método",
                "termo_busca_foto_processo": "termo em inglês de ação avançada sobre {tema}",
                "termo_busca_foto_resultado": "termo em inglês de resultado avançado sobre {tema}",
                "legenda_resultado": "Execução perfeita do método com estabilidade.",
                "alerta_tecnico": "Ponto crítico onde a maioria falha e como blindar a execução.",
                "conteudo": "Metodologia prática detalhada passo a passo sem esconder nada...",
                "receita_nome": "Protocolo Master de Execução",
                "tabela_ingredientes": [
                    {{"ingrediente": "Parâmetro Principal", "quantidade": "Especificação Técnica", "funcao": "Estabilidade e eficiência"}},
                    {{"ingrediente": "Parâmetro Secundário", "quantidade": "Especificação Técnica", "funcao": "Acabamento e durabilidade"}}
                ],
                "passos_preparo": [
                    "Etapa de preparação e alinhamento.",
                    "Etapa de aplicação e controle.",
                    "Etapa de validação prática."
                ]
            }},
            {{
                "numero": 3,
                "titulo": "Refinamento, Escala & Maximização de Resultados",
                "termo_busca_foto_processo": "termo em inglês de escala sobre {tema}",
                "termo_busca_foto_resultado": "termo em inglês de perfeição sobre {tema}",
                "legenda_resultado": "Padrão de excelência final alcançado com consistência.",
                "alerta_tecnico": "Segredo profissional para manter a consistência de longo prazo.",
                "conteudo": "Técnicas avançadas de manutenção de qualidade e consistência...",
                "receita_nome": "Checklist de Alta Performance",
                "tabela_ingredientes": [
                    {{"ingrediente": "Controle de Qualidade", "quantidade": "Diário / Semanal", "funcao": "Evitar regressão de resultados"}},
                    {{"ingrediente": "Otimização Contínua", "quantidade": "Periódico", "funcao": "Aceleração de desempenho"}}
                ],
                "passos_preparo": [
                    "Procedimento de monitoramento.",
                    "Ajuste fino de parâmetros.",
                    "Consolidação dos ganhos."
                ]
            }},
            {{
                "numero": 4,
                "titulo": "Dossiê Clínico de Resolução de Erros & Monetização",
                "termo_busca_foto_processo": "termo em inglês de diagnóstico sobre {tema}",
                "termo_busca_foto_resultado": "termo em inglês de negócio sucesso sobre {tema}",
                "legenda_resultado": "Estrutura final validada, lucrativa e livre de falhas.",
                "alerta_tecnico": "Atenção aos sinais prematuros de falha e como agir de imediato.",
                "conteudo": "Guia de Troubleshooting (o que fazer quando algo der errado) e estratégia comercial para precificar serviços ou produtos no nicho de {tema}.",
                "receita_nome": "Ficha Financeira e Matriz de Resolução de Problemas",
                "tabela_ingredientes": [
                    {{"ingrediente": "Custo de Implementação / Insumos", "quantidade": "Valor médio estimado", "funcao": "Base de custo real"}},
                    {{"ingrediente": "Preço de Cobrança / Venda Sugerido", "quantidade": "Margem de 100% a 150%", "funcao": "Lucro líquido sustentável"}},
                    {{"ingrediente": "Garantia de Satisfação do Cliente", "quantidade": "Procedimento padrão", "funcao": "Retenção e indicação orgânica"}}
                ],
                "passos_preparo": [
                    "Identifique o sintoma do problema antes de tentar qualquer correção.",
                    "Aplique a solução indicada no checklist de contingência.",
                    "Calcule o retorno sobre investimento (ROI) da operação."
                ]
            }}
        ]
    }}
    """
    resp = executar_prompt_ia(prompt, formato_json=True, temperatura=0.3)
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
        alerta_tr = traduzir_texto_ia(cap.get("alerta_tecnico", ""), idioma_destino)
        r_nome_tr = traduzir_texto_ia(cap.get("receita_nome", ""), idioma_destino)
        legenda_tr = traduzir_texto_ia(cap.get("legenda_resultado", ""), idioma_destino)

        tabela_tr = []
        for item in cap.get("tabela_ingredientes", []):
            tabela_tr.append({
                "ingrediente": traduzir_texto_ia(item.get("ingrediente", ""), idioma_destino),
                "quantidade": item.get("quantidade", ""),
                "funcao": traduzir_texto_ia(item.get("funcao", ""), idioma_destino)
            })

        passos_tr = [traduzir_texto_ia(p, idioma_destino) for p in cap.get("passos_preparo", [])]

        capitulos_tr.append({
            "numero": cap.get("numero", 1),
            "titulo": t_cap_tr,
            "termo_busca_foto_processo": cap.get("termo_busca_foto_processo", ""),
            "termo_busca_foto_resultado": cap.get("termo_busca_foto_resultado", ""),
            "legenda_resultado": legenda_tr,
            "alerta_tecnico": alerta_tr,
            "conteudo": c_cap_tr,
            "receita_nome": r_nome_tr,
            "tabela_ingredientes": tabela_tr,
            "passos_preparo": passos_tr
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
# 4. PROCESSAMENTO GRÁFICO EDITORIAL (DUPLA ILUSTRAÇÃO & ZERO ESPAÇO VAZIO)
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
            self.setFont("Helvetica-Bold", 8)
            self.setFillColor(colors.HexColor("#64748B"))
            self.drawString(36, 20, "MANUAL TÉCNICO PROFISSIONAL | TODOS OS DIREITOS RESERVADOS")
            texto_pag = f"Página {self._pageNumber} de {page_count}"
            self.drawRightString(576, 20, texto_pag)
            self.setStrokeColor(colors.HexColor("#CBD5E1"))
            self.setLineWidth(0.6)
            self.line(36, 30, 576, 30)
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

def compilar_pdf_ebook_com_fotos(dados: dict, pexels_key: str, caminho_pdf: str) -> str:
    doc = SimpleDocTemplate(
        caminho_pdf,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=42
    )
    styles = getSampleStyleSheet()

    cor_primaria = colors.HexColor("#0F172A")
    cor_azul = colors.HexColor("#1D4ED8")
    cor_azul_claro = colors.HexColor("#F0F7FF")
    cor_borda = colors.HexColor("#93C5FD")

    estilo_capa_tit = ParagraphStyle(
        'CapaTitulo',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=24,
        leading=30,
        textColor=cor_azul,
        alignment=1,
        spaceAfter=8
    )
    estilo_capa_sub = ParagraphStyle(
        'CapaSub',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=12,
        leading=16,
        textColor=cor_primaria,
        alignment=1,
        spaceAfter=18
    )
    estilo_h1 = ParagraphStyle(
        'TitCap',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=13.5,
        leading=17,
        textColor=cor_azul,
        spaceBefore=0,
        spaceAfter=5,
        keepWithNext=True
    )
    estilo_h2 = ParagraphStyle(
        'TitSec',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=10,
        leading=13.5,
        textColor=cor_primaria,
        spaceBefore=5,
        spaceAfter=3,
        keepWithNext=True
    )
    estilo_corpo = ParagraphStyle(
        'CorpoTexto',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=12.5,
        textColor=cor_primaria,
        spaceAfter=5
    )
    estilo_item = ParagraphStyle(
        'ItemPasso',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        leading=11.5,
        textColor=cor_primaria,
        spaceAfter=2
    )
    estilo_alerta = ParagraphStyle(
        'BoxAlerta',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#1E3A8A")
    )
    estilo_legenda_foto = ParagraphStyle(
        'LegendaFoto',
        parent=styles['Normal'],
        fontName='Helvetica-Oblique',
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor("#475569"),
        alignment=1,
        spaceBefore=2,
        spaceAfter=4
    )
    estilo_celula = ParagraphStyle(
        'CelulaTab',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=7.5,
        leading=10,
        textColor=cor_primaria
    )
    estilo_celula_header = ParagraphStyle(
        'CelulaHeader',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=7.5,
        leading=10,
        textColor=colors.white
    )

    flowables = []

    # CAPA
    flowables.append(Spacer(1, 20))
    flowables.append(Paragraph(dados.get("titulo", "Manual Técnico Profissional"), estilo_capa_tit))
    flowables.append(Paragraph(dados.get("subtitulo", "Guia Técnico & Comercial"), estilo_capa_sub))

    termo_capa = dados.get("termo_capa", "business strategy")
    capa_img_path = os.path.join(DIR_PEXELS, f"capa_{int(time.time())}.jpg")
    if buscar_foto_pexels(termo_capa, pexels_key, capa_img_path):
        try:
            flowables.append(RLImage(capa_img_path, width=540, height=270))
        except Exception:
            pass

    flowables.append(PageBreak())

    # INTRODUÇÃO
    flowables.append(Paragraph("Introdução Técnica & Fundamentos do Método", estilo_h1))
    flowables.append(Spacer(1, 4))
    for p in dados.get("introducao", "").split("\n"):
        if p.strip():
            flowables.append(Paragraph(p.strip(), estilo_corpo))

    flowables.append(Spacer(1, 8))
    flowables.append(HRFlowable(width="100%", thickness=0.8, color=colors.HexColor("#CBD5E1"), spaceAfter=10))

    # CAPÍTULOS TÉCNICOS COM DUPLA FOTO
    for cap in dados.get("capitulos", []):
        flowables.append(Paragraph(f"Módulo {cap.get('numero')}: {cap.get('titulo')}", estilo_h1))
        flowables.append(Spacer(1, 3))

        # FOTO 1: Ação / Preparo / Mão na Massa
        termo_proc = cap.get("termo_busca_foto_processo", cap.get("termo_busca_foto", "working process"))
        if termo_proc:
            proc_img_path = os.path.join(DIR_PEXELS, f"proc_{cap.get('numero')}_{int(time.time())}.jpg")
            if buscar_foto_pexels(termo_proc, pexels_key, proc_img_path):
                try:
                    flowables.append(RLImage(proc_img_path, width=540, height=95))
                    flowables.append(Spacer(1, 4))
                except Exception:
                    pass

        # Caixa de Alerta Técnico
        alerta = cap.get("alerta_tecnico", "")
        if alerta:
            tabela_alerta = Table(
                [[Paragraph(f"<b>⚠️ ALERTA TÉCNICO:</b> {alerta}", estilo_alerta)]],
                colWidths=[540]
            )
            tabela_alerta.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), cor_azul_claro),
                ('BOX', (0, 0), (-1, -1), 1, cor_borda),
                ('PADDING', (0, 0), (-1, -1), 4),
            ]))
            flowables.append(tabela_alerta)
            flowables.append(Spacer(1, 4))

        # Texto Explicativo Denso
        for p_cap in cap.get("conteudo", "").split("\n"):
            if p_cap.strip():
                flowables.append(Paragraph(p_cap.strip(), estilo_corpo))

        # Ficha Técnica com Tabela Universal
        receita_nome = cap.get("receita_nome", "")
        if receita_nome:
            flowables.append(Paragraph(f"📋 Ficha Técnica: {receita_nome}", estilo_h2))

            itens_tabela = cap.get("tabela_ingredientes", [])
            if itens_tabela:
                dados_tabela = [
                    [
                        Paragraph("<b>Insumo / Ferramenta / Etapa</b>", estilo_celula_header),
                        Paragraph("<b>Dose / Medida / Parâmetro</b>", estilo_celula_header),
                        Paragraph("<b>Função Prática / Impacto Técnico</b>", estilo_celula_header)
                    ]
                ]
                for item in itens_tabela:
                    dados_tabela.append([
                        Paragraph(item.get("ingrediente", ""), estilo_celula),
                        Paragraph(item.get("quantidade", ""), estilo_celula),
                        Paragraph(item.get("funcao", ""), estilo_celula)
                    ])

                tabela_receita = Table(dados_tabela, colWidths=[200, 80, 260])
                tabela_receita.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), cor_azul),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                    ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
                    ('PADDING', (0, 0), (-1, -1), 2.5),
                ]))
                flowables.append(tabela_receita)
                flowables.append(Spacer(1, 3))

            passos = cap.get("passos_preparo", [])
            if passos:
                flowables.append(Paragraph("<b>Procedimento Operacional Padrão (Passo a Passo):</b>", estilo_h2))
                for idx_p, passo in enumerate(passos, 1):
                    flowables.append(Paragraph(f"<b>{idx_p}.</b> {passo}", estilo_item))

        # FOTO 2: O Resultado Final Perfeito
        termo_res = cap.get("termo_busca_foto_resultado", "success professional result")
        if termo_res:
            res_img_path = os.path.join(DIR_PEXELS, f"res_{cap.get('numero')}_{int(time.time())}.jpg")
            if buscar_foto_pexels(termo_res, pexels_key, res_img_path):
                try:
                    flowables.append(Spacer(1, 3))
                    flowables.append(RLImage(res_img_path, width=540, height=95))
                    legenda = cap.get("legenda_resultado", "Resultado visual do processo concluído com sucesso.")
                    flowables.append(Paragraph(f"📷 <b>Resultado Esperado:</b> {legenda}", estilo_legenda_foto))
                except Exception:
                    pass

        flowables.append(Spacer(1, 4))
        flowables.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#E2E8F0"), spaceAfter=6))
        flowables.append(PageBreak())

    doc.build(flowables, canvasmaker=NumeradorPaginas)
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
# 6. INTERFACE STREAMLIT (SISTEMA CENTRALIZADO & INTEGRADO)
# ==============================================================================

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
        value=st.session_state["email_usuario_ativo"]
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
    st.write("• Pexels:", "🟢 Ativo" if PEXELS_API_KEY else "🔴 Ausente")

# ABAS PRINCIPAIS
tab_minerador, tab_vsl, tab_ebook, tab_master = st.tabs([
    "🔍 1. Minerador & Google Ads",
    "🚀 2. Criar VSL & Dublagem Global",
    "📚 3. Criar E-book & Tradução Global",
    "👑 4. Gestão Master"
])

# ------------------------------------------------------------------------------
# ABA 1: MINERADOR & GOOGLE ADS (COM PROPAGAÇÃO AUTOMÁTICA DE NICHO)
# ------------------------------------------------------------------------------
with tab_minerador:
    st.markdown("## 🔍 Minerador & Validador de Nichos com Kit Google Ads")
    st.caption("Analise nichos comerciais, descubra dores ocultas e obtenha a campanha completa pronta para o Google Ads e YouTube Ads.")

    NICHOS_PREDEFINIDOS = [
        "🐕 Adestramento Canino & Comportamento Pet",
        "🍞 Gastronomia & Pães Sem Glúten",
        "🎂 Confeitaria Lucrativa & Bolos Caseiros",
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
            placeholder="Ex: Instalação e higienização de ar condicionado split"
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
                    
                    # INTEGRAÇÃO INSTANTÂNEA COM AS OUTRAS ABAS
                    st.session_state["tema_vsl_ativo"] = nicho_final
                    st.session_state["promessa_vsl_ativo"] = f"Aprenda o método definitivo e comprovado sobre {nicho_final}"
                    st.session_state["tema_ebook_ativo"] = f"Manual Prático e Definitivo: {nicho_final}"
                    st.session_state["publico_ativo"] = "Pessoas e profissionais que buscam resultados rápidos e comprovados"

                    st.success(f"✅ Dossiê concluído! O nicho '{nicho_final}' já foi integrado automaticamente às abas de VSL e E-book.")
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
# ABA 2: CRIAR VSL & DUBLAGEM GLOBAL (CONECTADA AO NICHO ATIVO)
# ------------------------------------------------------------------------------
with tab_vsl:
    st.markdown("## 🚀 Criador de Vídeo de Vendas (VSL) & Dublagem Global")
    
    nicho_integrado = st.session_state.get("nicho_pesquisado_nome")
    if nicho_integrado:
        st.success(f"🎯 **Nicho Conectado da Mineração:** `{nicho_integrado}`")
    else:
        st.caption("Dica: você pode minerar um nicho na Aba 1 para preencher tudo automaticamente aqui.")

    col_v1, col_v2 = st.columns(2)
    with col_v1:
        tema_vsl_padrao = st.session_state.get("tema_vsl_ativo", "Adestramento Canino & Comportamento Pet")
        tema_vsl = st.text_input("Tema / Produto da VSL:", value=tema_vsl_padrao)
        
        promessa_padrao = st.session_state.get("promessa_vsl_ativo", "Elimine maus comportamentos e tenha um cão obediente em 15 dias")
        promessa_vsl = st.text_input("Grande Promessa:", value=promessa_padrao)
    with col_v2:
        publico_padrao = st.session_state.get("publico_ativo", "Tutores de cães de primeira viagem e famílias com pets")
        publico_vsl = st.text_input("Público-Alvo:", value=publico_padrao)
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
                use_container_width=True
            )

        st.markdown("---")
        with st.container(border=True):
            st.markdown("### 🌐 Dublar VSL em 36 Idiomas (DubfyAi Global)")
            st.caption("Traduza a narração, adapte valores para moedas locais e re-sincronize cortes.")

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
                    use_container_width=True
                )

# ------------------------------------------------------------------------------
# ABA 3: CRIAR E-BOOK & TRADUÇÃO GLOBAL (CONECTADO AO NICHO ATIVO)
# ------------------------------------------------------------------------------
with tab_ebook:
    st.markdown("## 📚 Criador de E-book Comercial & Diagramação Editorial")
    
    nicho_integrado = st.session_state.get("nicho_pesquisado_nome")
    if nicho_integrado:
        st.success(f"🎯 **Nicho Conectado da Mineração:** `{nicho_integrado}`")
    else:
        st.caption("Páginas 100% preenchidas com dupla fotografia e tabelas sob medida para qualquer nicho.")

    col_e1, col_e2 = st.columns(2)
    with col_e1:
        tema_ebook_padrao = st.session_state.get("tema_ebook_ativo", "Manual Definitivo de Adestramento Canino")
        tema_ebook = st.text_input("Tema do E-book:", value=tema_ebook_padrao)
    with col_e2:
        publico_ebook_padrao = st.session_state.get("publico_ativo", "Tutores de cães de primeira viagem e famílias com pets")
        publico_ebook = st.text_input("Público-Alvo:", value=publico_ebook_padrao)

    if st.button("📖 Gerar E-book Profissional Completo (.PDF) (10 cr)", type="primary"):
        if saldo_atual < 10:
            st.error("❌ Saldo insuficiente! Você precisa de 10 créditos.")
        else:
            with st.spinner(f"Construindo manual completo de '{tema_ebook}' com fotos e tabelas personalizadas..."):
                try:
                    dados_eb = gerar_conteudo_ebook_ia(tema_ebook, publico_ebook)
                    st.session_state["dados_ebook_sessao"] = dados_eb

                    nome_pdf = f"manual_{re.sub(r'[^a-zA-Z0-9]', '_', tema_ebook.lower())[:20]}_{int(time.time())}.pdf"
                    caminho_pdf = os.path.join(DIR_EBOOKS, nome_pdf)
                    compilar_pdf_ebook_com_fotos(dados_eb, PEXELS_API_KEY, caminho_pdf)

                    debitar_creditos_cloud(email_usuario, f"Criação E-book ({tema_ebook})", 10)
                    st.session_state["pdf_ebook_pronto"] = caminho_pdf
                    st.session_state["pdf_ebook_nome"] = nome_pdf
                    st.success(f"✅ E-book de '{tema_ebook}' gerado com layout editorial completo!")
                    st.rerun()
                except Exception as e_eb:
                    st.error(f"Erro na compilação do E-book: {e_eb}")

    if st.session_state.get("pdf_ebook_pronto") and os.path.exists(st.session_state["pdf_ebook_pronto"]):
        st.markdown("---")
        st.markdown("### 📥 Seu E-book Original em Português:")
        with open(st.session_state["pdf_ebook_pronto"], "rb") as f_eb:
            st.download_button(
                "⬇️ Baixar E-book Original (.PDF)",
                data=f_eb,
                file_name=st.session_state.get("pdf_ebook_nome", "ebook.pdf"),
                mime="application/pdf",
                use_container_width=True
            )

        st.markdown("---")
        with st.container(border=True):
            st.markdown("### 🌐 Tradução Global do E-book (36 Idiomas)")
            st.caption("Internacionalize mantendo a diagramação editorial de páginas cheias e fotos duplas.")

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
                    with st.spinner(f"Traduzindo tabelas, legendas e mantendo a diagramação editorial para {idioma_eb_sel}..."):
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

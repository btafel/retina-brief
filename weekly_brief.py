"""
Retina Literature Weekly Brief
Fetches top articles from key retina journals and sends a curated email summary.
Runs every Monday at 7:30 AM UTC via GitHub Actions.
"""

import os
import smtplib
import json
import re
import time
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import feedparser
from openai import OpenAI

# ─────────────────────────────────────────────
# CONFIGURATION — edit these values
# ─────────────────────────────────────────────

RECIPIENT_EMAIL = os.environ.get("RECIPIENT_EMAIL", "tu@email.com")
SENDER_EMAIL    = os.environ.get("SENDER_EMAIL", "tubot@gmail.com")
GMAIL_APP_PASS  = os.environ.get("GMAIL_APP_PASSWORD", "")
OPENAI_KEY      = os.environ.get("OPENAI_API_KEY", "")

TOP_N_ARTICLES = 5   # Número de artículos en el resumen final

# ─────────────────────────────────────────────
# RSS FEEDS — journals de retina clave
# Incluye feed principal + "most read" donde existe
# ─────────────────────────────────────────────

FEEDS = [
    # Retina (LWW)
    {
        "journal": "Retina",
        "url": "https://journals.lww.com/retinajournal/rss/mostpopular.xml",
        "label": "most_popular"
    },
    {
        "journal": "Retina",
        "url": "https://journals.lww.com/retinajournal/rss/latestissue.xml",
        "label": "latest"
    },

    # Ophthalmology Retina (AAO)
    {
        "journal": "Ophthalmology Retina",
        "url": "https://www.ophthalmologyretina.org/rss/latest",
        "label": "latest"
    },

    # American Journal of Ophthalmology
    {
        "journal": "American Journal of Ophthalmology",
        "url": "https://www.ajo.com/rss/S0002-9394.xml",
        "label": "latest"
    },

    # JAMA Ophthalmology
    {
        "journal": "JAMA Ophthalmology",
        "url": "https://jamanetwork.com/rss/site_3/67.xml",
        "label": "latest"
    },

    # British Journal of Ophthalmology
    {
        "journal": "British Journal of Ophthalmology",
        "url": "https://bjo.bmj.com/rss/current.xml",
        "label": "latest"
    },

    # Retina Cases & Brief Reports
    {
        "journal": "Retina Cases & Brief Reports",
        "url": "https://journals.lww.com/retinalcases/rss/latestissue.xml",
        "label": "latest"
    },

    # Survey of Ophthalmology (reviews)
    {
        "journal": "Survey of Ophthalmology",
        "url": "https://www.surveyophthalmol.com/rss/S0039-6257.xml",
        "label": "latest"
    },
]

# ─────────────────────────────────────────────
# CLINICAL FOCUS — temas prioritarios
# ─────────────────────────────────────────────

CLINICAL_FOCUS = """
Priorizá artículos con impacto clínico directo para retina médica/quirúrgica, incluyendo:
- Degeneración macular asociada a la edad (AMD/DMAE): anti-VEGF, terapia génica, atrofia geográfica
- Edema macular diabético (DME) y retinopatía diabética (DR)
- Oclusión venosa retiniana (RVO: BRVO, CRVO)
- Cirugía vitreorretinal: desprendimiento de retina, membrana epirretinal (ERM), agujero macular
- Nuevos tratamientos y ensayos clínicos fase 2/3
- Uveítis posterior con compromiso retinal
- Distrofias retinianas hereditarias (si hay terapia génica o trial relevante)

Evitá papers de ciencias básicas/laboratorio salvo que los hallazgos sean directamente traducibles
a práctica clínica o sean hitos (ej: nueva mutación con tratamiento disponible).
Dá más peso a: estudios randomizados, grandes series de casos, meta-análisis clínicos,
aprobaciones regulatorias recientes, y comparaciones de tratamiento head-to-head.
"""

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def fetch_all_articles(days_back: int = 14) -> list[dict]:
    """Fetch articles from all RSS feeds, optionally filtering by recency."""
    cutoff = datetime.now() - timedelta(days=days_back)
    seen_links = set()
    articles = []

    for feed_config in FEEDS:
        print(f"  Fetching: {feed_config['journal']} ({feed_config['label']}) ...")
        try:
            feed = feedparser.parse(feed_config["url"], agent="RetinaWeeklyBot/1.0")
            for entry in feed.entries:
                link = getattr(entry, "link", "")
                if not link or link in seen_links:
                    continue

                # Parse date if available
                published = None
                for attr in ("published_parsed", "updated_parsed"):
                    val = getattr(entry, attr, None)
                    if val:
                        try:
                            published = datetime(*val[:6])
                        except Exception:
                            pass
                        break

                # Skip if too old (only when date is available)
                if published and published < cutoff:
                    continue

                title   = getattr(entry, "title", "").strip()
                summary = getattr(entry, "summary", "") or getattr(entry, "description", "")
                # Strip HTML tags from summary
                summary = re.sub(r"<[^>]+>", " ", summary).strip()
                summary = re.sub(r"\s+", " ", summary)[:800]

                if not title:
                    continue

                seen_links.add(link)
                articles.append({
                    "journal": feed_config["journal"],
                    "label":   feed_config["label"],
                    "title":   title,
                    "summary": summary,
                    "link":    link,
                    "date":    published.strftime("%Y-%m-%d") if published else "n/a",
                })
        except Exception as e:
            print(f"    WARNING: Could not fetch {feed_config['url']}: {e}")
        time.sleep(0.5)  # polite delay

    print(f"  Total articles collected: {len(articles)}")
    return articles


def build_prompt(articles: list[dict], top_n: int) -> str:
    # Serialize articles compactly for the prompt
    articles_text = ""
    for i, a in enumerate(articles, 1):
        articles_text += (
            f"[{i}] Journal: {a['journal']} ({a['label']}) | Date: {a['date']}\n"
            f"    Title: {a['title']}\n"
            f"    Abstract: {a['summary']}\n"
            f"    URL: {a['link']}\n\n"
        )

    return f"""Sos un especialista en retina clínica y quirúrgica con más de 15 años de experiencia.
Tu tarea es revisar la siguiente lista de artículos recientes de journals de retina y producir
el "Retina Literature Weekly Brief": una selección de los {top_n} artículos más relevantes
para la práctica clínica, con un resumen estructurado de cada uno.

CRITERIOS DE SELECCIÓN Y PRIORIDAD:
{CLINICAL_FOCUS}

ARTÍCULOS DISPONIBLES ({len(articles)} en total):
{articles_text}

INSTRUCCIONES DE OUTPUT:
Devolvé ÚNICAMENTE un objeto JSON válido (sin markdown, sin backticks, sin texto adicional)
con la siguiente estructura exacta:

{{
  "articles": [
    {{
      "rank": 1,
      "title": "Título completo del artículo",
      "journal": "Nombre del journal",
      "date": "YYYY-MM-DD o 'n/a'",
      "why_it_matters": "2-3 oraciones: por qué este artículo es relevante para la práctica de retina",
      "study_design": "Tipo de estudio (ej: RCT, retrospectivo, meta-análisis, case series, etc.) y N de pacientes",
      "main_finding": "El hallazgo principal en 2-3 oraciones, con números si están disponibles",
      "clinical_applicability": "1-2 oraciones concretas: qué cambia o confirma en la práctica clínica",
      "link": "URL exacta del artículo"
    }}
  ],
  "editorial_note": "2-3 oraciones opcionales sobre tendencias o temas dominantes de la semana (puede ser null)"
}}

Seleccioná estrictamente los {top_n} más relevantes según los criterios clínicos.
No incluyas más ni menos de {top_n} artículos.
Asegurate de que el JSON sea válido y parseable.
"""


def call_claude(prompt: str) -> dict:
    """Call OpenAI API and parse the JSON response."""
    client = OpenAI(api_key=OPENAI_KEY)
    response = client.chat.completions.create(
        model="gpt-4o-mini",   # gratis en el free tier; cambiar a "gpt-4o" si querés más calidad
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = response.choices[0].message.content.strip()

    # Strip markdown code fences if present
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    return json.loads(raw)


def build_html_email(data: dict, week_str: str) -> str:
    """Render the structured data as a clean HTML email."""

    articles_html = ""
    for a in data.get("articles", []):
        articles_html += f"""
        <div class="article">
          <div class="article-rank">#{a['rank']}</div>
          <h2 class="article-title">{a['title']}</h2>
          <div class="article-meta">
            <span class="journal">{a['journal']}</span>
            {'<span class="date"> &middot; ' + a['date'] + '</span>' if a['date'] != 'n/a' else ''}
          </div>

          <div class="section">
            <span class="section-label">¿Por qué importa?</span>
            <p>{a['why_it_matters']}</p>
          </div>

          <div class="section">
            <span class="section-label">Diseño del estudio</span>
            <p>{a['study_design']}</p>
          </div>

          <div class="section">
            <span class="section-label">Hallazgo principal</span>
            <p>{a['main_finding']}</p>
          </div>

          <div class="section">
            <span class="section-label">Aplicabilidad clínica</span>
            <p>{a['clinical_applicability']}</p>
          </div>

          <a class="read-more" href="{a['link']}" target="_blank">Leer artículo completo →</a>
        </div>
        """

    editorial = ""
    if data.get("editorial_note"):
        editorial = f"""
        <div class="editorial">
          <span class="section-label">Nota editorial</span>
          <p>{data['editorial_note']}</p>
        </div>
        """

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  body {{
    font-family: Georgia, 'Times New Roman', serif;
    background: #f5f5f0;
    margin: 0; padding: 0;
    color: #1a1a1a;
  }}
  .wrapper {{
    max-width: 680px;
    margin: 0 auto;
    background: #ffffff;
  }}
  .header {{
    background: #1b3a5c;
    padding: 32px 40px 24px;
    color: white;
  }}
  .header h1 {{
    margin: 0 0 4px;
    font-size: 22px;
    font-weight: normal;
    letter-spacing: 0.5px;
  }}
  .header .subtitle {{
    font-size: 13px;
    color: #a8c0d6;
    font-family: Arial, sans-serif;
    margin: 0;
  }}
  .content {{
    padding: 32px 40px;
  }}
  .intro {{
    font-size: 14px;
    color: #555;
    font-family: Arial, sans-serif;
    border-left: 3px solid #1b3a5c;
    padding-left: 14px;
    margin-bottom: 32px;
    line-height: 1.6;
  }}
  .article {{
    border: 1px solid #e8e8e8;
    border-radius: 6px;
    padding: 24px 28px;
    margin-bottom: 24px;
    background: #fafaf8;
  }}
  .article-rank {{
    font-family: Arial, sans-serif;
    font-size: 12px;
    font-weight: bold;
    color: #1b3a5c;
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-bottom: 8px;
  }}
  .article-title {{
    font-size: 17px;
    margin: 0 0 8px;
    line-height: 1.4;
    color: #111;
  }}
  .article-meta {{
    font-family: Arial, sans-serif;
    font-size: 12px;
    color: #777;
    margin-bottom: 18px;
  }}
  .journal {{
    font-style: italic;
    color: #1b3a5c;
    font-weight: bold;
  }}
  .section {{
    margin-bottom: 14px;
  }}
  .section-label {{
    display: block;
    font-family: Arial, sans-serif;
    font-size: 11px;
    font-weight: bold;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    color: #888;
    margin-bottom: 4px;
  }}
  .section p {{
    margin: 0;
    font-size: 14px;
    line-height: 1.65;
    color: #333;
  }}
  .read-more {{
    display: inline-block;
    margin-top: 16px;
    font-family: Arial, sans-serif;
    font-size: 13px;
    color: #1b3a5c;
    text-decoration: none;
    font-weight: bold;
    border-bottom: 1px solid #a8c0d6;
    padding-bottom: 2px;
  }}
  .editorial {{
    background: #eef3f8;
    border-radius: 6px;
    padding: 20px 24px;
    margin-top: 8px;
    margin-bottom: 32px;
  }}
  .editorial p {{
    margin: 6px 0 0;
    font-size: 14px;
    line-height: 1.65;
    color: #444;
    font-style: italic;
  }}
  .footer {{
    border-top: 1px solid #e8e8e8;
    padding: 20px 40px;
    font-family: Arial, sans-serif;
    font-size: 11px;
    color: #aaa;
    text-align: center;
  }}
</style>
</head>
<body>
<div class="wrapper">
  <div class="header">
    <h1>🔬 Retina Literature Weekly Brief</h1>
    <p class="subtitle">Top {TOP_N_ARTICLES} artículos &middot; Semana del {week_str}</p>
  </div>

  <div class="content">
    <p class="intro">
      Selección automatizada de los artículos más relevantes publicados en los principales
      journals de retina, con foco en impacto clínico directo para retina médica y quirúrgica.
    </p>

    {articles_html}
    {editorial}
  </div>

  <div class="footer">
    Generado automáticamente · Retina Literature Weekly Brief<br>
    Fuentes: Retina, Ophthalmology Retina, AJO, JAMA Ophthalmology, BJO, Retina Cases, Survey of Ophthalmology
  </div>
</div>
</body>
</html>"""


def send_email(html_body: str, week_str: str) -> None:
    """Send the HTML email via Gmail SMTP."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Retina Literature Weekly Brief — {week_str}"
    msg["From"]    = SENDER_EMAIL
    msg["To"]      = RECIPIENT_EMAIL
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    print(f"  Sending email to {RECIPIENT_EMAIL} ...")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(SENDER_EMAIL, GMAIL_APP_PASS)
        server.sendmail(SENDER_EMAIL, RECIPIENT_EMAIL, msg.as_string())
    print("  Email sent successfully.")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    week_str = datetime.now().strftime("%d de %B de %Y")
    print(f"\n{'='*60}")
    print(f"  Retina Literature Weekly Brief — {week_str}")
    print(f"{'='*60}\n")

    # 1. Fetch articles
    print("[1/4] Fetching articles from RSS feeds...")
    articles = fetch_all_articles(days_back=14)

    if not articles:
        print("ERROR: No articles fetched. Check RSS feed URLs and network access.")
        return

    # 2. Build prompt and call Claude
    print(f"[2/4] Calling Claude to select and summarize top {TOP_N_ARTICLES} articles...")
    prompt = build_prompt(articles, TOP_N_ARTICLES)
    data   = call_claude(prompt)

    print(f"  Claude selected {len(data.get('articles', []))} articles.")
    for a in data.get("articles", []):
        print(f"    #{a['rank']} [{a['journal']}] {a['title'][:70]}...")

    # 3. Build HTML
    print("[3/4] Rendering HTML email...")
    html = build_html_email(data, week_str)

    # 4. Send email
    print("[4/4] Sending email...")
    send_email(html, week_str)

    print(f"\n✓ Done.\n")


if __name__ == "__main__":
    main()

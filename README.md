# Retina Literature Weekly Brief

Agente automatizado que cada lunes revisa los principales journals de retina, selecciona los 5 artículos más relevantes clínicamente, y envía un resumen estructurado por email.

## Journals monitoreados

- Retina (LWW)
- Ophthalmology Retina (AAO)
- American Journal of Ophthalmology
- JAMA Ophthalmology
- British Journal of Ophthalmology
- Retina Cases & Brief Reports
- Survey of Ophthalmology

## Setup

### 1. Crear el repositorio GitHub

```bash
git init retina-brief
cd retina-brief
# Copiar los archivos de este proyecto
git add .
git commit -m "Initial setup"
git remote add origin https://github.com/TU_USUARIO/retina-brief.git
git push -u origin main
```

### 2. Configurar Gmail App Password

1. Ir a [myaccount.google.com](https://myaccount.google.com)
2. Seguridad → Verificación en dos pasos (activar si no está)
3. Seguridad → Contraseñas de aplicaciones
4. Crear una nueva contraseña para "Mail / Windows Computer" (o cualquier nombre)
5. Guardar la contraseña de 16 caracteres generada

### 3. Configurar secrets en GitHub

En el repositorio: **Settings → Secrets and variables → Actions → New repository secret**

| Secret | Valor |
|--------|-------|
| `ANTHROPIC_API_KEY` | Tu API key de Anthropic (platform.anthropic.com) |
| `GMAIL_APP_PASSWORD` | La App Password de 16 caracteres del paso anterior |
| `SENDER_EMAIL` | La cuenta Gmail que envía (ej: tubot@gmail.com) |
| `RECIPIENT_EMAIL` | Tu email personal donde recibís el resumen |

> `SENDER_EMAIL` y `RECIPIENT_EMAIL` pueden ser la misma cuenta.

### 4. Probar manualmente

En GitHub: **Actions → Retina Literature Weekly Brief → Run workflow**

Si el workflow pasa (verde), vas a recibir el email en minutos.

## Estructura del proyecto

```
retina-brief/
├── weekly_brief.py              # Script principal
├── requirements.txt
└── .github/
    └── workflows/
        └── weekly_brief.yml    # GitHub Actions workflow (Lunes 7:30 AM ART)
```

## Personalización

Todo se configura en la sección `CONFIGURATION` al inicio de `weekly_brief.py`:

- `TOP_N_ARTICLES` — cuántos artículos incluir (default: 5)
- `FEEDS` — agregar o quitar journals
- `CLINICAL_FOCUS` — ajustar los temas prioritarios

## Costo estimado

Una corrida semanal consume ~3.000-5.000 tokens en total (input + output).
Con los precios actuales de Claude Sonnet, el costo es **< USD 0.05 por semana**.

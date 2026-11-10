# AI Credits Hunter v4.0 — producto funcional

Motor de recolección y verificación de ofertas de IA (créditos gratuitos, free tiers,
pruebas, descuentos y programas educativos) para un usuario en Argentina con
presupuesto incremental **USD 0**.

- **Solo biblioteca estándar de Python** (>= 3.11). Sin `pip install`, sin APIs pagas.
- **Fuentes reales por HTTP**: OpenRouter, DeepSeek, Cloudflare, Kiro, Vercel y feeds RSS oficiales.
- **Trazabilidad**: cada oferta guarda el fragmento literal que la respalda, la URL, el
  hash SHA-256 del cuerpo y el estado HTTP.
- **SQLite con claves foráneas activas**, migraciones versionadas e idempotentes.
- **Interfaz web local** en `http://127.0.0.1:8765`.

---

## 1. Instalación y arranque

Requisitos: Python 3.11+ en el PATH (`py -3` en Windows, `python3` en macOS/Linux).

```bat
cd /d ruta\al\repositorio
iniciar_v4.bat
```

Ese comando hace tres cosas: inicializa la base de ensayo, ejecuta una búsqueda real y
abre la interfaz. Para buscar sin abrir la interfaz: `buscar_v4.bat`.

Equivalente por consola:

```bat
py -3 -m ach init
py -3 -m ach run
py -3 -m ach serve --port 8765
```

## 2. Comandos

| Comando | Qué hace |
|---|---|
| `py -3 -m ach init` | Crea/migra `data/promotions_v4.sqlite3` y registra las fuentes. |
| `py -3 -m ach run` | Corrida real: HTTP → extracción → clasificación → SQLite → reporte. |
| `py -3 -m ach run --sources openrouter-free-models,deepseek-pricing` | Limita a ciertas fuentes. |
| `py -3 -m ach run --offline tests/fixtures` | Modo fixtures (nivel `FIXTURE`, no es una corrida real). |
| `py -3 -m ach list --band GRATIS_100` | Lista ofertas filtradas. |
| `py -3 -m ach show 12` | Detalle JSON con evidencia y eventos. |
| `py -3 -m ach verify --all` | Re-verifica por red que el fragmento siga en la página. |
| `py -3 -m ach sources` | Estado de cada fuente (HTTP, candidatos, error). |
| `py -3 -m ach export` | Exporta `reports/v4/ofertas_v4.json` y `.csv`. |
| `py -3 -m ach doctor` | Integridad, claves foráneas y conectividad de fuentes. |
| `py -3 -m ach serve --port 8765` | Interfaz web local (solo 127.0.0.1). |

## 3. Fuentes incluidas

| Fuente | Tipo | Qué aporta |
|---|---|---|
| `openrouter-free-models` | JSON (`/api/v1/models`) | Modelos con precio 0 por token. |
| `deepseek-pricing` | HTML | Tarifa off-peak (50%) con conversión de horario a ART. |
| `cloudflare-workers-ai-pricing` | HTML | 10.000 Neurons/día gratis y precio del excedente. |
| `kiro-pricing` | HTML | Plan FREE con 50 créditos/mes y precio del plan PRO. |
| `vercel-ai-gateway-pricing` | HTML | Crédito mensual de USD 5. |
| `openai-news-rss`, `google-ai-blog-rss`, `huggingface-blog-rss` | RSS | Anuncios con lenguaje promocional explícito (baja confianza). |

Añadir una fuente = una entrada en `ach/sources.py` + un extractor en `ach/extract.py`.
Si el patrón no aparece, el extractor devuelve **cero** candidatos: no se rellena nada.

## 4. Niveles de verificación

| Nivel | Significado |
|---|---|
| `NETWORK_VERIFIED` | HTTP 200 + fragmento literal presente + precio/descuento calculado desde la página. |
| `CONTENT_VERIFIED` | HTTP 200 + fragmento presente, sin magnitud verificable (p. ej. un anuncio). |
| `UNVERIFIED` | No se pudo comprobar por red. |
| `FIXTURE` | Respuesta guardada para pruebas. **Nunca** cuenta como verificación real. |

Una respuesta HTTP 200 **no** se interpreta como promoción confirmada.

## 5. Reglas de datos

- **No se inventa**: sin URL oficial, fragmento y fecha UTC no hay oferta verificada.
- **Argentina**: por defecto `ARGENTINA_NO_CONFIRMADA`. Solo pasa a
  `DISPONIBLE_POR_DECLARACION` si la fuente lo declara (`worldwide`, `globally`,
  `all countries`); a `REQUIERE_REVISION_GEO` si declara exclusiones.
- **Descuentos**: `100 × (1 − P1/P0)` con la misma unidad y modalidad. Sin base
  verificable → `SIN_BASE_VERIFICADA`.
- **Deduplicación**: clave SHA-256 de proveedor + producto + tipo + unidad + identificador.
  Volver a ver la misma oferta genera `VISTA`, no un duplicado.
- **Historial**: cada alta/cambio queda en `offer_event`; cada evidencia, en `evidence`.

## 6. Base de datos

`data/promotions_v4.sqlite3` (ensayo). Tablas: `provider`, `source`, `run`, `source_run`,
`offer`, `evidence`, `offer_event`, `schema_version`. Vista de lectura: `v_offer_public`.

- Migraciones en `migrations/*.sql`, aplicadas por número, con checksum: si un archivo ya
  aplicado cambia, el arranque aborta en vez de divergir en silencio.
- `PRAGMA foreign_keys=ON` en toda conexión.
- La base histórica `data/promotions.sqlite3` está **protegida**: `ach` se niega a abrirla
  en escritura.

## 7. Pruebas

```bat
py -3 -m unittest tests.test_ach_unit tests.test_ach_extractors -v
py -3 -m unittest tests.test_ach_security -v
py -3 -m unittest tests.test_ach_integration -v      :: requiere red
set ACH_OFFLINE=1 && py -3 -m unittest tests.test_ach_integration -v   :: omite la red
```

- `test_ach_unit`: migraciones, checksum, FK, dedupe, bandas, guardas de ruta.
- `test_ach_extractors`: extractores contra capturas reales en `tests/fixtures/`.
- `test_ach_security`: D-4 (sin `DROP TABLE`, FK activas, scripts destructivos bloqueados).
- `test_ach_integration`: corrida real contra 3 fuentes, persistencia, dedupe, fallos,
  interfaz y verificación de que la base productiva no cambia.

## 8. Limitaciones reales

1. **Cobertura**: 8 fuentes. Sitios con render 100% JavaScript (Groq, Gemini API) no se
   pueden leer sin navegador; quedan fuera en vez de simularse.
2. **Precios en texto**: `baseline_price`/`offer_price` son numéricos solo cuando la página
   publica números comparables; si publica "0.5x multiplier" se conserva como texto en la
   migración histórica, no en el motor v4.
3. **Anuncios RSS**: baja confianza por diseño; requieren abrir el enlace.
4. **Sin automatización**: no hay tarea programada activa. Ejecutar es manual.
5. **Un solo hilo de red**: la corrida tarda ~10 s con 8 fuentes.
6. **Sin reintento ante 429**: se reporta el error y se sigue.

## 9. Integración con producción

Ver `docs/V4_INFORME.md`, sección "Procedimiento de integración". Resumen: la versión v4
usa su propia base (`promotions_v4.sqlite3`) y no reemplaza nada. La sustitución de la base
productiva o la activación de tareas programadas requiere aprobación explícita.

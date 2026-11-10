# AI Credits Hunter — v0.1.0 (MVP)

Motor de recolección y verificación de ofertas de IA: créditos gratuitos, free tiers,
pruebas, descuentos y programas educativos. Pensado para un usuario en Argentina con
presupuesto incremental **USD 0**.

No es un agregador de noticias ni un buscador de promociones: cada oferta que entra a la
base tiene que estar respaldada por un fragmento literal de una página oficial, su URL, el
hash SHA-256 del cuerpo descargado y el estado HTTP de la respuesta.

- **Solo biblioteca estándar de Python (>= 3.11)**. Sin `pip install`, sin APIs pagas.
- **8 fuentes reales por HTTP**: OpenRouter, DeepSeek, Cloudflare Workers AI, Kiro, Vercel
  AI Gateway y tres feeds RSS oficiales.
- **Trazabilidad completa**: sin URL oficial, fragmento y fecha UTC no hay oferta.
- **SQLite** con claves foráneas activas, migraciones versionadas con checksum.
- **Interfaz web local** en `http://127.0.0.1:8765`.

> **Versión.** Esta etiqueta pública es `v0.1.0` (primer MVP). El paquete se identifica
> internamente como `ach 4.0.0`, que es la versión del motor ya probada; no se cambió
> código para publicar.

---

## 1. Requisitos

| Requisito | Detalle |
|---|---|
| Python | 3.11 o superior (probado con 3.14.10 en Windows 11) |
| Dependencias | Ninguna obligatoria |
| Red | Solo para `run`, `verify` y los tests de integración |
| Sistema | Windows, macOS o Linux. Los `.bat` son solo para Windows |

## 2. Instalación en otra computadora

```bash
git clone https://github.com/metecondrie/ai-credits-hunter.git
cd ai-credits-hunter
python -m ach init
```

En Windows con el lanzador oficial de Python:

```bat
py -3 -m ach init
```

`init` crea `data/promotions_v4.sqlite3`, aplica las migraciones pendientes y registra las
fuentes. Es idempotente: se puede correr las veces que haga falta.

## 3. Uso

| Comando | Qué hace |
|---|---|
| `python -m ach init` | Crea o migra la base y registra las fuentes. |
| `python -m ach run` | Corrida real: HTTP → extracción → clasificación → SQLite → reporte. |
| `python -m ach run --sources openrouter-free-models,deepseek-pricing` | Limita a ciertas fuentes. |
| `python -m ach run --offline tests/fixtures` | Modo fixtures (nivel `FIXTURE`, no es corrida real). |
| `python -m ach list --band GRATIS_100` | Lista ofertas filtradas. |
| `python -m ach show 12` | Detalle JSON con evidencia y eventos. |
| `python -m ach verify --all` | Re-verifica por red que el fragmento siga en la página. |
| `python -m ach sources` | Estado de cada fuente (HTTP, candidatos, error). |
| `python -m ach export` | Exporta `reports/v4/ofertas_v4.json` y `.csv`. |
| `python -m ach doctor` | Integridad, claves foráneas y conectividad de fuentes. |
| `python -m ach serve --port 8765` | Interfaz web local. |

En Windows hay dos atajos: `iniciar_v4.bat` (init + run + interfaz) y `buscar_v4.bat`
(solo init + run).

### Interfaz web

```bash
python -m ach serve --port 8765
```

Queda en `http://127.0.0.1:8765`. Escucha **solo en loopback**: no se expone a la red
local ni a internet.

## 4. Fuentes incluidas

| Fuente | Tipo | Qué aporta |
|---|---|---|
| `openrouter-free-models` | JSON (`/api/v1/models`) | Modelos con precio 0 por token. |
| `deepseek-pricing` | HTML | Tarifa off-peak con conversión de horario a ART. |
| `cloudflare-workers-ai-pricing` | HTML | Neurons diarios gratis y precio del excedente. |
| `kiro-pricing` | HTML | Plan FREE y precio del plan PRO. |
| `vercel-ai-gateway-pricing` | HTML | Crédito mensual. |
| `openai-news-rss`, `google-ai-blog-rss`, `huggingface-blog-rss` | RSS | Anuncios con lenguaje promocional (baja confianza). |

Agregar una fuente es una entrada en `ach/sources.py` más un extractor en `ach/extract.py`.
Si el patrón no aparece, el extractor devuelve **cero** candidatos: no se rellena nada.

## 5. Niveles de verificación

| Nivel | Significado |
|---|---|
| `NETWORK_VERIFIED` | HTTP 200 + fragmento literal presente + magnitud calculada desde la página. |
| `CONTENT_VERIFIED` | HTTP 200 + fragmento presente, sin magnitud verificable (por ejemplo, un anuncio). |
| `UNVERIFIED` | No se pudo comprobar por red. |
| `FIXTURE` | Respuesta guardada para pruebas. **Nunca** cuenta como verificación real. |

Un HTTP 200 **no** se interpreta como promoción confirmada.

## 6. Reglas de datos

- **No se inventa**: sin URL oficial, fragmento y fecha UTC no hay oferta verificada.
- **Argentina**: por defecto `ARGENTINA_NO_CONFIRMADA`. Pasa a
  `DISPONIBLE_POR_DECLARACION` solo si la fuente lo declara; a `REQUIERE_REVISION_GEO` si
  declara exclusiones.
- **Descuentos**: `100 × (1 − P1/P0)` con la misma unidad y modalidad. Sin base
  verificable → `SIN_BASE_VERIFICADA`.
- **Deduplicación**: SHA-256 de proveedor + producto + tipo + unidad + identificador.
  Volver a ver la misma oferta genera `VISTA`, no un duplicado.
- **Historial**: cada alta o cambio queda en `offer_event`; cada evidencia, en `evidence`.

## 7. Pruebas

```bash
python -m unittest discover -s tests -p "test_ach_unit.py"
python -m unittest discover -s tests -p "test_ach_extractors.py"
python -m unittest discover -s tests -p "test_ach_ai.py"
python -m unittest discover -s tests -p "test_ach_integration.py"
```

Resultado en la versión publicada: **50 pruebas offline en verde** (11 unitarias, 14 de
extractores, 25 de IA) y **9 de 11 en integración**. Las dos que fallan no son un defecto
del código: verifican que haya al menos tres proveedores con precio extraído y, al
2026-11-09, `deepseek-pricing` devuelve 0 candidatos porque DeepSeek cambió su página de
precios. El mismo resultado se reproduce en el árbol original.

Para correr la integración sin red:

```bash
ACH_OFFLINE=1 python -m unittest discover -s tests -p "test_ach_integration.py"
```

## 8. Estructura

```
ach/            motor: fuentes, fetch, extract, classify, store, pipeline, report, web
migrations/     SQL versionado (001..004), aplicado por número y con checksum
tests/          pruebas unitarias, de extractores, de IA e integración + fixtures
docs/           documentación técnica detallada del motor v4
data/           vacío: acá se crea la base operativa (no se versiona)
reports/v4/     vacío: acá se escriben los reportes de cada corrida (no se versionan)
```

## 9. Seguridad y datos

- **No hay credenciales en el repositorio.** Si se configura IA opcional, las claves se
  guardan en el Credential Manager del sistema vía `keyring`, nunca en SQLite, JSON, logs
  ni reportes.
- **No hay telemetría** ni llamadas a servicios propios. Las únicas salidas de red son las
  fuentes públicas listadas.
- **La base y los reportes quedan fuera de Git** por `.gitignore`; se regeneran con
  `init` y `run`.
- **Bases protegidas**: el motor se niega a abrir en escritura nombres de bases históricas
  (`promotions.sqlite3`, `hunter.db`).

Variables de entorno opcionales: `ACH_DB`, `ACH_TIMEOUT`, `ACH_RETRIES`, `ACH_DELAY`,
`ACH_MAX_BYTES`, `ACH_HOST_INTERVAL`, `ACH_OFFLINE`.

## 10. Limitaciones conocidas

1. **Cobertura**: 8 fuentes. Sitios con render 100 % JavaScript (Groq, Gemini API) no se
   pueden leer sin navegador y quedan afuera en vez de simularse.
2. **`deepseek-pricing`**: 0 candidatos al 2026-11-09 por cambio de maquetado en el sitio.
   El extractor no inventa datos: devuelve vacío.
3. **RSS**: baja confianza por diseño; requieren abrir el enlace.
4. **Sin automatización**: no hay tarea programada; ejecutar es manual.
5. **Un solo hilo de red**: la corrida tarda unos 10 s con 8 fuentes.
6. **Sin reintento ante 429**: se reporta el error y se sigue.
7. **Precios en texto**: `baseline_price`/`offer_price` son numéricos solo cuando la página
   publica números comparables.

## 11. Alcance de esta publicación

Esta edición contiene **solo el motor v4** (`ach`), sus migraciones, sus pruebas y su
documentación. No incluye los módulos legacy v2/v3 (`hunter/`, `core/`, `scripts/`), los
agentes rastreadores, la base histórica ni los respaldos. El motor v4 usa su propia base y
no reemplaza nada.

Esta versión no declara una licencia; se publica para lectura y evaluación.

# AI Credits Hunter — v0.1.0 (MVP)

Motor de recolección y verificación de ofertas de IA: créditos gratuitos, free tiers,
pruebas, descuentos y programas educativos. Pensado para un usuario en Argentina con
presupuesto incremental **USD 0**.

Esta versión **vigila fuentes oficiales preconfiguradas**; todavía no descubre nuevas
fuentes automáticamente. Cada hallazgo debe conservar un fragmento literal de la
fuente, su URL, el hash SHA-256 del cuerpo descargado y el estado HTTP.

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
extractores, 25 de IA) y **9 de 11 en integración**.

Con P0.1, P0.2 y P0.3 integrados (2026-11-10) el total pasa a **93 casos** (11
unitarias, **29 de extractores**, **32 de IA** y **21 de semántica de descuentos**):
+13 por el P0.2, +7 por el P0.1 y +23 por el P0.3. Con los sockets bloqueados y
bases temporales pasan **92 de 93**; **no debe afirmarse 93/93**. Las 61
deterministas (11 unitarias + 29 de extractores + 21 de semántica) están en verde
y de las 32 de IA pasan 31. La restante,
`test_openrouter_paid_model_blocked_without_authorization`,
**exige red**: `assess_cost()` llama a `list_models()` sin recibir el `http_post`
inyectado. Es un problema **preexistente**, ajeno a las correcciones (falla igual
sobre el `main` anterior con la red bloqueada) y solo pasa si se permite esa salida
HTTP, así que no debe contarse como prueba offline.

Las dos pruebas de integración que fallaban (`test_at_least_three_sources_verified` y
`test_prices_come_from_pages`) dependían de que `deepseek-pricing` extrajera precios:
la causa era la URL sin barra final, ya corregida y comprobada en vivo. **La suite
live no se re-ejecutó**: depende del contenido cambiante de terceros y exigiría
varias consultas no indispensables. No se afirma 11/11; queda clasificada como
verificación de conectividad pendiente, separada de las pruebas deterministas con
fixtures, que sí están en verde.

`ACH_OFFLINE=1` **solo lo lee `tests/test_ach_integration.py`**: omite con
`SkipTest` las pruebas que consultan fuentes reales. No está implementado en
`ach/`, así que no vuelve offline al motor ni a `test_ach_ai.py`,
`test_ach_unit.py` o `test_ach_extractors.py`: esas tres se comportan igual con o
sin la variable, y su aislamiento depende de los mocks y fixtures de cada prueba.

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
- **No hay telemetría propia** declarada. En modo determinista se consultan las fuentes
  configuradas; si se activa IA, también se envían fragmentos de evidencia al proveedor
  de modelos elegido. Verificá costos y privacidad antes de activar esa opción.
- **La base y los reportes quedan fuera de Git** por `.gitignore`; se regeneran con
  `init` y `run`.
- **Bases protegidas**: el motor se niega a abrir en escritura nombres de bases históricas
  (`promotions.sqlite3`, `hunter.db`).

Variables de entorno opcionales del motor: `ACH_DB`, `ACH_TIMEOUT`, `ACH_RETRIES`,
`ACH_DELAY`, `ACH_MAX_BYTES`, `ACH_HOST_INTERVAL`. `ACH_OFFLINE` no es del motor:
solo la usa la suite de integración para omitir las pruebas con red (sección 7).

## 10. Limitaciones conocidas

1. **Cobertura**: 8 fuentes. Sitios con render 100 % JavaScript (Groq, Gemini API) no se
   pueden leer sin navegador y quedan afuera en vez de simularse.
2. **`deepseek-pricing`**: reparado el 2026-11-10 (P0.2, sección 12). La causa no era un
   cambio de maquetado: la URL configurada no llevaba barra final y el host estático
   respondía HTTP 200 con el documento «Your First API Call», sin tabla de precios.
   Con `/quick_start/pricing/` vuelve a dar 6 candidatos (2 modelos × 3 categorías de
   tokens). Sigue siendo una fuente frágil: si el documento cambia, el extractor
   devuelve vacío y `source.last_candidates` lo deja visible.
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

---

## 12. Guía de continuidad para desarrolladores y agentes de IA

> **Objetivo:** que una persona o IA pueda retomar el proyecto sin repetir auditorías
> históricas ni rehacer el producto. Este apartado es una **lista de pendientes**, no
> funcionalidades ya implementadas. Mantenerlo actualizado en cada entrega.
>
> **Estado base:** tag `v0.1.0`, motor interno `ach 4.0.0`. El motor consulta ocho
> fuentes predefinidas y registra evidencia; cuenta con IA opcional (Gemini, Groq,
> OpenRouter y compatible OpenAI), selección/fallback y un proveedor
> `demo_local` **simulado**. Las pruebas de IA publicadas usan mocks o demo; no
> demuestran una clasificación completada con una API LLM real. El extractor
> DeepSeek quedó reparado el 2026-11-10 (P0.2); las dos pruebas de integración que
> dependían de él no se re-ejecutaron en vivo y siguen clasificadas como pendientes
> de conectividad, no como fallo del extractor.
>
> **Regla de trabajo:** un implementador, una revisión final, cambios pequeños y
> verificables. No crear una infraestructura multiagente, reconstruir el sistema
> ni ampliar alcance antes de resolver los fallos que afectan al usuario.

### P0 — Corregir antes de considerar una nueva versión estable

1. **Corregir el parseo del veredicto de IA.** — **VALIDACIÓN ESTRICTA RESUELTA**
   (2026-11-10, rama `fix/p01-is-offer-booleano-estricto`, commit base `30181c3`).
   En `ach/ai_classify.py`, `parse_response()` utilizaba `bool(data["is_offer"])`.
   En Python, `bool("false")` vale `True`: una respuesta JSON con texto en vez de
   booleano podía clasificar erróneamente una oferta. Ahora el campo se acepta
   **solo** si es un booleano JSON auténtico (`isinstance(valor, bool)`): `true` y
   `false` pasan; cadenas (`"false"`, `"true"`, `"no"`, `""`), números (`0`, `1`,
   `1.0`), `null`, listas y objetos levantan `ValueError` con el nombre del campo y
   el tipo recibido. El error se gestiona por la vía ya existente: `_attempt_target()`
   devuelve `TODOS_LOS_MODELOS_FALLARON` (o prueba el siguiente modelo de la cadena),
   `pipeline.run()` conserva la oferta y su evidencia, guarda el assessment con
   `is_offer NULL` y `error`, suma `ai_blocked` y la corrida **no** se interrumpe ni
   genera una clasificación positiva. Pruebas: 7 casos nuevos en
   `tests/test_ach_ai.py` (`ParseTestCase`, `ClassifyTestCase`,
   `FullJourneyTestCase`). La suite de IA suma 32 casos: los 7 nuevos son
   estrictamente offline y se comprobaron en rojo (18 fallos) contra el código
   previo; del total, 31 pasan con la red bloqueada y uno exige red por un problema
   preexistente ajeno a esta corrección (ver sección 7). No debe afirmarse 32/32 offline.

   **Sigue abierto** el segundo requisito del ítem: que `is_offer=false` de una IA no
   se confunda con una verificación documental y se presente como candidato rechazado
   o pendiente de revisión. No se tocó la presentación (`ach/web.py` muestra
   «No es oferta» y «IA bloqueada», pero eso no se auditó ni se cambió en esta
   entrega).

2. **Reparar el extractor de DeepSeek y hacer resilientes las pruebas live.** —
   **RESUELTO** (2026-11-10, rama `fix/p02-deepseek-pricing`, base `59b91ad`).

   **Causa del fallo:** `ach/sources.py` apuntaba a `.../quick_start/pricing` **sin
   barra final**. El host estático respondía **HTTP 200** con el documento «Your
   First API Call», que no contiene la tabla de precios. El extractor hacía bien en
   devolver 0 candidatos: no inventaba nada. No era un cambio de maquetado de la
   tabla, y el HTTP 200 no delataba el problema.

   **El beneficio sigue vigente.** La página oficial declara literalmente:
   «Off-peak rates are half of the peak rates. Peak hours are 01:00 - 04:00 and
   06:00 - 10:00 UTC, Monday through Friday, excluding Chinese public holidays.»
   El off-peak es un 50 % real sobre la tarifa peak, en la misma unidad (USD por 1M
   tokens) y la misma modalidad (cache hit, cache miss, salida). No es una tarifa
   normal disfrazada de promoción.

   **Solución:** URL con barra final; el extractor lee ahora **una columna por
   modelo** desde el encabezado `MODEL` (antes descartaba en silencio la segunda,
   `deepseek-v4-pro`), deriva `time_window_utc` del texto oficial en vez de
   hardcodearlo, y registra el complemento off-peak (fines de semana y feriados
   chinos completos). Una columna sin modelo identificable no se atribuye. Los
   precios de Search & Fetch (USD 0.75 cada 1000 requests) **no** se emiten como
   oferta: son tarifa normal, no descuento.

   **Evidencia:** comprobado en vivo a través del propio motor el
   2026-11-10T04:28:54Z (HTTP 200, una única consulta de lectura): 6 candidatos
   `NETWORK_VERIFIED`, banda `DESCUENTO_50_69`, precios exactos por modelo
   (flash: 0.003/0.006, 0.15/0.3, 0.6/1.2; v4-pro: 0.022/0.044, 0.66/1.32,
   1.98/3.96). El fixture existente ya era byte a byte idéntico a la respuesta
   correcta (sha256 `af667969…ece5`); se agregó
   `tests/fixtures/deepseek-pricing-wrong-document.html` con la captura real del
   documento equivocado. Nota: el motor guarda el sha256 y los bytes del cuerpo
   **comprimido** (gzip), por eso difieren de la captura sin comprimir.

   **Pruebas:** 13 casos nuevos en `tests/test_ach_extractors.py` (27 en total),
   deterministas, sin red y con bases temporales; incluyen integridad SQLite
   (`PRAGMA integrity_check` = `ok`, `foreign_key_check` vacío), nivel `FIXTURE`
   para las capturas y deduplicación en la segunda corrida. Contra el código
   original, 8 de esas pruebas fallan.

   **Queda pendiente:** re-ejecutar la suite live de integración (verificación de
   conectividad, no determinista) y el aviso explícito de «fuente requiere
   mantenimiento»: hoy una fuente con HTTP 200 y 0 coincidencias queda visible en
   `source.last_candidates` y `source_run`, pero no tiene un estado propio.

3. **Eliminar falsas comparaciones de precios.** — **RESUELTO** (2026-11-10,
   rama `fix/p03-discount-semantics`, base `c72eee5`).

   **Defectos encontrados.** Tres fuentes fabricaban un 100 % sin base comparable:
   Cloudflare comparaba la cuota diaria incluida contra el precio del **excedente**
   (`0.011` por 1000 Neurons: otro período y otros límites); Kiro comparaba el plan
   **FREE** contra el **PRO** (`20` USD/usuario/mes: otro producto, otros créditos y
   límites); Vercel usaba el **importe del crédito** (`5` USD/mes) como si fuera un
   precio de lista, con `discount_pct=100.0` hardcodeado. Las tres terminaban en
   `GRATIS_100`. OpenRouter no inventaba porcentaje, pero se mostraba como
   «sin base» en vez de como modelo gratuito.

   **Taxonomía.** `ach/classify.py` define siete clases de beneficio
   (`DESCUENTO`, `TARIFA_HORARIA`, `PLAN_GRATUITO`, `CUOTA_GRATUITA`, `CREDITO`,
   `PRUEBA_GRATUITA`, `MODELO_GRATUITO`). El extractor declara la clase en
   `Candidate.benefit_kind`; si no la declara, se infiere de `offer_type`.

   **Regla de comparabilidad.** Solo `DESCUENTO` y `TARIFA_HORARIA` pueden llevar
   porcentaje, y únicamente con base publicada positiva, precio oferta, unidad y
   moneda declaradas (`precios_comparables()`). `assess()` aplica una **guarda
   central**: descarta cualquier porcentaje que no cumpla la equivalencia y lo
   deja anotado en `notes`, así ningún extractor futuro puede fabricar un
   descuento. `GRATIS_100` queda reservado a un 100 % real con base comparable.

   **Resultado por fuente** (antes → después):

   | Fuente | Antes | Después |
   |---|---|---|
   | Cloudflare Workers AI | `100.0` / `GRATIS_100`, base `0.011` | sin porcentaje / `CUOTA_GRATUITA` |
   | Kiro | `100.0` / `GRATIS_100`, base `20.0` | sin porcentaje / `PLAN_GRATUITO` |
   | Vercel AI Gateway | `100.0` / `GRATIS_100`, base `5.0` | sin porcentaje / `CREDITO` |
   | OpenRouter | «sin base» / `SIN_BASE_VERIFICADA` | `MODELO_GRATUITO` |
   | DeepSeek (P0.2) | `50.0` / `DESCUENTO_50_69` | **igual, intacto** |

   Los datos oficiales no se pierden: los 10 000 Neurons/día, el excedente a
   `0.011`, los 50 créditos de Kiro, el PRO a `20` y el crédito de `5` siguen en
   `title`/`benefit` y en la evidencia literal. Solo se eliminan el porcentaje
   artificial y el `price_baseline` no comparable.

   **Interfaz.** `ach/web.py` nombra la gratuidad («Plan gratuito», «Cuota
   incluida», «Crédito», «Modelo gratuito», «Prueba gratuita») en vez de mostrar
   un porcentaje; el «de X» tachado solo aparece con descuento real; los filtros
   separan **Gratuidad (sin porcentaje)** de **Descuento porcentual real**; la
   fila «Descuento» del detalle pasó a «Beneficio». Reporte y CLI comparten las
   etiquetas vía `classify.kind_label()`.

   **Sin duplicados ni evidencia alterada.** La clase viaja en `discount_band`,
   que **no** forma parte de `dedupe_key()`; `offer_type`, `product`,
   `price_unit` y `dedupe_extra` quedan iguales, así que una base existente
   actualiza la oferta en vez de crear otra. No se agregó ninguna migración.

   **Pruebas.** 21 casos nuevos en `tests/test_ach_discount_semantics.py` y 2 en
   `tests/test_ach_extractors.py` (29 en ese archivo), más 3 aserciones corregidas
   que asumían el 100 % artificial. Offline, con sockets bloqueados y bases
   temporales: **92 de 93 en verde, 0 fallos**; el único error es
   `test_openrouter_paid_model_blocked_without_authorization`, preexistente y
   ajeno al P0.3 (exige red porque `assess_cost()` no recibe el `http_post`
   inyectado). Incluyen integridad SQLite, `foreign_key_check` vacío, segunda
   corrida sin duplicados (`offers_new=0`, mismos `offer_id`), evidencia y
   `content_sha256` intactos, y rendered de la interfaz. Contra el código
   original, la suite nueva da 12 fallos y 20 errores, y extractores 3 fallos y 2
   errores.

   **Desvíos y pendientes declarados.** (a) Cuando no hay base comparable se
   muestra la clase de beneficio (`PLAN_GRATUITO`, `CUOTA_GRATUITA`, `CREDITO`)
   con `discount_pct=None`; `SIN_BASE_VERIFICADA` queda para quien reclama un
   descuento sin base equivalente. (b) Vercel pasa de `NETWORK_VERIFIED` a
   `CONTENT_VERIFIED`: un crédito no tiene magnitud de precio comparable, y
   mentiría mantener el nivel anterior. (c) Ninguna fuente emite hoy `PRUEBA_GRATUITA`
   ni un `DESCUENTO` genérico: la taxonomía queda lista para cuando aparezcan.

4. **Arreglar la documentación de dependencias e instalación.**
   `requirements.txt` contiene texto de documentación, no una lista válida
   para `pip install -r requirements.txt`. Convertirlo a un fichero de
   requisitos válido o eliminarlo y documentar la instalación opcional de
   `keyring`. El motor básico debe seguir funcionando sin paquetes externos;
   la configuración segura de API keys exige un backend de credenciales
   compatible. Cierre: instalación reproducible en un entorno limpio.

5. **Revisar seguridad y límites de costos de IA antes de pruebas con claves.**
   La detección de modelo gratuito NO implica cuota disponible ni certeza
   de ausencia de cargos para una cuenta concreta. Mantener el bloqueo por
   defecto, comprobar clasificación de costos y límites de requests/tokens,
   y revisar el uso de API keys en URL, mensajes de error y Base URL
   configurable. En particular, investigar riesgo de enviar claves a hosts
   arbitrarios o de aceptar solicitudes web locales de orígenes no
   autorizados. No afirmar que existe una vulnerabilidad sin reproducirla.
   Archivos: `ach/ai_providers.py`, `ach/ai_settings.py`, `ach/web_ai.py`,
   `ach/web.py`. Cierre: pruebas negativas sin exponer credenciales.

### P1 — Aumentar la utilidad real del cazador

6. **Ampliar y administrar las fuentes.** Hoy `ach/sources.py` contiene
   ocho fuentes fijadas en código; la base almacena resultados/estado, pero
   no reemplaza al registro de extractores. Crear un catálogo administrable
   (URL, proveedor, dominio oficial, tipo, método de extracción, prioridad,
   cadencia, términos, estado, última revisión y motivos de fallo) y una
   interfaz para habilitar/deshabilitar fuentes sin editar Python.
   Incorporar fuentes oficiales de créditos, promociones, pruebas y
   beneficios educativos, priorizando disponibilidad en Argentina. Candidatos
   para investigar, **no ofertas confirmadas**: GitHub Education, Gemini API,
   Groq, Alibaba Cloud Model Studio y Google Cloud. Incorporar únicamente
   fuentes con extracción verificable, respetando términos y límites.

7. **Descubrir fuentes nuevas, no solo volver a consultar las conocidas.**
   Añadir una etapa de descubrimiento mediante feeds, APIs públicas y búsquedas
   gratuitas permitidas; cada URL descubierta entra como *candidata*,
   nunca como evidencia confirmada. Validar dominio oficial, relevancia,
   duplicados, fecha, accesibilidad y método de extracción antes de promover
   una fuente al catálogo activo. No construir un crawler masivo sin necesidad.

8. **Separar tipos de oportunidades y relevancia personal.**
   Distinguir `PROMOCION_TEMPORAL`, `CREDITO`, `PRUEBA`, `FREE_TIER`,
   `MODELO_GRATUITO`, `BENEFICIO_ESTUDIANTIL` y `ANUNCIO`. Ofrecer filtros
   que prioricen cero costo, Argentina, ausencia de tarjeta y utilidad real
   para un usuario individual. No recomendar como oportunidad general un
   anuncio restringido, por ejemplo, a administraciones públicas de EE. UU.
   Mantener el dato original y mostrar claramente «no aplicable» o
   «elegibilidad sin confirmar».

9. **Verificar IA real y su aporte incremental.** El recorrido con
   `demo_local` y fixtures demuestra integración técnica, **no razonamiento
   de un modelo remoto**. Ejecutar una prueba acotada con un modelo gratuito
   confirmado para la cuenta, **solo cuando el usuario configure su clave y
   autorice la prueba**, comparando 10–20 candidatos relevantes con la
   clasificación determinista. Medir falsos positivos, condiciones extraídas,
   elegibilidad AR, tokens, bloqueos y latencia. Si un modelo falla, conservar
   evidencia, registrar causa y continuar sin IA; no simular éxito.
   Evitar reenviar una oferta sin cambios a la IA para ahorrar cuota.

### P2 — Mejoras posteriores, NO bloquean el MVP

10. **Vigilancia y avisos opcionales.** Agregar planificación con consentimiento,
    alerta de oferta *nueva o cambiada* y resumen de novedades, con
    anti-duplicados y control de frecuencia. Nada de activar tareas de Windows
    ni notificaciones externas de forma automática.

11. **Robustez de extracción.** Manejar `429` y `Retry-After`, backoff,
    bloqueos, expiración y cambios de HTML; respetar `robots.txt` y límites
    de los sitios. Navegador headless solo para fuentes JS valiosas y cuando
    se justifique su costo de mantenimiento.

12. **Experiencia de uso.** Mostrar claramente cuándo una búsqueda es live,
    offline o demo; fecha de última comprobación, evidencia, URL oficial,
    costos, requisitos y razones del veredicto IA. Añadir opción de buscar
    desde la UI, estado de progreso y errores por fuente; no hacer pasar
    «23 registros históricos en la base» por «23 ofertas nuevas».

13. **Calidad y portabilidad.** Añadir tests de instalación desde clon limpio,
    compatibilidad con sistemas de credenciales según SO, migraciones
    idempotentes, integridad SQLite y reporte de resultados reales. Evaluar
    alternativas a `keyring` según el entorno sin guardar claves en claro.

### Lo que NO hay que hacer por defecto

- No reabrir las migraciones históricas `m001–m010` ni intentar fusionar
  automáticamente la base v2/v3 con la v4: esta publicación funciona con
  `data/promotions_v4.sqlite3` independiente.
- No recuperar los 15 bots estáticos del proyecto antiguo ni crear agentes
  adicionales para una tarea que puede resolver un desarrollador.
- No introducir APIs de pago, credenciales en fixtures, telemetría nueva,
  scraping agresivo ni automatizaciones sin autorización.
- No equiparar `HTTP 200`, `NETWORK_VERIFIED` o el veredicto LLM con
  vigencia comercial, elegibilidad argentina o disponibilidad garantizada.
- No declarar una entrega «terminada» solo por el número de tests.

### Protocolo para la próxima IA que abra el repositorio

1. Leer este README, `ach/sources.py`, `ach/pipeline.py`,
   `ach/ai_classify.py`, `ach/ai_settings.py` y las pruebas relacionadas.
2. Verificar `git status` y trabajar en una rama de cambios acotados.
   Proteger `data/`, `reports/`, credenciales y bases operativas. No ejecutar
   tests legacy ni scripts destructivos.
3. Elegir **un problema P0 o una mejora P1**, reproducirlo y entregar
   código + test + breve explicación. No hacer otra auditoría general.
4. Ejecutar primero pruebas unitarias y fixtures sin red. Después,
   solo cuando aporte evidencia, hacer una consulta live acotada.
5. Informar qué se cambió, qué quedó pendiente y cómo probarlo.
   Mantener esta hoja de ruta y sus estados actualizados en el mismo PR.

**Definición de entrega:** comportamiento observable, evidencia trazable,
sin secretos ni escrituras fuera del entorno elegido, costo controlado y
problema concreto resuelto. No se exige completar toda la hoja de ruta para
publicar una versión incremental.

